"""File-type helpers."""

from pathlib import Path

from models.constants import SUPPORTED_CODE_EXTS


def is_supported_code_file(path) -> bool:
    try:
        return Path(path).suffix.lower() in SUPPORTED_CODE_EXTS
    except Exception:
        return False


def supported_code_exts():
    return SUPPORTED_CODE_EXTS


def is_python_file(path) -> bool:
    try:
        return Path(path).suffix.lower() == ".py"
    except Exception:
        return False
