from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import copy
import re

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidgetAction,
    QWidget,
)

from tech_connector.ui.pipeline_node_types import (
    FLOW_PORT,
    display_output_type,
    display_param_type,
    infer_package,
    normalized_outputs,
)
from tech_connector.ui.pipeline_utility_nodes import (
    UTILITY_NODE_REGISTRY,
    add_dynamic_port,
    create_utility_step_data,
    remove_last_dynamic_port,
    utility_node_menu_items,
)
from tech_connector.services.tool_search_ranking_service import (
    tool_query_matches,
    tool_query_rank,
    tool_search_tokens,
)
ACTION_GROUP_KEYWORDS = (
    ("Rigging", ("rig", "joint", "skin", "constraint", "ik", "fk", "control", "retarget", "skeleton", "bone")),
    ("Animation", ("anim", "key", "pose", "timeline", "motion", "take", "sequence", "clip")),
    ("Effects", ("fx", "effect", "particle", "niagara", "sim", "simulation", "fluid", "pyro", "vfx", "dop")),
    ("Modeling", ("mesh", "model", "geo", "geometry", "curve", "shape", "primitive", "vertex", "sop")),
    ("Materials", ("material", "shader", "texture", "uv", "render", "lookdev")),
    ("Scene / Files", ("scene", "level", "asset", "file", "import", "export", "selection", "object", "actor", "node")),
)


class _ToolPickerFilterEdit(QLineEdit):
    navigationRequested = Signal(int)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Down:
            self.navigationRequested.emit(1)
            event.accept()
            return
        if event.key() == Qt.Key_Up:
            self.navigationRequested.emit(-1)
            event.accept()
            return
        super().keyPressEvent(event)


class _ToolPickerListWidget(QListWidget):
    symbolActivatedWithMode = Signal(dict, str)

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if item is not None:
            symbol = item.data(Qt.UserRole)
            if isinstance(symbol, dict):
                if event.button() == Qt.MiddleButton:
                    self.symbolActivatedWithMode.emit(symbol, "configured")
                    event.accept()
                    return
                if event.button() == Qt.RightButton:
                    self.symbolActivatedWithMode.emit(symbol, "workflow_context")
                    event.accept()
                    return
        super().mousePressEvent(event)


def _search_tokens(text: str) -> list[str]:
    return tool_search_tokens(text)


def _contains_ordered_terms(tokens: list[str], terms: list[str]) -> bool:
    if not terms:
        return True
    pos = 0
    for token in tokens:
        if token == terms[pos]:
            pos += 1
            if pos == len(terms):
                return True
    return False


def pipeline_tool_query_rank(row: dict[str, Any], terms: list[str]) -> tuple[int, int, str, str]:
    """Rank tool-search rows by closest name match before broader context matches."""
    return tool_query_rank(row, terms)

PROVIDER_TAXONOMIES = {
    "maya": {
        "display": "Maya",
        "order": 10,
        "categories": ["Animation", "Rigging", "Modeling", "Effects", "Rendering", "Scene", "Selection", "Files", "Other"],
    },
    "unreal": {
        "display": "Unreal",
        "order": 20,
        "categories": ["Assets", "Actors", "Animation", "Control Rig", "Sequencer", "Niagara", "Materials", "World", "Other"],
    },
    "blender": {
        "display": "Blender",
        "order": 30,
        "categories": ["Animation", "Rigging", "Modeling", "Materials", "Rendering", "Scene", "Selection", "Files", "Other"],
    },
    "motionbuilder": {
        "display": "MotionBuilder",
        "order": 40,
        "categories": ["Characters", "Animation", "Retargeting", "Scene", "Files", "Other"],
    },
    "substance_painter": {
        "display": "Substance Painter",
        "order": 50,
        "categories": ["Materials", "Textures", "Baking", "Export", "Files", "Other"],
    },
    "github": {
        "display": "GitHub",
        "order": 70,
        "categories": ["Repository", "Branches", "Commits", "Files", "Changes", "Pull Requests", "Issues", "Releases", "Other"],
    },
    "slack": {
        "display": "Slack",
        "order": 80,
        "categories": ["Messages", "Channels", "People", "Notifications", "Files", "Other"],
    },
    "discord": {
        "display": "Discord",
        "order": 82,
        "categories": ["Messages", "Channels", "People", "Notifications", "Other"],
    },
    "confluence": {
        "display": "Confluence",
        "order": 90,
        "categories": ["Pages", "Spaces", "Documentation", "Search", "Attachments", "Publishing", "Other"],
    },
    "jira": {
        "display": "Jira",
        "order": 92,
        "categories": ["Issues", "Projects", "Boards", "Sprints", "Search", "Transitions", "Other"],
    },
    "core": {
        "display": "Core",
        "order": 500,
        "categories": ["Dictionaries", "Lists", "Strings", "Filesystem", "Values", "Control Flow", "Other"],
    },
    "project": {
        "display": "Project",
        "order": 400,
        "categories": ["Project Tools", "Files", "Metadata", "Other"],
    },
}

PROVIDER_ALIASES = {
    "utility": "core",
    "pathlib": "core",
    "os.path": "core",
    "os_path": "core",
    "git": "github",
    "p4": "perforce",
    "substance": "substance_painter",
    "substance painter": "substance_painter",
    "atlassian": "confluence",
}

DCC_CONTEXT_APPS = {
    "blender",
    "houdini",
    "maya",
    "motionbuilder",
    "substance",
    "substance painter",
}
ENGINE_CONTEXT_APPS = {"godot", "unity", "unreal"}
VCS_CONTEXT_APPS = {"azure devops", "azuredevops", "git", "github", "gitlab", "perforce", "p4"}
MESSAGING_CONTEXT_APPS = {
    "discord",
    "gmail",
    "microsoft teams",
    "microsoftteams",
    "slack",
    "teams",
}
OPS_CONTEXT_APPS = {"atlassian", "jira", "jenkins", "linear", "miro", "notion"}


def symbol_search_text(symbol: dict[str, Any]) -> str:
    return " ".join(
        str((symbol or {}).get(key) or "")
        for key in (
            "name", "display_name", "function_display_name", "module", "function_path", "file_path",
            "qualified_name", "qualname", "class_name", "callable_scope",
            "docstring", "description", "signature", "source_package", "package", "provider_id",
            "provider_display_name", "category_id", "category_display_name", "tags",
        )
    ).lower()


def is_addable_tool_symbol(symbol: dict[str, Any]) -> bool:
    if not isinstance(symbol, dict):
        return False
    explicit_public = any(bool(symbol.get(key)) for key in (
        "public_tool", "pipeline_tool", "workflow_node", "tool_action", "capability_action", "utility_kind",
    ))
    if symbol.get("kind") not in {None, "", "function", "class"}:
        return bool(explicit_public and symbol.get("kind") == "utility")
    name = str(symbol.get("name") or "").strip()
    if name == "__init__":
        return False
    if name.startswith("_") and not explicit_public:
        return False
    if symbol.get("private") is True or symbol.get("internal") is True:
        return bool(explicit_public)
    callable_scope = str(symbol.get("callable_scope") or "").strip().lower()
    if not explicit_public and callable_scope in {
        "instance_method",
        "class_method",
        "nested_function",
    }:
        return False
    if (
        not explicit_public
        and symbol.get("class_name")
        and callable_scope != "static_method"
    ):
        return False
    return True


def _slug(value: str) -> str:
    import re
    text = (value or "").strip().lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "other"


def provider_metadata(symbol: dict[str, Any]) -> dict[str, Any]:
    explicit_id = str(symbol.get("provider_id") or "").strip()
    inferred = infer_package(symbol) or "Project"
    provider_id = _slug(explicit_id or inferred)
    provider_id = PROVIDER_ALIASES.get(provider_id, provider_id)
    taxonomy = PROVIDER_TAXONOMIES.get(provider_id, {})
    display = (
        symbol.get("provider_display_name")
        or taxonomy.get("display")
        or (inferred if provider_id != "core" else "Core")
        or provider_id.replace("_", " ").title()
    )
    return {
        "id": provider_id,
        "display": str(display),
        "order": int(taxonomy.get("order", 300)),
        "categories": list(taxonomy.get("categories") or ["Other"]),
    }


def _category_from_keywords(symbol: dict[str, Any], provider_id: str, provider_display: str = "") -> str:
    text = symbol_search_text(symbol)
    name = str(symbol.get("name") or "").lower()
    if provider_id in {"maya", "blender"}:
        if any(word in text for word in ("skin", "joint", "constraint", "ik", "fk", "rig", "control", "skeleton")):
            return "Rigging"
        if any(word in text for word in ("anim", "key", "pose", "timeline", "motion", "clip")):
            return "Animation"
        if any(word in text for word in ("mesh", "model", "geo", "curve", "shape", "vertex")):
            return "Modeling"
        if any(word in text for word in ("fx", "effect", "particle", "sim", "fluid", "vfx")):
            return "Effects"
        if any(word in text for word in ("render", "camera", "light")):
            return "Rendering"
        if any(word in text for word in ("select", "selection")):
            return "Selection"
        if any(word in text for word in ("file", "import", "export", "save", "load", "path")):
            return "Files"
        if any(word in text for word in ("scene", "object", "node", "outliner")):
            return "Scene"
    if provider_id == "unreal":
        if "control rig" in text or "control_rig" in text:
            return "Control Rig"
        if "niagara" in text:
            return "Niagara"
        if any(word in text for word in ("sequencer", "sequence", "movie")):
            return "Sequencer"
        if any(word in text for word in ("actor", "pawn", "component")):
            return "Actors"
        if any(word in text for word in ("asset", "content", "package", "uasset")):
            return "Assets"
        if any(word in text for word in ("material", "shader", "texture")):
            return "Materials"
        if any(word in text for word in ("world", "level", "map")):
            return "World"
        if any(word in text for word in ("anim", "skeleton", "montage")):
            return "Animation"
    if provider_id == "motionbuilder":
        if any(word in text for word in ("character", "hik")):
            return "Characters"
        if any(word in text for word in ("retarget", "mapping")):
            return "Retargeting"
        if any(word in text for word in ("anim", "take", "key", "motion")):
            return "Animation"
        if any(word in text for word in ("scene", "object", "selection")):
            return "Scene"
    if provider_id == "github":
        if any(word in text for word in ("pull_request", "pull request", " pr", "review")):
            return "Pull Requests"
        if any(word in text for word in ("issue", "ticket")):
            return "Issues"
        if any(word in text for word in ("branch", "checkout")):
            return "Branches"
        if any(word in text for word in ("commit", "history", "revision")):
            return "Commits"
        if any(word in text for word in ("diff", "change", "stage", "unstage", "status", "dirty", "changelist")):
            return "Changes"
        if any(word in text for word in ("file", "blob", "tree", "path")):
            return "Files"
        if any(word in text for word in ("release", "tag")):
            return "Releases"
        if any(word in text for word in ("repo", "repository", "clone", "remote")):
            return "Repository"
    if provider_id in {"slack", "discord"}:
        if any(word in text for word in ("channel", "conversation", "room")):
            return "Channels"
        if any(word in text for word in ("user", "member", "mention", "people")):
            return "People"
        if any(word in text for word in ("notify", "notification", "alert")):
            return "Notifications"
        if any(word in text for word in ("file", "upload", "attachment")):
            return "Files"
        if any(word in text for word in ("message", "send", "reply", "thread")):
            return "Messages"
    if provider_id == "confluence":
        if any(word in text for word in ("space", "workspace")):
            return "Spaces"
        if any(word in text for word in ("attach", "file", "upload")):
            return "Attachments"
        if any(word in text for word in ("search", "find", "query")):
            return "Search"
        if any(word in text for word in ("publish", "upload", "export")):
            return "Publishing"
        if any(word in text for word in ("doc", "documentation")):
            return "Documentation"
        if any(word in text for word in ("page", "content")):
            return "Pages"
    if provider_id == "core":
        if symbol.get("utility_kind"):
            return str(symbol.get("category_display_name") or symbol.get("category") or "Other")
        if any(word in text for word in ("dict", "json", "key", "value")):
            return "Dictionaries"
        if any(word in text for word in ("list", "array", "item", "append")):
            return "Lists"
        if any(word in text for word in ("string", "str", "text", "format")):
            return "Strings"
        if any(word in text for word in ("path", "file", "dir", "folder", "glob")):
            return "Filesystem"
        if any(word in text for word in ("bool", "int", "float", "value", "literal")):
            return "Values"
    if provider_id == "project":
        if any(word in text for word in ("file", "path", "asset")):
            return "Files"
        if any(word in text for word in ("meta", "version", "manifest")):
            return "Metadata"
        return "Project Tools"
    return "Other"


def tool_category(symbol: dict[str, Any], provider: dict[str, Any] | None = None) -> str:
    provider = provider or provider_metadata(symbol)
    explicit = str(symbol.get("category_display_name") or symbol.get("category") or "").strip()
    if not explicit:
        category_id = str(symbol.get("category_id") or "").strip()
        if category_id:
            categories_by_slug = {_slug(cat): cat for cat in provider.get("categories") or []}
            explicit = categories_by_slug.get(_slug(category_id), category_id.replace("_", " ").title())
    category = explicit or _category_from_keywords(symbol, provider["id"], provider["display"])
    categories = provider.get("categories") or []
    if category not in categories and "Other" in categories:
        category = "Other" if not explicit else category
    return category or "Other"


def core_utility_symbols() -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for definition in UTILITY_NODE_REGISTRY.values():
        symbols.append({
            "name": definition.name,
            "display_name": definition.name,
            "kind": "utility",
            "provider_id": "core",
            "provider_display_name": "Core",
            "category_id": _slug(definition.category),
            "category_display_name": definition.category,
            "source_kind": "utility",
            "package": "Utility",
            "utility_kind": definition.kind,
            "params": [dict(param) for param in definition.params],
            "outputs": [dict(output) for output in definition.outputs],
            "return_annotation": definition.return_annotation,
            "description": definition.description,
            "public_tool": True,
            "tags": ["core", "utility", definition.category],
        })
    return symbols


