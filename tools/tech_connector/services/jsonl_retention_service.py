"""Small, shared helpers for bounded JSONL runtime files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_ARCHIVE_COUNT = 2


def rotate_file(path: str | Path, *, max_bytes: int, archive_count: int) -> None:
    """Rotate ``path`` when it reaches ``max_bytes``, keeping bounded archives."""

    target = Path(path)
    try:
        if target.stat().st_size < max(1, int(max_bytes)):
            return
    except FileNotFoundError:
        return

    keep = max(0, int(archive_count))
    if keep == 0:
        target.unlink(missing_ok=True)
        return

    Path(f"{target}.{keep}").unlink(missing_ok=True)
    for index in range(keep - 1, 0, -1):
        source = Path(f"{target}.{index}")
        if source.exists():
            source.replace(Path(f"{target}.{index + 1}"))
    target.replace(Path(f"{target}.1"))


def append_jsonl_record(
    path: str | Path,
    payload: Any,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    archive_count: int = DEFAULT_ARCHIVE_COUNT,
    ensure_ascii: bool = True,
    sort_keys: bool = False,
) -> Path:
    """Append one JSON record while keeping the file and its archives bounded."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rotate_file(target, max_bytes=max_bytes, archive_count=archive_count)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                payload,
                ensure_ascii=ensure_ascii,
                sort_keys=sort_keys,
                default=str,
            )
            + "\n"
        )
    return target
