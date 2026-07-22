"""Deterministic helpers for converting common PySide2/PyQt5 code to PySide6."""

from __future__ import annotations

from dataclasses import dataclass, field
import re


MOVED_QTGUI_WIDGETS = {
    "QAction",
    "QActionGroup",
    "QClipboard",
    "QCursor",
    "QDesktopServices",
    "QDrag",
    "QFileOpenEvent",
    "QFont",
    "QFontDatabase",
    "QGuiApplication",
    "QIcon",
    "QImage",
    "QKeySequence",
    "QMovie",
    "QPainter",
    "QPalette",
    "QPixmap",
    "QShortcut",
    "QStandardItem",
    "QStandardItemModel",
    "QTextCursor",
    "QTextDocument",
}


@dataclass
class PySideConversionResult:
    """Result of converting legacy Qt binding references."""

    source: str
    changed: bool
    replacements: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def convert_pyside_to_pyside6(source: str, *, strict: bool = True) -> PySideConversionResult:
    """Convert common PySide2/PyQt5 imports and API patterns to PySide6."""

    converted = str(source or "")
    replacements: list[str] = []
    warnings: list[str] = []

    if strict:
        converted, import_replacements = _convert_imports(converted)
        replacements.extend(import_replacements)
    else:
        converted, prefer_replacements = _prefer_pyside6_compatible_imports(converted)
        replacements.extend(prefer_replacements)

    simple_patterns = [
        (r"\bshiboken2\b", "shiboken6", "shiboken2 -> shiboken6", None),
        (r"\.exec_\(", ".exec(", "exec_() -> exec()", None),
        (
            r"\bQApplication\.desktop\(\)",
            "QGuiApplication.primaryScreen()",
            "QApplication.desktop() -> QGuiApplication.primaryScreen()",
            "QGuiApplication",
        ),
    ]
    active_patterns = simple_patterns if strict else simple_patterns[2:]
    for pattern, replacement, label, required_qtgui in active_patterns:
        converted, count = re.subn(pattern, replacement, converted)
        if count:
            replacements.append(label)
            if required_qtgui:
                converted = _ensure_qtgui_import(converted, required_qtgui)

    if "QDesktopWidget" in converted:
        warnings.append("QDesktopWidget has no direct PySide6 equivalent; use QGuiApplication.primaryScreen()/screens().")
    if re.search(r"\bQt\.[A-Z][A-Za-z_]+\b", converted):
        warnings.append("Review Qt enum aliases; PySide6 may prefer scoped enums such as Qt.AlignmentFlag.AlignCenter.")
    if "QRegExp" in converted:
        warnings.append("QRegExp was replaced by QRegularExpression in Qt6.")

    return PySideConversionResult(
        source=converted,
        changed=converted != str(source or ""),
        replacements=replacements,
        warnings=warnings,
    )


def _convert_imports(source: str) -> tuple[str, list[str]]:
    """Convert common PySide2/PyQt5 import forms and fix QtGui symbol moves."""

    replacements: list[str] = []
    converted = source.replace("from PySide2", "from PySide6").replace("import PySide2", "import PySide6")
    converted = converted.replace("from PyQt5", "from PySide6").replace("import PyQt5", "import PySide6")
    if converted != source:
        replacements.append("binding imports -> PySide6")

    lines = converted.splitlines(keepends=True)
    output: list[str] = []
    pending_qtgui: set[str] = set()
    for line in lines:
        match = re.match(r"(?P<indent>\s*)from\s+PySide6\.QtWidgets\s+import\s+(?P<names>.+?)(?P<ending>\r?\n?)$", line)
        if not match:
            output.append(line)
            continue
        names = [item.strip() for item in match.group("names").split(",") if item.strip()]
        keep: list[str] = []
        for name in names:
            base = name.split(" as ", 1)[0].strip()
            if base in MOVED_QTGUI_WIDGETS:
                pending_qtgui.add(name)
            else:
                keep.append(name)
        if keep:
            output.append(f"{match.group('indent')}from PySide6.QtWidgets import {', '.join(keep)}{match.group('ending')}")
        if pending_qtgui:
            replacements.append("moved QtGui classes out of QtWidgets imports")
    if pending_qtgui:
        insert_at = _import_insert_index(output)
        output.insert(insert_at, f"from PySide6.QtGui import {', '.join(sorted(pending_qtgui))}\n")
    return "".join(output), sorted(set(replacements))


def _prefer_pyside6_compatible_imports(source: str) -> tuple[str, list[str]]:
    """Prefer PySide6 in simple fallback blocks while preserving PySide2 support."""

    replacements: list[str] = []
    pattern = re.compile(
        r"(?P<indent>^[ \t]*)try:\n"
        r"(?P=indent)[ \t]+from PySide2 import QtWidgets, QtCore, QtGui\n"
        r"(?P=indent)[ \t]+PYQT_VERSION = 2\n"
        r"(?P=indent)except ImportError:\n"
        r"(?P=indent)[ \t]+from PySide6 import QtWidgets, QtCore, QtGui\n"
        r"(?P=indent)[ \t]+PYQT_VERSION = 6",
        flags=re.MULTILINE,
    )

    def replace(match: re.Match[str]) -> str:
        indent = match.group("indent")
        replacements.append("prefer PySide6 fallback imports")
        child = indent + "    "
        return (
            f"{indent}try:\n"
            f"{child}from PySide6 import QtWidgets, QtCore, QtGui\n"
            f"{child}PYQT_VERSION = 6\n"
            f"{indent}except ImportError:\n"
            f"{child}from PySide2 import QtWidgets, QtCore, QtGui\n"
            f"{child}PYQT_VERSION = 2"
        )

    return pattern.sub(replace, source), sorted(set(replacements))


def _ensure_qtgui_import(source: str, symbol: str) -> str:
    """Ensure a PySide6.QtGui symbol is imported without duplicating it."""

    if re.search(rf"from\s+PySide6\.QtGui\s+import\s+.*\b{re.escape(symbol)}\b", source):
        return source
    lines = source.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if line.startswith("from PySide6.QtGui import "):
            ending = "\n" if line.endswith("\n") else ""
            names = line.removeprefix("from PySide6.QtGui import ").strip()
            names = names.rstrip("\r\n")
            parts = [item.strip() for item in names.split(",") if item.strip()]
            if symbol not in {part.split(" as ", 1)[0].strip() for part in parts}:
                parts.append(symbol)
            lines[idx] = f"from PySide6.QtGui import {', '.join(sorted(parts))}{ending}"
            return "".join(lines)
    insert_at = _import_insert_index(lines)
    lines.insert(insert_at, f"from PySide6.QtGui import {symbol}\n")
    return "".join(lines)


def _import_insert_index(lines: list[str]) -> int:
    """Return a stable insertion point after module comments/docstring and imports."""

    index = 0
    in_docstring = False
    quote = ""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if idx == 0 and stripped.startswith("#"):
            index = idx + 1
            continue
        if stripped.startswith(('"""', "'''")):
            token = stripped[:3]
            if stripped.count(token) == 1:
                in_docstring = not in_docstring
                quote = token if in_docstring else ""
            index = idx + 1
            continue
        if in_docstring:
            if quote and quote in stripped:
                in_docstring = False
            index = idx + 1
            continue
        if stripped.startswith(("import ", "from ")):
            index = idx + 1
            continue
        if not stripped:
            index = idx + 1
            continue
        break
    return index
