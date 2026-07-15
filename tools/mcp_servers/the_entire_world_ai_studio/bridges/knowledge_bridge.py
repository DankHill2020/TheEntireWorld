"""Knowledge index bridge."""

import os
import re
import subprocess

from PySide6.QtCore import QThread, Signal

from models.constants import APP_ROOT, V2_DB
from services.settings_service import install_components_to_tools


class KnowledgeBridge:
    """Access to the AST knowledge index."""

    @staticmethod
    def db_exists() -> bool:
        return V2_DB.exists()

    @staticmethod
    def db_path():
        return V2_DB


class IndexWorker(QThread):
    output = Signal(str)
    progress = Signal(int, int, int)
    finished_ok = Signal(bool, str)

    def __init__(self, roots):
        super().__init__()
        self.roots = roots
        self._stop = False

    def run(self):
        try:
            install_components_to_tools()
            indexer = APP_ROOT / "knowledge" / "build_knowledge_index_v2.py"
            if not indexer.exists():
                self.finished_ok.emit(False, f"Indexer not found: {indexer}")
                return

            env = os.environ.copy()
            env["AI_KNOWLEDGE_ROOTS"] = ";".join(self.roots)

            cmd = ["py", "-3.11", str(indexer)]
            self.output.emit("Starting AST index build...\n")
            self.output.emit("Roots:\n" + "\n".join(f"  - {r}" for r in self.roots) + "\n\n")

            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                bufsize=1,
                creationflags=creationflags,
            )

            scanned = 0
            updated = 0
            total_hint = 0

            for line in proc.stdout:
                if self._stop:
                    proc.kill()
                    self.finished_ok.emit(False, "Index build cancelled.")
                    return

                self.output.emit(line)

                if "Scanned files:" in line:
                    try:
                        scanned = int(line.split(":", 1)[1].strip())
                    except Exception:
                        pass
                elif "Updated files:" in line:
                    try:
                        updated = int(line.split(":", 1)[1].strip())
                    except Exception:
                        pass
                elif "Indexed/updated" in line:
                    m = re.search(r"Indexed/updated\s+(\d+)", line)
                    if m:
                        updated = int(m.group(1))

                self.progress.emit(scanned, total_hint, updated)

            code = proc.wait()
            ok = code == 0
            self.finished_ok.emit(ok, "Index build complete." if ok else f"Index build failed with code {code}.")
        except Exception as e:
            self.finished_ok.emit(False, str(e))

    def stop(self):
        self._stop = True
