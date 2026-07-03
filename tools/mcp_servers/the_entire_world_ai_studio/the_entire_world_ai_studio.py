import json
import base64
import ast
import socket
import urllib.request
import urllib.error
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, QRect, QSize
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QKeySequence, QPixmap, QTextCursor, QColor, QPainter, QTextFormat, QTextCharFormat, QSyntaxHighlighter, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
    QTextEdit, QVBoxLayout, QWidget, QTreeWidget, QTreeWidgetItem, QTabWidget, QStyle, QMenu, QToolButton, QSizePolicy, QMenu, QToolButton
)

APP_ROOT = Path(__file__).parent
LOGO_PATH = APP_ROOT / "assets" / "the_entire_world_logo.png"

APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TA_AI_Studio_MCPHost"
HISTORY_DIR = APP_DIR / "history"
IMAGE_DIR = APP_DIR / "images"
SETTINGS_PATH = APP_DIR / "settings.json"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

TOOLS_ROOT = Path(r"C:\depot\tools")
KNOWLEDGE_DIR = TOOLS_ROOT / "mcp_servers" / "knowledge_mcp"
V2_DB = TOOLS_ROOT / "knowledge" / "index" / "knowledge_index_v2.sqlite"

DEFAULT_MCPHOST = os.path.join(os.path.expanduser("~"), "go", "bin", "mcphost.exe")
DEFAULT_MODEL = "ollama:qwen3:8b"
DEFAULT_CONFIGS = [
    r"C:\depot\tools\mcp_unreal_maya_knowledge_config.json",
    r"C:\Users\Aaron\.gemini\antigravity\mcp_unreal_maya_knowledge_config.json",
    r"C:\Users\Aaron\.gemini\antigravity\mcp_unrealpy_config.json",
]

ASSUMED_DIRS = [
    r"C:\depot\tools",
    r"C:\Desktop\MayaMCP",
    r"C:\Desktop\UnrealGenAISupport",
    r"C:\depot\Time_Fighters 5.8",
    r"C:\Program Files\Autodesk\Maya2023\devkit",
    r"C:\Program Files\Autodesk\Maya2023\Python",
    r"C:\Program Files\Autodesk\Maya2023\scripts",
    r"C:\Program Files\Autodesk\Maya2023\plug-ins",
    r"C:\Users\Aaron\Documents\maya\scripts",
    r"C:\Program Files\Epic Games\UE_5.8\Engine\Plugins",
    r"C:\Program Files\Epic Games\UE_5.8\Engine\Source",
    r"C:\Program Files\Epic Games\UE_5.8\Engine\Content\Python",
]

ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

PRIME_PROMPT = (
    "Use tools before answering. Do not invent internal function names. "
    "For Aaron tools call knowledge__symbol_search or knowledge__knowledge_search first. "
    "For exact code use knowledge__read_symbol_source. "
    "For simple Maya/Unreal host queries, prefer direct UI host actions. For Maya code through MCP use maya__maya_execute_python with print(...). For Unreal through MCP use UnrealGenAI tools. For MotionBuilder use motionbuilder__motionbuilder_execute_python with print(...). "
    "For Unreal use UnrealGenAI tools. Never delete/overwrite/save/submit/mass rename "
    "without explicit confirmation. Be direct."
)


def best_config():
    for p in DEFAULT_CONFIGS:
        if Path(p).exists():
            return p
    return DEFAULT_CONFIGS[0]


def load_settings():
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "extra_dirs": [],
        "first_run_complete": False,
        "model": DEFAULT_MODEL,
        "config": best_config(),
        "auto_index_on_first_run": True,
    }


def save_settings(data):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def install_components_to_tools():
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    for name in ["build_knowledge_index_v2.py", "knowledge_mcp_server_v2.py"]:
        src = APP_ROOT / name
        if src.exists():
            shutil.copy2(src, KNOWLEDGE_DIR / name)

    maya_src = APP_ROOT / "maya_mcp_server_quiet.py"
    maya_dst_dir = Path(r"C:\Desktop\UnrealGenAISupport\Content\Python")
    maya_dst_dir.mkdir(parents=True, exist_ok=True)
    if maya_src.exists():
        shutil.copy2(maya_src, maya_dst_dir / "maya_mcp_server_quiet.py")


def update_mcp_config():
    cfg = Path(r"C:\depot\tools\mcp_unreal_maya_knowledge_config.json")
    if cfg.exists():
        try:
            shutil.copy2(cfg, Path(str(cfg) + ".bak"))
        except Exception:
            pass

    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            data = {"mcpServers": {}}
    else:
        data = {"mcpServers": {}}

    servers = data.setdefault("mcpServers", {})
    servers["knowledge"] = {
        "type": "stdio",
        "command": "py",
        "args": ["-3.11", r"C:\depot\tools\mcp_servers\knowledge_mcp\knowledge_mcp_server_v2.py"],
    }
    servers["maya"] = {
        "type": "stdio",
        "command": "py",
        "args": ["-3.11", r"C:\Desktop\UnrealGenAISupport\Content\Python\maya_mcp_server_quiet.py"],
    }

    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return str(cfg)


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
            indexer = KNOWLEDGE_DIR / "build_knowledge_index_v2.py"
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

                # We do not know total without doing a duplicate pre-scan, so progress bar is activity + counts.
                self.progress.emit(scanned, total_hint, updated)

            code = proc.wait()
            ok = code == 0
            self.finished_ok.emit(ok, "Index build complete." if ok else f"Index build failed with code {code}.")
        except Exception as e:
            self.finished_ok.emit(False, str(e))

    def stop(self):
        self._stop = True



class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self):
        return QSize(self.code_editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.code_editor.line_number_area_paint_event(event)


class SimpleCodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)

        self.keyword_format = QTextCharFormat()
        self.keyword_format.setForeground(QColor("#7aa2f7"))
        self.keyword_format.setFontWeight(QFont.Bold)

        self.string_format = QTextCharFormat()
        self.string_format.setForeground(QColor("#9ece6a"))

        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#565f89"))

        self.number_format = QTextCharFormat()
        self.number_format.setForeground(QColor("#ff9e64"))

        self.function_format = QTextCharFormat()
        self.function_format.setForeground(QColor("#bb9af7"))
        self.function_format.setFontWeight(QFont.Bold)

        self.class_format = QTextCharFormat()
        self.class_format.setForeground(QColor("#2ac3de"))
        self.class_format.setFontWeight(QFont.Bold)

        self.keywords = {
            "False", "None", "True", "and", "as", "assert", "async", "await",
            "break", "class", "continue", "def", "del", "elif", "else", "except",
            "finally", "for", "from", "global", "if", "import", "in", "is",
            "lambda", "nonlocal", "not", "or", "pass", "raise", "return",
            "try", "while", "with", "yield", "self"
        }

    def highlightBlock(self, text):
        # Comments
        comment_index = text.find("#")
        if comment_index >= 0:
            self.setFormat(comment_index, len(text) - comment_index, self.comment_format)

        # Strings
        for pattern in [r'"[^"\\]*(\\.[^"\\]*)*"', r"'[^'\\]*(\\.[^'\\]*)*'"]:
            for m in re.finditer(pattern, text):
                self.setFormat(m.start(), m.end() - m.start(), self.string_format)

        # Numbers
        for m in re.finditer(r"\b\d+(\.\d+)?\b", text):
            self.setFormat(m.start(), m.end() - m.start(), self.number_format)

        # Python keywords
        for word in self.keywords:
            for m in re.finditer(rf"\b{re.escape(word)}\b", text):
                self.setFormat(m.start(), m.end() - m.start(), self.keyword_format)

        # Function/class definitions
        for m in re.finditer(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)", text):
            self.setFormat(m.start(1), len(m.group(1)), self.function_format)
        for m in re.finditer(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", text):
            self.setFormat(m.start(1), len(m.group(1)), self.class_format)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.highlighter = SimpleCodeHighlighter(self.document())

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)

        self.update_line_number_area_width(0)
        self.highlight_current_line()

        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#0f1419"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        painter.setPen(QColor("#6b7280"))

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    number
                )

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self):
        selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#1a2b20"))
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            selections.append(selection)
        self.setExtraSelections(selections)

    def keyPressEvent(self, event):
        # Basic IDE indentation.
        if event.key() == Qt.Key_Tab:
            self.insertPlainText("    ")
            return

        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            block_text = cursor.block().text()
            indent = re.match(r"\s*", block_text).group(0)
            extra = "    " if block_text.rstrip().endswith(":") else ""
            super().keyPressEvent(event)
            self.insertPlainText(indent + extra)
            return

        super().keyPressEvent(event)

    def goto_line(self, line_number):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.Start)
        for _ in range(max(0, line_number - 1)):
            cursor.movePosition(QTextCursor.Down)
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()


class FirstRunDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("The Entire World AI Setup")
        self.resize(900, 620)

        layout = QVBoxLayout(self)

        brand = QHBoxLayout()
        if LOGO_PATH.exists():
            logo = QLabel()
            logo.setPixmap(QPixmap(str(LOGO_PATH)).scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            brand.addWidget(logo)
        title = QLabel("The Entire World\nTechnical Art AI")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #00b866;")
        brand.addWidget(title)
        brand.addStretch(1)
        layout.addLayout(brand)

        info = QLabel(
            "Default knowledge roots are locked. Add project/tool folders below. "
            "They will be included in the AST index, but default roots cannot be removed."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.dir_list = QListWidget()
        for d in ASSUMED_DIRS:
            item = QListWidgetItem("[default] " + d)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.dir_list.addItem(item)

        for d in self.settings.get("extra_dirs", []):
            self.dir_list.addItem("[extra] " + d)

        layout.addWidget(self.dir_list, 1)

        row = QHBoxLayout()
        add_btn = QPushButton("Add Tool/Project Directory")
        add_btn.clicked.connect(self.add_dir)
        row.addWidget(add_btn)

        remove_btn = QPushButton("Remove Selected Extra")
        remove_btn.clicked.connect(self.remove_selected_extra)
        row.addWidget(remove_btn)
        layout.addLayout(row)

        self.auto_index = QCheckBox("Build AST knowledge index after setup")
        self.auto_index.setChecked(bool(self.settings.get("auto_index_on_first_run", True)))
        layout.addWidget(self.auto_index)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Add knowledge directory")
        if d:
            existing = [self.dir_list.item(i).text().replace("[extra] ", "").replace("[default] ", "") for i in range(self.dir_list.count())]
            if d not in existing:
                self.dir_list.addItem("[extra] " + d)

    def remove_selected_extra(self):
        for item in self.dir_list.selectedItems():
            if item.text().startswith("[extra] "):
                self.dir_list.takeItem(self.dir_list.row(item))

    def accept(self):
        extras = []
        for i in range(self.dir_list.count()):
            text = self.dir_list.item(i).text()
            if text.startswith("[extra] "):
                extras.append(text.replace("[extra] ", "", 1))
        self.settings["extra_dirs"] = extras
        self.settings["first_run_complete"] = True
        self.settings["auto_index_on_first_run"] = self.auto_index.isChecked()
        save_settings(self.settings)
        super().accept()



class TerminalBridge(QObject):
    output = Signal(str)
    exited = Signal(str)

    def __init__(self):
        super().__init__()
        self.mode = None
        self.pty = None
        self.proc = None
        self.running = False
        self.thread = None

    def start(self, command_args, env=None, use_pty=False):
        """
        Start MCPHost.

        Default is normal subprocess pipes, not PTY. MCPHost's terminal UI works visually
        in a real terminal, but PTY mode is fragile when driven from a GUI.
        """
        if self.running:
            return

        self.running = True
        env_full = os.environ.copy()
        if env:
            env_full.update(env)

        if use_pty:
            try:
                import winpty
                self.mode = "pty"
                self.pty = winpty.PTY(160, 48)
                command_line = subprocess.list2cmdline(command_args)

                old_env = {}
                for key, value in (env or {}).items():
                    old_env[key] = os.environ.get(key)
                    os.environ[key] = value

                try:
                    self.pty.spawn(command_line)
                finally:
                    for key, old_value in old_env.items():
                        if old_value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = old_value

                self.output.emit("[PTY active]\n")
                self.thread = threading.Thread(target=self._read_pty, daemon=True)
                self.thread.start()
                return
            except Exception as e:
                self.output.emit(f"[PTY unavailable, using subprocess pipes: {e}]\n")

        self.mode = "pipes"
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self.proc = subprocess.Popen(
                command_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env_full,
                bufsize=1,
                shell=False,
                creationflags=creationflags,
            )
        except Exception as e:
            self.running = False
            self.exited.emit(f"Failed to start MCPHost: {e}")
            return

        self.output.emit("[subprocess pipe active]\n")
        self.thread = threading.Thread(target=self._read_pipes, daemon=True)
        self.thread.start()

    def _read_pty(self):
        consecutive_errors = 0
        try:
            while self.running and self.pty:
                try:
                    try:
                        data = self.pty.read(blocking=True)
                    except TypeError:
                        data = self.pty.read(True)

                    consecutive_errors = 0
                    if data:
                        self.output.emit(data)
                    else:
                        time.sleep(0.03)

                except EOFError:
                    break
                except Exception as e:
                    consecutive_errors += 1
                    msg = str(e).strip()

                    if not msg and consecutive_errors < 10:
                        time.sleep(0.1)
                        continue

                    self.output.emit(f"\n[PTY read warning: {msg or 'transient empty read'}]\n")

                    if consecutive_errors >= 10:
                        break

                    time.sleep(0.1)
        finally:
            self.running = False
            self.exited.emit("MCPHost exited.")

    def _read_pipes(self):
        try:
            while self.running and self.proc:
                line = self.proc.stdout.readline()
                if not line:
                    if self.proc.poll() is not None:
                        break
                    time.sleep(0.03)
                    continue
                self.output.emit(line)
        finally:
            self.running = False
            self.exited.emit("MCPHost exited.")

    def _one_line_prompt(self, text: str) -> str:
        """
        MCPHost is an interactive terminal prompt. Sending literal newlines can submit
        partial prompts early. Convert multiline text into one terminal line with visible
        \\n escapes.
        """
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.replace("\n", "\\n")

    def write(self, text):
        if not self.running:
            return False

        line = self._one_line_prompt(text)

        try:
            if self.mode == "pty" and self.pty:
                # Bubble Tea / textarea apps behave better when programmatic input is
                # delivered as bracketed paste instead of simulated raw typing.
                # Send CR only. Sending CRLF can be interpreted as an extra control
                # event by some terminal UIs and has caused MCPHost to quit/Goodbye.
                self.pty.write("\x1b[200~")
                self.pty.write(line)
                self.pty.write("\x1b[201~")
                self.pty.write("\r")
                return True

            if self.mode == "pipes" and self.proc and self.proc.stdin:
                self.proc.stdin.write(line + "\n")
                self.proc.stdin.flush()
                return True
        except Exception as e:
            self.output.emit(f"\n[Send failed: {e}]\n")
            return False

        return False

    def stop(self):
        self.running = False
        try:
            if self.mode == "pty" and self.pty:
                self.pty.close()
        except Exception:
            pass
        try:
            if self.proc:
                self.proc.kill()
        except Exception:
            pass


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle("The Entire World AI Studio v6.7")
        self.resize(1540, 960)
        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        self.bridge = TerminalBridge()
        self.bridge.output.connect(self.handle_output)
        self.bridge.exited.connect(self.on_finished)

        self.index_worker = None
        self.current_session = []
        self.attached_images = []
        self.code_snippets = []
        self._status_once = set()
        self._last_stream_line = ""
        self.ready_for_prompt = False
        self.pending_prime = False
        self.last_user_prompt = ""
        self.last_assistant_output = ""
        self.last_tool_output = ""
        self.mcphost_started_at = 0
        self.mcphost_ready = False
        self.mcphost_use_pty = False
        self._seen_tool_results = set()
        self._seen_compact_lines = set()
        self.pending_editor_patch = None

        self.build_ui()
        self.apply_branding()
        self.update_initial_status_cards()
        self.refresh_history()
        self.load_project_tree_lazy()
        self.append("Ready. Configure/index project, then start MCPHost.\n\n")

        if not self.settings.get("first_run_complete"):
            QTimer.singleShot(350, self.show_first_run)
        elif not V2_DB.exists():
            self.append("[Index v2 not found. Use Build/Rebuild Index before relying on tool search.]\n")

    def all_roots(self):
        roots = []
        for r in ASSUMED_DIRS + self.settings.get("extra_dirs", []):
            if r not in roots:
                roots.append(r)
        return roots

    def update_cursor_status(self):
        if not hasattr(self, "editor_status_label"):
            return
        cursor = self.code_editor.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.positionInBlock() + 1
        dirty = " • modified" if self.code_editor.document().isModified() else ""
        self.editor_status_label.setText(f"Line {line}, Col {col}{dirty}")

    def find_in_current_file(self):
        if not hasattr(self, "code_editor"):
            return
        query = self.editor_find.text().strip()
        if not query:
            return

        flags = QTextDocument.FindFlags()
        found = self.code_editor.find(query, flags)
        if not found:
            cursor = self.code_editor.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.code_editor.setTextCursor(cursor)
            found = self.code_editor.find(query, flags)

        if not found:
            self.append(f"\n[Find in file] No match for: {query}\n")

    def goto_line_from_box(self):
        text = self.goto_line_box.text().strip()
        if not text:
            return
        try:
            self.code_editor.goto_line(int(text))
        except Exception:
            self.append(f"\n[Go To Line] Invalid line: {text}\n")

    def duplicate_current_line(self):
        cursor = self.code_editor.textCursor()
        cursor.select(QTextCursor.LineUnderCursor)
        line = cursor.selectedText()
        cursor.movePosition(QTextCursor.EndOfLine)
        cursor.insertText("\n" + line)
        self.update_cursor_status()

    def comment_selection_python_style(self):
        cursor = self.code_editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.LineUnderCursor)

        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        start_block = cursor.blockNumber()
        cursor.setPosition(end)
        end_block = cursor.blockNumber()

        cursor.beginEditBlock()
        for block_no in range(start_block, end_block + 1):
            block = self.code_editor.document().findBlockByNumber(block_no)
            c = QTextCursor(block)
            text = block.text()
            stripped = text.lstrip()
            indent_len = len(text) - len(stripped)
            c.setPosition(block.position() + indent_len)
            if stripped.startswith("#"):
                c.deleteChar()
                if c.block().text()[indent_len:indent_len+1] == " ":
                    c.deleteChar()
            else:
                c.insertText("# ")
        cursor.endEditBlock()

    def format_python_basic(self):
        # Conservative whitespace cleanup only; no formatter dependency.
        text = self.code_editor.toPlainText()
        lines = [line.rstrip() for line in text.splitlines()]
        self.code_editor.setPlainText("\n".join(lines) + ("\n" if text.endswith("\n") else ""))
        self.append("\n[Editor] Trimmed trailing whitespace.\n")

    def _question_terms(self, question):
        raw_terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", question.lower())
        stop = {"is","there","a","an","the","that","to","in","of","for","with","does","do","class","function","method","file","this","are","any"}
        terms = [t for t in raw_terms if t not in stop and len(t) > 2]
        expansions = {
            "browse": ["browse","browser","browses","browsing","select","choose","pick","open"],
            "directory": ["directory","dir","folder","path"],
            "folder": ["folder","directory","dir","path"],
            "button": ["button","btn","pushbutton","qpushbutton"],
            "widget": ["widget","qwidget","control"],
        }
        expanded = set(terms)
        for t in list(terms):
            for key, vals in expansions.items():
                if t == key or t in vals:
                    expanded.update(vals)
        return sorted(expanded)

    def _extract_python_symbols_from_text(self, text):
        symbols = []
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except Exception:
            return symbols
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = getattr(node, "name", "")
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                start = getattr(node, "lineno", 1)
                end = getattr(node, "end_lineno", start)
                source = "\n".join(lines[start-1:end])
                doc = ast.get_docstring(node) or ""
                methods = []
                if isinstance(node, ast.ClassDef):
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            methods.append(child.name)
                symbols.append({
                    "name": name, "kind": kind, "start": start, "end": end,
                    "doc": doc, "methods": methods, "source": source,
                    "search": "\n".join([name, kind, doc, " ".join(methods), source]).lower(),
                })
        return symbols

    def _rank_symbols_for_question(self, symbols, terms):
        ranked = []
        for sym in symbols:
            score = 0
            name_low = sym["name"].lower()
            method_low = " ".join(sym["methods"]).lower()
            for term in terms:
                if term in name_low:
                    score += 12
                if term in sym["doc"].lower():
                    score += 6
                if term in method_low:
                    score += 5
                count = sym["search"].count(term)
                if count:
                    score += min(count, 10)
            if sym["kind"] == "class":
                score += 2
            if score:
                ranked.append((score, sym))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked

    def _build_safe_patch_for_symbol(self, path, sym):
        """
        Build small deterministic patches for obvious local bugs.

        This is intentionally conservative. It only prepares a patch when we can
        identify a simple, high-confidence issue.
        """
        source = sym.get("source", "")
        name = sym.get("name", "")

        if (
            name == "BrowseDirectory"
            and "directory=None" in source
            and "directory.replace" in source
            and "QtWidgets.QLineEdit" in source
        ):
            new_source = source.replace(
                "        self.directory = directory\n",
                "        if directory is None:\n"
                "            directory = \"\"\n"
                "        self.directory = directory.replace('\\\\\\\\', '/')\n"
            )
            new_source = new_source.replace(
                "        self.dir_name = QtWidgets.QLineEdit(directory.replace('\\\\\\\\', '/'))",
                "        self.dir_name = QtWidgets.QLineEdit(self.directory)"
            )

            if new_source != source:
                return {
                    "path": path,
                    "symbol": name,
                    "start": sym.get("start"),
                    "end": sym.get("end"),
                    "old": source,
                    "new": new_source,
                    "summary": "Guard `directory=None` and initialize the line edit from the normalized stored directory.",
                }

        return None

    def apply_pending_editor_patch(self):
        patch = getattr(self, "pending_editor_patch", None)
        if not patch:
            QMessageBox.information(self, "No patch", "No safe pending patch is available yet.")
            return

        path = Path(patch["path"])
        if not path.exists():
            QMessageBox.critical(self, "Patch failed", f"File not found: {path}")
            return

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            old = patch["old"]
            new = patch["new"]

            if old not in text:
                QMessageBox.critical(
                    self,
                    "Patch failed",
                    "The original code block was not found. The file may have changed. Re-open the file and ask again."
                )
                return

            backup = path.with_suffix(path.suffix + ".tew_backup")
            if not backup.exists():
                backup.write_text(text, encoding="utf-8")

            updated = text.replace(old, new, 1)
            path.write_text(updated, encoding="utf-8")

            if getattr(self, "current_file_path", "") == str(path):
                self.code_editor.setPlainText(updated)
                self.code_editor.document().setModified(False)
                self.update_cursor_status()

            self.append(
                "\\n[Applied Editor Patch]\\n"
                f"File: {path}\\n"
                f"Change: {patch.get('summary', 'Applied safe local patch.')}\\n"
                f"Backup: {backup}\\n"
            )
            self.pending_editor_patch = None

        except Exception as e:
            QMessageBox.critical(self, "Patch failed", str(e))

    def _summarize_python_symbol(self, sym, question):
        """
        Produce a useful local explanation with the code reference first,
        then the actual explanation below it.
        """
        source = sym.get("source", "")
        name = sym.get("name", "")
        kind = sym.get("kind", "symbol")
        methods = sym.get("methods", [])

        out = []

        out.append("Relevant source excerpt:")
        lang = "python"
        out.append(f"```{lang}\n{source[:2600]}\n```")
        out.append("")

        out.append("Explanation:")
        out.append(f"`{name}` is a Python {kind} defined on lines {sym.get('start')}-{sym.get('end')}.")

        if kind == "class":
            bases = ""
            try:
                tree = ast.parse(source)
                cls = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)), None)
                if cls:
                    base_names = []
                    for b in cls.bases:
                        try:
                            base_names.append(ast.unparse(b))
                        except Exception:
                            pass
                    if base_names:
                        bases = ", ".join(base_names)
            except Exception:
                pass

            if bases:
                out.append(f"It subclasses `{bases}`.")

            lowered = source.lower()
            responsibilities = []

            if "qfiledialog.getexistingdirectory" in lowered:
                responsibilities.append("opens a folder picker dialog so the user can choose a directory")
            if "qlineedit" in lowered:
                responsibilities.append("shows the current directory in an editable text field")
            if "qpushbutton" in lowered:
                responsibilities.append("provides a Browse button")
            if "textchanged.connect" in lowered:
                responsibilities.append("keeps its internal directory value synchronized when the user edits the text manually")
            if "replace('\\\\', '/')" in lowered or 'replace("\\\\", "/")' in lowered:
                responsibilities.append("normalizes Windows backslashes into forward slashes")
            if "partial(" in lowered:
                responsibilities.append("uses a partial/lambda callback to pass the line-edit widget into the browse handler")

            if responsibilities:
                out.append("")
                out.append("What it does:")
                for r in responsibilities:
                    out.append(f"- It {r}.")
            else:
                out.append("")
                out.append("What it does:")
                out.append("- It groups related UI behavior and state into a reusable class.")

            if methods:
                out.append("")
                out.append("Important methods:")
                for m in methods:
                    if m == "__init__":
                        out.append("- `__init__`: builds the widget layout, stores initial state, creates the line edit and Browse button, and wires UI signals.")
                    elif "get_dir" in m or "browse" in m:
                        out.append(f"- `{m}`: opens the directory browser and updates the stored directory if the user chooses one.")
                    elif "update" in m:
                        out.append(f"- `{m}`: updates internal state when the UI text changes.")
                    else:
                        out.append(f"- `{m}`")

            concerns = []
            if "directory.replace" in source and "directory=None" in source:
                concerns.append("`directory` defaults to `None`, but `directory.replace(...)` will crash if `None` is actually passed.")
            if "lambda:" in source and "partial(" in source:
                concerns.append("the signal connection is more complex than it needs to be; a normal method or lambda would be easier to read.")
            if "new_height = 10" in source:
                concerns.append("the repeated manual resize to height `10` looks suspicious and may produce cramped UI behavior.")
            if "self.tr('Select Export Directory')" in source:
                concerns.append("the dialog title says `Select Export Directory`, which may be too specific if the widget is meant to be generic.")

            if concerns:
                out.append("")
                out.append("Potential issues:")
                for c in concerns:
                    out.append(f"- {c}")

            out.append("")
            out.append("Direct answer:")
            if name.lower() == "browsedirectory":
                out.append("`BrowseDirectory` is a reusable Qt widget for displaying, editing, and browsing for a folder path. It combines a line edit and a Browse button, opens a directory picker, stores the selected path, and keeps the stored value updated when the user manually edits the text.")
            else:
                out.append(f"`{name}` is the best local match for your question based on its name, methods, and source.")

        else:
            out.append("")
            out.append("Direct answer:")
            out.append(f"`{name}` is a function. The local analyzer found it because its name/source matches your question.")
            src_low = source.lower()
            if "return" in src_low:
                out.append("- It returns a value.")
            if "print(" in src_low:
                out.append("- It prints output.")
            if "connect(" in src_low:
                out.append("- It connects UI/event behavior.")
            if "qfiledialog" in src_low:
                out.append("- It opens a Qt file/folder dialog.")

        return "\n".join(out)


    def local_answer_about_current_file(self, path, question):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[Editor Assist] Could not read file: {e}"

        terms = self._question_terms(question)
        ext = Path(path).suffix.lower()

        output = []
        output.append("Editor Assist")
        output.append(f"File: {path}")
        output.append(f"Question: {question}")
        output.append("")

        if ext == ".py":
            symbols = self._extract_python_symbols_from_text(text)
            ranked = self._rank_symbols_for_question(symbols, terms)

            if ranked:
                best_score, best = ranked[0]
                output.append(self._summarize_python_symbol(best, question))

                patch = self._build_safe_patch_for_symbol(path, best)
                self.pending_editor_patch = patch
                if patch:
                    output.append("")
                    output.append("Suggested fix available:")
                    output.append(f"- {patch['summary']}")
                    output.append("- Click `Apply Fix` in the Editor tab to apply it. A `.tew_backup` will be created first.")

                if len(ranked) > 1:
                    output.append("")
                    output.append("Other possible matches:")
                    for score, sym in ranked[1:6]:
                        output.append(f"- {sym['kind']} `{sym['name']}` lines {sym['start']}-{sym['end']} score {score}")

                output.append("")
                output.append("Answered locally from the open file without waiting on MCPHost/LLM.")
                return "\n".join(output)

        # Generic text fallback for non-Python or parse failure.
        hits = []
        for i, line in enumerate(text.splitlines(), start=1):
            score = sum(1 for t in terms if t in line.lower())
            if score:
                hits.append((score, i, line.strip()))

        hits.sort(key=lambda x: x[0], reverse=True)

        if hits:
            output.append("I found relevant lines, but this file type does not have rich local AST explanation yet:")
            for score, line_no, line in hits[:20]:
                output.append(f"- line {line_no}: {line[:220]}")
            output.append("")
            output.append("For a deeper explanation, select the relevant block and use Ask Selection.")
            return "\n".join(output)

        output.append("No obvious local matches found in the open file.")
        output.append("Try selecting the relevant code and using Ask Selection, or use the Search / Symbols tab.")
        return "\n".join(output)


    def ask_about_current_file(self):
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a file first.")
            return
        question = self.editor_prompt.text().strip()
        if not question:
            QMessageBox.information(self, "No question", "Type a question about the current file first.")
            return
        result = self.local_answer_about_current_file(path, question)
        self.last_user_prompt = question
        self.last_assistant_output = result
        self.workspace_tabs.setCurrentIndex(0)
        self.append("\nYOU [Editor Question]:\n" + question + "\n")
        self.append(result + "\n")


    def ask_about_file_with_llm(self):
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a file first.")
            return
        question = self.editor_prompt.text().strip()
        if not question:
            QMessageBox.information(self, "No question", "Type a question about the current file first.")
            return

        # Keep this concise so PTY does not get flooded.
        local_context = self.local_answer_about_current_file(path, question)
        prompt = f"""Improve this local code explanation for a non-technical/technical-artist user.

Question:
{question}

Local analysis:
```text
{local_context[:6000]}
```

Give a clear answer first, then mention relevant code details. Do not simply repeat the source.
"""
        self.workspace_tabs.setCurrentIndex(0)
        self.send_raw(prompt, "Editor LLM Question")

    def ask_about_selection(self):
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a file first.")
            return
        question = self.editor_prompt.text().strip() or "Explain this selected code and suggest improvements."
        cursor = self.code_editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n").strip()
        if not selected:
            QMessageBox.information(self, "No selection", "Select code in the editor first, or use Ask About File.")
            return
        if len(selected) > 8000:
            selected = selected[:8000] + "\n\n...[selection truncated]..."
        prompt = f"""Answer this question about selected code.

File:
{path}

Question:
{question}

Selected code:
```text
{selected}
```
"""
        self.workspace_tabs.setCurrentIndex(0)
        self.send_raw(prompt, "Editor Selection Question")


    def ask_for_edit_plan(self):
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a file first.")
            return
        request = self.editor_prompt.text().strip()
        if not request:
            QMessageBox.information(self, "No request", "Type the edit you want first.")
            return
        prompt = f"""Plan a safe edit for the currently open file.

File:
{path}

Requested change:
{request}

Use knowledge__read_tool_file with this file path to inspect contents before answering. Return:
1. What you would change.
2. Risks or dependencies.
3. A patch-style code block or replacement function if appropriate.
"""
        self.workspace_tabs.setCurrentIndex(0)
        self.send_raw(prompt, "Editor Edit Plan")


    def supported_code_exts(self):
        return {
            ".py", ".mel", ".cpp", ".h", ".hpp", ".cs", ".ts", ".tsx", ".js", ".jsx",
            ".html", ".css", ".json", ".yaml", ".yml", ".md", ".txt", ".ini", ".cfg",
            ".bat", ".ps1", ".usf", ".ush", ".uplugin", ".uproject"
        }

    def is_supported_code_file(self, path):
        try:
            return Path(path).suffix.lower() in self.supported_code_exts()
        except Exception:
            return False

    def load_project_tree(self):
        """Build an actual IDE-style folder hierarchy instead of a flat file list."""
        if not hasattr(self, "project_tree"):
            return

        self.project_tree.clear()

        max_files_per_root = 6000
        skip_dirs = {
            "__pycache__", ".git", ".svn", ".idea", ".vs",
            "Intermediate", "Saved", "DerivedDataCache", "Binaries",
            ".pytest_cache", "node_modules"
        }

        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

        for root_path in self.all_roots():
            root_p = Path(root_path)
            root_item = QTreeWidgetItem([root_p.name or str(root_p), str(root_p)])
            root_item.setIcon(0, folder_icon)
            self.project_tree.addTopLevelItem(root_item)

            if not root_p.exists():
                item = QTreeWidgetItem(["[missing]", str(root_p)])
                item.setIcon(0, file_icon)
                root_item.addChild(item)
                continue

            folder_items = {root_p: root_item}
            file_count = 0

            try:
                for p in sorted(root_p.rglob("*"), key=lambda x: str(x).lower()):
                    if file_count >= max_files_per_root:
                        item = QTreeWidgetItem([f"... truncated at {max_files_per_root} files ...", ""])
                        item.setIcon(0, file_icon)
                        root_item.addChild(item)
                        break

                    if any(part in skip_dirs for part in p.parts):
                        continue

                    try:
                        rel_parts = p.relative_to(root_p).parts
                    except Exception:
                        rel_parts = (p.name,)

                    parent_path = root_p
                    parent_item = root_item

                    for folder_name in rel_parts[:-1]:
                        parent_path = parent_path / folder_name
                        if parent_path not in folder_items:
                            folder_item = QTreeWidgetItem([folder_name, str(parent_path)])
                            folder_item.setIcon(0, folder_icon)
                            parent_item.addChild(folder_item)
                            folder_items[parent_path] = folder_item
                        parent_item = folder_items[parent_path]

                    if p.is_dir():
                        if p not in folder_items:
                            folder_item = QTreeWidgetItem([p.name, str(p)])
                            folder_item.setIcon(0, folder_icon)
                            parent_item.addChild(folder_item)
                            folder_items[p] = folder_item
                        continue

                    if not p.is_file() or not self.is_supported_code_file(p):
                        continue

                    file_item = QTreeWidgetItem([p.name, str(p)])
                    file_item.setIcon(0, file_icon)
                    parent_item.addChild(file_item)
                    file_count += 1

            except Exception as e:
                item = QTreeWidgetItem([f"[error: {e}]", str(root_p)])
                item.setIcon(0, file_icon)
                root_item.addChild(item)

            root_item.setExpanded(False)

        self.project_tree.resizeColumnToContents(0)

    def filter_project_tree(self, text):
        text = (text or "").lower().strip()

        def visit(item):
            own_match = not text or text in item.text(0).lower() or text in item.text(1).lower()
            child_match = False
            for i in range(item.childCount()):
                if visit(item.child(i)):
                    child_match = True
            visible = own_match or child_match
            item.setHidden(not visible)
            if text and child_match:
                item.setExpanded(True)
            return visible

        for i in range(self.project_tree.topLevelItemCount()):
            visit(self.project_tree.topLevelItem(i))

    def toggle_project_panel(self):
        if not hasattr(self, "left_panel") or not hasattr(self, "main_splitter"):
            return

        if self.left_panel.isVisible():
            sizes = self.main_splitter.sizes()
            if sizes and sizes[0] > 40:
                self._last_project_panel_width = sizes[0]
            self.left_panel.setVisible(False)
            self.toggle_project_btn.setText("Show")
        else:
            self.left_panel.setVisible(True)
            width = getattr(self, "_last_project_panel_width", 360)
            sizes = self.main_splitter.sizes()
            total = sum(sizes) if sizes else 1500
            self.main_splitter.setSizes([width, max(700, total - width)])
            self.toggle_project_btn.setText("Hide")

    def expand_project_panel(self):
        if not hasattr(self, "main_splitter"):
            return
        self.left_panel.setVisible(True)
        self.toggle_project_btn.setText("Hide")
        total = sum(self.main_splitter.sizes()) or 1500
        self.main_splitter.setSizes([520, max(700, total - 520)])

    def collapse_project_panel(self):
        if not hasattr(self, "main_splitter"):
            return
        self.left_panel.setVisible(True)
        self.toggle_project_btn.setText("Hide")
        total = sum(self.main_splitter.sizes()) or 1500
        self.main_splitter.setSizes([260, max(900, total - 260)])


    def load_project_tree_lazy(self):
        """Fast project tree: load roots immediately, then load folders only when expanded."""
        if not hasattr(self, "project_tree"):
            return
        self.project_tree.clear()
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        for root_path in self.all_roots():
            root_p = Path(root_path)
            root_item = QTreeWidgetItem([root_p.name or str(root_p), str(root_p)])
            root_item.setIcon(0, folder_icon)
            root_item.setData(0, Qt.UserRole, "folder")
            self.project_tree.addTopLevelItem(root_item)
            if root_p.exists():
                root_item.addChild(QTreeWidgetItem(["Loading...", ""]))
            else:
                root_item.addChild(QTreeWidgetItem(["[missing]", str(root_p)]))
        self.status.setText("Project roots loaded")

    def on_project_tree_expanded(self, item):
        path = item.text(1)
        if not path or item.data(0, Qt.UserRole + 1) == "loaded":
            return
        p = Path(path)
        if p.exists() and p.is_dir():
            self.populate_project_folder(item, p)
            item.setData(0, Qt.UserRole + 1, "loaded")

    def populate_project_folder(self, parent_item, folder_path):
        parent_item.takeChildren()
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        skip_dirs = {"__pycache__", ".git", ".svn", ".idea", ".vs", "Intermediate", "Saved", "DerivedDataCache", "Binaries", ".pytest_cache", "node_modules"}
        try:
            entries = sorted(folder_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except Exception as e:
            parent_item.addChild(QTreeWidgetItem([f"[error: {e}]", str(folder_path)]))
            return
        for child in entries:
            if child.name in skip_dirs:
                continue
            if child.is_dir():
                item = QTreeWidgetItem([child.name, str(child)])
                item.setIcon(0, folder_icon)
                item.setData(0, Qt.UserRole, "folder")
                try:
                    if any(True for _ in child.iterdir()):
                        item.addChild(QTreeWidgetItem(["Loading...", ""]))
                except Exception:
                    pass
                parent_item.addChild(item)
            elif child.is_file() and self.is_supported_code_file(child):
                item = QTreeWidgetItem([child.name, str(child)])
                item.setIcon(0, file_icon)
                item.setData(0, Qt.UserRole, "file")
                parent_item.addChild(item)

    def refresh_project_tree_fast(self):
        self.load_project_tree_lazy()
        self.append("\n[Project Tree] Refreshed roots. Expand folders to load contents.\n")

    def open_tree_file(self, item, column=0):
        path = item.text(1)
        if not path:
            return
        p = Path(path)
        if p.is_file() and self.is_supported_code_file(p):
            self.open_code_file(str(p))

    def open_code_file(self, path):
        p = Path(path)
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return

        self.current_file_path = str(p)
        self.file_path_label.setText(str(p))
        self.code_editor.setPlainText(txt)
        self.code_editor.document().setModified(False)
        self.update_cursor_status()
        self.append(f"\n[Opened file: {p}]\n")

    def save_code_file(self):
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "No file is currently open.")
            return

        p = Path(path)
        try:
            # Safety backup before editing.
            backup = p.with_suffix(p.suffix + ".tew_backup")
            if p.exists() and not backup.exists():
                backup.write_text(p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

            p.write_text(self.code_editor.toPlainText(), encoding="utf-8")
            self.code_editor.document().setModified(False)
            self.update_cursor_status()
            self.append(f"\n[Saved file: {p}]\n")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def find_in_project(self):
        query = self.project_search.text().strip()
        if not query:
            return

        self.search_results.clear()
        max_results = 250
        found = 0

        for root_path in self.all_roots():
            root_p = Path(root_path)
            if not root_p.exists():
                continue

            try:
                for p in root_p.rglob("*"):
                    if found >= max_results:
                        self.search_results.addItem("... truncated ...")
                        return

                    if not p.is_file() or not self.is_supported_code_file(p):
                        continue

                    try:
                        text = p.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue

                    low = text.lower()
                    q = query.lower()
                    if q not in low and q not in str(p).lower():
                        continue

                    line_no = 1
                    snippet = ""
                    for i, line in enumerate(text.splitlines(), start=1):
                        if q in line.lower():
                            line_no = i
                            snippet = line.strip()
                            break

                    try:
                        rel = p.relative_to(root_p)
                    except Exception:
                        rel = p

                    self.search_results.addItem(f"{p}::{line_no} — {snippet[:140]}")
                    found += 1
            except Exception:
                continue

        if found == 0:
            self.search_results.addItem("No results.")

    def open_search_result(self, item):
        text = item.text()
        if "::" not in text:
            return
        path, rest = text.split("::", 1)
        self.open_code_file(path)
        try:
            line_no = int(rest.split(" ", 1)[0])
            cursor = self.code_editor.textCursor()
            cursor.movePosition(QTextCursor.Start)
            for _ in range(max(0, line_no - 1)):
                cursor.movePosition(QTextCursor.Down)
            self.code_editor.setTextCursor(cursor)
            self.code_editor.setFocus()
        except Exception:
            pass

    def run_symbol_search_from_ui(self):
        q = self.symbol_query.text().strip()
        domain = self.symbol_domain.currentText().strip() or "all"
        if not q:
            return
        self.send_raw(
            f'Call knowledge__symbol_search with query "{q}" domain "{domain}" max_results 20 include_source false. Show raw results first.',
            "Symbol Search"
        )

    def run_callers_search_from_ui(self):
        q = self.symbol_query.text().strip()
        domain = self.symbol_domain.currentText().strip() or "all"
        if not q:
            return
        self.send_raw(
            f'Call knowledge__find_callers with call_name "{q}" domain "{domain}" max_results 20. Show raw results first.',
            "Find Callers"
        )

    def run_implementation_lookup_from_ui(self):
        q = self.symbol_query.text().strip()
        domain = self.symbol_domain.currentText().strip() or "all"
        if not q:
            return
        self.send_raw(
            f'Call knowledge__read_symbol_source with name "{q}" domain "{domain}" max_results 5. Show raw results first.',
            "Read Implementation"
        )

    def build_ui(self):
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        if LOGO_PATH.exists():
            logo = QLabel()
            logo.setPixmap(QPixmap(str(LOGO_PATH)).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            header.addWidget(logo)

        title_col = QVBoxLayout()
        title = QLabel("The Entire World AI Studio")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #00b866;")
        title_col.addWidget(title)
        subtitle = QLabel("Maya • Unreal • MotionBuilder • AST Knowledge Index • Pipeline Assistant")
        subtitle.setStyleSheet("color: #bdbdbd;")
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch(1)

        self.status = QLabel("Stopped")
        self.status.setStyleSheet("font-weight: bold; color: #ff5555;")
        header.addWidget(self.status)
        root.addLayout(header)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Model:"))
        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.addItems([self.settings.get("model", DEFAULT_MODEL), DEFAULT_MODEL, "ollama:qwen3:14b", "ollama:qwen2.5:7b"])
        controls.addWidget(self.model_box)

        controls.addWidget(QLabel("Config:"))
        self.config_box = QComboBox()
        self.config_box.setEditable(True)
        default_config = self.settings.get("config") or best_config()
        for c in [default_config] + DEFAULT_CONFIGS:
            if self.config_box.findText(c) < 0:
                self.config_box.addItem(c)
        controls.addWidget(self.config_box, 2)

        setup_btn = QPushButton("Project Dirs")
        setup_btn.clicked.connect(self.show_first_run)
        controls.addWidget(setup_btn)

        self.use_pty_checkbox = QCheckBox("Use PTY")
        self.use_pty_checkbox.setChecked(True)
        self.use_pty_checkbox.setToolTip("Recommended ON for MCPHost. Pipe mode can run but may hide MCPHost's terminal UI output.")
        controls.addWidget(self.use_pty_checkbox)

        install_btn = QPushButton("Install Components")
        install_btn.clicked.connect(self.install_components)
        controls.addWidget(install_btn)

        index_btn = QPushButton("Build/Rebuild Index")
        index_btn.clicked.connect(self.build_index)
        controls.addWidget(index_btn)

        root.addLayout(controls)

        status_cards = QHBoxLayout()
        self.status_cards = {}
        for key, label in [
            ("ollama", "Ollama"),
            ("mcphost", "MCPHost"),
            ("knowledge", "Knowledge"),
            ("maya", "Maya"),
            ("unreal", "Unreal"),
            ("motionbuilder", "MotionBuilder"),
        ]:
            card = QLabel(f"{label}: Unknown")
            card.setMinimumWidth(150)
            card.setStyleSheet("padding: 6px; border: 1px solid #1f5f3a; border-radius: 5px; background-color: #111611; color: #cfcfcf;")
            status_cards.addWidget(card)
            self.status_cards[key] = card
        root.addLayout(status_cards)

        index_row = QHBoxLayout()
        self.index_status = QLabel("Index: " + ("ready" if V2_DB.exists() else "missing"))
        index_row.addWidget(self.index_status)
        self.index_progress = QProgressBar()
        self.index_progress.setRange(0, 1)
        self.index_progress.setValue(0)
        index_row.addWidget(self.index_progress, 1)
        root.addLayout(index_row)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        root.addWidget(line)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(10)

        left = QWidget()
        left.setMinimumWidth(220)
        left.setMaximumWidth(900)
        left.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)
        project_header = QHBoxLayout()
        project_header.addWidget(QLabel("Project Files"), 1)

        narrow_btn = QPushButton("Narrow")
        narrow_btn.clicked.connect(self.collapse_project_panel)
        project_header.addWidget(narrow_btn)

        wide_btn = QPushButton("Wide")
        wide_btn.clicked.connect(self.expand_project_panel)
        project_header.addWidget(wide_btn)

        self.toggle_project_btn = QPushButton("Hide")
        self.toggle_project_btn.clicked.connect(self.toggle_project_panel)
        project_header.addWidget(self.toggle_project_btn)

        left_layout.addLayout(project_header)

        self.project_filter = QLineEdit()
        self.project_filter.setPlaceholderText("Filter project tree...")
        self.project_filter.textChanged.connect(self.filter_project_tree)
        left_layout.addWidget(self.project_filter)

        self.project_tree = QTreeWidget()
        self.project_tree.setHeaderLabels(["File", "Path"])
        self.project_tree.setColumnHidden(1, True)
        self.project_tree.itemDoubleClicked.connect(self.open_tree_file)
        self.project_tree.itemExpanded.connect(self.on_project_tree_expanded)
        left_layout.addWidget(self.project_tree, 2)

        refresh_tree_btn = QPushButton("Refresh Project Tree")
        refresh_tree_btn.clicked.connect(self.refresh_project_tree_fast)
        left_layout.addWidget(refresh_tree_btn)

        left_layout.addWidget(QLabel("Chat History"))
        self.history = QListWidget()
        self.history.itemDoubleClicked.connect(self.load_history_item)
        left_layout.addWidget(self.history, 1)

        hrow = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_history)
        hrow.addWidget(save_btn)
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self.new_chat)
        hrow.addWidget(new_btn)
        left_layout.addLayout(hrow)

        left_layout.addWidget(QLabel("Code Snippets"))
        self.code_list = QListWidget()
        self.code_list.itemDoubleClicked.connect(self.copy_selected_code)
        left_layout.addWidget(self.code_list)
        copy_btn = QPushButton("Copy Code")
        copy_btn.clicked.connect(self.copy_selected_code)
        left_layout.addWidget(copy_btn)

        self.left_panel = left
        self.main_splitter.addWidget(left)

        main = QWidget()
        main.setMinimumWidth(600)
        main.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout = QVBoxLayout(main)

        self.workspace_tabs = QTabWidget()

        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 10))
        chat_layout.addWidget(self.log, 1)
        self.workspace_tabs.addTab(chat_tab, "Chat")

        code_tab = QWidget()
        code_layout = QVBoxLayout(code_tab)

        file_top = QHBoxLayout()
        self.file_path_label = QLabel("No file open")
        file_top.addWidget(self.file_path_label, 1)
        save_file_btn = QPushButton("Save File")
        save_file_btn.clicked.connect(self.save_code_file)
        file_top.addWidget(save_file_btn)
        code_layout.addLayout(file_top)

        editor_tools = QHBoxLayout()

        self.editor_find = QLineEdit()
        self.editor_find.setPlaceholderText("Find in file...")
        self.editor_find.returnPressed.connect(self.find_in_current_file)
        editor_tools.addWidget(self.editor_find, 1)

        find_file_btn = QPushButton("Find")
        find_file_btn.clicked.connect(self.find_in_current_file)
        editor_tools.addWidget(find_file_btn)

        self.goto_line_box = QLineEdit()
        self.goto_line_box.setPlaceholderText("Line")
        self.goto_line_box.setMaximumWidth(70)
        self.goto_line_box.returnPressed.connect(self.goto_line_from_box)
        editor_tools.addWidget(self.goto_line_box)

        goto_btn = QPushButton("Go")
        goto_btn.clicked.connect(self.goto_line_from_box)
        editor_tools.addWidget(goto_btn)

        dup_btn = QPushButton("Duplicate Line")
        dup_btn.clicked.connect(self.duplicate_current_line)
        editor_tools.addWidget(dup_btn)

        comment_btn = QPushButton("Comment")
        comment_btn.clicked.connect(self.comment_selection_python_style)
        editor_tools.addWidget(comment_btn)

        trim_btn = QPushButton("Trim Spaces")
        trim_btn.clicked.connect(self.format_python_basic)
        editor_tools.addWidget(trim_btn)

        code_layout.addLayout(editor_tools)

        self.code_editor = CodeEditor()
        self.code_editor.setFont(QFont("Consolas", 10))
        self.code_editor.cursorPositionChanged.connect(self.update_cursor_status)
        self.code_editor.textChanged.connect(self.update_cursor_status)
        code_layout.addWidget(self.code_editor, 1)

        self.editor_status_label = QLabel("Line 1, Col 1")
        code_layout.addWidget(self.editor_status_label)

        editor_prompt_row = QHBoxLayout()
        self.editor_prompt = QLineEdit()
        self.editor_prompt.setPlaceholderText("Ask about this file or selected code...")
        self.editor_prompt.returnPressed.connect(self.ask_about_current_file)
        editor_prompt_row.addWidget(self.editor_prompt, 1)

        ask_file_btn = QPushButton("Ask About File")
        ask_file_btn.clicked.connect(self.ask_about_current_file)
        editor_prompt_row.addWidget(ask_file_btn)

        ask_selection_btn = QPushButton("Ask Selection")
        ask_selection_btn.clicked.connect(self.ask_about_selection)
        editor_prompt_row.addWidget(ask_selection_btn)

        ask_llm_btn = QPushButton("Ask AI")
        ask_llm_btn.setToolTip("Optional: sends the local analysis to the LLM for a more conversational answer.")
        ask_llm_btn.clicked.connect(self.ask_about_file_with_llm)
        editor_prompt_row.addWidget(ask_llm_btn)

        edit_plan_btn = QPushButton("Plan Edit")
        edit_plan_btn.clicked.connect(self.ask_for_edit_plan)
        editor_prompt_row.addWidget(edit_plan_btn)

        apply_fix_btn = QPushButton("Apply Fix")
        apply_fix_btn.setToolTip("Apply the latest safe local editor patch, if one was found.")
        apply_fix_btn.clicked.connect(self.apply_pending_editor_patch)
        editor_prompt_row.addWidget(apply_fix_btn)

        code_layout.addLayout(editor_prompt_row)

        self.workspace_tabs.addTab(code_tab, "Editor")

        search_tab = QWidget()
        search_layout = QVBoxLayout(search_tab)

        search_row = QHBoxLayout()
        self.project_search = QLineEdit()
        self.project_search.setPlaceholderText("Find in project...")
        self.project_search.returnPressed.connect(self.find_in_project)
        search_row.addWidget(self.project_search, 1)

        search_btn = QPushButton("Find")
        search_btn.clicked.connect(self.find_in_project)
        search_row.addWidget(search_btn)
        search_layout.addLayout(search_row)

        self.search_results = QListWidget()
        self.search_results.itemDoubleClicked.connect(self.open_search_result)
        search_layout.addWidget(self.search_results, 1)

        symbol_row = QHBoxLayout()
        self.symbol_query = QLineEdit()
        self.symbol_query.setPlaceholderText("Symbol / function / call name...")
        symbol_row.addWidget(self.symbol_query, 1)
        self.symbol_domain = QComboBox()
        self.symbol_domain.addItems(["all", "maya_tools", "maya", "unreal_tools", "unreal", "mobu_tools", "motionbuilder", "project", "depot"])
        symbol_row.addWidget(self.symbol_domain)

        sym_btn = QPushButton("Symbols")
        sym_btn.clicked.connect(self.run_symbol_search_from_ui)
        symbol_row.addWidget(sym_btn)

        callers_btn = QPushButton("Callers")
        callers_btn.clicked.connect(self.run_callers_search_from_ui)
        symbol_row.addWidget(callers_btn)

        impl_btn = QPushButton("Implementation")
        impl_btn.clicked.connect(self.run_implementation_lookup_from_ui)
        symbol_row.addWidget(impl_btn)

        search_layout.addLayout(symbol_row)
        self.workspace_tabs.addTab(search_tab, "Search / Symbols")

        main_layout.addWidget(self.workspace_tabs, 1)

        self.image_label = QLabel("Attached images: none")
        main_layout.addWidget(self.image_label)

        self.prime_editor = QPlainTextEdit()
        self.prime_editor.setPlainText(PRIME_PROMPT)
        self.prime_editor.setFont(QFont("Consolas", 9))
        self.prime_editor.setMaximumHeight(80)
        main_layout.addWidget(self.prime_editor)

        copy_row = QHBoxLayout()
        for label, callback in [
            ("Copy Last Prompt", self.copy_last_prompt),
            ("Copy Last Response", self.copy_last_response),
            ("Copy Full Log", self.copy_full_log),
            ("Health Check", self.health_check),
        ]:
            b = QPushButton(label)
            b.clicked.connect(callback)
            copy_row.addWidget(b)
        main_layout.addLayout(copy_row)

        quick = QHBoxLayout()

        start_btn = QPushButton("Start MCPHost")
        start_btn.clicked.connect(self.start_mcphost)
        quick.addWidget(start_btn)

        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self.stop_mcphost)
        quick.addWidget(stop_btn)

        prime_btn = QPushButton("Prime")
        prime_btn.clicked.connect(lambda: self.send_raw(PRIME_PROMPT, "Prime"))
        quick.addWidget(prime_btn)

        tools_menu_btn = QToolButton()
        tools_menu_btn.setText("Tools")
        tools_menu_btn.setPopupMode(QToolButton.InstantPopup)
        tools_menu = QMenu(tools_menu_btn)

        knowledge_menu = tools_menu.addMenu("Knowledge")
        knowledge_menu.addAction("/tools", lambda: self.send_raw("/tools", "/tools"))
        knowledge_menu.addAction("Index Stats", lambda: self.send_raw('Call knowledge__index_stats and show the raw response.', "Index Stats"))
        knowledge_menu.addAction("Symbol Search", lambda: self.send_raw('Call knowledge__symbol_search with query "brow eyebrow facial rig" domain "maya_tools" max_results 20 include_source false. Show raw results first.', "Symbol Search"))
        knowledge_menu.addAction("Read Symbol", lambda: self.send_raw('Call knowledge__read_symbol_source with name "create_brow_main_setup" domain "maya_tools" max_results 5. Show raw results first.', "Read Symbol"))
        knowledge_menu.addAction("Find Callers", lambda: self.send_raw('Call knowledge__find_callers with call_name "create_brow_main_setup" domain "maya_tools" max_results 20. Show raw results first.', "Find Callers"))

        maya_menu = tools_menu.addMenu("Maya")
        maya_menu.addAction("Selection", self.direct_maya_selection)
        maya_menu.addAction("Current File", self.direct_maya_file)
        maya_menu.addAction("Scene Objects", self.direct_maya_scene_objects)
        maya_menu.addAction("Call / Execute", self.direct_maya_call_from_text)

        unreal_menu = tools_menu.addMenu("Unreal")
        unreal_menu.addAction("Skeletons", self.direct_unreal_get_skeletons)
        unreal_menu.addAction("Meshes", self.direct_unreal_get_static_meshes)
        unreal_menu.addAction("Call Function", self.direct_unreal_call_from_text)

        mobu_menu = tools_menu.addMenu("MotionBuilder")
        mobu_menu.addAction("Selection", lambda: self.send_raw('Call motionbuilder__motionbuilder_selection and show the raw response.', "MoBu Selection"))
        mobu_menu.addAction("Takes", lambda: self.send_raw('Call motionbuilder__motionbuilder_takes and show the raw response.', "MoBu Takes"))

        tools_menu_btn.setMenu(tools_menu)
        quick.addWidget(tools_menu_btn)
        quick.addStretch(1)
        main_layout.addLayout(quick)


        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask naturally, or enter Maya Python / JSON function payload / Unreal function path, then press Maya Call or Unreal Call.")
        self.input.returnPressed.connect(self.send_message)
        input_row.addWidget(self.input, 1)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_message)
        input_row.addWidget(send_btn)

        paste_btn = QPushButton("Paste Image")
        paste_btn.clicked.connect(self.paste_image_from_clipboard)
        input_row.addWidget(paste_btn)

        attach_btn = QPushButton("Attach Images")
        attach_btn.clicked.connect(self.attach_images)
        input_row.addWidget(attach_btn)

        main_layout.addLayout(input_row)

        self.main_splitter.addWidget(main)
        self.main_splitter.setSizes([360, 1180])
        root.addWidget(self.main_splitter, 1)

    def apply_branding(self):
        self.setStyleSheet("""
            QWidget { background-color: #0b0f0c; color: #e8f5ed; }
            QTextEdit, QPlainTextEdit, QLineEdit, QListWidget, QComboBox {
                background-color: #050705; color: #e8f5ed; border: 1px solid #1f5f3a;
                selection-background-color: #00b866; selection-color: #000000;
            }
            QPushButton {
                background-color: #0f2518; color: #e8f5ed; border: 1px solid #00b866;
                border-radius: 5px; padding: 6px 10px;
            }
            QPushButton:hover { background-color: #123d25; }
            QProgressBar { border: 1px solid #1f5f3a; text-align: center; }
            QProgressBar::chunk { background-color: #00b866; }

            QSplitter::handle {
                background-color: #1f5f3a;
                border-left: 1px solid #00b866;
                border-right: 1px solid #00b866;
            }
            QSplitter::handle:horizontal { width: 10px; }
            QSplitter::handle:hover { background-color: #00b866; }

            QTabWidget::pane {
                border: 1px solid #1f5f3a;
                background-color: #050705;
            }
            QTabBar::tab {
                background-color: #101510;
                color: #cfe8d8;
                padding: 7px 16px;
                border: 1px solid #1f5f3a;
                border-bottom: none;
                min-width: 110px;
            }
            QTabBar::tab:selected {
                background-color: #0f2a19;
                color: #00ff88;
                font-weight: bold;
            }
            QTabBar::tab:hover { background-color: #14351f; color: #ffffff; }
            QTabBar::tab:!selected { margin-top: 3px; }

            QTreeWidget::item { padding: 2px; }
            QTreeWidget::item:selected {
                background-color: #00b866;
                color: #000000;
            }
            QMenu {
                background-color: #071007;
                color: #e5ffe5;
                border: 1px solid #00b866;
            }
            QMenu::item { padding: 6px 28px 6px 18px; }
            QMenu::item:selected { background-color: #00b866; color: #000000; }
        """)

    def set_card(self, key, state, detail=""):
        card = getattr(self, "status_cards", {}).get(key)
        if not card:
            return
        label = {
            "ollama": "Ollama",
            "mcphost": "MCPHost",
            "knowledge": "Knowledge",
            "maya": "Maya",
            "unreal": "Unreal",
            "motionbuilder": "MotionBuilder",
        }.get(key, key)

        color = {
            "ok": "#00b866",
            "warn": "#d4b000",
            "bad": "#e05252",
            "busy": "#4aa3ff",
            "off": "#777777",
            "unknown": "#cfcfcf",
        }.get(state, "#cfcfcf")

        prefix = {
            "ok": "●",
            "warn": "●",
            "bad": "●",
            "busy": "●",
            "off": "●",
            "unknown": "●",
        }.get(state, "●")

        text = f"{prefix} {label}: {detail or state.title()}"
        card.setText(text)
        card.setStyleSheet(
            f"padding: 6px; border: 1px solid {color}; border-radius: 5px; "
            f"background-color: #111611; color: {color}; font-weight: bold;"
        )

    def update_initial_status_cards(self):
        self.set_card("knowledge", "ok" if V2_DB.exists() else "warn", "Index ready" if V2_DB.exists() else "Index missing")
        self.set_card("mcphost", "off", "Stopped")
        self.set_card("ollama", "unknown", "Not checked")
        self.set_card("maya", "unknown", "Not checked")
        self.set_card("unreal", "unknown", "Not checked")
        self.set_card("motionbuilder", "off", "Optional")

    def copy_last_prompt(self):
        QGuiApplication.clipboard().setText(self.last_user_prompt or "")
        self.append("\n[Copied last prompt.]\n")

    def copy_last_response(self):
        QGuiApplication.clipboard().setText(self.last_assistant_output or self.last_tool_output or "")
        self.append("\n[Copied last response/output.]\n")

    def copy_full_log(self):
        QGuiApplication.clipboard().setText(self.log.toPlainText())
        self.append("\n[Copied full log.]\n")

    def health_check(self):
        msg = []
        msg.append("Health Check")
        msg.append(f"Knowledge DB: {'OK' if V2_DB.exists() else 'Missing'}")
        msg.append(f"MCPHost: {'Running' if self.bridge.running else 'Stopped'}")
        msg.append(f"Ready marker seen: {'Yes' if self.mcphost_ready else 'No'}")
        msg.append("")
        port = self.find_maya_port_direct()
        msg.append(f"Maya commandPort: {'OK :' + str(port) if port else 'Not found'}")
        msg.append("Maya test: use direct button 'Maya Selection' after Maya commandPort is running.")
        unreal_port = self.find_unreal_http_port_direct()
        msg.append(f"Unreal HTTP bridge: {'OK :' + str(unreal_port) if unreal_port else 'Not found'}")
        msg.append("Unreal test: use direct buttons after Unreal HTTP bridge is running.")
        msg.append("MotionBuilder is optional and will stay inactive unless configured.")
        self.append("\n" + "\n".join(msg) + "\n")

    def check_mcphost_startup_visibility(self):
        if not self.bridge.running:
            return
        if not self.mcphost_ready:
            self.set_card("mcphost", "warn", "Running, readiness unknown")
            if self.mcphost_use_pty:
                self.append(
                    "\n[Status] MCPHost is running in PTY mode, but the ready marker was not detected yet. "
                    "Wait a little longer, or check the visible terminal output above.\n"
                )
            else:
                self.append(
                    "\n[Status] MCPHost process is running, but no ready prompt/tool-load output was detected yet. "
                    "Pipe mode can be quiet with MCPHost's terminal UI. Turn on 'Use PTY' before starting MCPHost "
                    "for visible terminal output.\n"
                )

    def find_maya_port_direct(self, host="127.0.0.1"):
        candidates = []

        # Prefer explicit env var if present.
        env_port = os.environ.get("MAYA_COMMAND_PORT")
        if env_port:
            try:
                candidates.append(int(env_port))
            except Exception:
                pass

        # Existing Antigravity scratch port file.
        port_file = r"C:/Users/Aaron/.gemini/antigravity/brain/96780b9e-50af-48f5-bf67-f9aa5b5a9101/scratch/maya_port.txt"
        try:
            with open(port_file, "r", encoding="utf-8") as f:
                candidates.append(int(f.read().strip()))
        except Exception:
            pass

        candidates.append(7001)

        seen = set()
        for port in candidates:
            if port in seen:
                continue
            seen.add(port)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.25)
                    if s.connect_ex((host, port)) == 0:
                        return port
            except Exception:
                pass

        return None

    def direct_maya_execute(self, code, label="Maya Direct", timeout=5):
        """
        Execute code directly against Maya's commandPort capture function.

        This bypasses MCPHost and the LLM completely. It is the right path for
        deterministic UI buttons like Selection/File/Scene Objects because it should
        return in milliseconds instead of waiting for model inference.
        """
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n{code}\n")

        port = self.find_maya_port_direct()
        if not port:
            self.set_card("maya", "bad", "No commandPort")
            self.append("[Maya Direct] No Maya commandPort found. Start Maya and run maya_command_port_setup.py.\n")
            return

        self.set_card("maya", "busy", f"Executing :{port}")
        self.append(f"[Maya Direct] Executing on port {port}...\n")

        try:
            encoded = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            payload = f"maya_execute_and_capture('{encoded}')\n"

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(("127.0.0.1", port))
                s.sendall(payload.encode("utf-8"))

                chunks = []
                while True:
                    data = s.recv(4096)
                    if not data:
                        break
                    chunk = data.decode("utf-8", errors="replace")
                    chunks.append(chunk)
                    if "\x00" in chunk:
                        break

            result = "".join(chunks).replace("\x00", "").strip()
            if not result:
                result = "Maya returned no output."

            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("maya", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        except Exception as e:
            self.set_card("maya", "bad", "Execution failed")
            self.append(f"[Maya Direct Error] {e}\n")

    def direct_maya_selection(self):
        self.direct_maya_execute(
            "import maya.cmds as cmds\nprint(cmds.ls(sl=True))",
            "Maya Selection"
        )

    def direct_maya_file(self):
        self.direct_maya_execute(
            "import maya.cmds as cmds\nprint(cmds.file(q=True, sceneName=True))",
            "Maya File"
        )

    def direct_maya_scene_objects(self):
        self.direct_maya_execute(
            "import maya.cmds as cmds\nprint(cmds.ls(type='transform')[:500])",
            "Maya Scene Objects"
        )

    def direct_maya_call_function(self, function_path, args=None, kwargs=None, label="Maya Function"):
        """
        Import and call any Python function inside Maya.

        function_path example:
            maya_tools.rigging.create_rig.create_brow_main_setup

        This is the Maya equivalent of the Unreal HTTP function bridge.
        """
        args = args or []
        kwargs = kwargs or {}

        payload = {
            "function": function_path,
            "args": args,
            "kwargs": kwargs,
        }

        code = f"""
import sys, json, importlib, traceback
for p in [r"C:/depot/tools", r"C:/Desktop/UnrealGenAISupport", r"C:/Desktop/MayaMCP"]:
    if p not in sys.path:
        sys.path.append(p)

payload = {repr(payload)}
try:
    module_path, func_name = payload["function"].rsplit(".", 1)
    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    result = func(*payload.get("args", []), **payload.get("kwargs", {{}}))
    print(result)
except Exception:
    traceback.print_exc()
"""
        self.direct_maya_execute(code, label)

    def direct_maya_call_from_text(self):
        """
        Interpret the input box as either raw Python code or JSON:

        Raw Python:
            import maya.cmds as cmds
            print(cmds.ls(sl=True))

        JSON function call:
            {"function":"maya_tools.module.function","args":[],"kwargs":{}}
        """
        text = self.input.text().strip()
        if not text:
            self.append("\n[Maya Direct] Enter raw Maya Python or a JSON function payload first.\n")
            return

        self.input.clear()

        try:
            if text.startswith("{"):
                data = json.loads(text)
                self.direct_maya_call_function(
                    data["function"],
                    args=data.get("args", []),
                    kwargs=data.get("kwargs", {}),
                    label="Maya Function"
                )
            else:
                self.direct_maya_execute(text, "Maya Execute")
        except Exception as e:
            self.append(f"\n[Maya Direct Parse Error] {e}\n")

    def find_unreal_http_port_direct(self, host="127.0.0.1"):
        candidates = []

        env_port = os.environ.get("UNREAL_HTTP_PORT")
        if env_port:
            try:
                candidates.append(int(env_port))
            except Exception:
                pass

        for path in [
            r"C:\depot\tools\unreal_http_port.txt",
            r"C:\Users\Aaron\AppData\Local\TA_AI_Studio_MCPHost\unreal_http_port.txt",
        ]:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    candidates.append(int(f.read().strip()))
            except Exception:
                pass

        # Aaron's current Unreal HTTP bridge default.
        candidates.append(12347)

        seen = set()
        for port in candidates:
            if port in seen:
                continue
            seen.add(port)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.25)
                    if s.connect_ex((host, port)) == 0:
                        return port
            except Exception:
                pass

        return None

    def direct_unreal_call(self, function_path, args=None, kwargs=None, label="Unreal Direct", timeout=30):
        """
        Call Aaron's Unreal HTTP bridge directly.

        Expected Unreal server payload:
            {
                "function": "unreal_tools.some_module.some_function",
                "args": [...],
                "kwargs": {...}
            }

        This bypasses MCPHost and the LLM for deterministic Unreal actions.
        """
        args = args or []
        kwargs = kwargs or {}

        self.last_user_prompt = f"[{label}] {function_path} args={args} kwargs={kwargs}"
        self.append(f"\nYOU [{label}]:\n{function_path}\nargs={args}\nkwargs={kwargs}\n")

        port = self.find_unreal_http_port_direct()
        if not port:
            self.set_card("unreal", "bad", "HTTP bridge not found")
            self.append("[Unreal Direct] Unreal HTTP bridge not found on port 12347. Start your Unreal HTTP server first.\n")
            return

        self.set_card("unreal", "busy", f"Calling :{port}")
        self.append(f"[Unreal Direct] Calling {function_path} on port {port}...\n")

        try:
            payload = json.dumps({
                "function": function_path,
                "args": args,
                "kwargs": kwargs,
            }).encode("utf-8")

            req = urllib.request.Request(
                f"http://127.0.0.1:{port}",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")

            try:
                parsed = json.loads(raw)
                result = json.dumps(parsed, indent=2, default=str)
            except Exception:
                result = raw

            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("unreal", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        except Exception as e:
            self.set_card("unreal", "bad", "Call failed")
            self.append(f"[Unreal Direct Error] {e}\n")

    def direct_unreal_get_skeletons(self):
        self.direct_unreal_call(
            "unreal_tools.get_skeletons.get_all_assets_of_type",
            args=["Skeleton", "/Game/"],
            kwargs={},
            label="Unreal Skeletons"
        )

    def direct_unreal_get_static_meshes(self):
        self.direct_unreal_call(
            "unreal_tools.get_skeletons.get_all_assets_of_type",
            args=["StaticMesh", "/Game/"],
            kwargs={},
            label="Unreal Static Meshes"
        )

    def direct_unreal_call_from_text(self):
        """
        Interpret the input box as either:
          unreal_tools.module.function
        or JSON:
          {"function":"unreal_tools.module.function","args":[],"kwargs":{}}
        """
        text = self.input.text().strip()
        if not text:
            self.append("\n[Unreal Direct] Enter a function path or JSON payload in the input box first.\n")
            return

        self.input.clear()

        try:
            if text.startswith("{"):
                data = json.loads(text)
                fn = data["function"]
                args = data.get("args", [])
                kwargs = data.get("kwargs", {})
            else:
                fn = text
                args = []
                kwargs = {}

            self.direct_unreal_call(fn, args=args, kwargs=kwargs, label="Unreal Direct")
        except Exception as e:
            self.append(f"\n[Unreal Direct Parse Error] {e}\n")

    def send_with_timeout_notice(self, text, label):
        # Used for LLM/MCPHost prompts. Direct host actions bypass this.
        self.send_raw(text, label)
        QTimer.singleShot(30000, lambda: self.pending_response_notice(label))

    def pending_response_notice(self, label):
        if self.bridge.running:
            self.append(
                f"\n[Still waiting after 30s for {label}. "
                "For simple host queries, use the direct Maya/File/Selection buttons because they bypass the LLM.]\n"
            )

    def clean(self, text):
        """
        Compact MCPHost's Bubble Tea/TUI output.

        MCPHost redraws the whole response area many times while tokens stream. If we dump
        every redraw, the GUI appears to print one line per character. In PTY mode this
        cleaner hides box redraws and surfaces only useful status/tool/result lines.
        """
        text = ANSI_RE.sub("", text).replace("\x07", "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        while "\b" in text:
            text = re.sub(r".\b", "", text)

        out = []

        # Extract FastMCP wrapped result if visible in the terminal redraw.
        # Example contains: \"structuredContent\":{\"result\":\"['pelvis_ctrl']\"}
        for m in re.finditer(r'\\*"result\\*"\\s*:\\s*\\*"([^"]*?)\\*"', text):
            result = m.group(1)
            result = result.encode("utf-8", errors="replace").decode("unicode_escape", errors="replace")
            if result and result not in self._seen_tool_results:
                self._seen_tool_results.add(result)
                out.append("Tool Result:")
                out.append(result)

        for raw in text.splitlines():
            line = raw.strip()
            if not line or line in {"11;?", "11;? "}:
                continue

            # Drop terminal UI box redraws. These are the source of the "one line per character" spam.
            if "┃" in line or line in {"┏", "┓", "┗", "┛"}:
                # Keep only major status messages that are easier to parse before dropping box lines.
                if "Loaded" in line and "tools from MCP servers" in line:
                    m = re.search(r"Loaded\s+(\d+)\s+tools", line)
                    msg = f"Loaded {m.group(1)} tools from MCP servers." if m else "Loaded tools from MCP servers."
                    if msg not in self._seen_compact_lines:
                        self._seen_compact_lines.add(msg)
                        out.append(msg)
                continue

            # Drop broken prompt echo artifacts from terminal cursor redraw / bracketed paste.
            if line in {"Ty", "Calmay", "Calmaya__maya_se", "_maya_selection and show the raw response.", "ction and show the raw response."}:
                continue
            if line.startswith("Calmaya") or line.startswith("_maya_"):
                continue

            # Spinner/load frames: show only once.
            if "Loading Ollama model" in line:
                msg = "Loading Ollama model..."
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                    out.append(msg)
                continue

            if "Thinking" in line and ("∙" in line or "●" in line or line.endswith("Thinking...")):
                msg = "Thinking..."
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                    out.append(msg)
                continue

            if "Executing maya__" in line or "Executing knowledge__" in line or "Executing motionbuilder__" in line or "Executing unreal" in line.lower():
                msg = line
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                    out.append(msg)
                continue

            # Compact success states.
            if "Model loaded successfully on GPU" in line:
                msg = "✓ Model loaded successfully on GPU."
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                    out.append(msg)
                continue

            if "Model loaded:" in line:
                msg = line
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                    out.append(msg)
                continue

            if "tools from MCP servers" in line:
                msg = line
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                    out.append(msg)
                continue

            if "Enter your prompt" in line or "Type your message" in line or "enter submit" in line:
                msg = "MCPHost ready for input."
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                    out.append(msg)
                continue

            if "Finished without output" in line:
                # This is MCPHost saying the model/tool display had no extra terminal output.
                # It is misleading when we already extracted Tool Result above.
                continue

            if "Goodbye!" in line:
                out.append("MCPHost exited.")
                continue

            # Avoid repeated terminal redraw lines.
            if line == self._last_stream_line:
                continue
            self._last_stream_line = line

            # Keep non-box lines.
            out.append(raw)

        return ("\n".join(out) + "\n") if out else ""


    def append(self, text):
        if not text:
            return
        self.extract_code_blocks(text)
        scroll = self.log.verticalScrollBar()
        was_at_bottom = scroll.value() >= scroll.maximum() - 20
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        if was_at_bottom:
            self.log.moveCursor(QTextCursor.End)

    def extract_code_blocks(self, text):
        for m in re.finditer(r"```([A-Za-z0-9_+.-]*)\n(.*?)```", text, re.DOTALL):
            lang = m.group(1) or "text"
            code = m.group(2).strip()
            if not code:
                continue
            key = (lang, code)
            if key in self.code_snippets:
                continue
            self.code_snippets.append(key)
            preview = code.splitlines()[0] if code.splitlines() else code[:70]
            self.code_list.addItem(f"{len(self.code_snippets)}. {lang} — {preview[:70]}")

    def copy_selected_code(self):
        item = self.code_list.currentItem()
        if not item:
            return
        idx = self.code_list.row(item)
        if 0 <= idx < len(self.code_snippets):
            QGuiApplication.clipboard().setText(self.code_snippets[idx][1])
            self.append(f"\n[Copied code snippet {idx+1}.]\n")

    def show_first_run(self):
        dlg = FirstRunDialog(self.settings, self)
        if dlg.exec():
            self.settings = load_settings()
            self.append("\n[Project directories updated.]\n")
            self.load_project_tree()
            if self.settings.get("auto_index_on_first_run") and not V2_DB.exists():
                self.build_index()

    def install_components(self):
        try:
            install_components_to_tools()
            cfg = update_mcp_config()
            self.append(f"\n[Installed Knowledge v2 and quiet Maya MCP. Updated config: {cfg}]\n")
            self.config_box.setEditText(cfg)
        except Exception as e:
            QMessageBox.critical(self, "Install failed", str(e))

    def build_index(self):
        if self.index_worker and self.index_worker.isRunning():
            QMessageBox.information(self, "Index running", "Index build is already running.")
            return

        self.install_components()
        roots = self.all_roots()
        self.index_progress.setRange(0, 0)
        self.index_status.setText("Index: building AST index...")
        self.index_worker = IndexWorker(roots)
        self.index_worker.output.connect(lambda s: self.append(s))
        self.index_worker.progress.connect(self.on_index_progress)
        self.index_worker.finished_ok.connect(self.on_index_finished)
        self.index_worker.start()

    def on_index_progress(self, scanned, total, updated):
        self.index_status.setText(f"Index: building... updated {updated}")

    def on_index_finished(self, ok, msg):
        self.index_progress.setRange(0, 1)
        self.index_progress.setValue(1 if ok else 0)
        self.index_status.setText("Index: ready" if ok else "Index: failed")
        self.set_card("knowledge", "ok" if ok else "bad", "Index ready" if ok else "Index failed")
        self.append(f"\n[{msg}]\n")

    def start_mcphost(self):
        if self.bridge.running:
            return

        self.install_components()

        mcphost = DEFAULT_MCPHOST
        config = self.config_box.currentText().strip()
        model = self.model_box.currentText().strip()
        self.settings["model"] = model
        self.settings["config"] = config
        save_settings(self.settings)

        if not Path(mcphost).exists():
            QMessageBox.critical(self, "Missing MCPHost", f"Could not find:\n{mcphost}")
            return
        if not Path(config).exists():
            QMessageBox.critical(self, "Missing config", f"Could not find:\n{config}")
            return

        self._status_once = set()
        self._last_stream_line = ""
        self._seen_tool_results = set()
        self._seen_compact_lines = set()
        self.mcphost_started_at = time.time()
        self.mcphost_ready = False
        self.set_card("mcphost", "busy", "Starting")
        self.set_card("ollama", "busy", "Loading model")
        cmd_args = [mcphost, "-m", model, "--config", config]
        cmd_display = subprocess.list2cmdline(cmd_args)
        self.append("\n=== Starting MCPHost ===\n" + cmd_display + "\n\n")
        env = {"AI_KNOWLEDGE_ROOTS": ";".join(self.all_roots())}
        use_pty = self.use_pty_checkbox.isChecked()
        self.mcphost_use_pty = use_pty
        self.bridge.start(cmd_args, env=env, use_pty=use_pty)
        self.status.setText("Running")
        self.status.setStyleSheet("font-weight: bold; color: #00b866;")
        QTimer.singleShot(15000, self.check_mcphost_startup_visibility)

    def stop_mcphost(self):
        self.bridge.stop()
        self.set_card("mcphost", "off", "Stopped")
        self.status.setText("Stopped")
        self.status.setStyleSheet("font-weight: bold; color: #ff5555;")

    def send_raw(self, text, label="Prompt"):
        self.last_user_prompt = text
        self.append(f"\nYOU [{label}]:\n{text}\n")
        self.current_session.append({"role": "user", "content": text})
        if self.bridge.write(text):
            if self.mcphost_use_pty:
                self.append("[Sent to LLM via PTY. Waiting for assistant/tool output...]\n")
            else:
                self.append("[Sent to LLM. Waiting for assistant/tool output...]\n")
        else:
            self.append("\n[Send failed: MCPHost is not running or input stream is unavailable.]\n")

    def send_message(self):
        text = self.input.text().strip()
        if not text and not self.attached_images:
            return
        if self.attached_images:
            text += "\n\nAttached image paths:\n" + "\n".join(self.attached_images)
        self.input.clear()
        self.send_raw(text)
        self.attached_images = []
        self.update_image_label()

    def prime(self):
        self.send_raw(self.prime_editor.toPlainText().strip(), "Prime")

    def handle_output(self, data):
        raw = data or ""
        cleaned = self.clean(raw)

        if "subprocess pipe active" in raw:
            self.set_card("mcphost", "busy", "Process active")
        if "PTY active" in raw:
            self.set_card("mcphost", "busy", "PTY active")
        if "Loading Ollama model" in raw:
            self.set_card("ollama", "busy", "Loading")
        if "Model loaded:" in raw:
            self.set_card("ollama", "ok", self.model_box.currentText().strip())
        if "Model loaded successfully on GPU" in raw:
            self.set_card("ollama", "ok", "GPU loaded")
        if "tools from MCP servers" in raw:
            self.mcphost_ready = True
            m = re.search(r"Loaded\s+(\d+)\s+tools", raw)
            self.set_card("mcphost", "ok", f"Ready ({m.group(1)} tools)" if m else "Ready")
        if "Enter your prompt" in raw or "Type your message" in raw:
            self.mcphost_ready = True
            if "ok" not in self.status_cards["mcphost"].styleSheet():
                self.set_card("mcphost", "ok", "Ready")
        if "maya__" in raw or "Maya" in raw:
            # This is a weak signal, but better than silent ambiguity.
            if "Failed to load MCP server 'maya'" in raw:
                self.set_card("maya", "bad", "MCP failed")
            elif "maya__" in raw:
                self.set_card("maya", "busy", "Tool activity")
        if "Goodbye!" in raw:
            self.set_card("mcphost", "bad", "Exited after input")
            self.append(
                "\n[Status] MCPHost printed Goodbye after input. This usually means the terminal UI interpreted "
                "the programmatic input as a quit/EOF event. v5.2 sends prompts using bracketed paste to avoid this. "
                "If it still happens, the next step is direct model/tool orchestration instead of driving MCPHost's TUI.\n"
            )

        if "motionbuilder" in raw.lower():
            if "failed" in raw.lower():
                self.set_card("motionbuilder", "warn", "Optional / unavailable")
            else:
                self.set_card("motionbuilder", "busy", "Tool activity")

        if cleaned:
            self.last_assistant_output = cleaned
            self.append(cleaned)
            self.current_session.append({"role": "assistant_or_tool_output", "content": cleaned})

    def on_finished(self, msg="MCPHost exited."):
        self.set_card("mcphost", "off", "Exited")
        self.status.setText("Exited")
        self.status.setStyleSheet("font-weight: bold; color: #ff5555;")
        self.append(f"\n=== {msg} ===\n")

    def attach_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Attach images", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        self.attached_images.extend(files)
        self.update_image_label()

    def paste_image_from_clipboard(self):
        cb = QGuiApplication.clipboard()
        mime = cb.mimeData()
        saved = []
        if mime.hasImage():
            image = cb.image()
            if not image.isNull():
                path = IMAGE_DIR / f"clipboard_{time.strftime('%Y%m%d_%H%M%S')}.png"
                image.save(str(path), "PNG")
                saved.append(str(path))
        if saved:
            self.attached_images.extend(saved)
            self.update_image_label()
            self.append(f"\n[Attached pasted image: {Path(saved[0]).name}]\n")

    def update_image_label(self):
        self.image_label.setText("Attached images: " + ("; ".join(Path(p).name for p in self.attached_images) if self.attached_images else "none"))

    def refresh_history(self):
        self.history.clear()
        for p in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
            self.history.addItem(p.name)

    def save_history(self):
        p = HISTORY_DIR / f"chat_{time.strftime('%Y%m%d_%H%M%S')}.json"
        p.write_text(json.dumps(self.current_session, indent=2), encoding="utf-8")
        self.refresh_history()
        self.append(f"\n[Saved chat: {p}]\n")

    def new_chat(self):
        self.current_session = []
        self.code_snippets = []
        self.code_list.clear()
        self._seen_tool_results = set()
        self._seen_compact_lines = set()
        self.log.clear()
        self.append("New chat.\n")

    def load_history_item(self, item):
        p = HISTORY_DIR / item.text()
        self.current_session = json.loads(p.read_text(encoding="utf-8"))
        self.log.clear()
        for m in self.current_session:
            self.append(f"\n{m.get('role','').upper()}:\n{m.get('content','')}\n")


def main():
    app = QApplication(sys.argv)
    win = App()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()