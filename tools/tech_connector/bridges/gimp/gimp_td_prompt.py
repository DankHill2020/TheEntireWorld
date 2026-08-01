"""GIMP Technical Director prompt builder."""
from typing import Optional

_GIMP_PERSONA = """\
You are a Technical Artist and GIMP Python-Fu / Script-Fu expert.
Focus on batch texture conversion, channel packing, and automated color palette extraction.
Your top priorities are:
1. Produce clean Python-Fu scripts for batch texture processing and channel packing.
"""

def build_for_prompt(text: str = "", raw_snapshot: str = "", project_root: Optional[str] = None) -> str:
    snap = f"\n\nLATEST GIMP SNAPSHOT:\n{raw_snapshot[:12000]}" if raw_snapshot else "\n(No active GIMP snapshot available)"
    return f"{_GIMP_PERSONA}{snap}"
