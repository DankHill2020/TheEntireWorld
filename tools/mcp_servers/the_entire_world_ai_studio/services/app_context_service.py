"""Application context parsing for slash commands and app-scoped mentions."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class AppContext:
    id: str
    name: str
    category: str
    aliases: tuple[str, ...]
    mention_kinds: tuple[str, ...]
    source: str = "builtin"

    def slash_token(self) -> str:
        return "/" + self.name.replace(" ", "")

    def display(self) -> str:
        return f"{self.slash_token()}  [{self.category}]"


BUILTIN_APP_CONTEXTS: tuple[AppContext, ...] = (
    AppContext("maya", "Maya", "DCC", ("maya",), ("object", "selection", "node", "material")),
    AppContext("blender", "Blender", "DCC", ("blender",), ("object", "selection", "collection", "material")),
    AppContext("houdini", "Houdini", "DCC", ("houdini", "hou"), ("node", "selection", "network", "sop")),
    AppContext("substance_painter", "Substance Painter", "DCC", ("substance", "substancepainter", "painter"), ("texture_set", "material", "project")),
    AppContext("motionbuilder", "MotionBuilder", "DCC", ("motionbuilder", "mobu"), ("scene_object", "take", "character")),
    AppContext("unreal", "Unreal", "Engine", ("unreal", "unrealengine", "ue"), ("asset", "blueprint", "actor", "level")),
    AppContext("unity", "Unity", "Engine", ("unity",), ("scene", "gameobject", "asset")),
    AppContext("slack", "Slack", "Messaging", ("slack",), ("channel", "user", "message_target")),
    AppContext("discord", "Discord", "Messaging", ("discord",), ("channel", "user", "webhook")),
    AppContext("jira", "Jira", "Ops", ("jira",), ("project", "issue", "assignee", "label")),
    AppContext("confluence", "Confluence", "Ops", ("confluence",), ("space", "page", "parent_page")),
)


SLASH_RE = re.compile(r"(^|\s)/([A-Za-z][A-Za-z0-9_-]*)")


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _contexts_from_packages(packages: Iterable[dict]) -> list[AppContext]:
    contexts: list[AppContext] = []
    for package in packages or []:
        name = str(package.get("name") or package.get("id") or "").strip()
        if not name:
            continue
        package_type = str(package.get("type_label") or package.get("type") or "Integration")
        category = str((package.get("bridge_manifest") or {}).get("group") or package_type)
        aliases = {_normalize(name), _normalize(str(package.get("id") or ""))}
        for alias in package.get("aliases") or []:
            aliases.add(_normalize(str(alias)))
        contexts.append(
            AppContext(
                id=str(package.get("id") or _normalize(name)),
                name=name,
                category=category,
                aliases=tuple(sorted(alias for alias in aliases if alias)),
                mention_kinds=("resource", "target", "channel", "project", "page"),
                source="integration_package",
            )
        )
    return contexts


def installed_app_contexts() -> list[AppContext]:
    contexts = list(BUILTIN_APP_CONTEXTS)
    try:
        from services.integration_package_service import load_integration_packages

        contexts.extend(_contexts_from_packages(load_integration_packages()))
    except Exception:
        pass
    return dedupe_contexts(contexts)


def dedupe_contexts(contexts: Iterable[AppContext]) -> list[AppContext]:
    seen: set[str] = set()
    out: list[AppContext] = []
    for context in contexts:
        key = context.id.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(context)
    return sorted(out, key=lambda item: (item.category.lower(), item.name.lower()))


def app_context_for_token(token: str, contexts: Iterable[AppContext] | None = None) -> AppContext | None:
    normalized = _normalize(token)
    if not normalized:
        return None
    for context in contexts or installed_app_contexts():
        names = {_normalize(context.id), _normalize(context.name), *context.aliases}
        if normalized in names:
            return context
    return None


def active_app_context(text: str, cursor_pos: int | None = None, contexts: Iterable[AppContext] | None = None) -> AppContext | None:
    before = (text or "")[: cursor_pos if cursor_pos is not None else len(text or "")]
    matches = list(SLASH_RE.finditer(before))
    if not matches:
        return None
    return app_context_for_token(matches[-1].group(2), contexts)


def slash_suggestions(query: str = "", contexts: Iterable[AppContext] | None = None, limit: int = 12) -> list[AppContext]:
    q = _normalize(query)
    matches = []
    for context in contexts or installed_app_contexts():
        haystack = " ".join([context.id, context.name, context.category, *context.aliases])
        if not q or q in _normalize(haystack):
            matches.append(context)
    return matches[:limit]


def strip_app_slash_prefix(text: str) -> str:
    return SLASH_RE.sub(lambda m: m.group(1), text or "", count=1).strip()


def app_context_prompt_block(text: str) -> str:
    context = active_app_context(text)
    if not context:
        return ""
    kinds = ", ".join(context.mention_kinds)
    return (
        "Selected Application Context:\n"
        f"- app={context.name}\n"
        f"- category={context.category}\n"
        f"- mention_scope={kinds}\n"
        "- Use @mentions as references inside this application context. If a mention is unresolved, ask for clarification or search the configured connector/package before acting."
    )
