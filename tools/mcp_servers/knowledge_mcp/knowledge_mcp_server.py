import os
import re
from pathlib import Path
from fastmcp import FastMCP

mcp = FastMCP("KnowledgeMCP")

TOOLS_ROOT = Path(r"C:\depot\tools")

DEFAULT_ROOTS = [
    TOOLS_ROOT,

    # Maya 2023
    Path(r"C:\Program Files\Autodesk\Maya2023\devkit"),
    Path(r"C:\Program Files\Autodesk\Maya2023\Python"),
    Path(r"C:\Program Files\Autodesk\Maya2023\scripts"),
    Path(r"C:\Program Files\Autodesk\Maya2023\plug-ins"),
    Path(r"C:\Users\Aaron\Documents\maya\scripts"),

    # Unreal 5.8
    Path(r"C:\Program Files\Epic Games\UE_5.8\Engine\Plugins"),
    Path(r"C:\Program Files\Epic Games\UE_5.8\Engine\Source"),
    Path(r"C:\Program Files\Epic Games\UE_5.8\Engine\Content\Python"),

    # Project/tooling
    Path(r"C:\Desktop\MayaMCP"),
    Path(r"C:\Desktop\UnrealGenAISupport"),
    Path(r"C:\depot\Time_Fighters 5.8"),
]

TEXT_EXTS = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml",
    ".ini", ".cfg", ".bat", ".ps1", ".mel"
}

SKIP_DIRS = {
    "__pycache__", ".git", ".svn", ".idea", ".vs",
    "Intermediate", "Saved", "DerivedDataCache", "Binaries"
}


def root_dirs() -> list[Path]:
    """
    Return approved searchable roots.

    Optional override:
    AI_KNOWLEDGE_ROOTS="C:\\depot\\tools;C:\\Some\\Other\\Docs"
    """
    env = os.environ.get("AI_KNOWLEDGE_ROOTS")
    if env:
        roots = [Path(p.strip()) for p in env.split(";") if p.strip()]
    else:
        roots = DEFAULT_ROOTS

    return [r for r in roots if r.exists()]


def is_inside(path: Path, root: Path) -> bool:
    try:
        path = path.resolve()
        root = root.resolve()
        return path == root or root in path.parents
    except Exception:
        return False


def is_allowed_path(path: Path) -> bool:
    return any(is_inside(path, root) for root in root_dirs())


def iter_files(base: Path):
    if not base.exists():
        return

    for p in base.rglob("*"):
        if not p.is_file():
            continue

        if p.suffix.lower() not in TEXT_EXTS:
            continue

        parts = {part.lower() for part in p.parts}
        if any(skip.lower() in parts for skip in SKIP_DIRS):
            continue

        yield p


def tokenize(query: str) -> list[str]:
    return [
        t.lower()
        for t in re.findall(r"[A-Za-z0-9_./:-]+", query)
        if len(t) > 1
    ]


def score_text(path: Path, text: str, terms: list[str]) -> int:
    lower = text.lower()
    name_lower = str(path).lower()

    score = 0
    for term in terms:
        if term in name_lower:
            score += 10
        score += min(lower.count(term), 8)

    return score


def make_snippet(text: str, terms: list[str], radius_before=700, radius_after=1800) -> str:
    lower = text.lower()
    indexes = [lower.find(t) for t in terms if lower.find(t) >= 0]
    idx = min(indexes) if indexes else 0

    start = max(0, idx - radius_before)
    end = min(len(text), idx + radius_after)
    return text[start:end].strip()


def display_path(path: Path) -> str:
    for root in root_dirs():
        try:
            return f"{root.name}/{path.relative_to(root)}"
        except Exception:
            continue
    return str(path)


@mcp.tool()
def knowledge_search(query: str, subdir: str = "", max_results: int = 8) -> str:
    """
    Search approved knowledge roots:
    - C:/depot/tools
    - Maya 2023 examples/scripts/devkit
    - Unreal 5.8 plugins/source/python
    - project-specific tooling

    Use this before generating new Maya/Unreal code.
    """
    terms = tokenize(query)
    if not terms:
        return "No searchable terms provided."

    hits = []

    for root in root_dirs():
        base = root / subdir if subdir else root
        if not base.exists():
            continue

        for path in iter_files(base):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            score = score_text(path, text, terms)
            if score <= 0:
                continue

            snippet = make_snippet(text, terms)
            hits.append((score, path, snippet))

    hits.sort(key=lambda x: x[0], reverse=True)

    if not hits:
        return f"No results for: {query}"

    chunks = []
    for score, path, snippet in hits[:max_results]:
        chunks.append(
            f"## {display_path(path)}\n"
            f"Score: {score}\n\n"
            f"```text\n{snippet}\n```"
        )

    return "\n\n---\n\n".join(chunks)


@mcp.tool()
def read_tool_file(path: str, max_chars: int = 20000) -> str:
    """
    Read a file from any approved knowledge root.

    Relative paths resolve from C:/depot/tools.
    Absolute paths are allowed only if inside approved roots.
    """
    p = Path(path)

    if not p.is_absolute():
        p = TOOLS_ROOT / p

    try:
        rp = p.resolve()

        if not is_allowed_path(rp):
            return f"Refusing to read outside approved roots: {rp}"

        if not rp.exists():
            return f"File not found: {rp}"

        return rp.read_text(encoding="utf-8", errors="replace")[:max_chars]

    except Exception as e:
        return f"Error reading file: {e}"


@mcp.tool()
def write_pending_tool(relative_path: str, code: str) -> str:
    """
    Write generated code to C:/depot/tools/ai_generated/pending_review only.

    Do not write directly to production Maya/Unreal tools.
    """
    pending = (TOOLS_ROOT / "ai_generated" / "pending_review").resolve()
    target = (pending / relative_path).resolve()

    try:
        if not is_inside(target, pending):
            return f"Refusing to write outside pending_review: {target}"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")

        return f"Wrote pending tool: {target}"

    except Exception as e:
        return f"Error writing pending tool: {e}"


@mcp.tool()
def list_knowledge_roots() -> str:
    """List currently active searchable roots."""
    return "\n".join(str(r) for r in root_dirs())


@mcp.tool()
def list_depot_tree(subdir: str = "", max_entries: int = 250) -> str:
    """
    List files/folders under C:/depot/tools.
    """
    base = TOOLS_ROOT / subdir if subdir else TOOLS_ROOT

    if not base.exists():
        return f"Path does not exist: {base}"

    rows = []
    for i, path in enumerate(base.rglob("*")):
        if i >= max_entries:
            rows.append("... truncated ...")
            break

        try:
            rows.append(str(path.relative_to(TOOLS_ROOT)))
        except Exception:
            rows.append(str(path))

    return "\n".join(rows)


@mcp.tool()
def agent_workflow() -> str:
    """Read the AI agent workflow rules."""
    path = TOOLS_ROOT / "knowledge" / "AI_AGENT_WORKFLOW.md"

    if not path.exists():
        return "AI_AGENT_WORKFLOW.md not found."

    return path.read_text(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    mcp.run()