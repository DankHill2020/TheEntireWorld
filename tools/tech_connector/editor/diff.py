"""Deterministic patch building and application."""

import difflib
import re
from pathlib import Path


def build_safe_patch_for_symbol(path, sym):
    """
    Build small deterministic patches for obvious local bugs.
    Intentionally conservative — only prepares a patch for high-confidence issues.
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
            "        self.directory = directory.replace('\\\\\\\\', '/')\n",
        )
        new_source = new_source.replace(
            "        self.dir_name = QtWidgets.QLineEdit(directory.replace('\\\\\\\\', '/'))",
            "        self.dir_name = QtWidgets.QLineEdit(self.directory)",
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

    elif (
        name == "NonScrollingSpinBox"
        and "def wheelEvent(self, event):" in source
        and "event.ignore()" in source
    ):
        new_source = source.replace(
            "        event.ignore()",
            "        super(NonScrollingSpinBox, self).wheelEvent(event)"
        )
        if new_source != source:
            return {
                "path": path,
                "symbol": name,
                "start": sym.get("start"),
                "end": sym.get("end"),
                "old": source,
                "new": new_source,
                "summary": "Forward wheel events to the parent class to restore mouse wheel scrolling.",
            }

    return None


def patch_diff(patch: dict) -> str:
    """Return a unified diff for the pending patch block."""
    old = (patch.get("old") or "").splitlines()
    new = (patch.get("new") or "").splitlines()
    symbol = patch.get("symbol") or "code"
    return "\n".join(
        difflib.unified_diff(
            old,
            new,
            fromfile=f"{symbol} (current)",
            tofile=f"{symbol} (proposed)",
            lineterm="",
        )
    )


def analyze_patch_safety(patch: dict) -> dict:
    """Return patch safety metadata before applying an editor fix."""
    old = patch.get("old") or ""
    new = patch.get("new") or ""
    action = patch.get("action", "replace")
    symbol = patch.get("symbol") or ""

    old_lines = [line for line in old.splitlines() if line.strip()]
    new_lines = [line for line in new.splitlines() if line.strip()]
    old_count = len(old_lines)
    new_count = len(new_lines)
    removed = max(0, old_count - new_count)
    removal_ratio = removed / old_count if old_count else 0
    warnings = []
    blockers = []

    if action == "replace":
        if not new.strip():
            blockers.append("The proposed replacement is empty.")
        if old_count >= 8 and new_count <= max(2, old_count // 3):
            blockers.append("The proposed replacement removes most of the original block.")
        elif old_count >= 8 and removal_ratio >= 0.45:
            warnings.append("The proposed replacement deletes a large portion of the original block.")

        if symbol and re.search(rf"\b(class|def)\s+{re.escape(symbol)}\b", old):
            if not re.search(rf"\b(class|def)\s+{re.escape(symbol)}\b", new):
                blockers.append(f"The proposed replacement no longer defines `{symbol}`.")

    if "pass" == new.strip() and old_count > 3:
        blockers.append("The proposed replacement collapses the block to `pass`.")

    if old == new:
        blockers.append("The proposed code is identical to the original.")

    return {
        "safe": not blockers,
        "warnings": warnings,
        "blockers": blockers,
        "old_lines": old_count,
        "new_lines": new_count,
        "removed_lines": removed,
        "removal_ratio": removal_ratio,
    }


def apply_patch(patch: dict):
    """
    Apply a pending editor patch.
    Returns (success, message, updated_file_text_or_none).
    """
    path = Path(patch["path"])
    if not path.exists():
        return False, f"File not found: {path}", None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        old = patch["old"]
        new = patch["new"]
        safety = analyze_patch_safety(patch)
        if not safety["safe"] and not patch.get("force_apply"):
            return (
                False,
                "Patch refused by safety checks:\n- " + "\n- ".join(safety["blockers"]),
                None,
            )

        if old not in text:
            return (
                False,
                "The original code block was not found. The file may have changed. Re-open the file and ask again.",
                None,
            )

        backup = path.with_suffix(path.suffix + ".tew_backup")
        if not backup.exists():
            backup.write_text(text, encoding="utf-8")

        action = patch.get("action", "replace")
        if action == "insert_after":
            updated = text.replace(old, old + "\n\n\n" + new, 1)
        else:
            updated = text.replace(old, new, 1)

        path.write_text(updated, encoding="utf-8")

        msg = (
            f"File: {path}\n"
            f"Change: {patch.get('summary', 'Applied safe local patch.')}\n"
            f"Backup: {backup}"
        )
        return True, msg, updated
    except Exception as e:
        return False, str(e), None
