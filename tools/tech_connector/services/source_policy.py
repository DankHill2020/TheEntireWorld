"""Prompt policy for local-only versus live web/GitHub sourcing."""

from typing import Optional


LOCAL_ONLY_PROMPT_PREFIX = """Source mode: LOCAL ONLY.
Use only local project files, the local knowledge index, configured MCP tools,
and the current conversation. Do not browse the web, fetch GitHub repositories,
or suggest that live external code has been inspected.
"""

LIVE_SOURCES_PROMPT_PREFIX = """Source mode: LIVE WEB/GITHUB ENABLED.
You may search live web and GitHub sources when current tools, APIs, plugins,
or external workflows could matter. Prefer official docs and primary project
repositories. Before using or ingesting third-party code, summarize the source,
license/repo identity if available, files that would be imported, and any risk.
Do not overwrite local files or install dependencies without explicit approval.
"""

RESEARCH_MODE_PROMPT = """
Research mode:
- Use local project knowledge before external sources.
- Treat live web techniques as pattern research, not code to copy.
- Use GitHub examples only when enabled, and identify repo/license risk before ingesting anything.
- Compare architecture options before recommending a build path when comparison is enabled.
- Produce an implementation plan before mutating project files unless auto implement is explicitly enabled.
"""

DCC_ENGINE_GROUNDING_POLICY = """
DCC / engine development grounding:
- For Unreal, Maya, Blender, Houdini, MotionBuilder, Substance Painter, Unity, or other host-app development, never invent an API, command, node, plugin, asset path, or execution workflow when local project knowledge cannot verify it.
- First use local bridge capabilities, registered operations, indexed project code, ingested tools, and host snapshots.
- If the needed host API/tool/workflow is not known locally and live sources are enabled, search official docs or primary repositories before proposing or executing a solution.
- If live sources are disabled or the user cancels search, stop and say what is missing instead of fabricating a plausible implementation.
"""

COMPOSER_POLICY = """
Orchestrating & Composing Functions:
- When asked to combine, compose, or orchestrate multiple functions or tools together, generate a wrapper or composite function that coordinates them safely.
- Avoid rewriting dependencies or library functions unless necessary. Keep your wrapper simple, clean, and prefer standard Python imports.
- Make sure to add robust error handling, clear parameters, and docstrings explaining what the wrapper does.
- If the user request is underspecified (e.g. they ask to compose 'my exporter' with 'some zip tool' but didn't specify which file or function name, or what the exact orchestration order is), DO NOT write the code yet; instead, ask a clarifying follow-up question in your chat response to get the missing details.
"""


def live_sources_enabled(settings: Optional[dict]) -> bool:
    """Return whether the user has enabled live external sourcing."""
    return bool((settings or {}).get("enable_live_sources", False))


def get_ingested_tools_summary(settings: dict) -> str:
    from pathlib import Path
    import json
    from tech_connector.models.constants import EXTERNAL_TOOLS_DIR
    
    ext_tools_dir = settings.get("external_tools_dir", "") or str(EXTERNAL_TOOLS_DIR)
    ext_tools_path = Path(ext_tools_dir)
    
    if not ext_tools_path.exists() or not ext_tools_path.is_dir():
        return "Configured external tools folder does not exist or is not a directory."
        
    lines = []
    lines.append(f"Configured external tools folder: {ext_tools_path.absolute()}")
    lines.append("Ingested tools available for inspection/composition:")
    
    found = False
    try:
        for sub in ext_tools_path.iterdir():
            if sub.is_dir() and not sub.name.startswith("."):
                manifest_file = sub / "ai_studio_tool_manifest.json"
                status = "available"
                repo_url = ""
                desc = ""
                if manifest_file.exists():
                    try:
                        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                        status = manifest.get("status", "available")
                        repo_url = manifest.get("repo", {}).get("html_url", "")
                        desc = manifest.get("repo", {}).get("description", "")
                    except Exception:
                        pass
                lines.append(f"- Name: {sub.name}")
                lines.append(f"  Path: {sub.absolute()}")
                lines.append(f"  Status: {status}")
                if repo_url:
                    lines.append(f"  URL: {repo_url}")
                if desc:
                    lines.append(f"  Description: {desc}")
                found = True
    except Exception as e:
        lines.append(f"Error scanning external tools: {e}")
        found = True
            
    if not found:
        lines.append("(No tools currently ingested)")
        
    return "\n".join(lines)


