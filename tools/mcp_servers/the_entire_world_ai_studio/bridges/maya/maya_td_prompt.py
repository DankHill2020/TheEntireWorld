"""Maya Technical Director prompt builder.
Provides a wrapper similar to Unreal's TD prompt so the LLM can receive
project-specific context when the user asks about Maya.
"""
from typing import Optional, Dict, Any, List

_MAYA_PERSONA = """\
You are a Senior Pipeline Technical Director and Maya Python expert.
Focus on robust, production-ready tooling, reusable scripts, and clean asset pipelines.
Your top priorities are:
1. Understand the existing Maya project and pipeline.
2. Produce modular tools (PyMEL, maya.cmds, OpenMaya) rather than one-off scripts.
3. Follow pipeline naming conventions and directory structures.
4. Compose workflows out of existing tools when possible.
"""

def build_for_prompt(
    text: str = "", 
    raw_snapshot: str = "",
    project_root: Optional[str] = None,
    cap_query: str = "",
) -> str:
    # Truncate snapshot
    if raw_snapshot:
        snap = raw_snapshot[:24000]
        if len(raw_snapshot) > 24000:
            snap += "\n...[Maya snapshot truncated]..."
        snapshot_section = (
            "\n\n═══════════════════════════════════════════════════════\n"
            " LATEST MAYA SNAPSHOT\n"
            "═══════════════════════════════════════════════════════\n"
            f"{snap}\n"
        )
    else:
        snapshot_section = "\n\n(No active Maya snapshot available)\n"

    # Expert mode data (Capabilities)
    caps_section = ""
    try:
        from project_analysis.capability_registry import find_capabilities
        query = cap_query or (text[:60] if text else "maya")
        caps = find_capabilities(query, max_results=25)
        maya_caps = find_capabilities("", app="Maya", max_results=15)
        seen = {c["name"] for c in caps}
        caps += [c for c in maya_caps if c["name"] not in seen]
        
        if caps:
            lines = ["\nAvailable Internal Tools (registered capabilities):"]
            for cap in caps[:30]:
                name = cap.get("name", "")
                app  = cap.get("app", "")
                risk = cap.get("risk", "")
                doc  = (cap.get("docstring") or "")[:80].replace("\n", " ")
                lines.append(f"  • {name}  [{app}] [risk:{risk}]  {doc}")
            caps_section = "\n" + "\n".join(lines)
    except Exception:
        pass

    return f"{_MAYA_PERSONA}{snapshot_section}{caps_section}"
