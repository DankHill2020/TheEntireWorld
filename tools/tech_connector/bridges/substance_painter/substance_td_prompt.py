"""Substance 3D Painter Technical Director prompt builder."""
from typing import Optional

_SUBSTANCE_PERSONA = """\
You are a Senior Technical Artist and Substance 3D Painter Python API expert.
Focus on PBR material layer stack automation, texture set exports, and smart material presets.
Your top priorities are:
1. Understand the Substance Painter active project, texture sets, and layer stack.
2. Produce modular scripts using substance_painter.textureset, project, and export APIs.
3. Follow PBR workflow standards (Albedo, Normal, Roughness, Metallic, AO).
"""

def build_for_prompt(text: str = "", raw_snapshot: str = "", project_root: Optional[str] = None) -> str:
    snap = f"\n\nLATEST SUBSTANCE PAINTER SNAPSHOT:\n{raw_snapshot[:12000]}" if raw_snapshot else "\n(No active Substance snapshot available)"
    return f"{_SUBSTANCE_PERSONA}{snap}"
