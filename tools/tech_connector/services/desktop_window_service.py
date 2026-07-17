"""Read-only desktop window inspection for prompt and application commands."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
from typing import Any


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4


def _process_name(pid: int) -> str:
    if sys.platform != "win32" or not pid:
        return ""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).stem
    finally:
        kernel32.CloseHandle(handle)
    return ""


def inspect_desktop_windows(
    *,
    process_name: str = "",
    title_query: str = "",
    include_untitled: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """Enumerate visible top-level windows without focusing or changing them."""

    if sys.platform != "win32":
        return {
            "ok": False,
            "supported": False,
            "platform": sys.platform,
            "windows": [],
            "errors": ["Desktop window inspection is currently implemented for Windows."],
        }

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowEnabled.argtypes = [wintypes.HWND]
    user32.IsWindowEnabled.restype = wintypes.BOOL
    foreground = int(user32.GetForegroundWindow() or 0)
    process_filter = str(process_name or "").strip().lower().removesuffix(".exe")
    title_filter = str(title_query or "").strip().lower()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    def visit(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = int(user32.GetWindowTextLengthW(hwnd) or 0)
            title_buffer = ctypes.create_unicode_buffer(max(1, length + 1))
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            title = title_buffer.value.strip()
            if not title and not include_untitled:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            executable = _process_name(int(pid.value))
            if process_filter and process_filter not in executable.lower():
                return True
            if title_filter and title_filter not in title.lower():
                return True
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            owner = int(user32.GetWindow(hwnd, GW_OWNER) or 0)
            rows.append(
                {
                    "handle": int(hwnd),
                    "pid": int(pid.value),
                    "process_name": executable,
                    "title": title,
                    "bounds": {
                        "left": int(rect.left),
                        "top": int(rect.top),
                        "right": int(rect.right),
                        "bottom": int(rect.bottom),
                        "width": max(0, int(rect.right - rect.left)),
                        "height": max(0, int(rect.bottom - rect.top)),
                    },
                    "foreground": int(hwnd) == foreground,
                    "enabled": bool(user32.IsWindowEnabled(hwnd)),
                    "owner_handle": owner,
                    "owned_window": bool(owner),
                }
            )
            return len(rows) < max(1, int(limit or 100))
        except Exception as exc:
            errors.append(str(exc))
            return True

    callback = callback_type(visit)
    if not user32.EnumWindows(callback, 0):
        error_code = int(ctypes.get_last_error() or 0)
        if error_code:
            errors.append(f"EnumWindows failed with Win32 error {error_code}.")

    handles = {row["handle"] for row in rows}
    for row in rows:
        row["owner_in_result"] = row["owner_handle"] in handles
        row["modal_candidate"] = bool(row["owned_window"] or not row["enabled"])
    return {
        "ok": not errors,
        "supported": True,
        "platform": sys.platform,
        "filters": {"process_name": process_name, "title_query": title_query},
        "foreground_handle": foreground,
        "window_count": len(rows),
        "modal_candidate_count": sum(1 for row in rows if row["modal_candidate"]),
        "windows": rows,
        "errors": errors,
        "mutated_desktop": False,
    }


def render_desktop_window_inspection(result: dict[str, Any]) -> str:
    """Render a compact prompt answer from a typed window inspection result."""

    if not result.get("supported"):
        return "Desktop window inspection is not supported on this platform."
    rows = list(result.get("windows") or [])
    if not rows:
        filters = result.get("filters") or {}
        query = filters.get("process_name") or filters.get("title_query") or "the requested filter"
        return f"No visible desktop windows matched `{query}`."
    lines = [f"Visible windows: {len(rows)}"]
    for row in rows:
        state = []
        if row.get("foreground"):
            state.append("foreground")
        if row.get("modal_candidate"):
            state.append("modal candidate")
        if not row.get("enabled", True):
            state.append("disabled")
        suffix = f" ({', '.join(state)})" if state else ""
        bounds = row.get("bounds") or {}
        lines.append(
            f"- {row.get('process_name') or 'process'} [{row.get('pid')}]: "
            f"`{row.get('title') or '(untitled)'}` at "
            f"{bounds.get('left')},{bounds.get('top')} "
            f"{bounds.get('width')}x{bounds.get('height')}{suffix}"
        )
    return "\n".join(lines)
