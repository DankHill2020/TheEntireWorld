"""Ollama model install/check/warm helpers for Tech Connector."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.request

from PySide6.QtCore import QThread, Signal


OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}"


FAST_GENERAL_MODEL = "qwen3:4b-instruct"
FALLBACK_GENERAL_MODEL = "qwen3:4b-instruct"
VISUAL_MEDIA_MODEL = os.environ.get("AI_STUDIO_VISUAL_MEDIA_MODEL", "qwen3:4b-instruct")

# The semantic pass is intentionally small and cheap. A separate planning pass
# receives its hypothesis plus resolved context and performs the deeper reasoning.
SEMANTIC_INTENT_MODEL = os.environ.get("AI_STUDIO_SEMANTIC_INTENT_MODEL", "qwen3:4b-instruct")
FALLBACK_SEMANTIC_INTENT_MODEL = os.environ.get("AI_STUDIO_SEMANTIC_VERIFY_MODEL", "qwen3:4b-instruct")
SEMANTIC_ALIGNMENT_MODEL = os.environ.get("AI_STUDIO_SEMANTIC_ALIGNMENT_MODEL", "qwen3:4b-instruct")

FAST_CODE_MODEL = os.environ.get("AI_STUDIO_FAST_CODE_MODEL", "qwen2.5-coder:7b")
FALLBACK_CODE_MODEL = "qwen2.5-coder:7b"
CODE_MODEL_PROFILES = {
    "micro": os.environ.get("AI_STUDIO_MICRO_CODE_MODEL", "qwen2.5-coder:3b"),
    "small": os.environ.get("AI_STUDIO_SMALL_CODE_MODEL", "qwen2.5-coder:3b"),
    "standard": os.environ.get("AI_STUDIO_STANDARD_CODE_MODEL", "qwen2.5-coder:7b"),
    "quality": os.environ.get("AI_STUDIO_QUALITY_CODE_MODEL", "qwen2.5-coder:7b"),
    "deep": os.environ.get("AI_STUDIO_DEEP_CODE_MODEL", "qwen2.5-coder:7b"),
}

EMBEDDING_MODEL = "nomic-embed-text:latest"


AI_MODELS = {
    # Semantic roles produce a cheap first-pass hypothesis only.
    "intent": SEMANTIC_INTENT_MODEL,
    "semantic_router": SEMANTIC_INTENT_MODEL,
    "request_understanding": SEMANTIC_INTENT_MODEL,
    "task_splitter": SEMANTIC_INTENT_MODEL,
    "route_disambiguation": SEMANTIC_INTENT_MODEL,
    "general": FAST_GENERAL_MODEL,
    "plan": FAST_GENERAL_MODEL,
    "docs": FAST_GENERAL_MODEL,
    "visual": VISUAL_MEDIA_MODEL,
    "visual_media": VISUAL_MEDIA_MODEL,
    "image": VISUAL_MEDIA_MODEL,
    "video": VISUAL_MEDIA_MODEL,
    "camera": VISUAL_MEDIA_MODEL,
    "code": FAST_CODE_MODEL,
    "debug": FAST_CODE_MODEL,
    "dcc": FAST_CODE_MODEL,
    "maya": FAST_CODE_MODEL,
    "unreal": FAST_CODE_MODEL,
    "blender": FAST_CODE_MODEL,
    "substance_painter": FAST_CODE_MODEL,
    "motionbuilder": FAST_CODE_MODEL,
    "embed": EMBEDDING_MODEL,
}

REQUIRED_SEMANTIC_MODELS = [
    SEMANTIC_INTENT_MODEL,
    FALLBACK_SEMANTIC_INTENT_MODEL,
]

REQUIRED_CHAT_MODELS = [
    FAST_GENERAL_MODEL,
    FALLBACK_GENERAL_MODEL,
    VISUAL_MEDIA_MODEL,
    CODE_MODEL_PROFILES["standard"],
]

REQUIRED_EMBED_MODELS = [
    EMBEDDING_MODEL,
]

REQUIRED_MODELS = sorted(set(REQUIRED_SEMANTIC_MODELS + REQUIRED_CHAT_MODELS + REQUIRED_EMBED_MODELS))


def _creationflags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def normalize_ollama_model_name(model):
    model = (model or "").strip()
    if model.startswith("ollama:"):
        model = model.replace("ollama:", "", 1)
    return model


def _parse_ollama_model_size(model_name: str) -> float:
    name = str(model_name or "").strip().lower()
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*[bB]\b", name)
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def _build_local_model_candidates(model_name: str) -> list[str]:
    requested = normalize_ollama_model_name(model_name).lower()
    requested_size = _parse_ollama_model_size(requested)
    size_token = None if requested_size == 0.0 else str(requested_size).rstrip("0").rstrip(".") + "b"

    aliases = {
        "1.5b": "qwen2.5-coder:3b",
        "3b": "qwen2.5-coder:3b",
        "7b": "qwen2.5-coder:7b",
        "14b": "qwen2.5-coder:7b",
        "30b": "qwen2.5-coder:7b",
    }
    if requested in aliases:
        return [aliases[requested]]

    if requested in {"qwen2.5-coder:3b", "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen2.5-coder:7b", "qwen2.5-coder:30b"}:
        return [requested]

    families = ["qwen2.5-coder", "qwen2.5", "qwen3-coder", "qwen3", "qwen"]
    if "qwen2.5" in requested:
        families = ["qwen2.5", "qwen2.5-coder", "qwen3-coder", "qwen3", "qwen"]
    elif "qwen3" in requested:
        families = ["qwen3", "qwen3-coder", "qwen2.5-coder", "qwen2.5", "qwen"]

    candidates = [requested]
    if size_token:
        for family in families:
            candidates.append(f"{family}:{size_token}")
            candidates.append(f"{family}:{size_token.replace('.', '')}b")
        candidates.extend([
            "qwen2.5-coder:7b",
            "qwen2.5:latest",
            "qwen3-coder:latest",
            "qwen3:latest",
            FALLBACK_CODE_MODEL,
        ])
    else:
        candidates.append(FALLBACK_CODE_MODEL)
    return list(dict.fromkeys(candidates))


def resolve_ollama_model_name(model):
    """Resolve short/approximate Ollama model names to an installed local candidate."""
    requested = normalize_ollama_model_name(model)
    installed = installed_ollama_models()
    if not requested:
        return requested
    if not installed:
        return requested

    normalized_installed = {name.lower(): name for name in installed}
    if requested.lower() in normalized_installed:
        return normalized_installed[requested.lower()]

    for candidate in _build_local_model_candidates(requested):
        lookup = candidate.lower()
        if lookup in normalized_installed:
            return normalized_installed[lookup]

    # Keep size-only style aliases even if not yet installed; they will
    # trigger a clear install/runtime error instead of silently switching.
    return requested


def estimated_ollama_generation_timeout(model: str) -> int:
    size = _parse_ollama_model_size(model)
    if size <= 0.0:
        return 150
    if size <= 1.6:
        return 120
    if size <= 3.0:
        return 150
    if size <= 7.0:
        return 210
    if size <= 14.0:
        return 240
    if size <= 30.0:
        return 300
    return 420


def as_mcphost_model(model):
    return "ollama:" + normalize_ollama_model_name(model)


def model_for_role(role, default=None):
    """Return the canonical Ollama model for an application role.

    Semantic roles use the small configured model. Planning, code, debugging,
    and DCC generation use their respective larger models.
    """
    normalized_role = str(role or "").strip().lower()

    # 1. Check custom_model_mappings in settings first
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        mappings = settings.get("custom_model_mappings")
        if isinstance(mappings, dict) and normalized_role in mappings:
            return mappings[normalized_role]
    except Exception:
        pass

    # 2. Check for role-specific overrides in settings
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()

        # Check specific model classes
        if normalized_role in ("intent", "semantic_router", "request_understanding", "task_splitter", "route_disambiguation"):
            model_key = "semantic_intent_model"
        elif normalized_role in ("general", "plan", "docs"):
            model_key = "fast_general_model"
        elif normalized_role in ("visual", "visual_media", "image", "video", "camera"):
            model_key = "visual_media_model"
        elif normalized_role in ("code", "debug", "dcc", "maya", "unreal", "blender", "substance_painter", "motionbuilder"):
            model_key = "fast_code_model"
        elif normalized_role == "embed":
            model_key = "embedding_model"
        else:
            model_key = None

        if model_key and settings.get(model_key):
            return settings.get(model_key)
    except Exception:
        pass

    return AI_MODELS.get(normalized_role, default or FAST_GENERAL_MODEL)


def semantic_intent_model():
    """Return the small model used for the first semantic hypothesis."""
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        if settings.get("semantic_intent_model"):
            return settings.get("semantic_intent_model")
    except Exception:
        pass
    return SEMANTIC_INTENT_MODEL


def semantic_verifier_model():
    """Return the small general model used to verify prompt-plan alignment."""
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        if settings.get("semantic_verifier_model"):
            return settings.get("semantic_verifier_model")
    except Exception:
        pass
    return FALLBACK_SEMANTIC_INTENT_MODEL


def semantic_alignment_model():
    """Return the general model trusted for atomic prompt-plan comparisons."""
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        if settings.get("semantic_alignment_model"):
            return settings.get("semantic_alignment_model")
    except Exception:
        pass
    return SEMANTIC_ALIGNMENT_MODEL


def code_model_for_profile(
    profile: str,
    settings: dict | None = None,
) -> str:
    """
    Return the configured coder for a scoped generation or repair profile.
    :param profile: requested model profile
    :param settings: optional already-loaded application settings
    :return: configured or default model identifier
    """
    normalized = str(profile or "small").strip().lower()
    aliases = {
        "fast": "standard",
        "repair": "standard",
        "large": "quality",
        "large_tool": "quality",
    }
    target_profile = aliases.get(normalized, normalized)

    # Callers that already own settings pass them through so worker startup does
    # not repeatedly read and normalize the settings file.
    resolved_settings = settings
    if resolved_settings is None:
        try:
            from tech_connector.services.settings_service import load_settings

            resolved_settings = load_settings()
        except Exception:
            resolved_settings = {}
    try:
        if target_profile == "quality" and resolved_settings.get("fast_code_model"):
            return resolved_settings.get("fast_code_model")
        # Check custom mappings for specific profile names as roles
        custom_mappings = resolved_settings.get("custom_model_mappings", {})
        profile_role = f"profile_{target_profile}"
        if profile_role in custom_mappings:
            return custom_mappings[profile_role]
    except Exception:
        pass

    return CODE_MODEL_PROFILES.get(target_profile, CODE_MODEL_PROFILES["small"])


def is_ollama_running(timeout=2):
    try:
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout) as response:
            response.read()
        return True
    except Exception:
        return False


def ensure_ollama_server(wait_seconds=8):
    """Start Ollama server only if the API is not already reachable."""
    if is_ollama_running():
        return True, "Ollama already running."

    try:
        env = os.environ.copy()
        env.setdefault("OLLAMA_HOST", OLLAMA_HOST)

        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=_creationflags(),
        )
    except Exception as exc:
        return False, f"Could not start Ollama: {exc}"

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if is_ollama_running(timeout=1):
            return True, "Ollama started."
        time.sleep(0.5)

    return False, "Ollama did not become ready in time."


def installed_ollama_models():
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            check=True,
            creationflags=_creationflags(),
        )
    except Exception:
        return []

    models = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if line:
            models.append(line.split()[0])
    return models


def missing_required_models():
    installed = installed_ollama_models()
    return [m for m in REQUIRED_MODELS if m not in installed]


def warm_ollama_model(model: str, keep_alive: str | int = "2h") -> bool:
    """Warm or unload one model through the shared local-provider queue.

    :param model: Ollama model name.
    :param keep_alive: Ollama residency duration, or zero to unload.
    :return: True when Ollama accepts and completes the request.
    """

    model = normalize_ollama_model_name(model)

    def execute_warm_request() -> bool:
        """Perform the serialized Ollama resource request.

        :return: True when the resource request succeeds.
        """

        ok, _msg = ensure_ollama_server()
        if not ok:
            return False
        payload = json.dumps(
            {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": keep_alive,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(req, timeout=120) as response:
                response.read()
            return True
        except Exception:
            return False

    from tech_connector.services.llm_request_queue_service import (
        LLMQueueError,
        global_llm_request_queue,
        llm_queue_lane_options,
    )
    from tech_connector.services.settings_service import load_settings

    settings = load_settings()
    try:
        return bool(
            global_llm_request_queue().submit(
                execute_warm_request,
                provider="ollama",
                model=model,
                category="background",
                supersede_key=f"ollama-warm:{model}",
                **llm_queue_lane_options(settings, "ollama"),
            )
        )
    except LLMQueueError:
        return False


def loaded_ollama_models():
    """Return models currently resident in Ollama memory."""
    try:
        result = subprocess.run(
            ["ollama", "ps"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
            creationflags=_creationflags(),
        )
    except Exception:
        return []
    models = []
    for line in result.stdout.splitlines()[1:]:
        value = line.strip()
        if value:
            models.append(value.split()[0])
    return list(dict.fromkeys(models))


def unload_all_ollama_models():
    """Unload every resident model while leaving the lightweight server available."""
    models = loaded_ollama_models()
    results = {
        model: bool(warm_ollama_model(model, keep_alive=0))
        for model in models
    }
    return {
        "ok": all(results.values()) if results else True,
        "models": models,
        "results": results,
        "unloaded_count": sum(1 for value in results.values() if value),
    }


def unload_ollama_models(models):
    """Unload the requested resident models while leaving the Ollama server available."""
    normalized_models = []
    for model in models or []:
        normalized = normalize_ollama_model_name(model)
        if normalized and normalized not in normalized_models:
            normalized_models.append(normalized)

    results = {
        model: bool(warm_ollama_model(model, keep_alive=0))
        for model in normalized_models
    }
    return {
        "ok": all(results.values()) if results else True,
        "models": normalized_models,
        "results": results,
        "unloaded_count": sum(1 for value in results.values() if value),
    }


def warm_required_models_async(keep_alive="10m"):
    """Warm at most one model in the background.

    Multiple concurrent warm requests caused Ollama to load and evict models on
    8 GB GPUs. Explicit preloads still win, but only the first configured model
    is warmed. Otherwise the semantic-alignment model is warmed.
    """

    def run():
        try:
            from tech_connector.services.settings_service import load_settings

            settings = load_settings()
            if not bool(settings.get("ollama_preload_on_startup", False)):
                return
        except Exception:
            settings = {}

        ok, msg = ensure_ollama_server()
        if not ok:
            print(f"[Ollama] {msg}", flush=True)
            return

        try:
            configured_preloads = [
                normalize_ollama_model_name(model)
                for model in list(settings.get("ollama_preload_models") or [])
                if str(model or "").strip()
            ]
            warm_alignment = bool(
                settings.get("warm_semantic_alignment_model", True)
            )
        except Exception:
            configured_preloads = []
            warm_alignment = True

        primary_model = configured_preloads[0] if configured_preloads else ""
        if not primary_model and warm_alignment:
            primary_model = normalize_ollama_model_name(semantic_alignment_model())

        if not primary_model:
            return

        success = warm_ollama_model(primary_model, keep_alive)
        print(
            f"[Ollama] Warm {'completed' if success else 'failed'}: {primary_model}",
            flush=True,
        )

    threading.Thread(target=run, daemon=True).start()


def terminate_orphan_model_runtime_processes(include_ollama_server: bool = False) -> dict:
    """Stop known local model helper processes after owned sessions are idle."""
    targets = {"llama-server", "llama_cpp_server", "mcphost"}
    if include_ollama_server:
        targets.update({"ollama", "ollama app"})
    target_keys = {name.casefold() for name in targets}
    stopped = []
    errors = []
    try:
        if os.name == "nt":
            rows = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                creationflags=_creationflags(),
            )
            for raw in rows.stdout.splitlines():
                parts = [part.strip('"') for part in raw.split('","')]
                if len(parts) < 2:
                    continue
                image, pid = parts[0], parts[1]
                stem = os.path.splitext(image)[0].casefold()
                if stem not in target_keys:
                    continue
                result = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", pid],
                    capture_output=True,
                    text=True,
                    check=False,
                    creationflags=_creationflags(),
                )
                if result.returncode == 0:
                    stopped.append({"pid": pid, "process": image})
                else:
                    errors.append({"pid": pid, "process": image, "error": result.stderr.strip()})
        else:
            import signal

            rows = subprocess.run(
                ["ps", "-A", "-o", "pid=,comm="],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in rows.stdout.splitlines():
                fields = line.strip().split(None, 1)
                if len(fields) != 2:
                    continue
                pid, command = fields
                stem = os.path.basename(command).casefold()
                if stem not in target_keys:
                    continue
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    stopped.append({"pid": pid, "process": command})
                except Exception as exc:
                    errors.append({"pid": pid, "process": command, "error": str(exc)})
    except Exception as exc:
        errors.append({"error": str(exc)})
    return {"ok": not errors, "stopped": stopped, "errors": errors}


class ModelInstallWorker(QThread):
    output = Signal(str)
    progress = Signal(int)
    finished_ok = Signal(bool, str)

    ANSI_ESCAPE = re.compile(r"(?:\x1B[@-_][0-?]*[ -/]*[@-~])")
    PERCENT_RE = re.compile(r"(\d{1,3})%")

    def __init__(self, models):
        super().__init__()
        self.models = models
        self._stop = False

    def run(self):
        try:
            ok, msg = ensure_ollama_server()
            self.output.emit(f"\n[Ollama] {msg}\n")
            if not ok:
                self.finished_ok.emit(False, msg)
                return

            for model in self.models:
                if self._stop:
                    self.finished_ok.emit(False, "Model install cancelled.")
                    return

                self.progress.emit(0)
                self.output.emit(f"\n[Ollama] Pulling {model}...\n")

                proc = subprocess.Popen(
                    ["ollama", "pull", model],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=_creationflags(),
                )

                for line in proc.stdout:
                    if self._stop:
                        proc.kill()
                        self.finished_ok.emit(False, "Model install cancelled.")
                        return

                    clean = self.ANSI_ESCAPE.sub("", line)
                    self.output.emit(clean)

                    m = self.PERCENT_RE.search(clean)
                    if m:
                        value = max(0, min(100, int(m.group(1))))
                        self.progress.emit(value)

                code = proc.wait()
                if code != 0:
                    self.finished_ok.emit(False, f"Failed pulling {model}. Exit code {code}.")
                    return

                self.progress.emit(100)

            self.finished_ok.emit(True, "Required models installed.")

        except Exception as e:
            self.finished_ok.emit(False, str(e))

    def stop(self):
        self._stop = True
