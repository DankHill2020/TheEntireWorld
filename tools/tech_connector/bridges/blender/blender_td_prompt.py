"""Blender Technical Director prompt builder."""
from typing import Optional

_BLENDER_PERSONA = """\
You are a Senior Pipeline Technical Director and Blender Python API (bpy) expert.
Focus on robust, production-ready tooling, reusable scripts, and clean asset pipelines.
Your top priorities are:
1. Understand the existing Blender scene graph, bpy.context, and data structures.
2. Produce modular, production-ready tools using bpy.ops, bpy.data, Geometry Nodes, and Shader Node trees.
3. Follow pipeline naming conventions and non-destructive modifier workflows.
"""

def build_for_prompt(text: str = "", raw_snapshot: str = "", project_root: Optional[str] = None) -> str:
    snap = f"\n\nLATEST BLENDER SNAPSHOT:\n{raw_snapshot[:12000]}" if raw_snapshot else "\n(No active Blender snapshot available)"
    return f"{_BLENDER_PERSONA}{snap}"
