"""Portable import-path helpers for source and packaged Tech Connector runs."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_tools_root_on_path(anchor_file: str) -> Path:
    """Return the source/deployment root and add it to sys.path when needed."""
    configured = (
        os.environ.get("TOOLSROOT", "").strip()
        or os.environ.get("AI_STUDIO_TOOLS_ROOT", "").strip()
    )
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        anchor = Path(anchor_file).resolve()
        root = None
        for candidate in anchor.parents:
            if candidate.name.lower() == "tools":
                root = candidate
                break
        if root is None:
            package_parent = anchor.parent
            while package_parent.name.lower() != "tech_connector" and package_parent.parent != package_parent:
                package_parent = package_parent.parent
            root = package_parent.parent if package_parent.name.lower() == "tech_connector" else anchor.parent
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root
