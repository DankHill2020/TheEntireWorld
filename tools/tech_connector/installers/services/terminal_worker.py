from __future__ import annotations

"""Terminal/process execution worker for Tech Connector."""

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal


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
