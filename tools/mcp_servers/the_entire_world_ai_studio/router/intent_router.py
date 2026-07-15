"""Classify user input intent for deterministic routing."""

import json


class RequestIntent:
    LLM = "llm"
    MAYA_EXECUTE = "maya_execute"
    MAYA_FUNCTION = "maya_function"
    UNREAL_CALL = "unreal_call"
    BLENDER_FUNCTION = "blender_function"
    SUBSTANCE_PAINTER_FUNCTION = "substance_painter_function"
    MOTIONBUILDER_FUNCTION = "motionbuilder_function"
    UNITY_FUNCTION = "unity_function"
    KNOWLEDGE_SYMBOL = "knowledge_symbol"
    KNOWLEDGE_CALLERS = "knowledge_callers"
    KNOWLEDGE_SOURCE = "knowledge_source"
    EDITOR_LOCAL = "editor_local"
    EDITOR_LLM = "editor_llm"
    EDITOR_PROJECT_SEARCH = "editor_project_search"
    EDITOR_PROJECT_EDIT = "editor_project_edit"
    EDITOR_TARGET_DISCOVERY_EDIT = "editor_target_discovery_edit"
    MOTIONBUILDER_MCP = "motionbuilder_mcp"


class IntentRouter:
    """Determine how a request should be handled."""

    TOOL_DOMAIN_INTENTS = {
        "maya_tools.": RequestIntent.MAYA_FUNCTION,
        "unreal_tools.": RequestIntent.UNREAL_CALL,
        "blender_tools.": RequestIntent.BLENDER_FUNCTION,
        "substance_painter_tools.": RequestIntent.SUBSTANCE_PAINTER_FUNCTION,
        "mobu_tools.": RequestIntent.MOTIONBUILDER_FUNCTION,
        "motionbuilder_tools.": RequestIntent.MOTIONBUILDER_FUNCTION,
        "unity_tools.": RequestIntent.UNITY_FUNCTION,
    }

    @staticmethod
    def intent_for_function(function_path: str) -> str:
        function_path = (function_path or "").strip()
        for prefix, intent in IntentRouter.TOOL_DOMAIN_INTENTS.items():
            if function_path.startswith(prefix):
                return intent
        return RequestIntent.LLM

    @staticmethod
    def classify_chat_input(text: str) -> str:
        """Default chat input goes to LLM unless explicitly structured."""
        text = (text or "").strip()
        if not text:
            return RequestIntent.LLM

        if text.startswith("{"):
            try:
                data = json.loads(text)
                if "function" in data:
                    intent = IntentRouter.intent_for_function(data["function"])
                    if intent != RequestIntent.LLM:
                        return intent
            except json.JSONDecodeError:
                pass

        intent = IntentRouter.intent_for_function(text)
        if intent != RequestIntent.LLM:
            return intent

        lower = text.lower()
        try:
            from services.project_service import is_project_health_request
            if is_project_health_request(text):
                return RequestIntent.PROJECT_HEALTH
        except Exception:
            pass
        try:
            from services.project_service import is_target_discovery_edit_request
            if is_target_discovery_edit_request(text):
                return RequestIntent.PROJECT_TARGET_EDIT
        except Exception:
            pass

        if "import maya" in text or "maya.cmds" in text or "cmds." in text:
            return RequestIntent.MAYA_EXECUTE

        return RequestIntent.LLM


    @staticmethod
    def classify_editor_input(text: str) -> str:
        """Classify editor prompt scope for Ask About File / editor workflows."""
        text = (text or "").strip()
        lower = text.lower()
        if not text:
            return RequestIntent.EDITOR_LOCAL

        project_hints = (
            "project", "codebase", "whole repo", "entire repo", "entire project",
            "all files", "every file", "throughout", "everywhere", "anywhere",
            "find every", "find all", "where is", "where are", "used by",
            "usages", "references", "callers",
        )
        edit_hints = (
            "rename", "replace", "refactor", "update", "modify", "change",
            "fix", "remove", "delete", "add", "create", "write", "generate",
            "implement", "insert", "improve",
        )
        target_discovery_hints = (
            "find me a", "find a", "find the", "locate a", "locate the",
            "choose a", "pick a", "where should", "best place", "which file",
        )
        target_nouns = ("file", "module", "place", "location")

        if any(hint in lower for hint in project_hints):
            if any(hint in lower for hint in edit_hints):
                return RequestIntent.EDITOR_PROJECT_EDIT
            return RequestIntent.EDITOR_PROJECT_SEARCH

        if (
            any(hint in lower for hint in target_discovery_hints)
            and any(noun in lower for noun in target_nouns)
            and any(hint in lower for hint in edit_hints)
        ):
            return RequestIntent.EDITOR_TARGET_DISCOVERY_EDIT

        llm_hints = (
            "add", "make", "create", "write", "generate", "build", "implement",
            "change", "modify", "replace", "fix", "debug", "refactor",
        )
        if any(hint in lower for hint in llm_hints):
            return RequestIntent.EDITOR_LLM
        return RequestIntent.EDITOR_LOCAL

    @staticmethod
    def is_maya_python(text: str) -> bool:
        text = (text or "").strip()
        return bool(text) and not text.startswith("{")

    @staticmethod
    def is_maya_json(text: str) -> bool:
        text = (text or "").strip()
        return text.startswith("{")

    @staticmethod
    def is_unreal_function_path(text: str) -> bool:
        text = (text or "").strip()
        return bool(text) and (text.startswith("{") or text.startswith("unreal_tools."))
