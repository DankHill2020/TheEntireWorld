"""Background knowledge-index orchestration for Tech Connector.

This service keeps the UI responsive while building the searchable index and the
heavier dependency graph. It runs the build script as a subprocess so long AST /
SQLite work cannot freeze Qt.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal


UPDATED_RE = re.compile(r"Indexed/updated\s+(\d+)\s+files", re.IGNORECASE)
SUMMARY_RE = re.compile(
    r"^(Scanned files|Updated files|Indexed files|Chunks|Symbols|Calls|Imports|File dependencies):\s*(\d+)",
    re.IGNORECASE,
)


class KnowledgeBuildPhase:
    BOOTSTRAP_SYMBOLS = "bootstrap_symbols"
    QUICK_INDEX = "quick_index"
    DEPENDENCY_GRAPH = "dependency_graph"
    FULL_REBUILD = "full_rebuild"


class KnowledgeBuildWorker(QThread):
    """Run index/graph builds without blocking the UI."""

    output = Signal(str)
    status = Signal(str)
    progress = Signal(int, int, str)  # current, total/0 unknown, phase label
    finished_ok = Signal(bool, str)

    def __init__(
        self,
        project_root: str | None = None,
        phase: str = KnowledgeBuildPhase.QUICK_INDEX,
        python_exe: str | None = None,
        verbose_output: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.project_root = str(project_root or "").strip()
        self.phase = phase
        self.python_exe = python_exe or sys.executable
        self.verbose_output = bool(verbose_output)
        self._stop_requested = False
        self._proc: subprocess.Popen | None = None
        self.last_output_tail: list[str] = []
        self.summary_metrics: dict[str, int] = {}

    def stop(self):
        self._stop_requested = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def _creationflags(self):
        return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    def _base_cmd(self) -> list[str]:
        cmd = [self.python_exe, "-X", "faulthandler", "-u", "-m", "knowledge.build_knowledge_index_v2"]
        if self.project_root:
            cmd.extend(["--root", self.project_root])
        return cmd

    def _phase_cmds(self) -> list[tuple[str, list[str]]]:
        base = self._base_cmd()
        if self.phase == KnowledgeBuildPhase.BOOTSTRAP_SYMBOLS:
            return [("Bootstrap files / symbols", base + ["--symbols-only", "--no-graph"])]
        if self.phase == KnowledgeBuildPhase.QUICK_INDEX:
            # Fast foreground/background task: stale files, symbols, chunks, and FTS only.
            # The graph is launched separately by the UI after this succeeds.
            return [("Files / symbols / search tables", base + ["--no-graph"])]
        if self.phase == KnowledgeBuildPhase.DEPENDENCY_GRAPH:
            return [("Dependency graph", base + ["--graph-only", "--no-fts"])]
        return [("Full index rebuild", base + ["--full"])]

    def _record_output(self, line: str) -> None:
        self.last_output_tail.append(line.rstrip())
        if len(self.last_output_tail) > 80:
            self.last_output_tail = self.last_output_tail[-80:]

    def _failure_message(self, label: str, code: int) -> str:
        tail = "\n".join(self.last_output_tail[-40:]).strip()
        cmd = " ".join(self._proc.args) if self._proc is not None else ""
        msg = f"{label} failed with exit code {code}."
        if cmd:
            msg += f"\n\nCommand:\n{cmd}"
        if tail:
            msg += f"\n\nLast output:\n{tail}"
        return msg

    def run(self):
        try:
            for label, cmd in self._phase_cmds():
                if self._stop_requested:
                    self.finished_ok.emit(False, "Knowledge build cancelled.")
                    return

                self.status.emit(label)
                if self.verbose_output:
                    self.output.emit(f"\n[Knowledge] Starting {label}...\n")
                    self.output.emit(f"[Knowledge] Command: {' '.join(cmd)}\n")
                self.progress.emit(0, 0, label)

                self._proc = subprocess.Popen(
                    cmd,
                    cwd=str(Path(__file__).resolve().parent.parent),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=self._creationflags(),
                )

                assert self._proc.stdout is not None
                for line in self._proc.stdout:
                    if self._stop_requested:
                        self.stop()
                        self.finished_ok.emit(False, "Knowledge build cancelled.")
                        return

                    self._record_output(line)
                    clean = line.strip()

                    m = UPDATED_RE.search(clean)
                    if m:
                        self.progress.emit(int(m.group(1)), 0, label)

                    if "Rebuilding dependency graph" in clean:
                        self.status.emit("Dependency graph")
                        self.progress.emit(0, 0, "Dependency graph")
                    elif "Rebuilding FTS tables" in clean:
                        self.status.emit("Search tables")
                        self.progress.emit(0, 0, "Search tables")
                    elif "FTS rebuild complete" in clean:
                        self.progress.emit(1, 1, "Search tables")

                    sm = SUMMARY_RE.search(clean)
                    if sm:
                        key = sm.group(1)
                        value = int(sm.group(2))
                        self.summary_metrics[key] = value

                code = self._proc.wait()
                if code != 0:
                    self.finished_ok.emit(False, self._failure_message(label, code))
                    return

                self.progress.emit(1, 1, label)
                if self.verbose_output:
                    self.output.emit(f"[Knowledge] Finished {label}.\n")

            if self.phase == KnowledgeBuildPhase.BOOTSTRAP_SYMBOLS:
                self.status.emit("Symbols ready")
                indexed = int(self.summary_metrics.get("Indexed files", 0))
                updated = int(self.summary_metrics.get("Updated files", 0))
                self.finished_ok.emit(True, f"Knowledge bootstrap ready: {indexed} files known, {updated} files updated for symbol search. Rich search tables can build in the background.")
            elif self.phase == KnowledgeBuildPhase.QUICK_INDEX:
                self.status.emit("Index ready")
                updated = int(self.summary_metrics.get("Updated files", 0))
                if updated:
                    self.finished_ok.emit(True, f"Knowledge quick index updated {updated} file(s). Dependency graph can build in the background.")
                else:
                    self.finished_ok.emit(True, "Knowledge quick index found no stale files. Dependency graph rebuild skipped.")
            elif self.phase == KnowledgeBuildPhase.DEPENDENCY_GRAPH:
                self.status.emit("Graph ready")
                self.finished_ok.emit(True, "Knowledge dependency graph is ready. Project health analysis is now available.")
            else:
                self.status.emit("Ready")
                self.finished_ok.emit(True, "Knowledge index, dependency graph, and project health analysis are ready.")

        except Exception as exc:
            tail = "\n".join(self.last_output_tail[-40:]).strip()
            msg = f"Knowledge build failed: {exc}"
            if tail:
                msg += f"\n\nLast output:\n{tail}"
            self.finished_ok.emit(False, msg)