def source_mode_prefix(settings: Optional[dict]) -> str:
    """Return the policy prefix to attach to LLM prompts."""
    settings = settings or {}
    policy_parts = []
    
    # 1. Base search mode prefix
    if settings.get("last_search_cancelled"):
        settings["last_search_cancelled"] = False  # Consume the flag
        base_prefix = LOCAL_ONLY_PROMPT_PREFIX + "DCC context: A web/GitHub search was canceled. You MUST perform a deeper, thorough local analysis of the project functions, codebase files, and API structures to answer the query.\n"
    else:
        base_prefix = LIVE_SOURCES_PROMPT_PREFIX if live_sources_enabled(settings) else LOCAL_ONLY_PROMPT_PREFIX
        
    policy_parts.append(base_prefix)

    research_flags = {
        "project_snapshot": bool(settings.get("research_project_snapshot", True)),
        "unreal_capabilities": bool(settings.get("research_unreal_capabilities", True)),
        "official_docs": bool(settings.get("research_official_docs", True)),
        "best_practices": bool(settings.get("research_best_practices", False)),
        "web_techniques": bool(settings.get("research_web_techniques", False)),
        "github_examples": bool(settings.get("research_github_examples", False)),
        "compare_architectures": bool(settings.get("research_compare_architectures", True)),
        "generate_plan": bool(settings.get("research_generate_plan", True)),
        "auto_implement": bool(settings.get("research_auto_implement", False)),
        "previous_ai_work": bool(settings.get("ai_work_memory_enabled", True)),
        "locked_knowledge": bool(settings.get("ai_work_memory_include_locked", True)),
    }
    policy_parts.append(RESEARCH_MODE_PROMPT + json_dumps_research_flags(research_flags))
    policy_parts.append(DCC_ENGINE_GROUNDING_POLICY)
    
    # 2. Add composer/github tools strict rule
    search_github_tools = bool(settings.get("search_github_tools_when_composing", False))
    if search_github_tools:
        summary = get_ingested_tools_summary(settings)
        policy_parts.append(
            f"Composer mode: Sourced GitHub tools allowed. You may inspect and compose with third-party tools in the configured external tools folder and search GitHub for candidate code tools.\n\n{summary}\n"
        )
    else:
        policy_parts.append(
            "Composer mode: STRICT LOCAL ONLY. You are FORBIDDEN from reading, inspecting, or composing with any tools/files inside the configured external tools folder, or suggesting fetching/downloading external tools from GitHub. Only use the main codebase functions.\n"
        )
        
    # 3. Add composition guidelines
    policy_parts.append(COMPOSER_POLICY)
    
    return "\n".join(policy_parts)


def json_dumps_research_flags(flags: dict) -> str:
    import json

    return "Research flags:\n" + json.dumps(flags, indent=2)


def apply_source_policy(prompt: str, settings: Optional[dict]) -> str:
    """Attach source policy to a prompt if it is not already present."""
    prompt = prompt or ""
    if prompt.startswith("Source mode:"):
        return prompt
    return f"{source_mode_prefix(settings)}\nUser request:\n{prompt}"


SUSPICIOUS_PATTERNS = [
    r"\bkeylogger\b",
    r"\bransomware\b",
    r"\bbackdoor\b",
    r"\breverse\s+shell\b",
    r"\bspyware\b",
    r"\bmalware\b",
    r"\bexploit\s+code\b",
    r"\bcryptojacker\b",
    r"\brootkit\b",
    r"\bcred\s+stealer\b",
    r"\bcredential\s+stealer\b",
    r"\bwiper\s+malware\b",
    r"\bwindows\s+defender\s+bypass\b",
    r"\bdishonest\s+activity\b",
]

def check_moderation(text: str) -> tuple[bool, str]:
    """
    Check if a text contains potential security-risk keywords (malware/exploit terms).
    Returns (is_flagged, matched_reason).
    """
    import re
    if not text:
        return False, ""
    
    lower_text = text.lower()
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, lower_text):
            match_word = pattern.replace(r"\b", "").replace(r"\s+", " ")
            return True, f"contains terms related to potential security risks (e.g., '{match_word}')"
            
    return False, ""
