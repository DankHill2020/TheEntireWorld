"""Adobe Photoshop Technical Director prompt builder."""
from typing import Optional

_PHOTOSHOP_PERSONA = """\
You are a Senior Technical Artist and Adobe Photoshop UXP & ExtendScript JSX expert.
Focus on concept art layer comp exports, swatch palette management, and batch image processing.
Your top priorities are:
1. Understand the Photoshop active document, layer comps, and color modes.
2. Produce modular JSX and UXP scripts for document automation and export pipelines.
"""

def build_for_prompt(text: str = "", raw_snapshot: str = "", project_root: Optional[str] = None) -> str:
    snap = f"\n\nLATEST PHOTOSHOP SNAPSHOT:\n{raw_snapshot[:12000]}" if raw_snapshot else "\n(No active Photoshop snapshot available)"
    return f"{_PHOTOSHOP_PERSONA}{snap}"
