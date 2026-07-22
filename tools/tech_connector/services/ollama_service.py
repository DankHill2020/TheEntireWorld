"""Ollama model install/check/warm helpers for Tech Connector."""

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


FAST_GENERAL_MODEL = "qwen3:14b"
FALLBACK_GENERAL_MODEL = "qwen2.5-coder:latest"

# The semantic pass is intentionally small and cheap. A separate planning pass
# receives its hypothesis plus resolved context and performs the deeper reasoning.
SEMANTIC_INTENT_MODEL = os.environ.get("AI_STUDIO_SEMANTIC_INTENT_MODEL", "qwen2.5:1.5b")
FALLBACK_SEMANTIC_INTENT_MODEL = "qwen2.5:1.5b"

FAST_CODE_MODEL = "qwen2.5-coder:14b"
FALLBACK_CODE_MODEL = "qwen2.5-coder:latest"
CODE_MODEL_PROFILES = {
    "micro": os.environ.get("AI_STUDIO_MICRO_CODE_MODEL", "qwen2.5-coder:1.5b"),
    "small": os.environ.get("AI_STUDIO_SMALL_CODE_MODEL", "qwen2.5-coder:3b"),
    "standard": os.environ.get("AI_STUDIO_STANDARD_CODE_MODEL", "qwen2.5-coder:7b"),
    "quality": os.environ.get("AI_STUDIO_QUALITY_CODE_MODEL", FAST_CODE_MODEL),
    "deep": os.environ.get("AI_STUDIO_DEEP_CODE_MODEL", "qwen3-coder:30b"),
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
]

REQUIRED_CHAT_MODELS = [
    FAST_GENERAL_MODEL,
    FALLBACK_GENERAL_MODEL,
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


def code_model_for_profile(profile: str) -> str:
    """Return the configured coder for a scoped generation/repair profile."""
    normalized = str(profile or "small").strip().lower()
    aliases = {
        "fast": "standard",
        "repair": "standard",
        "large": "quality",
        "large_tool": "quality",
    }
    target_profile = aliases.get(normalized, normalized)

    # Allow custom settings overrides
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        if target_profile == "quality" and settings.get("fast_code_model"):
            return settings.get("fast_code_model")
        # Check custom mappings for specific profile names as roles
        custom_mappings = settings.get("custom_model_mappings", {})
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
    ensure_ollama_server()

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


def warm_ollama_model(model, keep_alive="2h"):
    ok, _msg = ensure_ollama_server()
    if not ok:
        return False

    model = normalize_ollama_model_name(model)

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


def warm_required_models_async(keep_alive="24h"):
    def run():
        ok, msg = ensure_ollama_server()
        if not ok:
            print(f"[Ollama] {msg}", flush=True)
            return

        try:
            from tech_connector.services.settings_service import load_settings

            settings = load_settings()
            configured_preloads = list(settings.get("ollama_preload_models") or [])
        except Exception:
            configured_preloads = []

        # Only explicitly resident models are warmed. Installed quality and
        # escalation models remain cold so they cannot evict the fast planner.
        models = set()
        models.update(
            normalize_ollama_model_name(model)
            for model in configured_preloads
            if str(model or "").strip()
        )
        # Warm independently so a cold quality model does not postpone the fast
        # planner becoming available during application startup.
        for model in sorted(models):
            threading.Thread(
                target=warm_ollama_model,
                args=(model, keep_alive),
                daemon=True,
            ).start()

    threading.Thread(target=run, daemon=True).start()


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
