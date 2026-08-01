# rules_loader.py
"""Project memory and rules loader for the Tech Connector pipeline.

Loads `.project_ai/` rule files from the configured project root and injects
their content as a system preamble for every LLM context window.
"""
import json
import yaml
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_AI_DIR = ".project_ai"

_FILES = {
    "rules":         "rules.md",
    "capabilities":  "capabilities.json",
    "asset_index":   "asset_index.json",
    "model_routing": "model_routing.json",
    "safety_rules":  "safety_rules.json",
}


def find_project_ai_dir(start: Optional[str] = None) -> Optional[Path]:
    """Walk up from *start* (or cwd) to find the nearest `.project_ai/` directory."""
    root = Path(start).resolve() if start else Path.cwd()
    for candidate in [root, *root.parents]:
        d = candidate / PROJECT_AI_DIR
        if d.is_dir():
            return d
    return None


def load_rules(project_root: Optional[str] = None) -> Dict[str, Any]:
    """Load all `.project_ai/` files and return a structured dict."""
    ai_dir = find_project_ai_dir(project_root)
    data: Dict[str, Any] = {}

    if ai_dir is None:
        return data

    for key, filename in _FILES.items():
        filepath = ai_dir / filename
        if not filepath.exists():
            continue
        try:
            text = filepath.read_text(encoding="utf-8")
            if filename.endswith(".json"):
                data[key] = json.loads(text)
            else:
                data[key] = text
        except Exception as e:
            data[key] = f"[Error reading {filename}: {e}]"

    return data


def build_system_preamble(project_root: Optional[str] = None) -> str:
    """Build a system-prompt preamble injected before every LLM call.

    Includes:
    - Studio rules and naming conventions
    - Model routing preferences
    - Safety rules
    - Asset index summary (top-level only, to keep tokens short)
    """
    rules = load_rules(project_root)
    lines = ["# Project Context (auto-injected by Tech Connector)\n"]

    if "rules" in rules:
        lines.append("## Studio Rules\n")
        lines.append(str(rules["rules"]))
        lines.append("\n")

    if "safety_rules" in rules:
        sr = rules["safety_rules"]
        lines.append("## Safety Rules\n")
        if isinstance(sr, dict):
            for k, v in sr.items():
                lines.append(f"- **{k}**: {v}")
        else:
            lines.append(str(sr))
        lines.append("\n")

    if "model_routing" in rules:
        mr = rules["model_routing"]
        lines.append("## Model Routing Preferences\n")
        if isinstance(mr, dict):
            for tier, model in mr.items():
                lines.append(f"- {tier}: `{model}`")
        else:
            lines.append(str(mr))
        lines.append("\n")

    if "asset_index" in rules:
        ai = rules["asset_index"]
        lines.append("## Recent Asset Index (summary)\n")
        if isinstance(ai, dict):
            for k, v in list(ai.items())[:5]:  # cap to keep tokens sane
                lines.append(f"- {k}: {v}")
        lines.append("\n")

    return "\n".join(lines)


def create_default_project_ai(project_root: str) -> Path:
    """Scaffold a default `.project_ai/` folder structure in *project_root*."""
    ai_dir = Path(project_root) / PROJECT_AI_DIR
    ai_dir.mkdir(parents=True, exist_ok=True)

    defaults = {
        "rules.md": "# Studio Rules\n\n- Follow naming conventions defined per-project.\n- Do not modify files in `/Binaries/`, `/Intermediate/`, or `/Saved/`.\n- Always back up assets before applying AI-generated changes.\n",
        "capabilities.json": json.dumps({"_note": "Auto-populated by the capability registry."}, indent=2),
        "asset_index.json": json.dumps({"_note": "Auto-populated by the Unreal scanner."}, indent=2),
        "model_routing.json": json.dumps({
            "embed":       "nomic-embed-text",
            "local_code":  "qwen2.5-coder:3b",
            "local_plan":  "qwen3:4b-instruct",
            "local_deep":  "qwen3:4b-instruct",
            "active":      "auto",
        }, indent=2),
        "safety_rules.json": json.dumps({
            "require_backup":    True,
            "require_preview":   True,
            "no_touch_dirs":     ["/Binaries", "/Intermediate", "/Saved", "/DerivedDataCache"],
            "confirm_mutations": True,
        }, indent=2),
    }

    for filename, content in defaults.items():
        p = ai_dir / filename
        if not p.exists():
            p.write_text(content, encoding="utf-8")

    return ai_dir


if __name__ == "__main__":
    preamble = build_system_preamble()
    print(preamble if preamble.strip() else "No .project_ai/ directory found.")
