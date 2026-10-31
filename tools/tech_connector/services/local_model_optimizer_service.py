"""Hardware-aware local model selection and speed measurement."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class LocalHardwareProfile:
    gpu_name: str = ""
    vram_gb: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_local_hardware() -> LocalHardwareProfile:
    """Return NVIDIA capacity when available, otherwise a CPU-safe profile."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        first = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
        if first:
            name, memory_mb = first.rsplit(",", 1)
            return LocalHardwareProfile(name.strip(), round(float(memory_mb) / 1024, 1))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return LocalHardwareProfile()


def recommend_local_models(
    installed_models: Iterable[str] = (),
    hardware: LocalHardwareProfile | None = None,
) -> dict[str, Any]:
    """Recommend a GPU-resident primary model and a separate quality lane."""
    hardware = hardware or detect_local_hardware()
    vram = hardware.vram_gb
    if vram >= 24:
        targets = {
            "intent": "qwen3.5:4b",
            "general": "qwen3.5:9b",
            "code": "qwen3.5:9b",
            "deep": "qwen3-coder:30b",
            "visual": "qwen3.5:9b",
        }
    elif vram >= 8:
        targets = {
            "intent": "qwen3.5:4b",
            "general": "qwen3.5:4b",
            # A focused, hidden-checked code-edit probe favored the installed
            # 7B coder over the 4B general model on this VRAM tier. Keep the
            # smaller general model for non-code roles.
            "code": "qwen2.5-coder:7b",
            "deep": "qwen3.5:9b",
            "visual": "qwen3.5:4b",
        }
    elif vram >= 5:
        targets = {role: "qwen3.5:4b" for role in ("intent", "general", "code", "deep", "visual")}
    else:
        targets = {role: "qwen3.5:2b" for role in ("intent", "general", "code", "deep", "visual")}
    installed = {
        str(model).removeprefix("ollama:").strip().lower():
        str(model).removeprefix("ollama:").strip()
        for model in installed_models
        if str(model).strip()
    }
    fallbacks = {
        "intent": ("qwen3.5:4b", "qwen3:4b-instruct", "qwen2.5-coder:3b"),
        "general": ("qwen3.5:4b", "qwen3:4b-instruct", "qwen2.5-coder:3b"),
        "code": ("qwen2.5-coder:7b", "qwen3.5:9b", "qwen3.5:4b", "qwen2.5-coder:3b"),
        "deep": ("qwen3-coder:30b", "qwen3.5:9b", "qwen2.5-coder:7b", "qwen3.5:4b"),
        "visual": ("qwen3.5:9b", "qwen3.5:4b", "qwen3:4b-instruct"),
    }
    active = {}
    for role, target in targets.items():
        active[role] = next(
            (
                installed[name.lower()]
                for name in (target, *fallbacks[role])
                if name.lower() in installed
            ),
            target,
        )
    return {
        "hardware": hardware.to_dict(),
        "policy": "hardware_aware_speed_first",
        "targets": targets,
        "active": active,
        "missing_recommended": sorted(
            target
            for target in set(targets.values())
            if target.lower() not in installed
        ),
        "runtime": {
            "default_num_ctx": 4096,
            "max_num_ctx": 8192 if vram >= 8 else 4096,
            "max_parallel": 1,
            "keep_alive": "30m",
        },
        "notes": [
            "Keep the primary model GPU-resident for low latency.",
            "Use the deep model or a cloud route only when quality warrants it.",
        ],
    }


def benchmark_local_model(
    model: str,
    *,
    prompt: str = "Write a concise Python function that groups paths by extension.",
    num_predict: int = 128,
    num_ctx: int = 4096,
    timeout: int = 300,
    base_url: str = "http://127.0.0.1:11434",
) -> dict[str, Any]:
    """Run a deterministic Ollama speed probe and return public metrics."""
    payload = json.dumps({
        "model": str(model).removeprefix("ollama:"), "prompt": prompt, "stream": False,
        "options": {"num_predict": max(1, int(num_predict)), "num_ctx": max(512, int(num_ctx)), "temperature": 0},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=max(1, int(timeout))) as response:
        result = json.loads(response.read().decode("utf-8"))
    eval_seconds = float(result.get("eval_duration") or 0) / 1_000_000_000
    output_tokens = int(result.get("eval_count") or 0)
    return {
        "model": str(model).removeprefix("ollama:"),
        "wall_seconds": round(time.monotonic() - started, 3),
        "load_seconds": round(
            float(result.get("load_duration") or 0) / 1_000_000_000,
            3,
        ),
        "prompt_tokens": int(result.get("prompt_eval_count") or 0),
        "output_tokens": output_tokens,
        "tokens_per_second": round(output_tokens / eval_seconds, 2) if eval_seconds else 0.0,
    }