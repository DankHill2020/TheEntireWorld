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


SEMANTIC_INTENT_MODEL = "qwen2.5:1.5b"
FALLBACK_SEMANTIC_INTENT_MODEL = "qwen2.5:1.5b"

FAST_GENERAL_MODEL = "qwen3:14b"
FALLBACK_GENERAL_MODEL = "qwen2.5-coder:latest"

FAST_CODE_MODEL = "qwen2.5-coder:14b"
FALLBACK_CODE_MODEL = "qwen2.5-coder:latest"

EMBEDDING_MODEL = "nomic-embed-text:latest"


AI_MODELS = {
    # Micro semantic roles: understand and decompose requests only.
    # These roles must not generate patches or perform deep reasoning.
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

    Semantic roles intentionally use the tiny qwen2.5:1.5b model. Code,
    debugging, and DCC generation remain on the coder models.
    """
    normalized_role = str(role or "").strip().lower()
    return AI_MODELS.get(normalized_role, default or FAST_GENERAL_MODEL)


def semantic_intent_model():
    """Return the dedicated non-reasoning model used for request understanding."""
    return SEMANTIC_INTENT_MODEL


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


def warm_required_models_async(keep_alive="2h"):
    def run():
        ok, msg = ensure_ollama_server()
        if not ok:
            print(f"[Ollama] {msg}", flush=True)
            return

        try:
            from services.settings_service import load_settings

            settings = load_settings()
            selected = settings.get("model")
        except Exception:
            selected = None

        # Keep the tiny semantic model warm because it sits on the request path.
        models = set(REQUIRED_SEMANTIC_MODELS + REQUIRED_CHAT_MODELS)
        if selected:
            models.add(normalize_ollama_model_name(selected))

        for model in sorted(models):
            warm_ollama_model(model, keep_alive=keep_alive)

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
