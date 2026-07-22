"""Application-wide constants."""

import json
import os
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
APP_PACKAGE = "tech_connector"
APP_DISPLAY_NAME = "The Entire World Tech Connector"
APP_SHORT_NAME = "Tech Connector"
APP_VERSION = "v6.7"
LOGO_PATH = APP_ROOT / "assets" / "tech_connector_logo.png"
FALLBACK_LOGO_PATH = APP_ROOT / "assets" / "the_entire_world_logo.png"

def _detect_tools_root() -> Path:
    configured = os.environ.get("AI_STUDIO_TOOLS_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    for candidate in [APP_ROOT] + list(APP_ROOT.parents):
        if candidate.name.lower() == "tools":
            return candidate
    return APP_ROOT


def app_module(relative_module: str) -> str:
    """Return a fully qualified module name for cross-process imports."""
    relative = str(relative_module or "").strip(".")
    return f"{APP_PACKAGE}.{relative}" if relative else APP_PACKAGE


APP_DIR = Path(os.environ.get("AI_STUDIO_APP_DIR", str(APP_ROOT / ".ai_studio"))).expanduser()
SCRATCHES_DIR = APP_DIR / "scratches"
HISTORY_DIR = SCRATCHES_DIR / "chat_history"
CODE_SNIPPETS_DIR = SCRATCHES_DIR / "code_snippets"
IMAGE_DIR = APP_DIR / "images"
SETTINGS_PATH = APP_DIR / "settings.json"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
CODE_SNIPPETS_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

TOOLS_ROOT = _detect_tools_root()
KNOWLEDGE_DIR = APP_ROOT / "knowledge"
PROJECT_ROOT_ENV = "TECH_CONNECTOR_PROJECT_ROOT"
PROJECT_KNOWLEDGE_RELATIVE = Path("tech_connector") / "knowledge" / "index"


def active_project_root(project_root: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the project that owns generated index data."""
    if project_root:
        return Path(project_root).expanduser().resolve()
    configured = os.environ.get(PROJECT_ROOT_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        active = str(settings.get("active_project", "")).strip()
        if active:
            return Path(active).expanduser().resolve()
    except (OSError, ValueError, TypeError):
        pass
    return TOOLS_ROOT


def set_active_project_root(project_root: str | os.PathLike[str] | None) -> Path:
    """Set the active project root inherited by worker and MCP processes."""
    resolved = active_project_root(project_root)
    os.environ[PROJECT_ROOT_ENV] = str(resolved)
    return resolved


def project_index_db_path(project_root: str | os.PathLike[str] | None = None) -> Path:
    """Return the stable per-project knowledge-index database path."""
    return active_project_root(project_root) / PROJECT_KNOWLEDGE_RELATIVE / "knowledge_index_v2.sqlite"


# Compatibility for external callers. Internal code resolves the path at use time.
V2_DB = project_index_db_path()
DCC_TOOL_PACKAGE_NAMES = [
    "maya_tools",
    "unreal_tools",
    "motionbuilder_tools",
    "mobu_tools",
    "blender_tools",
    "substance_painter_tools",
    "unity_tools",
]

try:
    if SETTINGS_PATH.exists():
        _settings_data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        _custom = _settings_data.get("custom_dcc_packages")
        if isinstance(_custom, list):
            for pkg in _custom:
                pkg_str = str(pkg).strip()
                if pkg_str and pkg_str not in DCC_TOOL_PACKAGE_NAMES:
                    DCC_TOOL_PACKAGE_NAMES.append(pkg_str)
except Exception:
    pass

DCC_TOOL_PACKAGE_DIRS = [
    TOOLS_ROOT / name
    for name in DCC_TOOL_PACKAGE_NAMES
    if (TOOLS_ROOT / name).exists()
]

DEFAULT_MAYA_PORT = 7001
DEFAULT_UNREAL_PORT = 8001
DEFAULT_BLENDER_PORT = 7021
DEFAULT_SUBSTANCE_PAINTER_PORT = 7041
DEFAULT_UNITY_PORT = 7071
DEFAULT_MOTIONBUILDER_PORT = 7051

DEFAULT_MCPHOST = os.path.join(os.path.expanduser("~"), "go", "bin", "mcphost.exe")
DEFAULT_MODEL = "ollama:qwen2.5-coder:1.5b"
DEFAULT_CONFIGS = [
    str(APP_ROOT / "knowledge" / "mcp_unreal_maya_knowledge_config.json"),
]

ASSUMED_DIRS = [
    str(APP_ROOT),
    *[str(path) for path in DCC_TOOL_PACKAGE_DIRS],
]

ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

def get_user_name() -> str:
    import os
    return os.environ.get("USERNAME") or os.environ.get("USER") or "User"

# Obfuscated Base64 representation of the priming instructions to prevent trivial guardrail bypassing
_RAW_PRIME_B64 = (
    b"VXNlIHRvb2xzIGJlZm9yZSBhbnN3ZXJpbmcuIERvIG5vdCBpbnZlbnQgaW50ZXJuYWwgZnVuY3Rpb24gbmFtZXMuIC"
    b"BGb3IgdG9vbHMgY2FsbCBrbm93bGVkZ2VfX3N5bWJvbF9zZWFyY2ggb3Iga25vd2xlZGdlX19rbm93bGVkZ2Vfc2Vh"
    b"cmNoIGZpcnN0LiBGb3IgZXhhY3QgY29kZSB1c2Uga25vd2xlZGdlX19yZWFkX3N5bWJvbF9zb3VyY2UuIEZvciBzaW"
    b"1wbGUgTWF5YS9VbnJlYWwvQmxlbmRlciBob3N0IHF1ZXJpZXMsIHByZWZlciBkaXJlY3QgVUkgaG9zdCBhY3Rpb25z"
    b"LiBGb3IgTWF5YSBjb2RlIHRocm91Z2ggTUNQIHVzZSBtYXlhX19tYXlhX2V4ZWN1dGVfcHl0aG9uIHdpdGggcHJpb"
    b"nQoLi4uKS4gRm9yIFVucmVhbCB0aHJvdWdoIE1DUCB1c2UgVW5yZWFsR2VuQUkgdG9vbHMuIEZvciBCbGVuZGVyIH"
    b"VzZSBkaXJlY3QgYnB5IGV4ZWN1dGlvbiB1bnRpbCBCbGVuZGVyIE1DUCBpcyBlbmFibGVkLiBGb3IgTW90aW9uQnV"
    b"pbGRlciB1c2UgbW90aW9uYnVpbGRlcl9fbW90aW9uYnVpbGRlcl9leGVjdXRlX3B5dGhvbiB3aXRoIHByaW50KC4u"
    b"LikuIEZvciBVbnJlYWwgdXNlIFVucmVhbEdlbkFJIHRvb2xzLiBOZXZlciBkZWxldGUvb3ZlcndyaXRlL3NhdmUvc"
    b"3VibWl0L21hc3MgcmVuYW1lIHdpdGhvdXQgZXhwbGljaXQgY29uZmlybWF0aW9uLiBCZSBkaXJlY3Qu"
)

import base64
_decoded_prompt = base64.b64decode(_RAW_PRIME_B64).decode("utf-8")
_decoded_prompt += (
    " When responding to queries in plain speech, always write in a friendly, conversational, and natural human tone. "
    "Avoid sounding like a robotic system or command-line utility. Be very clear in description, detail the exact "
    "DCC functions (Maya, Unreal, Blender, MotionBuilder, Unity) being run or suggested, including full "
    "names and all arguments, and format them in clear code blocks so the user can copy and run them "
    "directly in the DCC script editor."
)
# Format dynamic username rule into the prompt string
PRIME_PROMPT = _decoded_prompt.replace(" For ", f" For {get_user_name()} ")

SKIP_DIRS = {
    "__pycache__", ".git", ".svn", ".idea", ".vs",
    "Intermediate", "Saved", "DerivedDataCache", "Binaries",
    ".pytest_cache", "node_modules",
}

SUPPORTED_CODE_EXTS = {
    ".py", ".mel", ".cpp", ".h", ".hpp", ".cs", ".ts", ".tsx", ".js", ".jsx",
    ".html", ".css", ".json", ".yaml", ".yml", ".md", ".txt", ".ini", ".cfg",
    ".bat", ".ps1", ".usf", ".ush", ".uplugin", ".uproject",
}

STATUS_CARD_LABELS = {
    "ollama": "Ollama",
    "mcphost": "MCPHost",
    "knowledge": "Knowledge",
    "vcs": "VCS",
    "maya": "Maya",
    "unreal": "Unreal",
    "blender": "Blender",
    "substance_painter": "Substance",
    "motionbuilder": "MotionBuilder",
    "unity": "Unity",
    "houdini": "Houdini",
    "slack": "Slack",
    "discord": "Discord",
    "gmail": "Gmail",
    "email": "Email",
    "github": "GitHub",
    "git": "Git",
    "perforce": "Perforce",
    "p4": "Perforce",
    "atlassian": "Atlassian",
    "jira": "Jira",
    "integrations": "Integrations",
}

STATUS_CARD_ICONS = {
    "ollama": "OL",
    "mcphost": "MCP",
    "knowledge": "KB",
    "vcs": "VCS",
    "maya": "Maya",
    "unreal": "UE",
    "blender": "B",
    "substance_painter": "SP",
    "motionbuilder": "MB",
    "unity": "U",
    "houdini": "H",
    "slack": "SL",
    "discord": "DC",
    "gmail": "GM",
    "email": "@",
    "github": "GH",
    "git": "Git",
    "perforce": "P4",
    "p4": "P4",
    "atlassian": "AT",
    "jira": "Jira",
    "integrations": "+",
}

LOGO_GREEN = "#5bd000"
LOGO_BLUE = "#1e9bff"
LOGO_DARK = "#00040a"
LOGO_DARK_BLUE = "#000711"

STATUS_CARD_COLORS = {
    "ok": LOGO_GREEN,
    "warn": "#ff9f1c",
    "bad": "#e05252",
    "busy": LOGO_BLUE,
    "off": "#4d6872",
    "unknown": "#7fa8b8",
}


# Source-scope labels used by the knowledge index and project search ranking.
SOURCE_SCOPE_PROJECT = "project"
SOURCE_SCOPE_EXTERNAL_TOOLS = "external_tools"
SOURCE_SCOPE_THIRD_PARTY = "third_party"
SOURCE_SCOPE_PYTHON_STDLIB = "python_stdlib"
SOURCE_SCOPE_UNREAL_ENGINE = "unreal_engine"
SOURCE_SCOPE_MAYA = "maya"
SOURCE_SCOPE_DCC_APP = "dcc_app"
SOURCE_SCOPE_UNKNOWN = "unknown"
SOURCE_SCOPE_ALL = "all"
SOURCE_SCOPE_STRICT_PROJECT = "strict_project"
SOURCE_SCOPE_EXTERNAL = "external"