def public_tool_symbols(symbols: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    seen = set()
    for symbol in [*core_utility_symbols(), *(symbols or [])]:
        if not is_addable_tool_symbol(symbol):
            continue
        provider = provider_metadata(symbol)
        category = tool_category(symbol, provider)
        key = (
            provider["id"],
            category,
            str(symbol.get("utility_kind") or symbol.get("name") or ""),
            str(symbol.get("file_path") or ""),
            str(symbol.get("module") or ""),
            str(symbol.get("function_path") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(symbol)
        normalized.setdefault("provider_id", provider["id"])
        normalized.setdefault("provider_display_name", provider["display"])
        normalized.setdefault("category_display_name", category)
        public.append(normalized)
    return public


def is_studio_search_symbol(symbol: dict[str, Any]) -> bool:
    """Keep the type-ahead picker focused on callable studio/project tools."""
    if not is_addable_tool_symbol(symbol):
        return False
    provider = provider_metadata(symbol)
    provider_id = provider["id"]
    if provider_id == "core" or symbol.get("utility_kind"):
        return True
    if provider_id in {
        "builtins",
        "builtin",
        "python",
        "stdlib",
        "os",
        "pathlib",
        "typing",
        "inspect",
        "functools",
        "json",
        "re",
    }:
        return False
    file_path = str(symbol.get("file_path") or symbol.get("source_path") or "").replace("\\", "/").lower()
    if file_path:
        if "/site-packages/" in file_path or "/dist-packages/" in file_path:
            return False
        if "/python" in file_path and "/lib/" in file_path and "/depot/tools/" not in file_path:
            return False
        if file_path.endswith("/lib/os.py") or file_path.endswith("/lib/pathlib.py"):
            return False
        return True
    return any(
        bool(symbol.get(key))
        for key in ("public_tool", "pipeline_tool", "workflow_node", "tool_action", "capability_action")
    )


def tool_action_group(symbol: dict[str, Any], app_name: str = "") -> str:
    provider = provider_metadata(symbol)
    if app_name and _slug(app_name) != provider["id"]:
        provider = dict(provider)
        provider["display"] = app_name
    return tool_category(symbol, provider)


def _legacy_tool_action_group(symbol: dict[str, Any], app_name: str = "") -> str:
    app_key = (app_name or infer_package(symbol) or "").lower().replace("_", " ")
    text = symbol_search_text(symbol)
    if app_key in DCC_CONTEXT_APPS or app_key in ENGINE_CONTEXT_APPS:
        for group, keywords in ACTION_GROUP_KEYWORDS:
            if any(keyword in text for keyword in keywords):
                return group
        return "General"
    if app_key in VCS_CONTEXT_APPS:
        if any(word in text for word in ("pull", "push", "branch", "commit", "merge", "diff", "stash", "tag", "clone")):
            return "Repository"
        if any(word in text for word in ("issue", "ticket", "pull request", "pr", "review", "comment")):
            return "Issues / Reviews"
        if any(word in text for word in ("workflow", "action", "ci", "release", "build")):
            return "CI / Releases"
        return "General"
    if app_key in MESSAGING_CONTEXT_APPS:
        if any(word in text for word in ("message", "send", "reply", "email", "mail", "thread")):
            return "Messages"
        if any(word in text for word in ("channel", "conversation", "room", "space")):
            return "Channels"
        if any(word in text for word in ("user", "member", "mention", "contact")):
            return "People"
        return "General"
    if app_key in OPS_CONTEXT_APPS:
        if any(word in text for word in ("task", "issue", "ticket", "story", "epic", "card")):
            return "Tasks / Tickets"
        if any(word in text for word in ("deploy", "build", "job", "pipeline", "release")):
            return "Builds / Deploys"
        if any(word in text for word in ("incident", "alert", "status", "notify")):
            return "Incidents / Alerts"
        return "General"
    if app_key in {"pathlib", "os.path"}:
        if any(word in text for word in ("path", "file", "dir", "folder", "glob", "exists", "join")):
            return "Paths / Files"
        return "General"
    if app_key == "project":
        for group, keywords in ACTION_GROUP_KEYWORDS:
            if any(keyword in text for keyword in keywords):
                return group
        return "Project Tools"
    if app_key == "utility":
        return "Utility"
    for group, keywords in ACTION_GROUP_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return group
    return "General"


def tool_group_sort_key(group: str) -> tuple[bool, str]:
    return (group in {"General", "Project Tools", "Utility"}, group.lower())


def tool_menu_label(symbol: dict[str, Any]) -> str:
    return str(symbol.get("function_display_name") or symbol.get("display_name") or symbol.get("name") or "unnamed")


def compact_tool_label(symbol: dict[str, Any]) -> str:
    provider = provider_metadata(symbol)
    category = tool_category(symbol, provider)
    label = f"{provider['display']} / {category} / {tool_menu_label(symbol)}"
    source_path = str(symbol.get("file_path") or symbol.get("source_path") or "")
    source_name = source_path.replace("\\", "/").rsplit("/", 1)[-1]
    if source_name and str(symbol.get("source_kind") or "").lower() != "utility":
        label = f"{label} [{source_name}]"
    return label


def tool_symbol_identity(symbol: dict[str, Any]) -> tuple[str, ...]:
    provider = provider_metadata(symbol)
    source_path = str(
        symbol.get("file_path")
        or symbol.get("source_path")
        or symbol.get("module")
        or symbol.get("source_package")
        or ""
    ).replace("\\", "/").casefold()
    qualified_name = str(
        symbol.get("qualified_name")
        or symbol.get("qualname")
        or symbol.get("function_path")
        or ".".join(
            part
            for part in (
                str(symbol.get("class_name") or ""),
                str(symbol.get("name") or ""),
            )
            if part
        )
    ).casefold()
    return (
        str(provider.get("id") or "").casefold(),
        source_path,
        qualified_name,
        str(symbol.get("kind") or "").casefold(),
    )


def compact_tool_context(symbol: dict[str, Any]) -> str:
    provider = provider_metadata(symbol)
    app = provider["display"]
    group = tool_category(symbol, provider)
    module = str(symbol.get("module") or symbol.get("source_package") or "")
    pieces = [app]
    if group and group not in {"General", "Project Tools", "Utility"}:
        pieces.append(group)
    if module and module.lower() not in str(app).lower():
        pieces.append(module.rsplit(".", 1)[-1])
    return " / ".join(piece for piece in pieces if piece)


def tool_tooltip(symbol: dict[str, Any]) -> str:
    provider = provider_metadata(symbol)
    category = tool_category(symbol, provider)
    availability = str(symbol.get("availability") or symbol.get("availability_state") or "Available")
    parts = [
        f"{provider['display']} / {category}",
        str(symbol.get("description") or symbol.get("docstring") or ""),
        str(symbol.get("signature") or symbol.get("name") or ""),
        f"Availability: {availability}",
        str(symbol.get("file_path") or symbol.get("module") or symbol.get("source_module") or ""),
    ]
    return "\n".join(part for part in parts if part)


def add_owned_menu(parent: QMenu, title: str) -> QMenu:
    menu = QMenu(title, parent)
    parent.addMenu(menu)
    owned = getattr(parent, "_ai_studio_owned_menus", None)
    if owned is None:
        owned = []
        setattr(parent, "_ai_studio_owned_menus", owned)
    owned.append(menu)
    return menu


class ContextPatternDialog(QDialog):
    def __init__(self, parent: QWidget, symbol: dict[str, Any], plans: list[dict[str, Any]]):
        super().__init__(parent)
        self.setWindowTitle(f"Add Context: {tool_menu_label(symbol)}")
        self.resize(640, 460)
        self.selected_plan: dict[str, Any] | None = plans[0] if plans else None

        layout = QVBoxLayout(self)
        heading = QLabel(f"Choose context for {tool_menu_label(symbol)}")
        heading.setStyleSheet("font-weight:bold; color:#b9dcff;")
        layout.addWidget(heading)

        self.list_widget = QListWidget(self)
        self.list_widget.setMinimumHeight(130)
        layout.addWidget(self.list_widget)

        self.details = QTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(220)
        self.details.setStyleSheet("QTextEdit { background:#0b0f14; color:#d7dde5; border:1px solid #1e9bff; }")
        layout.addWidget(self.details, 1)

        for plan in plans[:3]:
            item = QListWidgetItem(plan.get("title") or "Usage pattern")
            item.setData(Qt.UserRole, plan)
            self.list_widget.addItem(item)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.button(QDialogButtonBox.Ok).setText("Add Selected Context")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.list_widget.currentItemChanged.connect(self._update_details)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def _update_details(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        plan = current.data(Qt.UserRole) if current is not None else None
        self.selected_plan = plan if isinstance(plan, dict) else None
        if not self.selected_plan:
            self.details.clear()
            return
        lines = [
            self.selected_plan.get("summary") or "",
            "",
            "How it is used:",
            self.selected_plan.get("usage") or "No detailed usage text registered yet.",
        ]
        if self.selected_plan.get("reuse"):
            lines.extend(["", "Reuse existing nodes:"])
            lines.extend(f"- {item.get('name')}" for item in self.selected_plan.get("reuse", []))
        if self.selected_plan.get("available"):
            lines.extend(["", "Add related functions:"])
            lines.extend(f"- {item.get('name')}" for item in self.selected_plan.get("available", []))
        if self.selected_plan.get("missing"):
            lines.extend(["", "Still unresolved:"])
            lines.extend(f"- {name}" for name in self.selected_plan.get("missing", []))
        if self.selected_plan.get("evidence"):
            lines.extend(["", "Evidence:"])
            lines.extend(f"- {item}" for item in self.selected_plan.get("evidence", []))
        self.details.setPlainText("\n".join(line for line in lines if line is not None))


def grouped_tool_symbols(symbols: list[dict[str, Any]], *, per_group_limit: int = 14) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    seen = set()
    for symbol in public_tool_symbols(symbols):
        if not is_addable_tool_symbol(symbol):
            continue
        key = (
            symbol.get("name") or "",
            symbol.get("file_path") or "",
            symbol.get("module") or "",
            symbol.get("function_path") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        provider = provider_metadata(symbol)
        app = provider["display"]
        group = tool_category(symbol, provider)
        grouped[app][group].append(symbol)

    sorted_grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    provider_order = {
        provider_metadata(symbol)["display"]: provider_metadata(symbol)["order"]
        for symbol in public_tool_symbols(symbols)
    }
    for app in sorted(grouped, key=lambda value: (provider_order.get(value, 300), value.lower())):
        sorted_grouped[app] = {}
        app_symbols = grouped[app]
        sample_provider = None
        for symbol in public_tool_symbols(symbols):
            provider = provider_metadata(symbol)
            if provider["display"] == app:
                sample_provider = provider
                break
        category_order = {name: idx for idx, name in enumerate((sample_provider or {}).get("categories") or [])}
        for group in sorted(app_symbols, key=lambda name: (category_order.get(name, 999), tool_group_sort_key(name))):
            sorted_grouped[app][group] = sorted(
                app_symbols[group],
                key=lambda sym: (
                    str(tool_menu_label(sym)).lower(),
                    str(sym.get("file_path") or "").lower(),
                ),
            )[:per_group_limit]
    return sorted_grouped

HOST_COLORS = {
    "maya": "#3fa7ff",
    "unreal": "#1e9bff",
    "blender": "#5bd000",
    "substance_painter": "#1e9bff",
    "substance": "#1e9bff",
    "unity": "#d7dde5",
    "motionbuilder": "#5bd000",
    "houdini": "#5bd000",
    "utility": "#1e9bff",
    "github": "#1e9bff",
    "project": "#5bd000",
    "general": "#5bd000",
}


@dataclass
class PipelineGraphNode:
    step_id: str
    step_data: dict[str, Any]
    symbol: dict[str, Any]
    params: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    x: float = 80
    y: float = 80


@dataclass
class PipelineGraphLink:
    from_step: str
    from_output: str
    to_step: str
    to_input: str
    link_type: str = "data"  # "data" or "flow"


class PipelinePortItem(QGraphicsEllipseItem):
    def __init__(self, node_item, name: str, direction: str, annotation: str = ""):
        super().__init__(-6, -6, 12, 12, node_item)
        self.node_item = node_item
        self.name = name
        self.direction = direction
        self.annotation = annotation or ""
        if direction == "flow_out":
            color = "#1e9bff"
        elif direction == "flow_in":
            color = "#5bd000"
        elif direction == "output":
            color = "#5bd000"
        else:
            color = "#d7dde5"
        self.setBrush(QColor(color))
        self.setPen(QPen(QColor("#02070a"), 1))
        readable = "Flow" if name == FLOW_PORT else name
        self.setToolTip(f"{direction}: {readable}: {self.annotation or 'Any'}")

    def scene_center(self):
        return self.mapToScene(self.rect().center())


class PipelineNodeItem(QGraphicsRectItem):
    WIDTH = 350
    HEADER = 54
    ROW = 23

    def __init__(self, view, graph_node: PipelineGraphNode):
        rows = max(len(graph_node.params), len(graph_node.outputs), 1)
        height = max(150, self.HEADER + 44 + rows * self.ROW + 20)
        super().__init__(0, 0, self.WIDTH, height)
        self.view = view
        self.graph_node = graph_node
        self.input_ports: dict[str, PipelinePortItem] = {}
        self.output_ports: dict[str, PipelinePortItem] = {}
        self.literal_labels: dict[str, QGraphicsSimpleTextItem] = {}
        self._validation_messages: list[str] = []

        package = infer_package(graph_node.symbol)
        host_key = package.lower().replace(" ", "_")
        color = HOST_COLORS.get(host_key, HOST_COLORS.get(graph_node.symbol.get("host", "general"), HOST_COLORS["general"]))
        self._base_color = color
        self.setPos(graph_node.x, graph_node.y)
        self.setBrush(QColor("#010507"))
        self.setPen(QPen(QColor(color), 2))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        title = QGraphicsSimpleTextItem(str(graph_node.symbol.get("name") or "step")[:36], self)
        title.setBrush(QColor("#ffffff"))
        title.setPos(10, 8)

        kind = graph_node.symbol.get("kind", "function")
        subtitle = QGraphicsSimpleTextItem(str(kind), self)
        subtitle.setBrush(QColor(color))
        subtitle.setPos(10, 30)

        # Package/source badge on top-right.
        badge_text = str(package or "Project")[:18]
        badge = QGraphicsSimpleTextItem(badge_text, self)
        badge.setBrush(QColor("#000711"))
        bw = badge.boundingRect().width() + 12
        badge_bg = QGraphicsRectItem(self.WIDTH - bw - 8, 8, bw, 20, self)
        badge_bg.setBrush(QColor(color))
        badge_bg.setPen(QPen(QColor(color), 1))
        badge.setParentItem(self)
        badge.setPos(self.WIDTH - bw - 2, 10)

        # Flow ports are order-of-operations only. They never pass data.
        flow_y = self.HEADER + 8
        flow_in = PipelinePortItem(self, FLOW_PORT, "flow_in", "execution order")
        flow_in.setPos(0, flow_y)
        self.input_ports[FLOW_PORT] = flow_in
        flow_lbl = QGraphicsSimpleTextItem("flow", self)
        flow_lbl.setBrush(QColor("#5bd000"))
        flow_lbl.setPos(13, flow_y - 8)

        flow_out = PipelinePortItem(self, FLOW_PORT, "flow_out", "execution order")
        flow_out.setPos(self.WIDTH, flow_y)
        self.output_ports[FLOW_PORT] = flow_out
        flow_out_lbl = QGraphicsSimpleTextItem("flow", self)
        flow_out_lbl.setBrush(QColor("#1e9bff"))
        flow_out_lbl.setPos(self.WIDTH - flow_out_lbl.boundingRect().width() - 13, flow_y - 8)

        y0 = self.HEADER + 38
        for idx, param in enumerate(graph_node.params):
            name = param.get("name") or f"input_{idx + 1}"
            annotation = display_param_type(param)
            y = y0 + idx * self.ROW
            port = PipelinePortItem(self, name, "input", annotation)
            port.setPos(0, y)
            self.input_ports[name] = port
            label = QGraphicsSimpleTextItem(self._literal_label_text(name, annotation), self)
            label.setBrush(QColor("#d7dde5"))
            label.setPos(13, y - 8)
            self.literal_labels[name] = label

        if graph_node.outputs:
            for idx, output in enumerate(graph_node.outputs):
                name = output.get("name") or ("result" if idx == 0 else f"output_{idx + 1}")
                annotation = display_output_type(output, graph_node.symbol)
                y = y0 + idx * self.ROW
                port = PipelinePortItem(self, name, "output", annotation)
                port.setPos(self.WIDTH, y)
                self.output_ports[name] = port
                label = QGraphicsSimpleTextItem(f"{name}: {annotation}"[:38], self)
                label.setBrush(QColor("#5bd000"))
                label.setPos(self.WIDTH - label.boundingRect().width() - 13, y - 8)
        else:
            label = QGraphicsSimpleTextItem("no data return", self)
            label.setBrush(QColor("#777777"))
            label.setPos(self.WIDTH - label.boundingRect().width() - 13, y0 - 8)

    def set_validation_messages(self, messages: list[str] | None) -> None:
        self._validation_messages = [str(msg) for msg in (messages or []) if str(msg).strip()]
        if self._validation_messages:
            summary = "\n".join(f"- {msg}" for msg in self._validation_messages[:8])
            if len(self._validation_messages) > 8:
                summary += f"\n- {len(self._validation_messages) - 8} more issue(s)"
            self.setToolTip(f"Pipeline data-flow warning:\n{summary}")
        else:
            self.setToolTip("Pipeline data flow satisfied.")
        self._apply_visual_state()

    def _apply_visual_state(self) -> None:
        if self.isSelected():
            self.setPen(QPen(QColor("#1e9bff"), 4))
            self.setBrush(QColor("#03131e"))
        elif self._validation_messages:
            self.setPen(QPen(QColor("#ff9f1c"), 4))
            self.setBrush(QColor("#120804"))
        else:
            self.setPen(QPen(QColor("#5bd000"), 3))
            self.setBrush(QColor("#010507"))

    def _literal_label_text(self, name: str, annotation: str = "") -> str:
        connection = self.view.input_connection(self.graph_node.step_id, name)
        if connection is not None:
            source_node = self.view.nodes.get(connection.from_step)
            source_name = str(
                ((source_node.symbol if source_node else {}) or {}).get("name")
                or connection.from_step
            )
            return f"{name}: <- {source_name}.{connection.from_output}"[:40]
        literal = self.view.literal_value(self.graph_node.step_data, name)
        display_value = (
            literal
            if literal is not None and literal != ""
            else (annotation or "Any")
        )
        return f"{name}: {display_value}"[:40]

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._apply_visual_state()
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.graph_node.x = float(self.pos().x())
            self.graph_node.y = float(self.pos().y())
            self.view.refresh_links()
            self.view.orderChanged.emit(self.view.execution_order())
        return super().itemChange(change, value)

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.State_Selected
        super().paint(painter, option, widget)

    def mouseDoubleClickEvent(self, event):
        item = self.view.scene_obj.itemAt(event.scenePos(), self.view.transform())
        if isinstance(item, PipelinePortItem) and item.direction == "input":
            self.view.edit_literal_for_port(item)
            return
        # Double-clicking anywhere on the node should make its data visible
        # in the right-side attribute editor. This keeps node selection and
        # attribute inspection discoverable even when the user clicks the body
        # or text instead of a specific port.
        self.setSelected(True)
        self.view.nodeSelected.emit(self.graph_node.step_data)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        step_data = self.graph_node.step_data
        symbol = step_data.get("symbol") or {}
        menu = QMenu()
        
        is_placeholder = "placeholders" in str(symbol.get("file_path", "")).lower()
        search_web = None
        replace_local = None
        
        if is_placeholder:
            search_web = menu.addAction("Search GitHub / Web for Tool...")
            replace_local = menu.addAction("Replace with Local Tool...")
            menu.addSeparator()

        add_dynamic = None
        remove_dynamic = None
        if symbol.get("utility_kind") in {"make_dict", "make_list"}:
            add_dynamic = menu.addAction("Add Input Port")
            remove_dynamic = menu.addAction("Remove Last Input Port")
            menu.addSeparator()
        focus = menu.addAction("Focus Node")
        action = menu.exec(event.screenPos())
        if action == add_dynamic:
            if add_dynamic_port(step_data):
                self.view.rebuild_node(step_data)
                self.view.statusMessage.emit("Added utility input port.")
        elif action == remove_dynamic:
            if remove_last_dynamic_port(step_data):
                self.view.rebuild_node(step_data)
                self.view.statusMessage.emit("Removed utility input port.")
        elif action == search_web:
            try:
                from tech_connector.ui.unreal_editor_dialogs import WebImportDialog
                import json
                dlg = WebImportDialog(self.view, initial_query=symbol.get("name", ""), workflow_goal=symbol.get("docstring", ""))
                if dlg.exec():
                    if hasattr(dlg, "saved_workflow") and dlg.saved_workflow:
                        new_sym = {
                            "name": dlg.saved_workflow.function_name,
                            "kind": "function",
                            "file_path": str(dlg.saved_workflow.module_path),
                            "signature": f"def {dlg.saved_workflow.function_name}()",
                            "params": [],
                            "outputs": []
                        }
                        try:
                            from tech_connector.services.tool_discovery_service import list_internal_functions
                            syms = list_internal_functions([str(dlg.saved_workflow.module_path.parent)])
                            for s in syms:
                                if s.get("name") == dlg.saved_workflow.function_name:
                                    new_sym = s
                                    break
                        except Exception as ex:
                            print(f"Failed to parse ingested symbols: {ex}")
                        self.view._push_undo_state("replace placeholder with ingested tool")
                        self.view.replace_node_symbol(self.graph_node.step_id, new_sym)
            except Exception as e:
                print(f"Error launching WebImportDialog: {e}")
        elif action == replace_local:
            try:
                from tech_connector.ui.node_search_dialog import ToolSearchDialog
                dlg = ToolSearchDialog(self.view)
                if dlg.exec():
                    new_sym = dlg.get_selected_symbol()
                    if new_sym:
                        self.view._push_undo_state("replace node tool")
                        self.view.replace_node_symbol(self.graph_node.step_id, new_sym)
            except Exception as e:
                print(f"Error replacing node: {e}")
        elif action == focus:
            self.view.fitInView(self.sceneBoundingRect().adjusted(-80, -80, 80, 80), Qt.KeepAspectRatio)

    def refresh_literal_label(self, name: str):
        label = self.literal_labels.get(name)
        if not label:
            return
        param = next((p for p in self.graph_node.params if (p.get("name") or "") == name), {})
        label.setText(self._literal_label_text(name, display_param_type(param)))


class PipelineLinkItem(QGraphicsPathItem):
    def __init__(self, view, link: PipelineGraphLink, source, target):
        super().__init__()
        self.view = view
        self.link = link
        self.source = source
        self.target = target
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(-10)
        self.update_pen()
        self.update_path()

    def update_pen(self):
        if self.link.link_type == "flow":
            color = "#1e9bff"
        else:
            color = "#5bd000" if self.isSelected() else "#3f8cff"
        self.setPen(QPen(QColor(color), 4 if self.isSelected() else 2, Qt.SolidLine if self.link.link_type == "data" else Qt.DashLine))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.update_pen()
        return super().itemChange(change, value)

    def update_path(self):
        a = self.source.scene_center()
        b = self.target.scene_center()
        dx = max(80, abs(b.x() - a.x()) * 0.45)
        path = QPainterPath(a)
        path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
        self.setPath(path)

    def contextMenuEvent(self, event):
        menu = QMenu()
        delete = menu.addAction("Delete Connection")
        if menu.exec(event.screenPos()) == delete:
            self.view.remove_link(self.link)


class TempLinkItem(QGraphicsPathItem):
    def __init__(self, source):
        super().__init__()
        self.source = source
        self.end = source.scene_center()
        color = "#1e9bff" if source.direction == "flow_out" else "#5bd000"
        self.setPen(QPen(QColor(color), 2, Qt.DashLine))
        self.setZValue(-9)
        self.update_path()

    def set_end(self, end):
        self.end = end
        self.update_path()

    def update_path(self):
        a = self.source.scene_center()
        b = self.end
        dx = max(80, abs(b.x() - a.x()) * 0.45)
        path = QPainterPath(a)
        path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
        self.setPath(path)


class PipelineNodeView(QGraphicsView):
    graphChanged = Signal()
    orderChanged = Signal(list)
    linkCreated = Signal(dict)
    linkDeleted = Signal(dict)
    literalChanged = Signal(dict)
    nodeDeleted = Signal(list)
    nodeSelected = Signal(dict)
    toolNodeRequested = Signal(dict)
    graphInteractionRequested = Signal()
    statusMessage = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)
        self.setRenderHints(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setSceneRect(0, 0, 3600, 2200)
        self.setStyleSheet("QGraphicsView { background:#000204; border:1px solid #12324a; }")
        self.nodes: dict[str, PipelineGraphNode] = {}
        self.node_items: dict[str, PipelineNodeItem] = {}
        self.links: list[PipelineGraphLink] = []
        self.link_items: list[PipelineLinkItem] = []
        self._undo_stack: list[dict[str, Any]] = []
        self._undo_limit = 80
        self._restoring_undo = False
        self.pending_port: PipelinePortItem | None = None
        self.temp_link: TempLinkItem | None = None
        self._ctrl_middle_panning = False
        self._ctrl_middle_pan_start = None
        self._ctrl_middle_h_start = 0
        self._ctrl_middle_v_start = 0
        self.tool_symbols: list[dict[str, Any]] = []
        self._tool_symbol_search_cache: list[dict[str, Any]] = []
        self._tool_symbol_search_cache_dirty = False
        self._tool_symbol_search_cache_build_scheduled = False
        self.empty = QGraphicsSimpleTextItem(
            "Add nodes. Use yellow flow ports for execution order. Use green data outputs only when a node returns data."
        )
        self.empty.setBrush(QColor("#8fb9c9"))
        self.empty.setPos(80, 80)
        self.scene_obj.addItem(self.empty)

    def set_tool_symbols(self, symbols: list[dict[str, Any]]) -> None:
        self.tool_symbols = [dict(symbol) for symbol in (symbols or []) if isinstance(symbol, dict)]
        self._tool_symbol_search_cache = []
        self._tool_symbol_search_cache_dirty = True
        if len(self.tool_symbols) <= 500:
            self._prepare_tool_symbol_search_cache()
        else:
            self._schedule_tool_symbol_search_cache_build()

    def _schedule_tool_symbol_search_cache_build(self) -> None:
        if not self._tool_symbol_search_cache_dirty or self._tool_symbol_search_cache_build_scheduled:
            return
        self._tool_symbol_search_cache_build_scheduled = True
        QTimer.singleShot(0, self._prepare_tool_symbol_search_cache)

    def _prepare_tool_symbol_search_cache(self) -> None:
        if not self._tool_symbol_search_cache_dirty:
            self._tool_symbol_search_cache_build_scheduled = False
            return
        self._tool_symbol_search_cache = self._build_tool_symbol_search_cache()
        self._tool_symbol_search_cache_dirty = False
        self._tool_symbol_search_cache_build_scheduled = False

    def _build_tool_symbol_search_cache(self) -> list[dict[str, Any]]:
        cache: list[dict[str, Any]] = []
        for symbol in public_tool_symbols(self.tool_symbols):
            if not is_studio_search_symbol(symbol):
                continue
            provider = provider_metadata(symbol)
            category = tool_category(symbol, provider)
            label = tool_menu_label(symbol)
            cache.append(
                {
                    "symbol": symbol,
                    "provider": provider,
                    "category": category,
                    "label": label,
                    "haystack": symbol_search_text(symbol),
                    "name": str(symbol.get("name") or "").lower(),
                    "label_lower": label.lower(),
                    "path_lower": str(symbol.get("file_path") or "").lower(),
                    "priority": int(provider.get("order") or 300),
                }
            )
        cache.sort(key=lambda row: (row["priority"], row["label_lower"], row["path_lower"]))
        return cache

    def _request_graph_interaction_ready(self) -> None:
        try:
            self.graphInteractionRequested.emit()
        except Exception:
            pass

    def focusInEvent(self, event):
        self._request_graph_interaction_ready()
        return super().focusInEvent(event)

    def mousePressEvent(self, event):
        self._request_graph_interaction_ready()
        return super().mousePressEvent(event)

    def _filtered_tool_symbols_for_context_menu(
        self,
        query: str,
        *,
        require_query: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        terms = tool_search_tokens(query)
        if require_query and not terms:
            return []
        cache = self._tool_symbol_search_cache
        if self._tool_symbol_search_cache_dirty:
            if len(self.tool_symbols) <= 500:
                self._prepare_tool_symbol_search_cache()
                cache = self._tool_symbol_search_cache
            else:
                self._schedule_tool_symbol_search_cache_build()
                return []
        rows = []
        for row in cache:
            if terms and not tool_query_matches(row, terms):
                continue
            rows.append(row)
        if terms:
            rows = sorted(rows, key=lambda row: pipeline_tool_query_rank(row, terms))
        unique_rows = []
        seen_symbols = set()
        for row in rows:
            identity = tool_symbol_identity(row["symbol"])
            if identity in seen_symbols:
                continue
            seen_symbols.add(identity)
            unique_rows.append(row)
        if limit is not None:
            unique_rows = unique_rows[: max(0, limit)]
        return [row["symbol"] for row in unique_rows]

    def _populate_add_tool_menu(
            self,
            add_tool_menu: QMenu,
            symbols: list[dict[str, Any]],
            tool_actions: dict[Any, dict[str, Any]],
    ) -> None:
        for action in list(add_tool_menu.actions()):
            data = action.data()
            if data == "tool-filter":
                continue
            add_tool_menu.removeAction(action)
        tool_actions.clear()

        grouped_tools = grouped_tool_symbols(symbols)
        if not grouped_tools:
            empty_action = add_tool_menu.addAction("No matching tools")
            empty_action.setEnabled(False)
            return

        all_menu = add_owned_menu(add_tool_menu, "All")
        all_symbols = sorted(
            public_tool_symbols(symbols),
            key=lambda sym: (
                provider_metadata(sym)["order"],
                provider_metadata(sym)["display"].lower(),
                tool_category(sym, provider_metadata(sym)).lower(),
                tool_menu_label(sym).lower(),
            ),
        )
        for symbol in all_symbols[:80]:
            self._add_tool_symbol_action(all_menu, tool_actions, symbol, include_context_in_title=True)
        if len(all_symbols) > 80:
            more_action = all_menu.addAction(
                f"Type in the filter to search all tools ({len(all_symbols) - 80} more)"
            )
            more_action.setEnabled(False)
        if len(all_symbols) > 80:
            more_action = all_menu.addAction(f"Type in the filter to search {len(all_symbols) - 80} more...")
            more_action.setEnabled(False)

        for app_name, action_groups in grouped_tools.items():
            app_menu = add_owned_menu(add_tool_menu, app_name)
            all_menu = add_owned_menu(app_menu, "All")
            app_symbols = []
            seen = set()
            for symbol in public_tool_symbols(symbols):
                provider = provider_metadata(symbol)
                if provider["display"] != app_name:
                    continue
                key = (
                    symbol.get("name") or "",
                    symbol.get("file_path") or "",
                    symbol.get("module") or "",
                    symbol.get("function_path") or "",
                )
                if key in seen:
                    continue
                seen.add(key)
                app_symbols.append(symbol)
            app_symbols = sorted(app_symbols, key=lambda sym: (str(sym.get("name") or "").lower(), str(sym.get("file_path") or "").lower()))
            for symbol in app_symbols[:50]:
                self._add_tool_symbol_action(all_menu, tool_actions, symbol)
            if len(app_symbols) > 50:
                more_action = all_menu.addAction(f"Type in the filter to search {len(app_symbols) - 50} more...")
                more_action.setEnabled(False)
            for group_name, group_symbols in action_groups.items():
                group_menu = add_owned_menu(app_menu, group_name)
                for symbol in group_symbols:
                    self._add_tool_symbol_action(group_menu, tool_actions, symbol)

    def _add_tool_symbol_action(
        self,
        parent_menu: QMenu,
        tool_actions: dict[Any, Any],
        symbol: dict[str, Any],
        *,
        include_context_in_title: bool = False,
    ) -> None:
        provider = provider_metadata(symbol)
        category = tool_category(symbol, provider)
        title = tool_menu_label(symbol)
        if include_context_in_title:
            title = f"{provider['display']} / {category} / {title}"
        symbol_menu = add_owned_menu(parent_menu, title)
        symbol_menu.setToolTip(tool_tooltip(symbol))

        add_action = symbol_menu.addAction("Add Node")
        add_action.setToolTip(tool_tooltip(symbol))
        tool_actions[add_action] = ("add", symbol)

        configured_action = symbol_menu.addAction("Add Configured Node")
        configured_action.setToolTip("Add this function and apply grounded defaults or registered call-site values.")
        tool_actions[configured_action] = ("add_configured", symbol)

        existing = self.context_connection_suggestions(symbol)
        if existing:
            label = f"Add and Connect Existing Context ({len(existing)})"
            action = symbol_menu.addAction(label)
            action.setToolTip(self._context_suggestion_tooltip(existing))
            tool_actions[action] = ("add_connect_existing", symbol, existing)

        context_plan = self.context_addition_plan(symbol)
        if context_plan.get("available") or context_plan.get("reuse"):
            action = symbol_menu.addAction("Add and Connect Context")
            action.setToolTip(self._context_addition_tooltip(context_plan))
            tool_actions[action] = ("add_connect_context", symbol, context_plan)
        elif self._has_registered_context_pattern(symbol):
            action = symbol_menu.addAction("Add and Connect Context")
            action.setEnabled(False)
            action.setToolTip("Known context metadata exists, but the related producer functions are not registered in this tool menu.")

        details = symbol_menu.addAction("View Function Details")
        details.setEnabled(False)
        details.setToolTip(tool_tooltip(symbol))

    def _has_registered_context_pattern(self, symbol: dict[str, Any]) -> bool:
        return any(symbol.get(key) for key in ("required_context", "common_predecessors", "usage_patterns", "context_patterns"))

    def _context_suggestion_tooltip(self, suggestions: list[dict[str, str]]) -> str:
        lines = ["Suggested connections:"]
        for suggestion in suggestions:
            lines.append(
                f"{suggestion.get('from_label')} -> {suggestion.get('to_input')} "
                f"({suggestion.get('confidence', 'medium')})"
            )
        return "\n".join(lines)

    def _context_addition_tooltip(self, plan: dict[str, Any]) -> str:
        lines = ["Add/reuse related context functions, then connect compatible outputs."]
        if plan.get("reuse"):
            lines.append("Reuse:")
            lines.extend(f"- {item.get('name')}" for item in plan.get("reuse", []))
        if plan.get("available"):
            lines.append("Add:")
            lines.extend(f"- {item.get('name')}" for item in plan.get("available", []))
        if plan.get("missing"):
            lines.append("Unavailable:")
            lines.extend(f"- {name}" for name in plan.get("missing", []))
        return "\n".join(lines)

    def _context_pattern_predecessor_names(self, symbol: dict[str, Any]) -> list[str]:
        names: list[str] = []
        for value in symbol.get("common_predecessors") or []:
            if isinstance(value, str):
                names.append(value)
            elif isinstance(value, dict) and value.get("function"):
                names.append(str(value.get("function")))
        for pattern in symbol.get("usage_patterns") or symbol.get("context_patterns") or []:
            if not isinstance(pattern, dict):
                continue
            for value in pattern.get("common_predecessors") or pattern.get("predecessors") or []:
                if isinstance(value, str):
                    names.append(value)
                elif isinstance(value, dict) and value.get("function"):
                    names.append(str(value.get("function")))
            inputs = pattern.get("inputs") or {}
            if isinstance(inputs, dict):
                for binding in inputs.values():
                    if isinstance(binding, dict) and binding.get("producer"):
                        names.append(str(binding.get("producer")))
        result = []
        seen = set()
        for name in names:
            key = name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(name.strip())
        return result

    def _pattern_predecessor_names(self, pattern: dict[str, Any]) -> list[str]:
        names: list[str] = []
        for value in pattern.get("common_predecessors") or pattern.get("predecessors") or []:
            if isinstance(value, str):
                names.append(value)
            elif isinstance(value, dict) and value.get("function"):
                names.append(str(value.get("function")))
        inputs = pattern.get("inputs") or {}
        if isinstance(inputs, dict):
            for binding in inputs.values():
                if isinstance(binding, dict) and binding.get("producer"):
                    names.append(str(binding.get("producer")))
        result = []
        seen = set()
        for name in names:
            key = name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(name.strip())
        return result

    def usage_patterns_for_symbol(self, symbol: dict[str, Any]) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        explicit = symbol.get("usage_patterns") or symbol.get("context_patterns") or []
        for index, pattern in enumerate(explicit):
            if not isinstance(pattern, dict):
                continue
            title = str(pattern.get("title") or pattern.get("name") or f"Registered usage pattern {index + 1}")
            predecessors = self._pattern_predecessor_names(pattern)
            summary = str(pattern.get("summary") or pattern.get("description") or "")
            usage = str(pattern.get("usage") or pattern.get("example") or "")
            evidence = pattern.get("evidence") or pattern.get("sources") or ["Registered tool metadata"]
            if isinstance(evidence, str):
                evidence = [evidence]
            normalized = {
                "title": title,
                "summary": summary or f"Uses {', '.join(predecessors) or 'registered context'} before {symbol.get('name')}.",
                "usage": usage,
                "predecessors": predecessors,
                "evidence": [str(item) for item in evidence],
                "rank": int(pattern.get("rank") or pattern.get("confidence_rank") or index + 1),
            }
            for key in (
                "literal_values",
                "default_literal_values",
                "hardcoded_args",
                "configured_args",
                "kwargs",
                "bound_arguments",
                "inputs",
            ):
                if key in pattern:
                    normalized[key] = copy.deepcopy(pattern.get(key))
            patterns.append(normalized)
        if not patterns and self._context_pattern_predecessor_names(symbol):
            predecessors = self._context_pattern_predecessor_names(symbol)
            patterns.append({
                "title": "Registered setup pattern",
                "summary": f"Common setup calls: {', '.join(predecessors)}.",
                "usage": "Adds the registered predecessor functions, reuses any already present in the graph, then connects compatible outputs to the new node.",
                "predecessors": predecessors,
                "evidence": ["Registered common_predecessors metadata"],
                "rank": 1,
            })
        if not patterns and self.context_connection_suggestions(symbol):
            patterns.append({
                "title": "Existing graph context",
                "summary": "The current graph already has outputs that appear compatible with this function.",
                "usage": "Adds the selected node and connects compatible outputs already present in the graph.",
                "predecessors": [],
                "evidence": ["Current graph provider/type/name compatibility"],
                "rank": 1,
            })
        return sorted(patterns, key=lambda item: int(item.get("rank") or 999))[:3]

    def _node_matches_function(self, node: PipelineGraphNode, function_name: str, provider_id: str) -> bool:
        symbol = node.symbol or {}
        return (
            str(symbol.get("name") or "").lower() == function_name.lower()
            and provider_metadata(symbol)["id"] == provider_id
        )

    def _find_existing_context_node(self, function_name: str, provider_id: str) -> PipelineGraphNode | None:
        for step_id in self.execution_order():
            node = self.nodes.get(step_id)
            if node and self._node_matches_function(node, function_name, provider_id):
                return node
        return None

    def _find_registered_context_symbol(self, function_name: str, provider_id: str) -> dict[str, Any] | None:
        for candidate in public_tool_symbols(self.tool_symbols):
            if str(candidate.get("name") or "").lower() != function_name.lower():
                continue
            if provider_metadata(candidate)["id"] != provider_id:
                continue
            return candidate
        return None

    def context_addition_plan(self, symbol: dict[str, Any], pattern: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_id = provider_metadata(symbol)["id"]
        names = list((pattern or {}).get("predecessors") or []) or self._context_pattern_predecessor_names(symbol)
        plan = {
            "title": (pattern or {}).get("title") or "Registered setup pattern",
            "summary": (pattern or {}).get("summary") or "",
            "usage": (pattern or {}).get("usage") or "",
            "evidence": list((pattern or {}).get("evidence") or []),
            "pattern": copy.deepcopy(pattern or {}),
            "reuse": [],
            "available": [],
            "missing": [],
        }
        for name in names:
            existing = self._find_existing_context_node(name, provider_id)
            if existing is not None:
                plan["reuse"].append({"name": name, "step_id": existing.step_id})
                continue
            candidate = self._find_registered_context_symbol(name, provider_id)
            if candidate is not None:
                plan["available"].append(candidate)
            else:
                plan["missing"].append(name)
        return plan

    def context_addition_plans(self, symbol: dict[str, Any]) -> list[dict[str, Any]]:
        patterns = self.usage_patterns_for_symbol(symbol)
        plans = [self.context_addition_plan(symbol, pattern) for pattern in patterns]
        return [plan for plan in plans if plan.get("available") or plan.get("reuse") or plan.get("missing")]

    def choose_context_addition_plan(self, symbol: dict[str, Any], fallback_plan: dict[str, Any] | None = None) -> dict[str, Any] | None:
        plans = self.context_addition_plans(symbol)
        if not plans and fallback_plan:
            plans = [fallback_plan]
        actionable = [plan for plan in plans if plan.get("available") or plan.get("reuse")]
        if not actionable:
            return fallback_plan
        if len(actionable) == 1:
            return actionable[0]
        dialog = ContextPatternDialog(self, symbol, actionable[:3])
        if dialog.exec() == QDialog.Accepted:
            return dialog.selected_plan
        return None

    def _function_literal_values_from_mapping(
        self,
        mapping: Any,
        symbol: dict[str, Any],
        *,
        provenance: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if not isinstance(mapping, dict):
            return {}, {}
        name = str(symbol.get("name") or "")
        function_path = str(symbol.get("function_path") or symbol.get("module") or "")
        candidates = [name, function_path, function_path.rsplit(".", 1)[-1] if function_path else ""]
        values: dict[str, Any] = {}
        sources: dict[str, str] = {}
        if any(key in mapping for key in candidates if key):
            for key in candidates:
                nested = mapping.get(key) if key else None
                if isinstance(nested, dict):
                    for arg_name, value in nested.items():
                        values[str(arg_name)] = value
                        sources[str(arg_name)] = provenance
        else:
            for arg_name, value in mapping.items():
                if not isinstance(value, (dict, list, tuple)) or arg_name in {p.get("name") for p in symbol.get("params") or [] if isinstance(p, dict)}:
                    values[str(arg_name)] = value
                    sources[str(arg_name)] = provenance
        return values, sources

    def literal_values_for_tool_symbol(
        self,
        symbol: dict[str, Any],
        pattern: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        values: dict[str, Any] = {}
        provenance: dict[str, str] = {}
        param_names = {
            str(param.get("name") or "")
            for param in (symbol.get("params") or [])
            if isinstance(param, dict) and str(param.get("name") or "")
        }

        for param in symbol.get("params") or []:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "")
            if not name or "default" not in param:
                continue
            default = param.get("default")
            if default in {"", None}:
                continue
            values[name] = default
            provenance[name] = "function_default"

        for key, source in (
            ("literal_values", "registered_literal"),
            ("default_literal_values", "registered_default"),
            ("hardcoded_args", "registered_hardcoded"),
            ("configured_args", "registered_configured"),
            ("kwargs", "registered_kwargs"),
        ):
            found, sources = self._function_literal_values_from_mapping(symbol.get(key), symbol, provenance=source)
            values.update(found)
            provenance.update(sources)

        if pattern:
            for key, source in (
                ("literal_values", "usage_literal"),
                ("bound_arguments", "usage_bound_argument"),
                ("inputs", "usage_input"),
            ):
                value = pattern.get(key)
                if key == "bound_arguments" and isinstance(value, list):
                    for item in value:
                        if not isinstance(item, dict):
                            continue
                        item_function = str(item.get("node") or item.get("function") or item.get("callable") or "")
                        symbol_names = {str(symbol.get("name") or ""), str(symbol.get("function_path") or ""), str(symbol.get("module") or "")}
                        if item_function and item_function not in symbol_names and not any(name and item_function.endswith(f".{name}") for name in symbol_names):
                            continue
                        arg_name = str(item.get("argument") or item.get("parameter") or item.get("name") or "")
                        if not arg_name:
                            continue
                        if "value" in item:
                            values[arg_name] = item.get("value")
                            provenance[arg_name] = str(item.get("provenance") or source)
                    continue
                if key == "inputs" and isinstance(value, dict):
                    extracted: dict[str, Any] = {}
                    for arg_name, binding in value.items():
                        if isinstance(binding, dict):
                            if "value" in binding:
                                extracted[str(arg_name)] = binding.get("value")
                            elif "literal" in binding:
                                extracted[str(arg_name)] = binding.get("literal")
                            elif "default" in binding:
                                extracted[str(arg_name)] = binding.get("default")
                        elif not isinstance(binding, str) or not binding.startswith("$"):
                            extracted[str(arg_name)] = binding
                    found, sources = self._function_literal_values_from_mapping(extracted, symbol, provenance=source)
                else:
                    found, sources = self._function_literal_values_from_mapping(value, symbol, provenance=source)
                values.update(found)
                provenance.update(sources)

        if param_names:
            values = {key: value for key, value in values.items() if key in param_names}
            provenance = {key: value for key, value in provenance.items() if key in values}
        return values, provenance

    def apply_configured_literals_to_step(
        self,
        step_data: dict[str, Any],
        symbol: dict[str, Any],
        pattern: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values, provenance = self.literal_values_for_tool_symbol(symbol, pattern)
        if not values:
            return {}
        step_data.setdefault("literal_values", {}).update(values)
        step_data.setdefault("literal_value_provenance", {}).update(provenance)
        step_data["configured_from_usage"] = bool(pattern)
        return values

    def add_configured_tool_node(
        self,
        symbol: dict[str, Any],
        pattern: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        before_ids = set(self.nodes)
        step_data = {"symbol": dict(symbol)}
        self.add_pipeline_step(step_data, symbol.get("params") or [], symbol.get("outputs") or [])
        if not step_data.get("graph_step_id"):
            new_ids = [step_id for step_id in self.nodes if step_id not in before_ids]
            if new_ids:
                step_data = self.nodes[new_ids[-1]].step_data
        applied = self.apply_configured_literals_to_step(step_data, symbol, pattern)
        if applied:
            step_id = str(step_data.get("graph_step_id") or "")
            item = self.node_items.get(step_id)
            if item:
                for name in applied:
                    item.refresh_literal_label(name)
            self.literalChanged.emit({"step_data": step_data, "step_id": step_id, "values": applied})
            self.graphChanged.emit()
            self.statusMessage.emit(f"Added configured node: {symbol.get('name')} ({len(applied)} value(s)).")
        else:
            self.statusMessage.emit(f"Added node: {symbol.get('name')} (no grounded literals found).")
        return step_data

    def _compatible_context_output(self, target_symbol: dict[str, Any], param: dict[str, Any], source_node: PipelineGraphNode, output: dict[str, Any]) -> bool:
        source_symbol = source_node.symbol or {}
        target_provider = provider_metadata(target_symbol)["id"]
        source_provider = provider_metadata(source_symbol)["id"]
        if source_provider not in {target_provider, "core", "project"} and target_provider not in {"core", "project"}:
            return False
        input_name = str(param.get("name") or "").lower()
        output_name = str(output.get("name") or "").lower()
        if not input_name or not output_name:
            return False
        if input_name == output_name:
            return True
        input_sem = str(param.get("semantic_type") or "").lower()
        output_sem = str(output.get("semantic_type") or "").lower()
        if input_sem and output_sem and input_sem == output_sem:
            return True
        input_type = str(param.get("python_type") or param.get("annotation") or "").lower()
        output_type = str(output.get("python_type") or output.get("annotation") or "").lower()
        aliases = {
            "body": {"body_map", "body"},
            "face": {"face_map", "face"},
            "root_joint": {"root", "joint", "root_joint", "skeleton_root", "origin_joint"},
        }
        if input_name in aliases and output_name in aliases[input_name] and input_type and output_type and input_type == output_type:
            return True
        return bool(input_type and output_type and input_type not in {"any", "unknown"} and input_type == output_type and input_name in output_name)

    def context_connection_suggestions(self, symbol: dict[str, Any]) -> list[dict[str, str]]:
        params = symbol.get("params") or []
        if not params or not self.nodes:
            return []
        suggestions: list[dict[str, str]] = []
        matched_inputs = set()
        for param in params:
            if not isinstance(param, dict):
                continue
            input_name = str(param.get("name") or "")
            if not input_name or input_name == FLOW_PORT or input_name.startswith("*"):
                continue
            if input_name in matched_inputs:
                continue
            for step_id in self.execution_order():
                source_node = self.nodes.get(step_id)
                if not source_node:
                    continue
                for output in source_node.outputs or []:
                    output_name = str(output.get("name") or "")
                    if not output_name:
                        continue
                    if self._compatible_context_output(symbol, param, source_node, output):
                        suggestions.append({
                            "from_step": step_id,
                            "from_output": output_name,
                            "from_label": f"{source_node.symbol.get('name', step_id)}.{output_name}",
                            "to_input": input_name,
                            "confidence": "high" if output_name.lower() == input_name.lower() else "medium",
                            "evidence": "Compatible provider/type/name metadata in current graph.",
                        })
                        matched_inputs.add(input_name)
                        break
                if input_name in matched_inputs:
                    break
        return suggestions

    def add_tool_node_with_existing_context(self, symbol: dict[str, Any], suggestions: list[dict[str, str]]) -> None:
        before_ids = set(self.nodes)
        step_data = self.add_pipeline_step({"symbol": dict(symbol)}, symbol.get("params") or [], symbol.get("outputs") or [])
        target_step = step_data.get("graph_step_id") if isinstance(step_data, dict) else ""
        if not target_step:
            new_ids = [step_id for step_id in self.nodes if step_id not in before_ids]
            target_step = new_ids[-1] if new_ids else ""
        if not target_step:
            return
        existing_inputs = {(link.to_step, link.to_input) for link in self.links if link.link_type == "data"}
        created = 0
        for suggestion in suggestions:
            to_input = suggestion.get("to_input") or ""
            if (target_step, to_input) in existing_inputs:
                continue
            link = PipelineGraphLink(
                suggestion.get("from_step") or "",
                suggestion.get("from_output") or "",
                target_step,
                to_input,
                "data",
            )
            if not link.from_step or not link.from_output or not link.to_input:
                continue
            self.links.append(link)
            created += 1
            self.linkCreated.emit(self._link_payload(link))
        if created:
            self.refresh_links(rebuild=True)
            self.graphChanged.emit()
            self.orderChanged.emit(self.execution_order())
            self.statusMessage.emit(f"Added node and connected {created} existing context input(s).")
        if isinstance(step_data, dict):
            step_data["context_addition_details"] = {
                "mode": "Add and Connect Existing Context",
                "pattern": "Existing graph context",
                "summary": "Reused compatible nodes already present in the current pipeline.",
                "usage": "The selected function was added, then compatible existing outputs were connected to matching inputs.",
                "reused": sorted({suggestion.get("from_label", "").split(".", 1)[0] for suggestion in suggestions if suggestion.get("from_label")}),
                "added": [],
                "connections": [
                    f"{suggestion.get('from_label')} -> {suggestion.get('to_input')}"
                    for suggestion in suggestions
                    if suggestion.get("from_label") and suggestion.get("to_input")
                ],
                "missing": [],
                "evidence": sorted({suggestion.get("evidence", "") for suggestion in suggestions if suggestion.get("evidence")}),
            }
            self.nodeSelected.emit(step_data)

    def add_tool_node_with_context(self, symbol: dict[str, Any], plan: dict[str, Any]) -> None:
        added_names = []
        pattern = dict(plan.get("pattern") or {})
        for producer in plan.get("available") or []:
            if self._find_existing_context_node(str(producer.get("name") or ""), provider_metadata(producer)["id"]):
                continue
            producer_step = {"symbol": dict(producer)}
            self.add_pipeline_step(producer_step, producer.get("params") or [], producer.get("outputs") or [])
            self.apply_configured_literals_to_step(producer_step, producer, pattern)
            added_names.append(str(producer.get("name") or "context"))
        suggestions = self.context_connection_suggestions(symbol)
        self.add_tool_node_with_existing_context(symbol, suggestions)
        target_step = None
        for step_id in reversed(self.execution_order()):
            node = self.nodes.get(step_id)
            if node and (node.symbol or {}).get("name") == symbol.get("name"):
                target_step = node.step_data
                break
        if isinstance(target_step, dict):
            self.apply_configured_literals_to_step(target_step, symbol, pattern)
            target_step["context_addition_details"] = {
                "mode": "Add and Connect Context",
                "pattern": plan.get("title") or "Selected usage pattern",
                "summary": plan.get("summary") or "Added missing context functions and connected compatible outputs.",
                "usage": plan.get("usage") or "Related setup nodes were added or reused before the selected function node.",
                "reused": [item.get("name") for item in plan.get("reuse", []) if item.get("name")],
                "added": added_names,
                "connections": [
                    f"{suggestion.get('from_label')} -> {suggestion.get('to_input')}"
                    for suggestion in suggestions
                    if suggestion.get("from_label") and suggestion.get("to_input")
                ],
                "missing": list(plan.get("missing") or []),
                "evidence": list(plan.get("evidence") or []),
            }
            self.nodeSelected.emit(target_step)
        if added_names:
            self.statusMessage.emit(
                f"Added context node(s): {', '.join(added_names)}; connected compatible context."
            )

    def add_tool_node_with_grounded_context(self, symbol: dict[str, Any]) -> None:
        plan = self.choose_context_addition_plan(symbol)
        if plan:
            self.add_tool_node_with_context(symbol, plan)
            return
        suggestions = self.context_connection_suggestions(symbol)
        if suggestions:
            self.add_tool_node_with_existing_context(symbol, suggestions)
            return
        self.add_configured_tool_node(symbol)

    def _populate_context_tool_list(
        self,
        list_widget: QListWidget,
        symbols: list[dict[str, Any]],
        *,
        max_rows: int = 160,
        show_empty_message: bool = True,
        show_more_message: bool = True,
    ) -> None:
        list_widget.clear()
        display_symbols = list(symbols)
        for symbol in display_symbols[:max_rows]:
            label = compact_tool_label(symbol)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, symbol)
            context = compact_tool_context(symbol)
            tooltip_parts = [
                context,
                str(symbol.get("signature") or symbol.get("name") or ""),
                str(symbol.get("file_path") or symbol.get("module") or ""),
            ]
            item.setToolTip("\n".join(part for part in tooltip_parts if part))
            list_widget.addItem(item)
        if show_more_message and len(display_symbols) > max_rows:
            item = QListWidgetItem(f"Type more to narrow results... ({len(display_symbols) - max_rows} hidden)")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            list_widget.addItem(item)
        if show_empty_message and not display_symbols:
            item = QListWidgetItem("No matching tools")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            list_widget.addItem(item)

    def _build_context_tool_picker(self, root_menu: QMenu, add_tool_menu: QMenu) -> tuple[QLineEdit, QListWidget]:
        picker = QWidget(add_tool_menu)
        picker.setMinimumWidth(360)
        picker.setMaximumWidth(460)
        picker.setStyleSheet("QWidget { background:#000204; color:#d7dde5; }")
        layout = QVBoxLayout(picker)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        filter_edit = _ToolPickerFilterEdit(picker)
        filter_edit.setPlaceholderText("Filter tools...")
        filter_edit.setClearButtonEnabled(True)
        filter_edit.setStyleSheet("QLineEdit { background:#000711; border:1px solid #1e9bff; color:#d7dde5; padding:4px; }")
        layout.addWidget(filter_edit)

        result_list = _ToolPickerListWidget(picker)
        result_list.setMinimumHeight(240)
        result_list.setMaximumHeight(360)
        result_list.setMinimumWidth(340)
        result_list.setMaximumWidth(440)
        result_list.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        result_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        result_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        result_list.setUniformItemSizes(True)
        result_list.setAlternatingRowColors(False)
        result_list.setStyleSheet(
            "QListWidget { background:#000204; border:1px solid #1e9bff; color:#d7dde5; }"
            "QListWidget::item { padding:4px 6px; }"
            "QListWidget::item:selected { background:#062b40; color:#eaffff; }"
        )
        layout.addWidget(result_list)

        picker_action = QWidgetAction(add_tool_menu)
        picker_action.setDefaultWidget(picker)
        picker_action.setData("tool-filter")
        add_tool_menu.addAction(picker_action)

        refresh_timer = QTimer(picker)
        refresh_timer.setSingleShot(True)
        refresh_timer.setInterval(70)

        def refresh(value: str) -> None:
            text = (value or "").strip()
            if not text:
                result_list.clear()
                return
            matches = self._filtered_tool_symbols_for_context_menu(text, require_query=True, limit=5)
            if self._tool_symbol_search_cache_dirty and not matches:
                result_list.clear()
                item = QListWidgetItem("Preparing function search...")
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                result_list.addItem(item)
                self._schedule_tool_symbol_search_cache_build()
                QTimer.singleShot(120, lambda: refresh(filter_edit.text()))
                return
            self._populate_context_tool_list(
                result_list,
                matches,
                max_rows=5,
                show_more_message=False,
            )

        def schedule_refresh(_value: str) -> None:
            refresh_timer.start()

        def add_symbol(symbol: dict[str, Any], mode: str = "plain") -> None:
            if mode == "configured":
                self.add_configured_tool_node(symbol)
            elif mode == "workflow_context":
                self.add_tool_node_with_grounded_context(symbol)
            else:
                self.toolNodeRequested.emit(symbol)
            add_tool_menu.close()
            root_menu.close()

        def add_selected(item: QListWidgetItem) -> None:
            symbol = item.data(Qt.UserRole)
            if isinstance(symbol, dict):
                add_symbol(symbol, "plain")

        refresh_timer.timeout.connect(lambda: refresh(filter_edit.text()))
        def on_filter_changed(value: str) -> None:
            if len(self.tool_symbols) <= 500 and not self._tool_symbol_search_cache_dirty:
                refresh(value)
            else:
                schedule_refresh(value)

        filter_edit.textChanged.connect(on_filter_changed)
        result_list.symbolActivatedWithMode.connect(add_symbol)
        result_list.itemActivated.connect(add_selected)
        result_list.itemClicked.connect(add_selected)

        def close_picker() -> None:
            add_tool_menu.close()
            root_menu.close()

        inactivity_timer = QTimer(picker)
        inactivity_timer.setSingleShot(True)
        inactivity_timer.setInterval(3000)

        def reset_inactivity_timer(*_args) -> None:
            inactivity_timer.start()

        def picker_has_focus() -> bool:
            focus = QApplication.focusWidget()
            if focus is None:
                return False
            return any(
                focus is root or root.isAncestorOf(focus)
                for root in (root_menu, add_tool_menu, picker)
            )

        def close_if_inactive() -> None:
            if picker_has_focus():
                reset_inactivity_timer()
                return
            close_picker()

        def focus_results(direction: int) -> None:
            enabled_rows = [
                row
                for row in range(result_list.count())
                if result_list.item(row).flags() & Qt.ItemIsEnabled
            ]
            if not enabled_rows:
                return
            current = result_list.currentRow()
            if current not in enabled_rows:
                current = enabled_rows[0] if direction > 0 else enabled_rows[-1]
            result_list.setCurrentRow(current)
            result_list.setFocus(Qt.ShortcutFocusReason)
            reset_inactivity_timer()

        inactivity_timer.timeout.connect(close_if_inactive)
        filter_edit.navigationRequested.connect(focus_results)
        filter_edit.textEdited.connect(reset_inactivity_timer)
        result_list.currentRowChanged.connect(reset_inactivity_timer)
        result_list.itemEntered.connect(reset_inactivity_timer)
        result_list.setMouseTracking(True)
        root_menu.hovered.connect(reset_inactivity_timer)
        add_tool_menu.hovered.connect(reset_inactivity_timer)
        picker._inactivity_timer = inactivity_timer
        reset_inactivity_timer()
        return filter_edit, result_list

    def _snapshot_state(self) -> dict[str, Any]:
        """Capture graph state for local Ctrl+Z undo."""
        nodes = []
        for step_id, node in self.nodes.items():
            step_data = copy.deepcopy(node.step_data)
            step_data["graph_step_id"] = step_id
            nodes.append({
                "step_id": step_id,
                "step_data": step_data,
                "params": copy.deepcopy(node.params),
                "outputs": copy.deepcopy(node.outputs),
                "x": float(node.x),
                "y": float(node.y),
            })
        links = [copy.deepcopy(self._link_payload(link)) for link in self.links]
        return {"nodes": nodes, "links": links}

    def _push_undo_state(self, reason: str = "") -> None:
        if self._restoring_undo:
            return
        try:
            state = self._snapshot_state()
            if self._undo_stack and self._undo_stack[-1] == state:
                return
            self._undo_stack.append(state)
            if len(self._undo_stack) > self._undo_limit:
                self._undo_stack.pop(0)
        except Exception as exc:
            self.statusMessage.emit(f"Undo snapshot failed: {exc}")

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def undo_last_change(self) -> None:
        if not self._undo_stack:
            self.statusMessage.emit("Nothing to undo in the node graph.")
            return
        state = self._undo_stack.pop()
        self._restore_state(state)
        self.statusMessage.emit("Undid last node graph change.")

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._restoring_undo = True
        try:
            for item in list(self.link_items):
                self.scene_obj.removeItem(item)
            self.link_items.clear()
            for item in list(self.node_items.values()):
                self.scene_obj.removeItem(item)
            self.node_items.clear()
            self.nodes.clear()
            if self.empty:
                try:
                    self.scene_obj.removeItem(self.empty)
                except Exception:
                    pass
                self.empty = None

            for entry in state.get("nodes", []):
                step_id = entry.get("step_id") or f"step_{len(self.nodes)+1}"
                step_data = entry.get("step_data") or {}
                step_data["graph_step_id"] = step_id
                symbol = step_data.get("symbol") or {}
                params = entry.get("params") or step_data.get("params") or symbol.get("params") or []
                outputs = entry.get("outputs") or step_data.get("outputs") or normalized_outputs(symbol, symbol.get("outputs") or [])
                node = PipelineGraphNode(
                    step_id,
                    step_data,
                    symbol,
                    params,
                    outputs,
                    float(entry.get("x", 80)),
                    float(entry.get("y", 80)),
                )
                self.nodes[step_id] = node
                step_data["params"] = params
                step_data["outputs"] = outputs
                item = PipelineNodeItem(self, node)
                self.scene_obj.addItem(item)
                self.node_items[step_id] = item

            self.links.clear()
            for payload in state.get("links", []):
                self.links.append(PipelineGraphLink(
                    payload.get("from_step", ""),
                    payload.get("from_output", ""),
                    payload.get("to_step", ""),
                    payload.get("to_input", ""),
                    payload.get("type", "data"),
                ))
            if not self.nodes:
                self.empty = QGraphicsSimpleTextItem(
                    "Add nodes. Use yellow flow ports for execution order. Use green data outputs only when a node returns data."
                )
                self.empty.setBrush(QColor("#8fb9c9"))
                self.empty.setPos(80, 80)
                self.scene_obj.addItem(self.empty)
            self.refresh_links(rebuild=True)
            self.graphChanged.emit()
            self.orderChanged.emit(self.execution_order())
        finally:
            self._restoring_undo = False

    def input_connection(self, step_id: str, param_name: str):
        return next(
            (
                link
                for link in self.links
                if link.link_type == "data"
                and link.to_step == step_id
                and link.to_input == param_name
            ),
            None,
        )

    def connected_input_sources(self, step_data: dict[str, Any]) -> dict[str, str]:
        step_id = str((step_data or {}).get("graph_step_id") or "")
        if not step_id:
            return {}
        connected = {}
        for link in self.links:
            if link.link_type != "data" or link.to_step != step_id or not link.to_input:
                continue
            source_node = self.nodes.get(link.from_step)
            source_name = str(
                ((source_node.symbol if source_node else {}) or {}).get("name")
                or link.from_step
            )
            connected[str(link.to_input)] = f"{source_name}.{link.from_output}"
        return connected

    def disconnect_input(self, step_id: str, param_name: str) -> bool:
        matching = [
            link
            for link in self.links
            if link.link_type == "data"
            and link.to_step == step_id
            and link.to_input == param_name
        ]
        if not matching:
            return False
        self._push_undo_state(f"disconnect input {param_name}")
        self.links = [link for link in self.links if link not in matching]
        self.refresh_links(rebuild=True)
        node_item = self.node_items.get(step_id)
        if node_item is not None:
            node_item.refresh_literal_label(param_name)
        self.linkDeleted.emit({
            "count": len(matching),
            "to_step": step_id,
            "to_input": param_name,
        })
        self.graphChanged.emit()
        self.orderChanged.emit(self.execution_order())
        self.statusMessage.emit(
            f"Unlocked input '{param_name}' by disconnecting {len(matching)} data link(s)."
        )
        return True

    def literal_value(self, step_data, param_name):
        return ((step_data.get("literal_values") or {}).get(param_name) or "")

    def set_literal_value(self, step_data, param_name, value):
        step_data.setdefault("literal_values", {})[param_name] = value

    def _param_has_value_or_link(self, step_id: str, step_data: dict[str, Any], param_name: str) -> bool:
        literal = self.literal_value(step_data, param_name)
        if literal not in {"", None}:
            return True
        return any(
            link.link_type == "data" and link.to_step == step_id and link.to_input == param_name
            for link in self.links
        )

    def _param_has_default(self, param: dict[str, Any]) -> bool:
        if not isinstance(param, dict):
            return False
        if "default" not in param:
            return False
        default = param.get("default")
        return default not in {"", None}

    def validate_data_flow(self) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        for step_id in self.execution_order():
            node = self.nodes.get(step_id)
            if not node:
                continue
            node_name = str((node.symbol or {}).get("name") or step_id)
            for param in node.params or []:
                if not isinstance(param, dict):
                    continue
                param_name = str(param.get("name") or "")
                if not param_name or param_name.startswith("*") or param_name == FLOW_PORT:
                    continue
                if self._param_has_default(param):
                    continue
                if self._param_has_value_or_link(step_id, node.step_data, param_name):
                    continue
                issues.append({
                    "step_id": step_id,
                    "node": node_name,
                    "input": param_name,
                    "message": f"{node_name}.{param_name} needs a value or data connection.",
                })
        for link in self.links:
            source_node = self.nodes.get(link.from_step)
            target_node = self.nodes.get(link.to_step)
            if not source_node or not target_node:
                issues.append({
                    "step_id": link.to_step or link.from_step,
                    "node": "Unknown node",
                    "input": link.to_input or link.from_output,
                    "message": "A connection references a missing node.",
                })
                continue
            if link.link_type == "data":
                if link.from_output not in {out.get("name") for out in source_node.outputs or []}:
                    issues.append({
                        "step_id": link.from_step,
                        "node": str((source_node.symbol or {}).get("name") or link.from_step),
                        "input": link.from_output,
                        "message": f"Connection uses missing output: {link.from_output}.",
                    })
                if link.to_input not in {param.get("name") for param in target_node.params or []}:
                    issues.append({
                        "step_id": link.to_step,
                        "node": str((target_node.symbol or {}).get("name") or link.to_step),
                        "input": link.to_input,
                        "message": f"Connection targets missing input: {link.to_input}.",
                    })
        return issues

    def refresh_data_flow_warnings(self) -> list[dict[str, str]]:
        issues = self.validate_data_flow()
        by_step: dict[str, list[str]] = {}
        for issue in issues:
            by_step.setdefault(issue.get("step_id") or "", []).append(issue.get("message") or "Data-flow issue")
        for step_id, item in self.node_items.items():
            item.set_validation_messages(by_step.get(step_id, []))
        try:
            from tech_connector.services.pipeline_graph_intelligence_service import (
                analyze_pipeline_graph,
                graph_snapshot_from_view,
            )

            self._last_graph_intelligence = analyze_pipeline_graph(
                graph_snapshot_from_view(self),
                issues,
            )
        except Exception:
            self._last_graph_intelligence = {}
        return issues

    def graph_intelligence_report(self) -> dict[str, Any]:
        try:
            from tech_connector.services.pipeline_graph_intelligence_service import (
                analyze_pipeline_graph,
                graph_snapshot_from_view,
            )

            self._last_graph_intelligence = analyze_pipeline_graph(
                graph_snapshot_from_view(self),
                self.validate_data_flow(),
            )
        except Exception:
            self._last_graph_intelligence = {}
        return dict(getattr(self, "_last_graph_intelligence", {}) or {})

    def add_utility_node(self, utility_kind: str):
        step_data, params, outputs = create_utility_step_data(utility_kind)
        self.add_pipeline_step(step_data, params, outputs)
        return step_data

    def clear_pipeline(self, *, push_undo: bool = True, reason: str = "clear pipeline") -> None:
        if push_undo:
            self._push_undo_state(reason)
        self._restore_state({"nodes": [], "links": []})

    def materialize_action_graph(self, graph: dict[str, Any], *, append: bool = False) -> dict[str, Any]:
        """Create a validated node-view pipeline from a canonical action graph."""

        from reasoning_runtime.action.action_graph_service import normalize_action_graph, validate_action_graph

        data = normalize_action_graph(graph)
        graph_validation = validate_action_graph(data)
        errors = list(graph_validation.get("errors") or [])
        actions = list(data.get("actions") or [])
        node_specs: dict[str, dict[str, Any]] = {}
        data_specs: list[dict[str, Any]] = []
        flow_specs: list[dict[str, Any]] = []
        literal_specs: list[dict[str, Any]] = []

        for action in actions:
            action_type = str(action.get("type") or action.get("action_type") or "")
            args = dict(action.get("args") or action.get("input") or {})
            if action_type == "create_node":
                symbol = dict(args.get("symbol") or {})
                node_name = str(args.get("node") or symbol.get("name") or "").strip()
                source_path = Path(str(symbol.get("file_path") or ""))
                if not node_name:
                    errors.append("A create_node action is missing its indexed symbol name.")
                    continue
                if node_name in node_specs:
                    errors.append(f"Duplicate pipeline node name: {node_name}.")
                    continue
                if not source_path.is_file():
                    errors.append(f"{node_name} is not backed by an existing indexed source file: {source_path}.")
                    continue
                node_specs[node_name] = {
                    "action": action,
                    "symbol": symbol,
                    "params": list(args.get("params") or symbol.get("params") or []),
                    "outputs": list(args.get("outputs") or symbol.get("outputs") or []),
                }
            elif action_type == "connect_data":
                data_specs.append(args)
            elif action_type == "connect_flow":
                flow_specs.append(args)
            elif action_type == "bind_literal":
                literal_specs.append(args)
            elif action_type in {"execute_dcc", "validate_dcc_call"}:
                action_id = str(action.get("id") or action.get("action_id") or f"action_{len(node_specs) + 1}")
                operation = str(args.get("operation") or "")
                callable_path = str(args.get("callable") or args.get("callable_name") or "")
                params = dict(args.get("params") or {})
                produces = [str(item) for item in (args.get("produces") or []) if str(item)]
                node_name = action_id
                if node_name in node_specs:
                    errors.append(f"Duplicate pipeline node name: {node_name}.")
                    continue
                function_name = callable_path.rsplit(".", 1)[-1] if callable_path else operation
                param_specs = [
                    {"name": name, "python_type": "Any", "annotation": "Any"}
                    for name in params
                    if name
                ]
                output_specs = [
                    {"name": name, "python_type": "Any", "annotation": "Any"}
                    for name in (produces or ["result"])
                ]
                symbol = {
                    "name": function_name or node_name,
                    "function_path": callable_path,
                    "provider_id": str(args.get("host") or ""),
                    "kind": "function" if callable_path else "dcc_operation",
                    "operation": operation,
                    "pipeline_operation": "dcc_operation",
                    "params": param_specs,
                    "outputs": output_specs,
                    "public_tool": True,
                }
                node_specs[node_name] = {
                    "action": action,
                    "symbol": symbol,
                    "params": param_specs,
                    "outputs": output_specs,
                }
                for param_name, value in params.items():
                    if isinstance(value, str) and value.startswith("$"):
                        source_output = value[1:]
                        source_node = ""
                        for existing_node, existing_spec in node_specs.items():
                            if any(str(output.get("name") or "") == source_output for output in existing_spec["outputs"]):
                                source_node = existing_node
                                break
                        if source_node:
                            data_specs.append({
                                "from": {"node": source_node, "port": source_output},
                                "to": {"node": node_name, "port": str(param_name)},
                            })
                        else:
                            errors.append(f"{node_name}.{param_name} references unresolved output {value}.")
                    else:
                        literal_specs.append({"node": node_name, "parameter": str(param_name), "value": value})
                for dependency in action.get("depends_on") or []:
                    if dependency:
                        flow_specs.append({"from": str(dependency), "to": node_name})

        bound_inputs = {
            (str(item.get("node") or ""), str(item.get("parameter") or ""))
            for item in literal_specs
        }
        for item in data_specs:
            source = dict(item.get("from") or {})
            target = dict(item.get("to") or {})
            source_name = str(source.get("node") or "")
            source_port = str(source.get("port") or "")
            target_name = str(target.get("node") or "")
            target_port = str(target.get("port") or "")
            if source_name not in node_specs or target_name not in node_specs:
                errors.append(f"Data link references an unresolved node: {source_name} -> {target_name}.")
                continue
            outputs = {str(value.get("name") or "") for value in node_specs[source_name]["outputs"]}
            inputs = {str(value.get("name") or "") for value in node_specs[target_name]["params"]}
            if source_port not in outputs:
                errors.append(f"{source_name}.{source_port} is not an indexed output.")
            if target_port not in inputs:
                errors.append(f"{target_name}.{target_port} is not an indexed input.")
            bound_inputs.add((target_name, target_port))

        for item in flow_specs:
            source_name = str(item.get("from") or "")
            target_name = str(item.get("to") or "")
            if source_name not in node_specs or target_name not in node_specs:
                errors.append(f"Flow link references an unresolved node: {source_name} -> {target_name}.")

        for node_name, spec in node_specs.items():
            for param in spec["params"]:
                param_name = str(param.get("name") or "")
                if not param_name or param_name.startswith("*") or "default" in param:
                    continue
                if (node_name, param_name) not in bound_inputs:
                    errors.append(f"{node_name}.{param_name} has no literal or verified data connection.")

        if not node_specs:
            errors.append("The action graph contains no verified executable function nodes.")
        if errors:
            return {
                "ok": False,
                "status": "materialization_blocked",
                "errors": list(dict.fromkeys(errors)),
                "node_count": 0,
                "link_count": 0,
            }

        before = self._snapshot_state()
        self._push_undo_state("materialize prompt pipeline")
        step_ids: dict[str, str] = {}
        self._restoring_undo = True
        try:
            if not append:
                self._restore_state({"nodes": [], "links": []})
                self._restoring_undo = True
            for node_name, spec in node_specs.items():
                step_data = {
                    "symbol": spec["symbol"],
                    "source_action_id": spec["action"].get("id") or spec["action"].get("action_id"),
                    "prompt_materialized": True,
                }
                self.add_pipeline_step(step_data, spec["params"], spec["outputs"])
                step_ids[node_name] = str(step_data.get("graph_step_id") or "")
            for item in literal_specs:
                node_name = str(item.get("node") or "")
                step_id = step_ids[node_name]
                self.set_literal_value(self.nodes[step_id].step_data, str(item.get("parameter") or ""), item.get("value"))
            for item in data_specs:
                source = dict(item.get("from") or {})
                target = dict(item.get("to") or {})
                self.links.append(PipelineGraphLink(
                    step_ids[str(source.get("node") or "")],
                    str(source.get("port") or ""),
                    step_ids[str(target.get("node") or "")],
                    str(target.get("port") or ""),
                    "data",
                ))
            for item in flow_specs:
                self.links.append(PipelineGraphLink(
                    step_ids[str(item.get("from") or "")],
                    FLOW_PORT,
                    step_ids[str(item.get("to") or "")],
                    FLOW_PORT,
                    "flow",
                ))
        except Exception as exc:
            self._restoring_undo = False
            self._restore_state(before)
            return {
                "ok": False,
                "status": "materialization_failed",
                "errors": [str(exc)],
                "node_count": 0,
                "link_count": 0,
            }
        finally:
            self._restoring_undo = False

        self.refresh_links(rebuild=True)
        issues = self.refresh_data_flow_warnings()
        if issues:
            self._restore_state(before)
            return {
                "ok": False,
                "status": "materialization_failed_validation",
                "errors": [str(item.get("message") or item) for item in issues],
                "node_count": 0,
                "link_count": 0,
            }
        self.graphChanged.emit()
        self.orderChanged.emit(self.execution_order())
        self.statusMessage.emit(f"Materialized {len(step_ids)} verified pipeline nodes from the prompt.")
        return {
            "ok": True,
            "status": "materialized",
            "errors": [],
            "node_count": len(step_ids),
            "link_count": len(data_specs) + len(flow_specs),
            "execution_order": self.execution_order(),
            "append": bool(append),
        }

    def materialize_prompt_route_decision(self, decision: dict[str, Any], *, append: bool = False) -> dict[str, Any]:
        """Materialize resolved prompt operations into nodes and data links."""

        actions: list[dict[str, Any]] = []
        previous = ""
        for index, operation in enumerate(list((decision or {}).get("operations") or []), start=1):
            operation_key = str(operation.get("operation") or "")
            action_id = str(operation.get("id") or f"operation_{index}")
            action_type = "validate_dcc_call" if operation_key in {"scene.find_joint", "scene.object_exists"} else "execute_dcc"
            action = {
                "id": action_id,
                "type": action_type,
                "title": str(operation.get("label") or operation_key or action_id),
                "args": {
                    "host": str(operation.get("host") or (decision or {}).get("host") or ""),
                    "operation": operation_key,
                    "callable": str(operation.get("callable") or ""),
                    "params": dict(operation.get("args") or {}),
                    "produces": list(operation.get("produces") or []),
                    "requires": list(operation.get("requires") or []),
                },
                "depends_on": [previous] if previous else [],
                "requires_approval": bool(operation.get("requires_confirmation")),
                "source": "prompt_route_operations",
            }
            actions.append(action)
            previous = action_id
        return self.materialize_action_graph({
            "goal": str((decision or {}).get("primary_goal") or (decision or {}).get("intent_category") or "prompt pipeline"),
            "intent": str((decision or {}).get("intent_category") or "prompt_pipeline"),
            "planner": "prompt_route_decision",
            "actions": actions,
        }, append=append)

    def add_pipeline_step(self, step_data, params, outputs):
        self._push_undo_state("add node")
        if self.empty:
            self.scene_obj.removeItem(self.empty)
            self.empty = None
        step_id = f"step_{len(self.nodes) + 1}_{id(step_data)}"
        symbol = step_data.get("symbol") or {}
        params = params or symbol.get("params") or []
        data_outputs = normalized_outputs(symbol, outputs)
        graph_node = PipelineGraphNode(
            step_id,
            step_data,
            symbol,
            params,
            data_outputs,
            80 + len(self.nodes) * 380,
            90,
        )
        self.nodes[step_id] = graph_node
        item = PipelineNodeItem(self, graph_node)
        self.scene_obj.addItem(item)
        self.node_items[step_id] = item
        step_data["graph_step_id"] = step_id
        step_data["params"] = params
        step_data["outputs"] = data_outputs
        self.statusMessage.emit(f"Added node: {symbol.get('name')} ({infer_package(symbol)})")
        self.graphChanged.emit()
        self.orderChanged.emit(self.execution_order())

    def rebuild_node(self, step_data: dict[str, Any]):
        self._push_undo_state("rebuild node")
        step_id = step_data.get("graph_step_id")
        if not step_id or step_id not in self.nodes:
            return
        old_node = self.nodes[step_id]
        old_pos = old_node.x, old_node.y
        # Remove links for deleted ports, keep compatible links where possible.
        item = self.node_items.pop(step_id, None)
        if item:
            self.scene_obj.removeItem(item)
        symbol = step_data.get("symbol") or {}
        params = symbol.get("params") or step_data.get("params") or []
        outputs = normalized_outputs(symbol, symbol.get("outputs") or step_data.get("outputs") or [])
        graph_node = PipelineGraphNode(step_id, step_data, symbol, params, outputs, old_pos[0], old_pos[1])
        self.nodes[step_id] = graph_node
        step_data["params"] = params
        step_data["outputs"] = outputs
        new_item = PipelineNodeItem(self, graph_node)
        self.scene_obj.addItem(new_item)
        self.node_items[step_id] = new_item
        valid_inputs = {FLOW_PORT, *(p.get("name") for p in params)}
        valid_outputs = {FLOW_PORT, *(o.get("name") for o in outputs)}
        self.links = [l for l in self.links if (l.from_step != step_id or l.from_output in valid_outputs) and (l.to_step != step_id or l.to_input in valid_inputs)]
        self.refresh_links(rebuild=True)
        self.graphChanged.emit()
        self.orderChanged.emit(self.execution_order())

    def replace_node_symbol(self, step_id, new_symbol):
        if not step_id or step_id not in self.nodes:
            return
        node = self.nodes[step_id]
        node.symbol = new_symbol
        node.params = new_symbol.get("params") or []
        node.outputs = normalized_outputs(new_symbol, new_symbol.get("outputs") or [])
        node.step_data["symbol"] = new_symbol
        node.step_data["params"] = node.params
        node.step_data["outputs"] = node.outputs
        self.rebuild_node(node.step_data)

    def refresh_node_literals(self, step_data):
        step_id = step_data.get("graph_step_id") if isinstance(step_data, dict) else None
        item = self.node_items.get(step_id) if step_id else None
        if not item:
            return
        for name in list(getattr(item, "literal_labels", {}).keys()):
            item.refresh_literal_label(name)
        self.graphChanged.emit()

    def selected_node_ids(self):
        return [step_id for step_id, item in self.node_items.items() if item.isSelected()]

    def selected_link_items(self):
        return [item for item in self.link_items if item.isSelected()]

    def delete_selected(self):
        if self.selected_link_items() or self.selected_node_ids():
            self._push_undo_state("delete selection")
        links = self.selected_link_items()
        nodes = self.selected_node_ids()
        if links:
            for item in list(links):
                self.remove_link(item.link, emit=False)
            self.linkDeleted.emit({"count": len(links)})
            self.graphChanged.emit()
            self.statusMessage.emit(f"Deleted {len(links)} selected connection(s).")
        if nodes:
            for step_id in list(nodes):
                self.remove_node(step_id, emit=False)
            self.nodeDeleted.emit(nodes)
            self.graphChanged.emit()
            self.orderChanged.emit(self.execution_order())
            self.statusMessage.emit(f"Deleted {len(nodes)} selected node(s).")

    def delete_selected_nodes(self):
        self.delete_selected()

    def remove_node(self, step_id, emit=True):
        if emit:
            self._push_undo_state("remove node")
        item = self.node_items.pop(step_id, None)
        if item:
            self.scene_obj.removeItem(item)
        self.nodes.pop(step_id, None)
        self.links = [l for l in self.links if l.from_step != step_id and l.to_step != step_id]
        self.refresh_links(rebuild=True)
        if emit:
            self.nodeDeleted.emit([step_id])
            self.graphChanged.emit()
            self.orderChanged.emit(self.execution_order())

    def remove_link(self, link, emit=True):
        if emit:
            self._push_undo_state("remove link")
        self.links = [l for l in self.links if l is not link]
        self.refresh_links(rebuild=True)
        if emit:
            self.linkDeleted.emit(self._link_payload(link))
            self.graphChanged.emit()
            self.orderChanged.emit(self.execution_order())

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Undo):
            self.undo_last_change()
            return
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected()
            return
        if event.matches(QKeySequence.SelectAll):
            for item in self.node_items.values():
                item.setSelected(True)
            for item in self.link_items:
                item.setSelected(True)
            return
        super().keyPressEvent(event)

    def edit_literal_for_port(self, port):
        if port.name == FLOW_PORT:
            return
        step = port.node_item.graph_node.step_data
        step_id = port.node_item.graph_node.step_id
        connection = self.input_connection(step_id, port.name)
        if connection is not None:
            source_node = self.nodes.get(connection.from_step)
            source_name = str(
                ((source_node.symbol if source_node else {}) or {}).get("name")
                or connection.from_step
            )
            self.statusMessage.emit(
                f"Input '{port.name}' is driven by "
                f"{source_name}.{connection.from_output}. Disconnect it to edit a literal value."
            )
            return
        value, ok = QInputDialog.getText(self, "Edit input value", f"{port.name}:", text=str(self.literal_value(step, port.name)))
        if ok:
            self._push_undo_state("edit literal")
            self.set_literal_value(step, port.name, value)
            port.node_item.refresh_literal_label(port.name)
            self.literalChanged.emit({"step_data": step, "step_id": step_id, "input": port.name, "value": value})
            self.graphChanged.emit()

    def contextMenuEvent(self, event):
        self._request_graph_interaction_ready()
        item = self.scene_obj.itemAt(self.mapToScene(event.pos()), self.transform())
        if item is not None:
            return super().contextMenuEvent(event)
        menu = QMenu(self)
        undo_action = menu.addAction("Undo Graph Change")
        undo_action.setEnabled(self.can_undo())
        menu.addSeparator()
        
        add_tool_menu = menu.addMenu("Add Tool Node")
        self._build_context_tool_picker(menu, add_tool_menu)
        tool_actions = {}
        menu.addSeparator()
        
        actions = {}
        for category, items in utility_node_menu_items().items():
            sub = menu.addMenu(category)
            for kind, label in items:
                actions[sub.addAction(label)] = kind
        
        action = menu.exec(event.globalPos())
        if action == undo_action:
            self.undo_last_change()
        elif action in tool_actions:
            payload = tool_actions[action]
            if isinstance(payload, tuple) and payload and payload[0] == "add_connect_existing":
                self.add_tool_node_with_existing_context(payload[1], payload[2])
            elif isinstance(payload, tuple) and payload and payload[0] == "add_connect_context":
                plan = self.choose_context_addition_plan(payload[1], payload[2])
                if plan:
                    self.add_tool_node_with_context(payload[1], plan)
            elif isinstance(payload, tuple) and payload and payload[0] == "add_configured":
                self.add_configured_tool_node(payload[1])
            elif isinstance(payload, tuple) and payload and payload[0] == "add":
                self.toolNodeRequested.emit(payload[1])
            else:
                self.toolNodeRequested.emit(payload)
        elif action in actions:
            self.add_utility_node(actions[action])


    def _split_count_from_annotation(self, annotation: str) -> int:
        text = (annotation or "").strip()
        low = text.lower()
        if not text:
            return 2
        # tuple[A, B] / Tuple[A, B] means we know the arity.
        if "tuple[" in low or low.startswith("tuple(") or low.startswith("tuple"):
            inner = text[text.find("[") + 1:text.rfind("]")] if "[" in text and "]" in text else ""
            if inner:
                depth = 0
                count = 1
                for ch in inner:
                    if ch in "[(":
                        depth += 1
                    elif ch in ")]":
                        depth = max(0, depth - 1)
                    elif ch == "," and depth == 0:
                        count += 1
                return max(1, min(count, 24))
        # list[...] does not tell us runtime length. Give a practical two-port start.
        if "list" in low or "sequence" in low or "iterable" in low:
            return 2
        return 2

    def _output_annotation_for_port(self, step_id: str, output_name: str) -> str:
        node = self.nodes.get(step_id)
        if not node:
            return ""
        for output in node.outputs or []:
            if (output.get("name") or "") == output_name:
                return output.get("annotation") or output.get("python_type") or ""
        return ""

    def _refresh_split_list_outputs_for_link(self, link: PipelineGraphLink) -> None:
        if link.link_type != "data" or link.to_input != "source":
            return
        target_node = self.nodes.get(link.to_step)
        if not target_node:
            return
        symbol = target_node.symbol or {}
        if symbol.get("utility_kind") != "split_list_items":
            return
        annotation = self._output_annotation_for_port(link.from_step, link.from_output)
        count = self._split_count_from_annotation(annotation)
        outputs = [{"name": f"item_{idx}", "annotation": "Any", "python_type": "Any"} for idx in range(count)]
        symbol["outputs"] = outputs
        target_node.step_data["outputs"] = outputs
        self.rebuild_node(target_node.step_data)
        self.statusMessage.emit(f"Split List Items outputs refreshed to {count} item port(s).")

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton and event.modifiers() & Qt.ControlModifier:
            self._ctrl_middle_panning = True
            self._ctrl_middle_pan_start = event.pos()
            self._ctrl_middle_h_start = self.horizontalScrollBar().value()
            self._ctrl_middle_v_start = self.verticalScrollBar().value()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        scene_pos = self.mapToScene(event.pos())
        item = self.scene_obj.itemAt(scene_pos, self.transform())
        if isinstance(item, PipelinePortItem) and item.direction in {"output", "flow_out"}:
            self._push_undo_state("create link")
            self.pending_port = item
            self.temp_link = TempLinkItem(item)
            self.scene_obj.addItem(self.temp_link)
            return
        if isinstance(item, PipelinePortItem) and item.direction in {"input", "flow_in"} and self.pending_port:
            self._finish_link(item)
            return
        if isinstance(item, PipelineNodeItem):
            if event.button() == Qt.LeftButton:
                self._push_undo_state("move node")
            self.nodeSelected.emit(item.graph_node.step_data)
        else:
            parent = item.parentItem() if item else None
            if parent is not None and hasattr(parent, "graph_node"):
                self.nodeSelected.emit(parent.graph_node.step_data)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._ctrl_middle_panning and self._ctrl_middle_pan_start is not None:
            delta = event.pos() - self._ctrl_middle_pan_start
            self.horizontalScrollBar().setValue(self._ctrl_middle_h_start - delta.x())
            self.verticalScrollBar().setValue(self._ctrl_middle_v_start - delta.y())
            event.accept()
            return
        if self.temp_link:
            self.temp_link.set_end(self.mapToScene(event.pos()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._ctrl_middle_panning:
            self._ctrl_middle_panning = False
            self._ctrl_middle_pan_start = None
            self.unsetCursor()
            event.accept()
            return
        if self.pending_port:
            item = self.scene_obj.itemAt(self.mapToScene(event.pos()), self.transform())
            if isinstance(item, PipelinePortItem) and item.direction in {"input", "flow_in"}:
                self._finish_link(item)
            else:
                self._clear_temp_link()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_in() if event.angleDelta().y() > 0 else self.zoom_out()
            return
        super().wheelEvent(event)

    def _link_payload(self, link: PipelineGraphLink) -> dict[str, str]:
        return {
            "from_step": link.from_step,
            "from_output": link.from_output,
            "to_step": link.to_step,
            "to_input": link.to_input,
            "type": link.link_type,
        }

    def _finish_link(self, target):
        source = self.pending_port
        if not source:
            return
        if source.node_item is target.node_item:
            self.statusMessage.emit("Cannot connect a node to itself.")
            self._clear_temp_link()
            return

        if source.direction == "flow_out" and target.direction == "flow_in":
            link_type = "flow"
        elif source.direction == "output" and target.direction == "input":
            link_type = "data"
        else:
            self.statusMessage.emit("Invalid connection. Use yellow flow → flow or green data output → argument input.")
            self._clear_temp_link()
            return

        self.links = [
            l for l in self.links
            if not (l.to_step == target.node_item.graph_node.step_id and l.to_input == target.name and l.link_type == link_type)
        ]

        link = PipelineGraphLink(
            source.node_item.graph_node.step_id,
            source.name,
            target.node_item.graph_node.step_id,
            target.name,
            link_type,
        )
        self.links.append(link)
        if link_type == "data":
            self._refresh_split_list_outputs_for_link(link)
        self._clear_temp_link()
        self.refresh_links(rebuild=True)
        self.linkCreated.emit(self._link_payload(link))
        self.graphChanged.emit()
        self.orderChanged.emit(self.execution_order())

    def _clear_temp_link(self):
        if self.temp_link:
            self.scene_obj.removeItem(self.temp_link)
        self.temp_link = None
        self.pending_port = None

    def refresh_links(self, rebuild=False):
        if rebuild:
            for item in list(self.link_items):
                self.scene_obj.removeItem(item)
            self.link_items.clear()
            for link in self.links:
                s_item = self.node_items.get(link.from_step)
                t_item = self.node_items.get(link.to_step)
                if not s_item or not t_item:
                    continue
                source = s_item.output_ports.get(link.from_output)
                target = t_item.input_ports.get(link.to_input)
                if not source or not target:
                    continue
                item = PipelineLinkItem(self, link, source, target)
                self.scene_obj.addItem(item)
                self.link_items.append(item)
        else:
            for item in self.link_items:
                item.update_path()

    def _position_order(self) -> list[str]:
        return [n.step_id for n in sorted(self.nodes.values(), key=lambda n: (n.x, n.y))]

    def execution_order(self):
        base = self._position_order()
        base_index = {step_id: idx for idx, step_id in enumerate(base)}
        edges = [(l.from_step, l.to_step) for l in self.links if l.link_type == "flow"]
        if not edges:
            return base
        incoming = {step_id: 0 for step_id in base}
        outgoing = {step_id: [] for step_id in base}
        for src, dst in edges:
            if src in incoming and dst in incoming and src != dst:
                outgoing[src].append(dst)
                incoming[dst] += 1
        queue = sorted([s for s, count in incoming.items() if count == 0], key=lambda s: base_index.get(s, 0))
        result = []
        while queue:
            current = queue.pop(0)
            result.append(current)
            for dst in sorted(outgoing.get(current, []), key=lambda s: base_index.get(s, 0)):
                incoming[dst] -= 1
                if incoming[dst] == 0:
                    queue.append(dst)
                    queue.sort(key=lambda s: base_index.get(s, 0))
        if len(result) != len(base):
            self.statusMessage.emit("Flow cycle detected. Falling back to left-to-right node order.")
            return base
        return result

    def ordered_step_data(self):
        return [self.nodes[step_id].step_data for step_id in self.execution_order() if step_id in self.nodes]

    def manifest_data_links(self):
        ordered_ids = self.execution_order()
        index = {step_id: i + 1 for i, step_id in enumerate(ordered_ids)}
        result = []
        for link in self.links:
            if link.link_type != "data":
                continue
            if link.from_step in index and link.to_step in index:
                result.append({"from": f"step{index[link.from_step]}.{link.from_output}", "to": f"step{index[link.to_step]}.{link.to_input}", "type": "data"})
        return result

    def manifest_flow_links(self):
        ordered_ids = self.execution_order()
        index = {step_id: i + 1 for i, step_id in enumerate(ordered_ids)}
        result = []
        for link in self.links:
            if link.link_type != "flow":
                continue
            if link.from_step in index and link.to_step in index:
                result.append({"from": f"step{index[link.from_step]}", "to": f"step{index[link.to_step]}", "type": "flow"})
        return result

    def manifest_links(self):
        return self.manifest_data_links()

    def zoom_in(self):
        self.scale(1.18, 1.18)

    def zoom_out(self):
        self.scale(1 / 1.18, 1 / 1.18)

    def focus_all(self):
        if not self.node_items:
            return
        rect = None
        for item in self.node_items.values():
            r = item.sceneBoundingRect()
            rect = r if rect is None else rect.united(r)
        if rect:
            self.fitInView(rect.adjusted(-80, -80, 80, 80), Qt.KeepAspectRatio)

    def focus_selection(self):
        selected = [item for item in self.scene_obj.selectedItems() if isinstance(item, (PipelineNodeItem, PipelineLinkItem))]
        if not selected:
            return self.focus_all()
        rect = None
        for item in selected:
            r = item.sceneBoundingRect()
            rect = r if rect is None else rect.united(r)
        if rect:
            self.fitInView(rect.adjusted(-60, -60, 60, 60), Qt.KeepAspectRatio)
