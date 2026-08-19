"""Account-backed model providers that leave credentials with official tools."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any


@dataclass(frozen=True)
class ProviderAccountStatus:
    """Installation and login state for one official provider client."""

    provider_id: str
    executable: str
    installed: bool
    connected: bool
    detail: str


_STATUS_CACHE: dict[str, tuple[float, ProviderAccountStatus]] = {}
_STATUS_TTL_SECONDS = 15.0


def _configured_executable(provider_id: str) -> str:
    try:
        from tech_connector.services.settings_service import load_settings

        configured = load_settings().get("provider_executables") or {}
        return str(configured.get(provider_id) or "").strip()
    except Exception:
        return ""


def _candidate_paths(provider_id: str) -> list[str]:
    names = {
        "openai": ("codex.cmd", "codex.exe", "codex"),
        "anthropic": ("claude.cmd", "claude.exe", "claude"),
        "x": ("grok.cmd", "grok.exe", "grok"),
        "google": ("agy.cmd", "agy.exe", "agy", "gcloud.cmd", "gcloud.exe", "gcloud"),
    }.get(provider_id, ())
    candidates = [_configured_executable(provider_id), *names]

    home = Path.home()
    local_app_data = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    roaming_app_data = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    for name in names:
        candidates.extend(
            [
                str(home / ".local" / "bin" / name),
                str(roaming_app_data / "npm" / name),
                str(local_app_data / "Programs" / name),
                str(local_app_data / "OpenAI" / "Codex" / "bin" / name),
            ]
        )
    return [candidate for candidate in candidates if candidate]


def resolve_provider_executable(provider_id: str) -> str:
    """Resolve a CLI without mistaking a provider desktop app for its CLI."""
    for candidate in _candidate_paths(provider_id):
        path = Path(candidate)
        if path.is_file():
            return str(path)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    npx_packages = {
        "openai": "@openai/codex",
        "anthropic": "@anthropic-ai/claude-code",
        "x": "grok-cli",
        "google": "@google/agy",
    }
    if provider_id in npx_packages and (shutil.which("npx") or shutil.which("npx.cmd")):
        return f"npx -y {npx_packages[provider_id]}"
    return ""


def _build_cmd(executable: str, args: list[str]) -> list[str]:
    if os.name == "nt":
        if executable.startswith("npx ") or executable.lower().endswith((".cmd", ".bat", ".ps1")) or " " in executable:
            return ["cmd.exe", "/c", f"{executable} {' '.join(args)}".strip()]
    return [executable, *args]


def _status_args(provider_id: str) -> list[str]:
    return {
        "openai": ["login", "status"],
        "anthropic": ["auth", "status"],
        "x": ["models"],
        "google": ["models"],
    }.get(provider_id, [])


def _login_args(provider_id: str) -> list[str]:
    return {
        "openai": ["login"],
        "anthropic": ["auth", "login"],
        "x": ["login"],
        "google": ["auth", "application-default", "login"],
    }.get(provider_id, [])


def provider_account_status(
    provider_id: str,
    *,
    refresh: bool = False,
    timeout: int = 6,
) -> ProviderAccountStatus:
    """Check official client status without reading browser or token storage."""
    if provider_id == "ollama":
        return ProviderAccountStatus(provider_id, "", True, True, "Local provider")

    now = time.monotonic()
    cached = _STATUS_CACHE.get(provider_id)
    if not refresh and cached and now - cached[0] < _STATUS_TTL_SECONDS:
        return cached[1]

    executable = resolve_provider_executable(provider_id)
    if not executable:
        result = ProviderAccountStatus(
            provider_id,
            "",
            False,
            False,
            "Official command-line client is not installed or configured.",
        )
        _STATUS_CACHE[provider_id] = (now, result)
        return result

    try:
        completed = subprocess.run(
            _build_cmd(executable, _status_args(provider_id)),
            capture_output=True,
            text=True,
            timeout=max(1, timeout),
            check=False,
        )
        connected = completed.returncode == 0
        detail = (
            (completed.stdout or completed.stderr or "Connected through official account login.").strip()
            if connected
            else (completed.stderr or completed.stdout or "Sign in is required.").strip()
        )
    except (OSError, subprocess.SubprocessError) as exc:
        connected = False
        detail = f"Could not check login status: {exc}"

    result = ProviderAccountStatus(
        provider_id,
        executable,
        True,
        connected,
        detail,
    )
    _STATUS_CACHE[provider_id] = (now, result)
    return result


def account_provider_is_connected(provider_id: str) -> bool:
    return provider_account_status(provider_id).connected


def begin_provider_login(provider_id: str, *, cwd: str | None = None) -> str:
    """Launch 100% keyless official CLI OAuth Web SSO login in dedicated terminal console."""
    import os
    import subprocess

    pid = provider_id.lower().strip()
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
    
    keyless_args = {
        "anthropic": ["npx", "-y", "@anthropic-ai/claude-code", "auth", "login"],
        "google": ["gcloud", "auth", "application-default", "login"],
        "openai": ["npx", "-y", "@openai/codex", "login"],
        "x": ["npx", "-y", "grok-cli", "login"],
    }
    args = keyless_args.get(pid, keyless_args["openai"])
    command = ["cmd.exe", "/k", *args] if os.name == "nt" else args

    try:
        subprocess.Popen(
            command,
            cwd=cwd or os.getcwd(),
            creationflags=creationflags,
            shell=False,
        )
        return f"Launched 100% Keyless OAuth Sign-In for {pid.upper()} in console terminal."
    except Exception as exc:
        return str(exc)


def _combined_prompt(
    prompt: str,
    system: str | None,
    response_format: dict | str | None,
) -> str:
    parts = []
    if system:
        parts.append(f"System instructions:\n{system}")
    parts.append("Do not edit files or run tools. Return only the requested response.")
    if response_format == "json" or isinstance(response_format, dict):
        parts.append("Return valid JSON only, without a Markdown fence.")
    parts.append(f"User request:\n{prompt}")
    return "\n\n".join(parts)


def _extract_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        return "".join(filter(None, (_extract_text(item) for item in payload)))
    if not isinstance(payload, dict):
        return ""
    for key in ("response", "result", "text", "output_text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("message", "content", "output"):
        value = _extract_text(payload.get(key))
        if value:
            return value
    return ""


def _run_provider(
    command: list[str],
    *,
    prompt_input: str | None,
    timeout: int,
) -> str:
    if command:
        command = _build_cmd(command[0], command[1:])
    completed = subprocess.run(
        command,
        input=prompt_input,
        capture_output=True,
        text=True,
        timeout=max(1, timeout),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            (completed.stderr or completed.stdout or "Provider command failed.").strip()
        )

    output = completed.stdout.strip()
    try:
        value = _extract_text(json.loads(output))
        if value:
            return value
    except json.JSONDecodeError:
        pass

    final_text = ""
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                final_text = str(item.get("text") or final_text)
        else:
            final_text = _extract_text(event) or final_text
    if final_text:
        return final_text
    raise RuntimeError("Provider completed without a readable response.")


def query_account_provider(
    provider_id: str,
    model: str,
    prompt: str,
    system: str | None,
    response_format: dict | str | None,
    timeout: int,
) -> str:
    """Generate through an authenticated official command-line client."""
    executable = resolve_provider_executable(provider_id)
    if not executable:
        raise FileNotFoundError("Official command-line client is not installed or configured.")
    combined = _combined_prompt(prompt, system, response_format)

    if provider_id == "openai":
        command = [
            executable,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "--model",
            model,
            "-",
        ]
        return _run_provider(command, prompt_input=combined, timeout=timeout)
    if provider_id == "anthropic":
        command = [
            executable,
            "-p",
            "--output-format",
            "json",
            "--model",
            model,
            "--permission-mode",
            "plan",
            "--no-session-persistence",
        ]
        return _run_provider(command, prompt_input=combined, timeout=timeout)
    if provider_id == "x":
        command = [
            executable,
            "--no-auto-update",
            "-p",
            combined,
            "--output-format",
            "json",
            "--model",
            model,
            "--no-plan",
        ]
        return _run_provider(command, prompt_input=None, timeout=timeout)
    if provider_id == "google":
        command = [
            executable,
            "-p",
            combined,
            "--output-format",
            "json",
            "--model",
            model,
            "--mode",
            "plan",
        ]
        return _run_provider(command, prompt_input=None, timeout=timeout)
    raise ValueError(f"Unsupported account provider: {provider_id}")
