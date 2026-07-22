from __future__ import annotations

"""Persistent terminal sessions and one-shot command workers for Tech Connector."""

import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot


@dataclass
class TerminalSessionConfig:
    cwd: str = ""
    shell: str = "powershell"
    startup_command: str = ""


def default_shell_args(shell: str = "powershell") -> list[str]:
    shell = (shell or "powershell").lower()
    if os.name == "nt":
        if shell in {"pwsh", "powershell7", "powershell-core"}:
            return ["pwsh", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass"]
        if shell in {"cmd", "cmd.exe"}:
            return ["cmd.exe"]
        return ["powershell", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    if shell in {"sh", "shell"}:
        return ["/bin/sh"]
    return ["/bin/bash", "-i"]


class _TerminalReader(QThread):
    output = Signal(str)
    exited = Signal(int)

    def __init__(self, process: subprocess.Popen):
        super().__init__()
        self.process = process
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            assert self.process.stdout is not None
            while self._running:
                char = self.process.stdout.read(1)
                if char:
                    self.output.emit(char)
                    continue
                if self.process.poll() is not None:
                    break
            self.exited.emit(int(self.process.poll() or 0))
        except Exception as exc:
            self.output.emit(f"\n[terminal reader error] {exc}\n")
            try:
                self.exited.emit(int(self.process.poll() or -1))
            except Exception:
                self.exited.emit(-1)


class TerminalSession(QObject):
    output = Signal(str)
    started = Signal()
    exited = Signal(int)

    def __init__(self, config: TerminalSessionConfig | None = None, parent=None):
        super().__init__(parent)
        self.config = config or TerminalSessionConfig()
        self.process: subprocess.Popen | None = None
        self.reader: _TerminalReader | None = None

    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    def start(self):
        if self.is_running():
            return

        cwd = Path(self.config.cwd or os.getcwd()).expanduser()
        if not cwd.exists():
            cwd = Path.cwd()

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        # Make prompt output predictable enough for embedded display.
        env.setdefault("TERM", "xterm")

        args = default_shell_args(self.config.shell)
        self.process = subprocess.Popen(
            args,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=0,
            env=env,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt"
                else 0
            ),
        )

        self.reader = _TerminalReader(self.process)
        self.reader.output.connect(self.output)
        self.reader.exited.connect(self._on_exited)
        self.reader.start()

        self.started.emit()
        self.output.emit(f"[Tech Connector terminal started in {cwd}]\n")

        if os.name == "nt" and args[0].lower().startswith("powershell"):
            # Keep PowerShell prompt anchored to the active cwd.
            self.send("$host.UI.RawUI.WindowTitle = 'Tech Connector Terminal'")
            self.send("function prompt { 'PS ' + (Get-Location) + '> ' }")
        if self.config.startup_command:
            self.send(self.config.startup_command)

    @Slot(str)
    def send(self, text: str):
        if not self.is_running():
            self.start()
        if not self.process or not self.process.stdin:
            return
        try:
            self.process.stdin.write((text or "") + "\n")
            self.process.stdin.flush()
        except Exception as exc:
            self.output.emit(f"\n[terminal send error] {exc}\n")

    def cd(self, path: str):
        if not path:
            return
        safe = str(Path(path).expanduser())
        if os.name == "nt":
            safe = safe.replace("'", "''")
            self.send(f"Set-Location -LiteralPath '{safe}'")
        else:
            safe = safe.replace("'", "'\"'\"'")
            self.send(f"cd '{safe}'")

    def interrupt(self):
        if not self.process:
            return
        try:
            if os.name == "nt":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                self.process.send_signal(signal.SIGINT)
        except Exception:
            try:
                self.process.terminate()
            except Exception:
                pass

    def close(self):
        if self.reader:
            self.reader.stop()
        if self.process and self.process.poll() is None:
            try:
                self.send("exit")
            except Exception:
                pass
            try:
                self.process.terminate()
            except Exception:
                pass

    def _on_exited(self, code: int):
        self.output.emit(f"\n[terminal exited: {code}]\n")
        self.exited.emit(code)


DESTRUCTIVE_MARKERS = (
    " rm ", " del ", " rmdir ", " remove-item", " format ", " mkfs",
    " shutdown", " restart-computer", " git reset", " git clean",
    " p4 revert", " p4 delete", " p4 obliterate",
)


@dataclass
class TerminalCommand:
    command: str
    cwd: str = ""
    shell: bool = True
    label: str = "Terminal"


def looks_destructive(command: str) -> bool:
    text = f" {command or ''} ".lower()
    return any(marker in text for marker in DESTRUCTIVE_MARKERS)


def default_shell_command(command: str) -> list[str] | str:
    if os.name == "nt":
        return [
            "powershell", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-Command", command,
        ]
    return ["/bin/bash", "-lc", command]


class TerminalWorker(QThread):
    output = Signal(str)
    finished_with_result = Signal(bool, int, str)

    def __init__(self, command: TerminalCommand):
        super().__init__()
        self.command = command
        self._process: subprocess.Popen | None = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        proc = self._process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def run(self):
        command = (self.command.command or "").strip()
        if not command:
            self.finished_with_result.emit(False, -1, "No command provided.")
            return

        cwd = Path(self.command.cwd or os.getcwd()).expanduser()
        if not cwd.exists():
            cwd = Path.cwd()

        self.output.emit(f"$ {command}\n")
        self.output.emit(f"[cwd] {cwd}\n\n")

        try:
            args = default_shell_command(command) if self.command.shell else shlex.split(command)
            env = os.environ.copy()
            env.setdefault("PYTHONUNBUFFERED", "1")
            env.setdefault("PYTHONIOENCODING", "utf-8")

            self._process = subprocess.Popen(
                args, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                bufsize=1, universal_newlines=True, env=env,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt"
                    else 0
                ),
            )
            assert self._process.stdout is not None
            while True:
                line = self._process.stdout.readline()
                if line:
                    self.output.emit(line)
                    continue
                if self._process.poll() is not None:
                    remainder = self._process.stdout.read()
                    if remainder:
                        self.output.emit(remainder)
                    break
            exit_code = self._process.wait()
            ok = exit_code == 0 and not self._cancelled
            status = "cancelled" if self._cancelled else ("ok" if ok else "failed")
            self.finished_with_result.emit(ok, int(exit_code), status)
        except Exception as exc:
            self.output.emit(f"\n[terminal error] {exc}\n")
            self.finished_with_result.emit(False, -1, str(exc))
