from __future__ import annotations

"""Route commands to the appropriate bridge."""

import contextlib
import importlib
import io
import json
import re
import threading
import time
from pathlib import Path

from tech_connector.bridges.blender.blender_bridge import BlenderBridge
from tech_connector.bridges.houdini.houdini_bridge import HoudiniBridge
from tech_connector.bridges.maya.maya_bridge import MayaBridge
from tech_connector.bridges.motionbuilder.motionbuilder_adapter import MotionBuilderAdapter
from tech_connector.bridges.motionbuilder.motionbuilder_bridge import MotionBuilderBridge
from tech_connector.bridges.substance_painter.substance_painter_bridge import SubstancePainterBridge
from tech_connector.bridges.unity.unity_bridge import UnityBridge
from tech_connector.bridges.unreal import unreal_intent_parser as _uip
from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.bridges.unreal.unreal_scanner import UnrealScanner
from tech_connector.models.constants import TOOLS_ROOT
from tech_connector.router.intent_router import IntentRouter, RequestIntent
from tech_connector.services.dcc.dcc_operation_service import dcc_operation_function
from tech_connector.services.unreal.unreal_operation_service import (
    build_unreal_execution_plan,
    explain_unreal_execution_plan,
    operation_catalog,
    unreal_operation_payload,
    unreal_project_scan_payloads,
)

HOST_ALIASES = {
    "maya": ("maya", "cmds", "pymel"),
    "unreal": ("unreal", "ue", "uproject", "blueprint", "uasset"),
    "blender": ("blender", "bpy", "blend file"),
    "substance_painter": ("substance painter", "substance", "painter"),
    "motionbuilder": ("motionbuilder", "motion builder", "mobu"),
    "unity": ("unity", "gameobject", "prefab", "unityeditor"),
    "houdini": ("houdini", "hou", "hip file", "hdri", "vex", "vop", "dop", "sop"),
}

DEFAULT_TOOL_DOMAINS = {
    "maya": "maya_tools",
    "unreal": "unreal_tools",
    "blender": "blender_tools",
    "substance_painter": "substance_painter_tools",
    "motionbuilder": "motionbuilder_tools",
    "unity": "unity_tools",
    "houdini": "houdini_tools",
}

TOOL_DOMAIN_ALIASES = {
    "motionbuilder": ("motionbuilder_tools", "mobu_tools"),
}

GENERIC_DCC_TERMS = {
    "a",
    "an",
    "and",
    "are",
    "asset",
    "assets",
    "call",
    "can",
    "create",
    "current",
    "dcc",
    "do",
    "find",
    "for",
    "from",
    "get",
    "give",
    "how",
    "in",
    "into",
    "list",
    "make",
    "me",
    "my",
    "of",
    "on",
    "please",
    "scene",
    "show",
    "the",
    "this",
    "to",
    "tool",
    "tools",
    "use",
    "using",
    "want",
    "with",
}

UNREAL_ASSET_TYPE_ALIASES = (
    (("skeletons", "skeleton"), "Skeleton", "Unreal Skeletons"),
    (("skeletal meshes", "skeletal mesh"), "SkeletalMesh", "Unreal Skeletal Meshes"),
    (
        ("static meshes", "static mesh", "meshes", "mesh"),
        "StaticMesh",
        "Unreal Static Meshes",
    ),
    (("materials", "material"), "Material", "Unreal Materials"),
    (("textures", "texture2d", "texture"), "Texture2D", "Unreal Textures"),
    (("blueprints", "blueprint"), "Blueprint", "Unreal Blueprints"),
    (
        ("animation sequences", "anim sequences", "animations", "animation"),
        "AnimSequence",
        "Unreal Animations",
    ),
    (
        ("level sequences", "sequences", "sequence"),
        "LevelSequence",
        "Unreal Level Sequences",
    ),
    (("maps", "levels", "worlds"), "World", "Unreal Maps"),
)


class CommandRouter:
    """Execute deterministic commands via host bridges."""

    def __init__(self):
        self.blender = BlenderBridge()
        self.houdini = HoudiniBridge()
        self.maya = MayaBridge()
        self.unreal = UnrealBridge()
        self.motionbuilder = MotionBuilderBridge()
        self.motionbuilder_adapter = MotionBuilderAdapter()
        self.substance_painter = SubstancePainterBridge()
        self.unity = UnityBridge()
        self._dcc_candidate_cache = {}
        self._dcc_candidate_cache_ttl = 30.0
        self._active_dcc_context_cache = ""
        self._active_dcc_context_cache_at = 0.0
        self._active_dcc_context_refreshing = False
        self._active_dcc_context_lock = threading.Lock()

    def _plugin_tool_domains(self) -> dict[str, str]:
        domains = dict(DEFAULT_TOOL_DOMAINS)
        try:
            from tech_connector.models.constants import APP_ROOT

            registry_path = APP_ROOT / "plugins" / "plugin_registry.json"
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            for host, info in (data.get("plugins") or {}).items():
                tool_domain = (info or {}).get("tool_domain")
                if tool_domain:
                    domains[host] = tool_domain
        except Exception:
            pass
        return domains

    def parse_tool_function_payload(self, text: str):
        text = (text or "").strip()
        if not text:
            return None
        if text.startswith("{"):
            data = json.loads(text)
            if "function" not in data:
                return None
            return data["function"], data.get("args", []), data.get("kwargs", {})
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$", text):
            return text, [], {}
        return None

    def host_for_tool_function(self, function_path: str) -> str:
        function_path = (function_path or "").strip()
        for host, domain in self._plugin_tool_domains().items():
            domains = (domain, *TOOL_DOMAIN_ALIASES.get(host, ()))
            if any(function_path.startswith(f"{item}.") for item in domains):
                return host
        for host, domain in DEFAULT_TOOL_DOMAINS.items():
            domains = (domain, *TOOL_DOMAIN_ALIASES.get(host, ()))
            if any(function_path.startswith(f"{item}.") for item in domains):
                return host
        return ""

    def execute_tool_function_from_text(self, text: str) -> tuple[str, bool, str]:
        parsed = self.parse_tool_function_payload(text)
        if not parsed:
            return (
                "DCC Tool Function",
                False,
                "Expected a tool function path or JSON payload with function/args/kwargs.",
            )

        function_path, args, kwargs = parsed
        host = self.host_for_tool_function(function_path)
        try:
            if host == "maya":
                ok, result = self.maya.call_function(
                    function_path, args=args, kwargs=kwargs
                )
                return "Maya Function", ok, result
            if host == "unreal":
                ok, result = self.unreal.call(function_path, args=args, kwargs=kwargs)
                return "Unreal Direct", ok, result
            if host == "blender":
                ok, result = self.blender.call_function(
                    function_path, args=args, kwargs=kwargs
                )
                return "Blender Function", ok, result
            if host == "substance_painter":
                ok, result = self.substance_painter.call_function(
                    function_path, args=args, kwargs=kwargs
                )
                return "Substance Painter Function", ok, result
            if host == "motionbuilder":
                ok, result = self.motionbuilder.call_function(
                    function_path, args=args, kwargs=kwargs
                )
                return "MotionBuilder Function", ok, result
            if host == "houdini":
                ok, result = self.houdini.call_function(
                    function_path, args=args, kwargs=kwargs
                )
                return "Houdini Function", ok, result
            if host == "unity":
                return (
                    "Unity Function",
                    False,
                    "Unity package functions need a Unity C# bridge/API wrapper; direct Python package calls are not available.",
                )
            return (
                "DCC Tool Function",
                False,
                f"Unknown DCC tool domain for function: {function_path}",
            )
        except Exception as e:
            return "DCC Tool Function", False, str(e)

    def _host_bridge_for_operation(self, host: str):
        return {
            "maya": self.maya,
            "blender": self.blender,
            "substance_painter": self.substance_painter,
            "motionbuilder": self.motionbuilder,
            "unity": self.unity,
            "houdini": self.houdini,
        }.get(host)

    def dcc_context_snapshot(self, host: str) -> str:
        try:
            if host == "maya":
                from tech_connector.bridges.maya.maya_adapter import MayaAdapter

                return MayaAdapter().build_context_summary()
            if host == "motionbuilder":
                return self.motionbuilder_adapter.build_context_summary()
            if host == "houdini":
                from tech_connector.bridges.houdini.houdini_adapter import HoudiniAdapter

                return HoudiniAdapter().build_context_summary()
            if host == "substance_painter":
                from tech_connector.bridges.substance_painter.substance_painter_adapter import SubstancePainterAdapter

                return SubstancePainterAdapter().build_context_summary()

            presets = {
                "blender": (
                    self.blender.find_port(),
                    self.blender.get_current_file_code(),
                    self.blender.get_scene_objects_code(),
                    self.blender.execute,
                ),
                "unity": (
                    self.unity.find_port(),
                    self.unity.get_current_file_code(),
                    self.unity.get_scene_objects_code(),
                    self.unity.execute,
                ),
            }
            if host not in presets:
                return ""
            port, file_code, objects_code, execute = presets[host]
            if not port:
                return f"{host}: bridge not connected."
            file_ok, file_result = execute(file_code)
            objects_ok, objects_result = execute(objects_code)
            return json.dumps(
                {
                    "host": host,
                    "connected": True,
                    "file": file_result if file_ok else "",
                    "objects": objects_result if objects_ok else "",
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            return f"{host}: context snapshot failed: {e}"

    def execute_dcc_editor_operation(
        self, host: str, mode: str, params: dict
    ) -> tuple[str, bool, str]:
        if host == "unreal":
            if mode == "prototype":
                return self.execute_unreal_operation(
                    "gameplay.prototype_from_template", params
                )
            if mode == "debug":
                return self.execute_unreal_operation("project.debug", params)

        label = f"{host.replace('_', ' ').title()} {'Prototype' if mode == 'prototype' else 'Debug'}"
        bridge = self._host_bridge_for_operation(host)
        if not bridge:
            return label, False, f"No bridge configured for host: {host}"

        if host == "unity":
            payload = json.dumps(params, default=str).replace('"', '""')
            method = "PrototypeFromTemplate" if mode == "prototype" else "DebugProject"
            code = f'AIStudioOperations.{method}(@"{payload}")'
            ok, result = self.unity.execute(code, timeout=60)
            return label, ok, result

        function_path = dcc_operation_function(host, mode)
        call_function = getattr(bridge, "call_function", None)
        if not call_function:
            return (
                label,
                False,
                f"{label} requires a host package function endpoint: {function_path}",
            )
        ok, result = call_function(function_path, kwargs=params)
        if not ok and (
            "No module named" in result
            or "ModuleNotFoundError" in result
            or "AttributeError" in result
        ):
            result = (
                f"{result}\n\nExpected host-side endpoint: {function_path}. "
                "Add this function to the host tool package to make project-aware editor operations executable."
            )
        return label, ok, result

    def execute_registered_dcc_operation(
        self,
        host: str,
        operation_key: str,
        params: dict | None = None,
        *,
        approved: bool = True,
        timeout_seconds: float = 60.0,
    ) -> tuple[str, bool, str]:
        """Execute a registered Maya/Blender operation through the canonical DCC adapter stack."""
        normalized_host = (host or "").strip().lower()
        if normalized_host not in {"maya", "blender"}:
            return "DCC Operation", False, f"Registered DCC operation execution is not wired for host: {host}"

        try:
            from reasoning_runtime.engine.request_context import RequestContext
            from tech_connector.services.dcc.dcc_execution_service import (
                DccExecutionRequest,
                default_dcc_execution_adapters,
            )
        except Exception as exc:
            return "DCC Operation", False, f"DCC execution service unavailable: {exc}"

        adapters = default_dcc_execution_adapters()
        adapter = adapters.get(normalized_host)
        if not adapter:
            return "DCC Operation", False, f"No registered DCC execution adapter for host: {normalized_host}"

        operation_params = dict(params or {})
        try:
            from tech_connector.services.dcc.dcc_operation_service import registered_dcc_operation

            operation = registered_dcc_operation(normalized_host, operation_key)
        except Exception:
            operation = None
        if operation is None:
            return (
                f"{normalized_host.title()} Registered Operation",
                False,
                f"Unknown registered {normalized_host} operation: {operation_key}",
            )
        missing_slots = [
            name
            for name in tuple(getattr(operation, "required", ()) or ())
            if operation_params.get(name) in (None, "")
        ]
        request = DccExecutionRequest(
            execution_environment=normalized_host,
            operation_mode="execute",
            target_type="registered_dcc_operation",
            target_identifier=operation_key,
            callable_name=str(getattr(operation, "function", "") or ""),
            keyword_args=operation_params,
            missing_slots=missing_slots,
            approved=bool(approved),
            timeout_seconds=float(timeout_seconds or 60.0),
            original_prompt=f"Execute {normalized_host} operation {operation_key}",
        )

        class _Window:
            command_router = self

        context = RequestContext(
            text=request.original_prompt,
            extras={"window": _Window()},
        )
        check = adapter.check_capabilities(request, context)
        if not check.ok:
            return (
                f"{normalized_host.title()} Registered Operation",
                False,
                json.dumps({"status": "capability_failure", "failures": check.to_dict().get("failures", [])}, indent=2, default=str),
            )
        result = adapter.execute(request, context)
        return (
            f"{normalized_host.title()} Registered Operation",
            result.status == "completed",
            json.dumps(result.to_dict(), indent=2, default=str),
        )

    def detect_dcc_hosts(self, text: str, route_task_role: str = "") -> list[str]:
        q = (text or "").lower()
        hosts = []
        if route_task_role in DEFAULT_TOOL_DOMAINS:
            hosts.append(route_task_role)
        for host, aliases in HOST_ALIASES.items():
            if any(alias in q for alias in aliases) and host not in hosts:
                hosts.append(host)
        return hosts

    def _dcc_keywords(self, text: str, limit: int = 8) -> list[str]:
        keywords = []
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text or ""):
            token = token.lower()
            if token in GENERIC_DCC_TERMS or token in DEFAULT_TOOL_DOMAINS:
                continue
            if len(token) < 3:
                continue
            if token not in keywords:
                keywords.append(token)
            if len(keywords) >= limit:
                break
        return keywords

    def _module_path_from_file(self, file_path: str, tool_domain: str) -> str:
        path = Path(file_path or "")
        parts = list(path.parts)
        lowered = [p.lower() for p in parts]
        if tool_domain.lower() not in lowered:
            return ""
        index = lowered.index(tool_domain.lower())
        module_parts = parts[index:]
        if module_parts and module_parts[-1].endswith(".py"):
            module_parts[-1] = Path(module_parts[-1]).stem
        if module_parts and module_parts[-1] == "__init__":
            module_parts = module_parts[:-1]
        return ".".join(p for p in module_parts if p)

    def find_dcc_tool_candidates(
        self, text: str, route_task_role: str = "", limit: int = 6
    ) -> list[dict]:
        hosts = self.detect_dcc_hosts(text, route_task_role=route_task_role)
        if not hosts:
            return []

        domains = self._plugin_tool_domains()
        keywords = self._dcc_keywords(text)
        cache_key = (tuple(hosts), tuple(keywords), limit)
        cached = self._dcc_candidate_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < self._dcc_candidate_cache_ttl:
            return list(cached[1])

        candidates = []
        seen = set()

        def add_candidate(host: str, domain: str, result: dict):
            file_path = result.get("file_path") or ""
            module = self._module_path_from_file(file_path, domain)
            if not module:
                return
            name = result.get("name") or ""
            function_path = f"{module}.{name}" if name else module
            key = (host, function_path)
            if key in seen:
                return
            seen.add(key)
            candidates.append(
                {
                    "host": host,
                    "domain": domain,
                    "function": function_path,
                    "signature": result.get("signature") or "",
                    "docstring": (result.get("docstring") or "")
                    .strip()
                    .replace("\n", " "),
                    "file_path": file_path,
                    "kind": result.get("kind") or "",
                }
            )

        if "unreal" in hosts and any(
            word in (text or "").lower()
            for word in (
                "asset",
                "assets",
                "skeleton",
                "mesh",
                "material",
                "texture",
                "blueprint",
                "animation",
                "sequence",
                "map",
                "level",
            )
        ):
            add_candidate(
                "unreal",
                domains.get("unreal", "unreal_tools"),
                {
                    "name": "get_all_assets_of_type",
                    "signature": "get_all_assets_of_type(type='Skeleton', directory='/Game/')",
                    "docstring": "Return Unreal assets of a specific asset class under a content directory.",
                    "file_path": str(TOOLS_ROOT / "unreal_tools" / "get_skeletons.py"),
                    "kind": "function",
                },
            )

        if keywords:
            try:
                from tech_connector.knowledge.search import search_project_symbols_by_keywords

                with contextlib.redirect_stdout(io.StringIO()):
                    results = search_project_symbols_by_keywords(keywords)
                for result in results:
                    for host in hosts:
                        domain = domains.get(host, DEFAULT_TOOL_DOMAINS.get(host, ""))
                        file_path = result.get("file_path") or ""
                        is_supported_ext = file_path.endswith(
                            (".py", ".cs", ".cpp", ".h", ".js")
                        )
                        if domain and (
                            domain.lower() in file_path.lower() or is_supported_ext
                        ):
                            add_candidate(host, domain or "project", result)
                    if len(candidates) >= limit:
                        break
            except Exception:
                pass

        limited = candidates[:limit]
        self._dcc_candidate_cache[cache_key] = (now, list(limited))
        return limited

    def get_active_dcc_context_cached(self, max_age: float = 5.0) -> str:
        """Return recent DCC scene context immediately and refresh stale data in the background."""
        now = time.monotonic()
        with self._active_dcc_context_lock:
            cached = self._active_dcc_context_cache
            is_fresh = cached and now - self._active_dcc_context_cache_at <= max_age
            if is_fresh:
                return cached
            if self._active_dcc_context_refreshing:
                return cached
            self._active_dcc_context_refreshing = True

        def refresh():
            context = ""
            try:
                context = self.get_active_dcc_context()
            finally:
                with self._active_dcc_context_lock:
                    self._active_dcc_context_cache = context
                    self._active_dcc_context_cache_at = time.monotonic()
                    self._active_dcc_context_refreshing = False

        thread = threading.Thread(
            target=refresh, name="dcc-context-refresh", daemon=True
        )
        thread.start()
        return cached

    def get_active_dcc_context(self) -> str:
        """Query active DCC host bridges in the background to supply real-time context to the LLM."""
        context_parts = []

        # 1. Maya
        try:
            maya_port = self.maya.find_port()
            if maya_port:
                ok_file, file_res = self.maya.execute(
                    "import maya.cmds as cmds\nprint(cmds.file(q=True, sceneName=True))",
                    timeout=0.3,
                )
                ok_sel, sel_res = self.maya.execute(
                    "import maya.cmds as cmds\nprint(cmds.ls(sl=True))", timeout=0.3
                )

                parts = ["- Active DCC Host: Maya"]
                if (
                    ok_file
                    and file_res.strip()
                    and "error" not in file_res.lower()
                    and "exception" not in file_res.lower()
                    and "no output" not in file_res.lower()
                ):
                    parts.append(f"  - Active Scene File: {file_res.strip()}")
                if (
                    ok_sel
                    and sel_res.strip()
                    and "error" not in sel_res.lower()
                    and "exception" not in sel_res.lower()
                    and "[]" not in sel_res
                ):
                    parts.append(f"  - Current Selection: {sel_res.strip()}")
                context_parts.append("\n".join(parts))
        except Exception:
            pass

        # 2. Blender
        try:
            blender_port = self.blender.find_port()
            if blender_port:
                ok_file, file_res = self.blender.execute(
                    "import bpy\nprint(bpy.data.filepath)", timeout=0.3
                )
                ok_sel, sel_res = self.blender.execute(
                    "import bpy\nprint([o.name for o in bpy.context.selected_objects])",
                    timeout=0.3,
                )

                parts = ["- Active DCC Host: Blender"]
                if ok_file and file_res.strip() and "error" not in file_res.lower():
                    parts.append(f"  - Active File: {file_res.strip()}")
                if (
                    ok_sel
                    and sel_res.strip()
                    and "error" not in sel_res.lower()
                    and "[]" not in sel_res
                ):
                    parts.append(f"  - Current Selection: {sel_res.strip()}")
                context_parts.append("\n".join(parts))
        except Exception:
            pass

        # 3. Unreal
        try:
            unreal_port = self.unreal.find_port()
            if unreal_port:
                context_parts.append("- Active DCC Host: Unreal Engine (Bridge Active)")
        except Exception:
            pass

        # 4. Unity
        try:
            unity_port = self.unity.find_port()
            if unity_port:
                context_parts.append("- Active DCC Host: Unity (Bridge Active)")
        except Exception:
            pass

        if context_parts:
            return "Active DCC Context:\n" + "\n\n".join(context_parts)
        return ""

    def build_dcc_tool_context(self, text: str, route_task_role: str = "") -> str:
        hosts = self.detect_dcc_hosts(text, route_task_role=route_task_role)
        if not hosts:
            return ""

        domains = self._plugin_tool_domains()
        candidates = self.find_dcc_tool_candidates(
            text, route_task_role=route_task_role
        )
        lines = [
            "DCC routing context:",
            "The user is asking about a bridged DCC host. Prefer the host's internal tool package when it matches the task; otherwise use safe host-native Python/C# through the bridge.",
            "Do not invent internal function names. If no listed candidate fits, search the local knowledge tools for the host tool domain before calling a package function.",
            "Ask for missing object names, paths, or destructive confirmation instead of guessing.",
            "Host tool domains:",
        ]
        for host in hosts:
            domain = domains.get(host, DEFAULT_TOOL_DOMAINS.get(host, ""))
            if domain:
                lines.append(f"- {host}: {domain}")
        try:
            from tech_connector.services.task_playbook_service import task_playbook_context

            for host in hosts:
                playbook = task_playbook_context(text, host=host, limit=1)
                if playbook:
                    lines.extend(["", playbook])
                    break
        except Exception:
            pass
        if candidates:
            lines.append("Candidate internal functions:")
            for candidate in candidates:
                details = candidate["signature"] or candidate["function"]
                doc = (
                    f" - {candidate['docstring'][:180]}"
                    if candidate["docstring"]
                    else ""
                )
                lines.append(
                    f"- {candidate['host']} {candidate['function']} {details}{doc}"
                )
        return "\n".join(lines)

    def unreal_natural_asset_query(
        self, text: str
    ) -> "tuple[str, str, list, dict] | None":
        """Detect Unreal intent from natural-language text.

        Delegates to bridges.unreal.unreal_intent_parser which uses a
        confidence-scored, vocabulary-driven approach that:
          - Works WITHOUT the word "unreal" in the prompt
          - Covers Control Rig, Niagara, Motion Matching and 15+ asset types
          - Blocks purely educational queries (explain / how-do-I)
          - Returns None for scan/debug/compile (caller should route those
            to their dedicated direct_unreal_* methods instead)
        """
        intent = _uip.parse(text)
        if intent is None:
            return None
        return _uip.to_command_router_result(intent)

    def unreal_detect_intent(self, text: str) -> "_uip.UnrealIntent | None":
        """Return the full UnrealIntent object (for action-type routing)."""
        return _uip.parse(text)

    def execute_maya_from_text(self, text: str) -> tuple[str, bool, str]:
        """
        Parse and execute Maya input.
        Returns (label, success, result).
        """
        text = text.strip()
        try:
            if IntentRouter.is_maya_json(text):
                data = json.loads(text)
                label = "Maya Function"
                ok, result = self.maya.call_function(
                    data["function"],
                    args=data.get("args", []),
                    kwargs=data.get("kwargs", {}),
                )
            else:
                label = "Maya Execute"
                ok, result = self.maya.execute(text)
            return label, ok, result
        except Exception as e:
            return "Maya Direct", False, str(e)

    def maya_natural_language_to_python(
        self, text: str, require_maya_word: bool = True
    ) -> str:
        """Translate common natural Maya scene commands into maya.cmds Python."""
        q = (text or "").strip().lower()
        if not q or (require_maya_word and "maya" not in q):
            return ""

        def name_arg(default_name: str) -> str:
            m = re.search(
                r"\b(?:named|called|name(?:d)? it)\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?",
                text,
                re.IGNORECASE,
            )
            return m.group(1) if m else default_name

        def split_object_list(raw: str) -> list[str]:
            cleaned = re.sub(
                r"\b(objects?|transforms?|nodes?)\b", "", raw, flags=re.IGNORECASE
            )
            cleaned = re.sub(
                r"\b(?:without|no)\s+offset\b", "", cleaned, flags=re.IGNORECASE
            )
            cleaned = cleaned.replace(" and ", ",")
            names = []
            for token in re.split(r"[,\s]+", cleaned):
                token = token.strip(" \t\r\n'\"`")
                if not token:
                    continue
                if token.lower() in {
                    "the",
                    "to",
                    "with",
                    "a",
                    "an",
                    "maya",
                    "scene",
                    "current",
                }:
                    continue
                if re.match(r"^[A-Za-z_][A-Za-z0-9_:|.-]*$", token):
                    names.append(token)
            return names

        def constraint_command() -> str:
            constraint_types = [
                ("parent", "parentConstraint"),
                ("orient", "orientConstraint"),
                ("point", "pointConstraint"),
                ("scale", "scaleConstraint"),
                ("aim", "aimConstraint"),
            ]
            command = ""
            for keyword, maya_command in constraint_types:
                if re.search(
                    rf"\b{keyword}\s+(?:constraint|constrain|constrian|consrain)\b", q
                ):
                    command = maya_command
                    break
            if not command:
                return ""

            # Natural phrasing: "parent constrain pelvis_ctrl to x, y, and z objects".
            match = re.search(
                r"\b(?:parent|orient|point|scale|aim)\s+(?:constraint|constrain|constrian|consrain)\s+"
                r"(?:the\s+)?(?P<driven>[A-Za-z_][A-Za-z0-9_:|.-]*)\s+to\s+(?P<targets>.+)$",
                text,
                re.IGNORECASE,
            )
            if not match:
                return ""

            driven = match.group("driven")
            targets = split_object_list(match.group("targets"))
            if not driven or not targets:
                return ""

            maintain_offset = "no offset" not in q and "without offset" not in q
            return (
                "import maya.cmds as cmds\n"
                f"targets = {targets!r}\n"
                f"driven = {driven!r}\n"
                "missing = [obj for obj in targets + [driven] if not cmds.objExists(obj)]\n"
                "if missing:\n"
                "    raise RuntimeError('Missing Maya object(s): {}'.format(', '.join(missing)))\n"
                f"constraint = cmds.{command}(targets, driven, maintainOffset={maintain_offset!r})\n"
                "cmds.select(driven, replace=True)\n"
                "print(constraint[0] if constraint else 'Constraint created')"
            )

        constraint_code = constraint_command()
        if constraint_code:
            return constraint_code

        create_requested = any(
            word in q for word in ("create", "make", "add", "spawn", "build")
        )
        if create_requested:
            primitives = [
                ("polycube", "polyCube", "cube"),
                ("cube", "polyCube", "cube"),
                ("sphere", "polySphere", "sphere"),
                ("cylinder", "polyCylinder", "cylinder"),
                ("cone", "polyCone", "cone"),
                ("plane", "polyPlane", "plane"),
                ("torus", "polyTorus", "torus"),
            ]
            for keyword, command, default_name in primitives:
                if keyword in q:
                    obj_name = name_arg(default_name)
                    return (
                        "import maya.cmds as cmds\n"
                        f"created = cmds.{command}(name={obj_name!r})\n"
                        "cmds.select(created[0], replace=True)\n"
                        "print(created[0])"
                    )

        if any(
            phrase in q
            for phrase in (
                "delete selected",
                "delete selection",
                "remove selected",
                "remove selection",
            )
        ):
            return (
                "import maya.cmds as cmds\n"
                "selection = cmds.ls(selection=True)\n"
                "cmds.delete(selection)\n"
                "print('Deleted: {}'.format(selection))"
            )

        if any(
            phrase in q
            for phrase in (
                "list objects",
                "show objects",
                "scene objects",
                "what objects",
            )
        ):
            return "import maya.cmds as cmds\nprint(cmds.ls(type='transform')[:500])"

        if any(
            phrase in q
            for phrase in ("frame selected", "frame selection", "zoom selected")
        ):
            return "import maya.cmds as cmds\ncmds.viewFit()\nprint('Framed selection')"

        return ""

    def execute_unreal_from_text(self, text: str) -> tuple[str, bool, str]:
        text = text.strip()
        try:
            fn, args, kwargs = self.unreal.parse_input(text)
            ok, result = self.unreal.call(fn, args=args, kwargs=kwargs)
            return "Unreal Direct", ok, result
        except Exception as e:
            return "Unreal Direct", False, str(e)

    def execute_blender_from_text(self, text: str) -> tuple[str, bool, str]:
        """
        Parse and execute Blender input.
        Returns (label, success, result).
        """
        text = text.strip()
        try:
            mode, data = self.blender.parse_input(text)
            if mode == "function":
                label = "Blender Function"
                ok, result = self.blender.call_function(
                    data["function"],
                    args=data.get("args", []),
                    kwargs=data.get("kwargs", {}),
                )
            else:
                label = "Blender Execute"
                ok, result = self.blender.execute(text)
            return label, ok, result
        except Exception as e:
            return "Blender Direct", False, str(e)

    def execute_motionbuilder_from_text(self, text: str) -> tuple[str, bool, str]:
        """Parse and execute MotionBuilder Python or a JSON function payload."""
        text = text.strip()
        try:
            mode, data = self.motionbuilder.parse_input(text)
            if mode == "function":
                label = "MotionBuilder Function"
                ok, result = self.motionbuilder.call_function(
                    data["function"],
                    args=data.get("args", []),
                    kwargs=data.get("kwargs", {}),
                )
            else:
                label = "MotionBuilder Execute"
                ok, result = self.motionbuilder.execute(text)
            return label, ok, result
        except Exception as e:
            return "MotionBuilder Direct", False, str(e)

    def execute_maya_preset(self, preset: str) -> tuple[str, bool, str]:
        presets = {
            "selection": ("Maya Selection", self.maya.get_selection_code()),
            "file": ("Maya File", self.maya.get_current_file_code()),
            "objects": ("Maya Scene Objects", self.maya.get_scene_objects_code()),
        }
        if preset not in presets:
            return preset, False, f"Unknown Maya preset: {preset}"
        label, code = presets[preset]
        ok, result = self.maya.execute(code)
        return label, ok, result

    def execute_unreal_preset(self, preset: str) -> tuple[str, bool, str]:
        presets = {
            "skeletons": (
                "Unreal Skeletons",
                "unreal_tools.get_skeletons.get_all_assets_of_type",
                ["Skeleton", "/Game/"],
                {},
            ),
            "meshes": (
                "Unreal Static Meshes",
                "unreal_tools.get_skeletons.get_all_assets_of_type",
                ["StaticMesh", "/Game/"],
                {},
            ),
        }
        if preset not in presets:
            return preset, False, f"Unknown Unreal preset: {preset}"
        label, fn, args, kwargs = presets[preset]
        ok, result = self.unreal.call(fn, args=args, kwargs=kwargs)
        return label, ok, result

    def plan_unreal_request(
        self,
        text: str,
        *,
        project_root: str | None = None,
        settings: dict | None = None,
    ) -> dict:
        scanner = UnrealScanner(project_root=project_root)
        try:
            if getattr(
                scanner, "should_use_fast_path", None
            ) and scanner.should_use_fast_path(text or ""):
                context = scanner.build_unreal_context_fast(text or "unreal request")
            else:
                context = scanner.build_unreal_context(text or "unreal request")
        except Exception as exc:
            context = {
                "summary": f"context unavailable: {exc}",
                "recommended_model": "strong_reasoning",
            }
        plan = build_unreal_execution_plan(
            text, context=context, settings=settings or {}
        )
        if plan.get("high_risk_graph_rewrite"):
            try:
                from tech_connector.services.unreal.rewrite_plan_service import build_rewrite_plan

                asset_path = (plan.get("affected_assets") or [""])[0]
                graph_snapshot = {}
                if asset_path:
                    graph_snapshot = self.unreal.inspect_blueprint_graph(asset_path)
                plan["rewrite_plan"] = build_rewrite_plan(
                    text, context=context, graph_snapshot=graph_snapshot
                )
            except Exception as exc:
                plan.setdefault("warnings", []).append(
                    f"rewrite plan graph introspection failed: {exc}"
                )
        plan["context"] = context
        plan["explanation"] = explain_unreal_execution_plan(plan)
        return plan

    def execute_unreal_operation(
        self, operation_key: str, params=None
    ) -> tuple[str, bool, str]:
        params = params or {}
        auto_open_path = None
        for p_key in ("asset_path", "blueprint_path", "target_path"):
            if p_key in params and isinstance(params[p_key], str) and params[p_key]:
                is_read_only = any(term in operation_key.lower() for term in ("inspect", "scan", "health", "read", "get", "query"))
                if not is_read_only and operation_key != "navigation.open_asset":
                    auto_open_path = params[p_key]
                    break

        label, ok, result = self._execute_unreal_operation_impl(operation_key, params)

        if ok and auto_open_path:
            try:
                from tech_connector.services.unreal.unreal_operation_service import normalize_unreal_package_path
                norm_path = normalize_unreal_package_path(auto_open_path, default_name="Asset")
                self.unreal.execute_python(
                    f"import unreal; unreal.get_editor_subsystem(unreal.AssetEditorSubsystem).open_editor_for_assets([unreal.EditorAssetLibrary.load_asset({norm_path!r})])",
                    timeout=5
                )
            except Exception:
                pass

        return label, ok, result

    def _execute_unreal_operation_impl(
        self, operation_key: str, params=None
    ) -> tuple[str, bool, str]:
        params = params or {}
        try:
            from tech_connector.services.unreal.unreal_operation_service import normalize_unreal_package_path
            for p_key in ("asset_path", "target_path", "blueprint_path"):
                if p_key in params and isinstance(params[p_key], str):
                    default_name = "NE_AIStudioEmitter" if "niagara" in operation_key else ("BP_NewBlueprint" if "blueprint" in operation_key else "Asset")
                    params[p_key] = normalize_unreal_package_path(params[p_key], default_name=default_name)
        except Exception:
            pass
        try:
            canonical_plugin_operations = {
                "niagara.list_module_inputs",
                "niagara.set_user_parameter",
                "niagara.set_renderer_property",
                "niagara.set_module_input",
                "niagara.delete_emitter",
                "niagara.set_emitter_property",
                "physics.list_bodies",
                "physics.list_constraints",
                "physics.set_body_property",
                "physics.set_constraint_property",
                "physics.set_profile_property",
                "physics.list_profiles",
                "physics.add_profile",
                "physics.remove_profile",
            }
            if operation_key in canonical_plugin_operations:
                payload = unreal_operation_payload(operation_key, params)
                ok, result = self.unreal.call(
                    payload["function"],
                    args=payload["args"],
                    kwargs=payload["kwargs"],
                    retry_safe=not bool(payload.get("mutates_project")),
                    operation=operation_key,
                )
                if ok and isinstance(result, str):
                    try:
                        structured_result = json.loads(result)
                    except Exception:
                        structured_result = None
                    if isinstance(structured_result, dict) and structured_result.get("ok") is False:
                        ok = False
                return payload["label"], ok, result

            if operation_key == "blueprint.dynamic_inspect":
                asset_name = params.get("asset_name") or params.get("asset_path") or ""
                code = self._unreal_blueprint_dynamic_inspect_code(
                    asset_name,
                    allow_cpp_bridge=bool(params.get("allow_cpp_bridge", False)),
                )
                response = self.unreal.execute_python(
                    code, timeout=params.get("timeout", 45), reset_globals=True
                )
                return (
                    "Unreal Blueprint Dynamic Inspect",
                    bool(response.get("ok")),
                    json.dumps(response, indent=2, default=str),
                )

            if operation_key == "niagara.inspect_system":
                asset_path = params.get("asset_path") or ""
                code = f"""
import json
import unreal

asset_path = {asset_path!r}
out = {{
    "ok": False,
    "operation": "niagara.inspect_system",
    "asset_path": asset_path,
    "asset_class": None,
    "emitters": [],
    "user_parameters": [],
    "renderers": [],
    "module_inputs": [],
    "warnings": [],
    "errors": [],
}}

try:
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        out["errors"].append("Niagara asset could not be loaded")
    else:
        try:
            out["asset_class"] = asset.get_class().get_name()
        except Exception:
            pass
        handles = []
        for attr in ("emitter_handles", "emitters"):
            try:
                handles = asset.get_editor_property(attr)
                if handles:
                    break
            except Exception:
                pass
        for handle in handles or []:
            handle_info = {"name": None, "renderers": [], "module_inputs": []}
            try:
                handle_info["name"] = str(handle.get_name())
            except Exception:
                handle_info["name"] = str(handle)
            inst = None
            try:
                inst = handle.get_editor_property("instance")
            except Exception:
                pass
            if inst:
                for prop in ("renderer_properties", "renderers"):
                    try:
                        renderers = inst.get_editor_property(prop)
                        if renderers:
                            for idx, renderer in enumerate(renderers):
                                renderer_name = None
                                renderer_class = None
                                try:
                                    renderer_name = str(renderer.get_name())
                                except Exception:
                                    renderer_name = str(renderer)
                                try:
                                    renderer_class = renderer.get_class().get_name()
                                except Exception:
                                    pass
                                handle_info["renderers"].append({"index": idx, "name": renderer_name, "class": renderer_class})
                            break
                    except Exception:
                        pass
                for prop in ("scripts", "script_props", "module_scripts"):
                    try:
                        scripts = inst.get_editor_property(prop)
                        if scripts:
                            for script in scripts:
                                script_name = None
                                try:
                                    script_name = str(script.get_name())
                                except Exception:
                                    script_name = str(script)
                                handle_info["module_inputs"].append({"module": script_name})
                            break
                    except Exception:
                        pass
            out["emitters"].append(handle_info)
        for attr in ("exposed_parameters", "user_parameters"):
            try:
                store = asset.get_editor_property(attr)
                if store:
                    out["user_parameters"].append(attr)
            except Exception:
                pass
        out["renderers"] = [r for e in out["emitters"] for r in (e.get("renderers") or [])]
        out["module_inputs"] = [m for e in out["emitters"] for m in (e.get("module_inputs") or [])]
        out["ok"] = True
except Exception as exc:
    out["errors"].append(str(exc))

print(json.dumps(out))
"""
                response = self.unreal.execute_python(
                    code, timeout=params.get("timeout", 20), reset_globals=True
                )
                return (
                    "Unreal Inspect Niagara System",
                    bool(response.get("ok")),
                    json.dumps(response, indent=2, default=str),
                )

            if operation_key == "niagara.attach_editable_character_fx":
                blueprint_path = params.get("blueprint_path") or "BP_ThirdPersonCharacter"
                source_system_path = params.get("source_system_path") or "/Game/Variant_Platforming/VFX/NS_Jump_Trail"
                system_path = params.get("system_path") or "/Game/AIStudio/Prototypes/Niagara/NS_AIStudio_CharacterAura"
                component_name = params.get("component_name") or "AIStudio_AuraFX"
                socket_name = params.get("socket_name") or "spine_03"
                tunables = dict(params.get("parameters") or {})
                extra_components = list(params.get("extra_components") or [])
                save = bool(params.get("save", True))
                code = f"""
import json
import unreal

blueprint_path = {blueprint_path!r}
source_system_path = {source_system_path!r}
system_path = {system_path!r}
component_name = {component_name!r}
socket_name = {socket_name!r}
tunables = json.loads({json.dumps(tunables, default=str)!r})
extra_components = json.loads({json.dumps(extra_components, default=str)!r})
save = {save!r}
out = {{
    "ok": False,
    "operation": "niagara.attach_editable_character_fx",
    "blueprint_path": blueprint_path,
    "resolved_blueprint_path": "",
    "source_system_path": source_system_path,
    "system_path": system_path,
    "component_name": component_name,
    "socket_name": socket_name,
    "system_created": False,
    "system_reused": False,
    "warnings": [],
    "errors": [],
    "actions": [],
    "validation": {{"blueprint_loaded": False, "system_exists": False}},
    "systems": [],
}}

def resolve_asset_path(value, wanted_class=""):
    text = str(value or "").strip().strip("'\\\"")
    if not text:
        return ""
    if text.startswith("/"):
        direct = text.split(".", 1)[0]
        if unreal.EditorAssetLibrary.does_asset_exist(direct):
            return direct
        text = direct.rsplit("/", 1)[-1]
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        for data in registry.get_assets_by_path("/Game", recursive=True) or []:
            name = str(data.asset_name)
            path = str(data.package_name)
            try:
                cls = str(data.asset_class_path.asset_name)
            except Exception:
                cls = str(getattr(data, "asset_class", ""))
            if name.lower() == text.lower() or path.lower().endswith("/" + text.lower()):
                if not wanted_class or wanted_class.lower() in cls.lower() or "blueprint" in cls.lower():
                    return path
    except Exception as exc:
        out["warnings"].append("asset registry resolve failed: " + str(exc))
    return "/Game/" + text.lstrip("/")

try:
    out["resolved_blueprint_path"] = resolve_asset_path(blueprint_path, wanted_class="Blueprint")
    bp = unreal.EditorAssetLibrary.load_asset(out["resolved_blueprint_path"])
    out["validation"]["blueprint_loaded"] = bool(bp)
    if not bp:
        out["errors"].append("Blueprint could not be loaded: " + out["resolved_blueprint_path"])
    else:
        system_specs = [
            {{"component_name": component_name, "source_system_path": source_system_path, "system_path": system_path, "socket_name": socket_name}}
        ] + list(extra_components or [])
        for spec in system_specs:
            spec_system_path = str(spec.get("system_path") or system_path)
            spec_source_path = str(spec.get("source_system_path") or source_system_path)
            row = {{"component_name": spec.get("component_name"), "system_path": spec_system_path, "source_system_path": spec_source_path, "created": False, "reused": False, "exists": False, "warnings": []}}
            if unreal.EditorAssetLibrary.does_asset_exist(spec_system_path):
                row["reused"] = True
                out["actions"].append("reuse_existing_system:" + spec_system_path)
            else:
                source = unreal.EditorAssetLibrary.load_asset(spec_source_path)
                if source:
                    duplicated = unreal.EditorAssetLibrary.duplicate_asset(spec_source_path, spec_system_path)
                    row["created"] = bool(duplicated)
                    out["actions"].append("duplicate_source_system:" + spec_system_path)
                else:
                    factory_cls = getattr(unreal, "NiagaraSystemFactoryNew", None)
                    system_cls = getattr(unreal, "NiagaraSystem", None)
                    if factory_cls and system_cls:
                        package_path, asset_name = spec_system_path.rsplit("/", 1)
                        duplicated = unreal.AssetToolsHelpers.get_asset_tools().create_asset(asset_name, package_path, system_cls, factory_cls())
                        row["created"] = bool(duplicated)
                        out["actions"].append("create_empty_system:" + spec_system_path)
                    else:
                        row["warnings"].append("No source system and NiagaraSystemFactoryNew unavailable")
            row["exists"] = unreal.EditorAssetLibrary.does_asset_exist(spec_system_path)
            if spec_system_path == system_path:
                out["system_created"] = bool(row["created"])
                out["system_reused"] = bool(row["reused"])
            try:
                asset = unreal.EditorAssetLibrary.load_asset(spec_system_path)
                if asset:
                    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
            except Exception as exc:
                row["warnings"].append("system save warning: " + str(exc))
            out["systems"].append(row)
        out["validation"]["system_exists"] = unreal.EditorAssetLibrary.does_asset_exist(system_path)
        if not all(row.get("exists") for row in out["systems"]):
            out["errors"].append("One or more requested Niagara systems could not be created or loaded")
except Exception as exc:
    out["errors"].append(str(exc))

print(json.dumps(out))
"""
                response = self.unreal.execute_python(
                    code, timeout=params.get("timeout", 45), reset_globals=True
                )
                structured = response.get("data") if isinstance(response, dict) else {}
                if not isinstance(structured, dict):
                    structured = {}
                result = {
                    "creation": structured,
                    "creation_response": response,
                    "component": None,
                    "extra_components": [],
                    "variables": [],
                    "scan": None,
                    "niagara_stack_synthesis": None,
                    "params": params,
                }
                ok = bool(response.get("ok")) and bool(structured.get("validation", {}).get("system_exists"))
                if ok:
                    resolved_blueprint_path = (
                        structured.get("resolved_blueprint_path")
                        or blueprint_path
                    )
                    component_specs = [
                        {
                            "component_name": component_name,
                            "system_path": system_path,
                            "socket_name": socket_name,
                        }
                    ] + [
                        {
                            "component_name": str(item.get("component_name") or "AIStudio_ExtraFX"),
                            "system_path": str(item.get("system_path") or system_path),
                            "socket_name": str(item.get("socket_name") or socket_name),
                        }
                        for item in extra_components
                    ]
                    for index, spec in enumerate(component_specs):
                        component_params = {
                            "blueprint_path": resolved_blueprint_path,
                            "component_class": "NiagaraComponent",
                            "component_name": spec["component_name"],
                            "asset_path": spec["system_path"],
                            "attach_bone": spec["socket_name"],
                            "socket_name": spec["socket_name"],
                            "user_parameters": tunables,
                            "save": False,
                        }
                        label, comp_ok, comp_result = self.execute_unreal_operation(
                            "blueprint.add_component", component_params
                        )
                        component_row = {
                            "label": label,
                            "ok": comp_ok,
                            "params": component_params,
                            "result": comp_result,
                        }
                        if index == 0:
                            result["component"] = component_row
                        else:
                            result["extra_components"].append(component_row)
                        ok = ok and comp_ok
                    def infer_fx_variable_type(value):
                        if isinstance(value, bool):
                            return "boolean"
                        if isinstance(value, (int, float)):
                            return "real"
                        if isinstance(value, (list, tuple)):
                            if len(value) == 4:
                                return "linearcolor"
                            if len(value) == 3:
                                return "vector"
                        return ""

                    variable_specs = [
                        ("FX_Color", "linearcolor", tunables.get("FX_Color", [0.2, 0.85, 1.0])),
                        ("FX_SecondaryColor", "linearcolor", tunables.get("FX_SecondaryColor", [0.75, 0.15, 1.0])),
                        ("FX_Intensity", "real", tunables.get("FX_Intensity", 6.0)),
                        ("FX_SpawnRate", "real", tunables.get("FX_SpawnRate", 160.0)),
                        ("FX_Radius", "real", tunables.get("FX_Radius", 72.0)),
                        ("FX_Lifetime", "real", tunables.get("FX_Lifetime", 1.25)),
                        ("FX_PulseSpeed", "real", tunables.get("FX_PulseSpeed", 2.5)),
                        ("FX_TrailLength", "real", tunables.get("FX_TrailLength", 450.0)),
                        ("FX_RingSpeed", "real", tunables.get("FX_RingSpeed", 3.5)),
                        ("FX_NoiseAmount", "real", tunables.get("FX_NoiseAmount", 0.65)),
                        ("FX_GroundSparks", "real", tunables.get("FX_GroundSparks", 1.0)),
                        ("FX_AccelerationBoost", "real", tunables.get("FX_AccelerationBoost", 2.0)),
                        ("FX_AutoActivate", "boolean", tunables.get("FX_AutoActivate", True)),
                        ("FX_AttachSocket", "name", tunables.get("FX_AttachSocket", socket_name)),
                        ("FX_AttachOffset", "vector", tunables.get("FX_AttachOffset", [0.0, 0.0, 45.0])),
                    ]
                    seen_variable_names = {name for name, _type_name, _value in variable_specs}
                    for tunable_name, tunable_value in sorted(tunables.items()):
                        if tunable_name in seen_variable_names or not str(tunable_name).startswith("FX_"):
                            continue
                        inferred_type = infer_fx_variable_type(tunable_value)
                        if inferred_type:
                            variable_specs.append((str(tunable_name), inferred_type, tunable_value))
                            seen_variable_names.add(str(tunable_name))
                    for variable_name, variable_type, default_value in variable_specs:
                        label, var_ok, var_result = self.execute_unreal_operation(
                            "blueprint.create_variable",
                            {
                                "blueprint_path": resolved_blueprint_path,
                                "variable_name": variable_name,
                                "variable_type": variable_type,
                                "default_value": default_value,
                                "save": False,
                            },
                        )
                        result["variables"].append(
                            {
                                "label": label,
                                "ok": var_ok,
                                "variable_name": variable_name,
                                "variable_type": variable_type,
                                "default_value": default_value,
                                "result": var_result,
                            }
                        )
                    binding_specs = [
                        {
                            "variable_name": variable_name,
                            "variable_type": variable_type,
                            "parameter_name": "User." + variable_name,
                        }
                        for variable_name, variable_type, _default_value in variable_specs
                        if variable_type in {"real", "bool", "boolean", "linearcolor"}
                    ]
                    binding_component_specs = [
                        {
                            "component_name": component_name,
                            "system_path": system_path,
                            "socket_name": socket_name,
                        }
                    ] + [
                        {
                            "component_name": str(item.get("component_name") or "AIStudio_ExtraFX"),
                            "system_path": str(item.get("system_path") or system_path),
                            "socket_name": str(item.get("socket_name") or socket_name),
                        }
                        for item in extra_components
                    ]
                    binding_code = f"""
import json
import re
import unreal

bp_path = {resolved_blueprint_path!r}
component_specs = json.loads({json.dumps(binding_component_specs, default=str)!r})
binding_specs = json.loads({json.dumps(binding_specs, default=str)!r})
save = {save!r}
out = {{
    "ok": False,
    "operation": "blueprint.bind_niagara_user_parameters",
    "bp_path": bp_path,
    "components": [],
    "bindings_created": [],
    "bindings_skipped": [],
    "warnings": [],
    "errors": [],
    "validation": {{"beginplay_found": False, "sequence_inserted": False, "compiled": False, "saved": False}},
}}

def sanitized(value):
    return "".join(ch for ch in str(value or "") if ch.isalnum())

def pin(node, wanted):
    if not node:
        return None
    target = str(wanted or "").replace(" ", "").lower()
    for item in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
        name = str(unreal.BlueprintGraphPinLibrary.get_pin_name(item))
        if name.replace(" ", "").lower() == target:
            return item
    return None

def output_pin(node):
    if not node:
        return None
    try:
        result = unreal.BlueprintEditorLibrary.find_result_pin(node)
        if result:
            return result
    except Exception:
        pass
    ignored = {"execute", "then", "outputdelegate"}
    try:
        for item in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
            name = str(unreal.BlueprintGraphPinLibrary.get_pin_name(item)).replace(" ", "").lower()
            if name and name not in ignored:
                return item
    except Exception:
        pass
    return None

def connect(src, dst, label):
    if not src or not dst:
        out["warnings"].append("Missing pin for " + label)
        return False
    try:
        ok = bool(unreal.BlueprintGraphPinLibrary.try_create_connection(src, dst))
        if not ok:
            src.make_link_to(dst)
            ok = True
        return ok
    except Exception as exc:
        out["warnings"].append("Connection failed " + label + ": " + str(exc))
        return False

def set_pin_text(pin_obj, value, label):
    if not pin_obj:
        out["warnings"].append("Missing value pin " + label)
        return False
    try:
        ok = bool(unreal.BlueprintGraphPinLibrary.set_pin_value(pin_obj, str(value)))
        try:
            pin_obj.default_value = str(value)
        except Exception:
            pass
        return ok
    except Exception:
        try:
            pin_obj.default_value = str(value)
            return True
        except Exception as exc:
            out["warnings"].append("Set pin value failed " + label + ": " + str(exc))
            return False

def action_for_type(type_name):
    t = str(type_name or "").lower()
    if t in {"real", "float", "double"}:
        return "Niagara|SetNiagaraVariable(Float)"
    if t in {"bool", "boolean"}:
        return "Niagara|SetNiagaraVariable(Bool)"
    if t in {"linearcolor", "linear_color", "color"}:
        return "Niagara|SetNiagaraVariable(LinearColor)"
    return ""

try:
    bp = unreal.EditorAssetLibrary.load_asset(bp_path)
    if not bp:
        out["errors"].append("Blueprint could not be loaded")
    else:
        graph = unreal.BlueprintGraphEditor.get_graph_editor_by_name(bp, "EventGraph")
        if not graph:
            out["errors"].append("EventGraph could not be loaded")
        else:
            existing_marker_nodes = [
                node
                for node in graph.list_all_nodes() or []
                if str(node.get_name()).startswith("AIStudio_FXBind_")
            ]
            existing_sequence = None
            existing_setters = []
            existing_complete = True
            for marker_node in existing_marker_nodes:
                title = str(unreal.BlueprintEditorLibrary.get_node_title(marker_node))
                if title == "Sequence":
                    existing_sequence = marker_node
                    continue
                if "Set Niagara Variable" in title:
                    existing_setters.append(marker_node)
                    for required_pin in ("self", "InValue"):
                        required = pin(marker_node, required_pin)
                        if not required or len(list(unreal.BlueprintGraphPinLibrary.list_connected_pins(required) or [])) == 0:
                            existing_complete = False
                    name_pin = pin(marker_node, "InVariableName")
                    try:
                        if not name_pin or not str(name_pin.default_value):
                            existing_complete = False
                    except Exception:
                        existing_complete = False
            if existing_marker_nodes and existing_setters and existing_complete:
                out["bindings_skipped"].append("Existing AIStudio_FXBind graph already has connected setter nodes.")
                out["ok"] = True
            else:
                if existing_setters:
                    try:
                        graph.remove_nodes(existing_setters)
                        out["bindings_skipped"].append("Removed incomplete AIStudio_FXBind setter nodes before regeneration.")
                    except Exception as exc:
                        out["warnings"].append("Could not remove incomplete generated setters: " + str(exc))
                nodes = list(graph.list_all_nodes() or [])
                begin = None
                for node in nodes:
                    title = str(unreal.BlueprintEditorLibrary.get_node_title(node))
                    if title == "Event BeginPlay":
                        begin = node
                        break
                if begin is None:
                    begin = graph.create_node_from_name("AddEvent|EventBeginPlay", unreal.Vector2D(0.0, -120.0), [], None)
                out["validation"]["beginplay_found"] = bool(begin)
                begin_then = pin(begin, "then")
                old_links = list(unreal.BlueprintGraphPinLibrary.list_connected_pins(begin_then) or []) if begin_then else []
                sequence = existing_sequence or graph.create_node_from_name("Utilities|FlowControl|Sequence", unreal.Vector2D(280.0, -60.0), [], None)
                if sequence:
                    try:
                        sequence.rename("AIStudio_FXBind_Sequence")
                    except Exception:
                        pass
                if existing_sequence:
                    try:
                        unreal.BlueprintGraphPinLibrary.break_pin_links(pin(sequence, "then_1"))
                    except Exception:
                        pass
                    out["validation"]["sequence_inserted"] = True
                elif begin_then and sequence:
                    try:
                        unreal.BlueprintGraphPinLibrary.break_pin_links(begin_then)
                    except Exception:
                        pass
                    connect(begin_then, pin(sequence, "execute"), "BeginPlay to FX binding sequence")
                    for old in old_links:
                        connect(pin(sequence, "then_0"), old, "Preserve previous BeginPlay chain")
                    out["validation"]["sequence_inserted"] = True
                chain_exec = pin(sequence, "then_1") if sequence else begin_then
                y = 140.0
                for comp_index, comp in enumerate(component_specs):
                    comp_name = str(comp.get("component_name") or "")
                    comp_action = "Variables|Default|Get" + sanitized(comp_name)
                    comp_get = graph.create_node_from_name(comp_action, unreal.Vector2D(520.0 + comp_index * 40.0, y), [], None)
                    comp_pin = output_pin(comp_get)
                    comp_row = {{"component_name": comp_name, "getter_created": bool(comp_get), "bindings": []}}
                    for bind_index, spec in enumerate(binding_specs):
                        setter_action = action_for_type(spec.get("variable_type"))
                        var_name = str(spec.get("variable_name") or "")
                        if not setter_action or not var_name:
                            continue
                        var_action = "Variables|Default|Get" + sanitized(var_name)
                        var_get = graph.create_node_from_name(var_action, unreal.Vector2D(840.0 + bind_index * 18.0, y + bind_index * 96.0), [], None)
                        setter = graph.create_node_from_name(setter_action, unreal.Vector2D(1180.0 + bind_index * 18.0, y + bind_index * 96.0), [comp_pin] if comp_pin else [], None)
                        row = {{
                            "component_name": comp_name,
                            "variable_name": var_name,
                            "parameter_name": spec.get("parameter_name"),
                            "setter_action": setter_action,
                            "getter_created": bool(var_get),
                            "setter_created": bool(setter),
                            "exec_connected": False,
                            "self_connected": False,
                            "value_connected": False,
                            "name_set": False,
                        }}
                        if setter:
                            try:
                                setter.rename("AIStudio_FXBind_" + sanitized(comp_name) + "_" + sanitized(var_name))
                            except Exception:
                                pass
                            row["exec_connected"] = connect(chain_exec, pin(setter, "execute"), "exec " + comp_name + " " + var_name)
                            row["self_connected"] = connect(comp_pin, pin(setter, "self"), "self " + comp_name + " " + var_name)
                            row["name_set"] = set_pin_text(pin(setter, "InVariableName"), spec.get("parameter_name"), "name " + var_name)
                            row["value_connected"] = connect(output_pin(var_get), pin(setter, "InValue"), "value " + var_name)
                            chain_exec = pin(setter, "then") or chain_exec
                        comp_row["bindings"].append(row)
                        out["bindings_created"].append(row)
                    out["components"].append(comp_row)
                    y += max(1, len(binding_specs)) * 120.0 + 160.0
                try:
                    out["validation"]["compiled"] = bool(unreal.BlueprintEditorLibrary.compile_blueprint(bp))
                except Exception as exc:
                    out["warnings"].append("compile warning: " + str(exc))
                if save:
                    try:
                        out["validation"]["saved"] = bool(unreal.EditorAssetLibrary.save_loaded_asset(bp, False))
                    except Exception as exc:
                        out["warnings"].append("save warning: " + str(exc))
                out["ok"] = bool(out["bindings_created"]) and all(
                    item.get("setter_created") and item.get("self_connected") and item.get("name_set")
                    for item in out["bindings_created"]
                )
except Exception as exc:
    out["errors"].append(str(exc))

print(json.dumps(out))
"""
                    if bool(params.get("enable_python_graph_binding", False)):
                        result["parameter_binding"] = self.unreal.execute_python(
                            binding_code, timeout=params.get("timeout", 90), reset_globals=True
                        )
                        binding_data = (result["parameter_binding"] or {}).get("data") or {}
                        ok = ok and bool(binding_data.get("ok"))
                    elif not bool(params.get("disable_native_graph_binding", False)):
                        native_binding_chunk_size = max(1, int(params.get("native_binding_chunk_size", 2) or 2))
                        native_binding_code = f"""
import json
import unreal

bp_path = {resolved_blueprint_path!r}
component_names = {[item.get("component_name") for item in binding_component_specs]!r}
bindings = json.loads({json.dumps(binding_specs, default=str)!r})
chunk_size = {native_binding_chunk_size!r}
out = {{
    "ok": False,
    "operation": "AIStudioBridgeLibrary.bind_niagara_user_parameters_on_begin_play",
    "bp_path": bp_path,
    "component_names": component_names,
    "requested_binding_count": len(component_names) * len(bindings),
    "binding_count": 0,
    "chunk_size": chunk_size,
    "chunks": [],
    "status": "",
    "errors": [],
    "warnings": [],
}}
try:
    bp = unreal.EditorAssetLibrary.load_asset(bp_path)
    bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
    if not bp:
        out["status"] = "blueprint_not_loaded"
        out["errors"].append("Blueprint could not be loaded")
    elif not bridge or not hasattr(bridge, "bind_niagara_user_parameters_on_begin_play"):
        out["status"] = "native_cpp_binding_unavailable"
        out["errors"].append("AIStudioBridge plugin must be rebuilt/reloaded to expose bind_niagara_user_parameters_on_begin_play")
    else:
        all_ok = True
        for component_name in component_names:
            for start in range(0, len(bindings), chunk_size):
                chunk = bindings[start:start + chunk_size]
                raw = bridge.bind_niagara_user_parameters_on_begin_play(
                    bp,
                    [unreal.Name(str(component_name))],
                    json.dumps(chunk),
                )
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = {{"ok": False, "raw": raw}}
                chunk_ok = bool(parsed.get("ok"))
                all_ok = all_ok and chunk_ok
                out["binding_count"] += int(parsed.get("binding_count") or 0)
                out["chunks"].append({{
                    "component_name": component_name,
                    "start": start,
                    "requested": len(chunk),
                    "ok": chunk_ok,
                    "binding_count": parsed.get("binding_count"),
                    "sample": (parsed.get("bindings_created") or [])[:3],
                    "error": parsed.get("error", ""),
                }})
                if not chunk_ok:
                    out["errors"].append("Native binding chunk failed for " + str(component_name) + " at " + str(start))
                    break
            if not all_ok:
                break
        out["ok"] = bool(all_ok and out["binding_count"] > 0)
        out["status"] = "native_cpp_binding_chunks_executed" if out["ok"] else "native_cpp_binding_chunks_failed"
except Exception as exc:
    out["status"] = "native_cpp_binding_exception"
    out["errors"].append(str(exc))
print(json.dumps(out))
"""
                        result["parameter_binding"] = self.unreal.execute_python(
                            native_binding_code, timeout=params.get("timeout", 90), reset_globals=True
                        )
                        binding_data = (result["parameter_binding"] or {}).get("data") or {}
                        ok = ok and bool(binding_data.get("ok"))
                    else:
                        result["parameter_binding"] = {
                            "ok": False,
                            "status": "native_graph_binding_disabled_by_request",
                            "reason": (
                                "Native graph binding was disabled by parameter. The normal path uses chunked native "
                                "binding unless disable_native_graph_binding is true."
                            ),
                            "binding_count": len(binding_component_specs) * len(binding_specs),
                            "components": [item.get("component_name") for item in binding_component_specs],
                            "parameters": [item.get("parameter_name") for item in binding_specs],
                        }
                    source_mode = str(
                        tunables.get("FX_SourceMode")
                        or tunables.get("FX_SourceStrategy")
                        or ""
                    )
                    source_modes_requiring_stack_synthesis = {
                        "camera_facing_character_outline",
                        "skeletal_mesh_surface",
                        "custom_emitter_source",
                    }
                    if source_mode in source_modes_requiring_stack_synthesis:
                        result["niagara_stack_synthesis"] = {
                            "ok": False,
                            "complete": False,
                            "status": "requires_niagara_source_strategy_stack_synthesis",
                            "source_mode": source_mode,
                            "system_path": system_path,
                            "component_name": component_name,
                            "completed_layers": [
                                "niagara_system_asset_created_or_reused",
                                "blueprint_niagara_component_created",
                                "editable_blueprint_variables_created",
                                "blueprint_variables_bound_to_niagara_user_parameters",
                            ],
                            "remaining_layers": [
                                "author Niagara emitter stack/modules for the requested source strategy",
                                "validate emitted particles originate from the requested source",
                                "read back Niagara module/renderer evidence after compile",
                            ],
                            "reason": (
                                "The current safe implementation wires the Blueprint control surface and User parameters. "
                                "True mesh/custom/camera-outline emitter source behavior requires Niagara stack/module synthesis."
                            ),
                        }
                    save_code = f"""
import json
import unreal

bp_path = {resolved_blueprint_path!r}
save = {save!r}
out = {{"ok": False, "bp_path": bp_path, "compiled": False, "saved": False, "warnings": [], "errors": []}}

try:
    bp = unreal.EditorAssetLibrary.load_asset(bp_path)
    if not bp:
        out["errors"].append("Blueprint could not be loaded")
    else:
        try:
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
            out["compiled"] = True
        except Exception as exc:
            out["warnings"].append("BlueprintEditorLibrary.compile_blueprint failed: " + str(exc))
        if save:
            try:
                out["saved"] = bool(unreal.EditorAssetLibrary.save_loaded_asset(bp, False))
            except Exception as exc:
                out["warnings"].append("save_loaded_asset failed: " + str(exc))
        out["ok"] = bool(out["compiled"] or out["saved"] or not out["errors"])
except Exception as exc:
    out["errors"].append(str(exc))

print(json.dumps(out))
"""
                    result["finalize"] = self.unreal.execute_python(
                        save_code, timeout=params.get("timeout", 45), reset_globals=True
                    )
                    scan_label, scan_ok, scan_result = self.execute_unreal_operation(
                        "blueprint.scan",
                        {
                            "asset_path": resolved_blueprint_path,
                            "include_graphs": False,
                            "include_defaults": True,
                        },
                    )
                    result["scan"] = {"label": scan_label, "ok": scan_ok, "result": scan_result}
                    ok = ok and all(item.get("ok") for item in result["variables"]) and scan_ok
                return (
                    "Unreal Attach Editable Character Niagara FX",
                    bool(ok),
                    json.dumps(result, indent=2, default=str),
                )

            if operation_key == "niagara.create_emitter":
                asset_path = params.get("asset_path") or ""
                template = params.get("template") or "empty_emitter"
                create_kind = (params.get("parameters") or {}).get(
                    "asset_kind"
                ) or "emitter"
                requested_color = (params.get("parameters") or {}).get("requested_color") or ""
                target_blueprint = (params.get("parameters") or {}).get("target_blueprint") or ""
                attach_bone = (params.get("parameters") or {}).get("attach_bone") or ""
                attach_to_selected_actor = bool(
                    (params.get("parameters") or {}).get(
                        "attach_to_selected_actor", False
                    )
                )
                add_to_selected_blueprint = bool(
                    (params.get("parameters") or {}).get(
                        "add_to_selected_blueprint", False
                    )
                )
                code = f"""
import json
import unreal

asset_path = {asset_path!r}
template = {template!r}
create_kind = {create_kind!r}
requested_color = {requested_color!r}
target_blueprint = {target_blueprint!r}
attach_bone = {attach_bone!r}
attach_to_selected_actor = {attach_to_selected_actor!r}
add_to_selected_blueprint = {add_to_selected_blueprint!r}
out = {{
    "ok": False,
    "operation": "niagara.create_emitter",
    "asset_path": asset_path,
    "asset_name": "",
    "asset_kind": create_kind,
    "partial": False,
    "selected_actors": [],
    "selected_assets": [],
    "attached_to_actor": None,
    "selected_blueprint": None,
    "requested_color": requested_color,
    "target_blueprint": target_blueprint,
    "attach_bone": attach_bone,
    "warnings": [],
    "errors": [],
    "validation": {{"asset_exists": False}},
}}

try:
    try:
        actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        out["selected_actors"] = [str(a.get_path_name()) for a in actor_subsystem.get_selected_level_actors() or []]
    except Exception:
        pass
    try:
        selected_assets = unreal.EditorUtilityLibrary.get_selected_assets() or []
        out["selected_assets"] = [str(a.get_path_name()) if hasattr(a, "get_path_name") else str(a) for a in selected_assets]
        for asset in selected_assets:
            try:
                asset_name = str(asset.get_path_name()) if hasattr(asset, "get_path_name") else str(asset)
            except Exception:
                asset_name = str(asset)
            lower_name = asset_name.lower()
            if out["selected_blueprint"] is None and ("bp_" in lower_name or "blueprint" in lower_name):
                out["selected_blueprint"] = asset_name
    except Exception:
        pass

    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        out["warnings"].append("Target asset already exists; returning existing asset.")
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    else:
        package_path, asset_name = asset_path.rsplit("/", 1)
        out["asset_name"] = asset_name
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        asset = None
        if create_kind == "emitter":
            factory = unreal.NiagaraEmitterFactoryNew()
            asset = asset_tools.create_asset(asset_name, package_path, unreal.NiagaraEmitter, factory)
        else:
            factory = unreal.NiagaraSystemFactoryNew()
            asset = asset_tools.create_asset(asset_name, package_path, unreal.NiagaraSystem, factory)
        if not asset:
            out["errors"].append("Niagara asset creation returned null")
        else:
            out["ok"] = True
            try:
                out["asset_name"] = asset.get_name()
            except Exception:
                pass
            try:
                out["asset_path"] = asset.get_path_name()
            except Exception:
                pass
            try:
                unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
            except Exception as save_exc:
                out["warnings"].append("save warning: " + str(save_exc))

    out["validation"]["asset_exists"] = unreal.EditorAssetLibrary.does_asset_exist(asset_path)

    if attach_to_selected_actor and out["selected_actors"]:
        out["warnings"].append("Selected actor attachment for Niagara assets is not yet a first-class safe operation; asset was created only.")
        out["attached_to_actor"] = out["selected_actors"][0]
    if add_to_selected_blueprint and out["selected_blueprint"]:
        out["warnings"].append("Selected Blueprint insertion requested without an explicit target; follow-up composition should provide a target Blueprint path or name.")
except Exception as exc:
    out["errors"].append(str(exc))

print(json.dumps(out))
"""
                response = self.unreal.execute_python(
                    code, timeout=params.get("timeout", 45), reset_globals=True
                )
                followups = []
                created_ok = bool(response.get("ok"))
                created_path = asset_path
                response_data = response.get("data") if isinstance(response, dict) else None
                if isinstance(response_data, dict):
                    created_path = response_data.get("asset_path") or created_path
                    created_ok = bool(response_data.get("ok")) or created_ok
                if created_ok and requested_color:
                    for op_key, op_params in (
                        (
                            "niagara.set_user_parameter",
                            {
                                "asset_path": created_path,
                                "parameter_name": "Color",
                                "value": requested_color,
                                "value_type": "color",
                            },
                        ),
                        (
                            "niagara.set_renderer_property",
                            {
                                "asset_path": created_path,
                                "property_name": "color",
                                "value": requested_color,
                                "value_type": "color",
                            },
                        ),
                        (
                            "niagara.set_module_input",
                            {
                                "asset_path": created_path,
                                "module_name": "Color",
                                "input_name": "Color",
                                "value": requested_color,
                                "value_type": "color",
                            },
                        ),
                    ):
                        label, ok, result = self.execute_unreal_operation(op_key, op_params)
                        followups.append(
                            {
                                "operation": op_key,
                                "label": label,
                                "ok": ok,
                                "params": op_params,
                                "result": result,
                            }
                        )
                        if ok:
                            break
                if created_ok and target_blueprint:
                    component_params = {
                        "blueprint_path": target_blueprint,
                        "component_class": "NiagaraComponent",
                        "component_name": asset_path.rsplit("/", 1)[-1] + "_Component",
                        "asset_path": created_path,
                        "attach_bone": attach_bone,
                        "socket_name": attach_bone,
                        "save": True,
                    }
                    label, ok, result = self.execute_unreal_operation(
                        "blueprint.add_component", component_params
                    )
                    followups.append(
                        {
                            "operation": "blueprint.add_component",
                            "label": label,
                            "ok": ok,
                            "params": component_params,
                            "result": result,
                        }
                    )
                if followups:
                    response["followups"] = followups
                    response["ok"] = created_ok and all(item.get("ok") for item in followups)
                return (
                    "Unreal Create Niagara Emitter",
                    bool(response.get("ok")),
                    json.dumps(response, indent=2, default=str),
                )

            if operation_key == "blueprint.add_component":
                blueprint_path = params.get("blueprint_path") or params.get("asset_path") or ""
                component_class = params.get("component_class") or "ActorComponent"
                component_name = params.get("component_name") or "AIStudioComponent"
                component_asset_path = params.get("asset_path") or ""
                attach_bone = params.get("attach_bone") or params.get("socket_name") or ""
                user_parameters = dict(params.get("user_parameters") or {})
                save = bool(params.get("save", True))
                code = f"""
import json
import unreal

blueprint_path = {blueprint_path!r}
component_class = {component_class!r}
component_name = {component_name!r}
component_asset_path = {component_asset_path!r}
attach_bone = {attach_bone!r}
user_parameters = json.loads({json.dumps(user_parameters, default=str)!r})
save = {save!r}
out = {{
    "ok": False,
    "operation": "blueprint.add_component",
    "blueprint_path": blueprint_path,
    "resolved_blueprint_path": "",
    "component_class": component_class,
    "component_name": component_name,
    "component_asset_path": component_asset_path,
    "attach_bone": attach_bone,
    "actions": [],
    "warnings": [],
    "errors": [],
    "validation": {{
        "blueprint_loaded": False,
        "component_created": False,
        "asset_assigned": False,
        "attachment_parent": "",
        "requested_socket": attach_bone,
        "resolved_socket": "",
        "socket_valid": False,
        "attached_to_mesh": False,
        "user_parameters_applied": [],
        "user_parameters_failed": [],
    }},
}}

def resolve_asset_path(value, wanted_class=""):
    text = str(value or "").strip().strip("'\\\"")
    if not text:
        return ""
    if text.startswith("/"):
        return text.split(".", 1)[0]
    if text.lower().startswith(("game/", "engine/", "plugin/")):
        return "/" + text
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        assets = registry.get_assets_by_path("/Game", recursive=True)
        for data in assets:
            name = str(data.asset_name)
            path = str(data.package_name)
            cls = ""
            try:
                cls = str(data.asset_class_path.asset_name)
            except Exception:
                try:
                    cls = str(data.asset_class)
                except Exception:
                    pass
            if name.lower() == text.lower() or path.lower().endswith("/" + text.lower()):
                if not wanted_class or wanted_class.lower() in cls.lower() or "blueprint" in cls.lower():
                    return path
    except Exception as exc:
        out["warnings"].append("asset registry resolve failed: " + str(exc))
    return "/Game/" + text

def component_class_object(name):
    aliases = {{
        "niagaracomponent": unreal.NiagaraComponent if hasattr(unreal, "NiagaraComponent") else None,
        "niagara": unreal.NiagaraComponent if hasattr(unreal, "NiagaraComponent") else None,
        "actorcomponent": unreal.ActorComponent,
        "scenecomponent": unreal.SceneComponent,
    }}
    key = "".join(ch for ch in str(name or "").lower() if ch.isalnum())
    cls = aliases.get(key)
    if cls:
        return cls
    try:
        return getattr(unreal, str(name))
    except Exception:
        return None

def find_component_handle(bp, wanted_name="", class_fragment=""):
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    library = unreal.SubobjectDataBlueprintFunctionLibrary
    handles = list(subsystem.k2_gather_subobject_data_for_blueprint(bp) or [])
    wanted = str(wanted_name or "")
    fragment = str(class_fragment or "").lower()
    for handle in handles:
        data = library.get_data(handle)
        if not library.is_component(data):
            continue
        obj = None
        try:
            obj = library.get_object(data)
        except Exception:
            obj = None
        name = str(library.get_variable_name(data))
        class_name = obj.get_class().get_name() if obj else ""
        if wanted and name == wanted:
            return handle, data, obj
        if fragment and fragment in class_name.lower():
            return handle, data, obj
    return None, None, None

def validate_socket(mesh_template, requested):
    if not mesh_template or not requested:
        return "", False
    candidate = str(requested)
    try:
        if int(mesh_template.get_bone_index(unreal.Name(candidate))) >= 0:
            return candidate, True
    except Exception:
        pass
    try:
        if bool(mesh_template.does_socket_exist(unreal.Name(candidate))):
            return candidate, True
    except Exception:
        pass
    return "", False

def apply_niagara_user_parameters(template, values):
    if not template or not values:
        return
    for key, value in dict(values or {{}}).items():
        name = str(key)
        if not name.startswith("User."):
            name = "User." + name
        try:
            if isinstance(value, bool):
                template.set_niagara_variable_bool(name, bool(value))
                out["validation"]["user_parameters_applied"].append(name)
            elif isinstance(value, (int, float)):
                template.set_niagara_variable_float(name, float(value))
                out["validation"]["user_parameters_applied"].append(name)
            elif isinstance(value, (list, tuple)) and len(value) >= 4 and "color" in key.lower():
                template.set_niagara_variable_linear_color(
                    name,
                    unreal.LinearColor(float(value[0]), float(value[1]), float(value[2]), float(value[3])),
                )
                out["validation"]["user_parameters_applied"].append(name)
            elif isinstance(value, (list, tuple)) and len(value) >= 3 and "color" in key.lower():
                template.set_niagara_variable_linear_color(
                    name,
                    unreal.LinearColor(float(value[0]), float(value[1]), float(value[2]), 1.0),
                )
                out["validation"]["user_parameters_applied"].append(name)
            elif isinstance(value, (list, tuple)) and len(value) >= 3:
                template.set_niagara_variable_vec3(
                    name,
                    unreal.Vector(float(value[0]), float(value[1]), float(value[2])),
                )
                out["validation"]["user_parameters_applied"].append(name)
        except Exception as exc:
            out["validation"]["user_parameters_failed"].append({{"name": name, "error": str(exc)}})

try:
    resolved_bp_path = resolve_asset_path(blueprint_path, wanted_class="Blueprint")
    out["resolved_blueprint_path"] = resolved_bp_path
    bp = unreal.EditorAssetLibrary.load_asset(resolved_bp_path)
    out["validation"]["blueprint_loaded"] = bool(bp)
    if not bp:
        out["errors"].append("Blueprint could not be loaded: " + str(resolved_bp_path))
    else:
        cls = component_class_object(component_class)
        if not cls:
            out["errors"].append("Component class is not available in this Unreal Python runtime: " + str(component_class))
        else:
            template = None
            node = None
            mesh_handle, mesh_data, mesh_template = find_component_handle(bp, "Mesh", "skeletalmeshcomponent")
            if mesh_template:
                out["validation"]["attachment_parent"] = str(unreal.SubobjectDataBlueprintFunctionLibrary.get_variable_name(mesh_data))
            resolved_socket, socket_valid = validate_socket(mesh_template, attach_bone)
            out["validation"]["resolved_socket"] = resolved_socket
            out["validation"]["socket_valid"] = bool(socket_valid)
            if attach_bone and not socket_valid:
                fallback_socket, fallback_valid = validate_socket(mesh_template, "spine_03")
                if fallback_valid:
                    resolved_socket = fallback_socket
                    out["validation"]["resolved_socket"] = resolved_socket
                    out["validation"]["socket_valid"] = True
                    out["warnings"].append("Requested socket/bone was invalid for Mesh; fell back to spine_03: " + str(attach_bone))
                else:
                    out["warnings"].append("Requested socket/bone was invalid and no fallback socket was available: " + str(attach_bone))
            try:
                scs = bp.get_editor_property("simple_construction_script")
            except Exception:
                scs = None
            if scs and hasattr(scs, "create_node"):
                try:
                    node = scs.create_node(cls, component_name)
                    try:
                        root_nodes = scs.get_root_nodes() or []
                    except Exception:
                        root_nodes = []
                    if root_nodes and hasattr(scs, "add_node"):
                        scs.add_node(node)
                    elif hasattr(scs, "add_node"):
                        scs.add_node(node)
                    out["actions"].append("SimpleConstructionScript.create_node")
                    out["validation"]["component_created"] = True
                    try:
                        template = node.get_editor_property("component_template")
                    except Exception:
                        template = None
                except Exception as exc:
                    out["warnings"].append("SimpleConstructionScript create_node failed: " + str(exc))
            if not out["validation"]["component_created"]:
                try:
                    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
                    library = unreal.SubobjectDataBlueprintFunctionLibrary
                    handles = list(subsystem.k2_gather_subobject_data_for_blueprint(bp) or [])
                    existing = []
                    for handle in handles:
                        data = library.get_data(handle)
                        if not library.is_component(data):
                            continue
                        existing_name = str(library.get_variable_name(data))
                        existing.append(existing_name)
                        if existing_name == str(component_name):
                            out["validation"]["component_created"] = True
                            out["actions"].append("SubobjectDataSubsystem.reuse_existing_component")
                            try:
                                template = library.get_object(data)
                            except Exception:
                                template = None
                            break
                    if not out["validation"]["component_created"] and handles:
                        params_obj = unreal.AddNewSubobjectParams()
                        params_obj.set_editor_property("parent_handle", mesh_handle or handles[0])
                        params_obj.set_editor_property("new_class", cls)
                        params_obj.set_editor_property("blueprint_context", bp)
                        handle, fail_reason = subsystem.add_new_subobject(params_obj)
                        if library.is_handle_valid(handle):
                            try:
                                subsystem.rename_subobject(handle, str(component_name))
                            except Exception as exc:
                                out["warnings"].append("rename_subobject failed: " + str(exc))
                            data = library.get_data(handle)
                            try:
                                template = library.get_object(data)
                            except Exception:
                                template = None
                            out["validation"]["component_created"] = True
                            out["actions"].append("SubobjectDataSubsystem.add_new_subobject")
                        else:
                            out["warnings"].append("SubobjectDataSubsystem add failed: " + str(fail_reason))
                except Exception as exc:
                    out["warnings"].append("SubobjectDataSubsystem fallback failed: " + str(exc))
            if not out["validation"]["component_created"]:
                out["errors"].append("No exposed Blueprint component creation API succeeded for this Unreal runtime.")
            if template:
                asset = unreal.EditorAssetLibrary.load_asset(component_asset_path) if component_asset_path else None
                if asset:
                    for prop in ("asset", "template_asset", "niagara_system", "effect_asset"):
                        try:
                            template.set_editor_property(prop, asset)
                            out["validation"]["asset_assigned"] = True
                            out["actions"].append("set component asset property: " + prop)
                            break
                        except Exception:
                            pass
                    try:
                        if hasattr(template, "set_asset"):
                            template.set_asset(asset)
                            out["validation"]["asset_assigned"] = True
                            out["actions"].append("NiagaraComponent.set_asset")
                    except Exception as exc:
                        out["warnings"].append("set_asset failed: " + str(exc))
                if attach_bone:
                    for prop in ("auto_attach_socket_name", "attach_socket_name", "socket_name", "parent_socket", "bone_name"):
                        try:
                            template.set_editor_property(prop, unreal.Name(str(resolved_socket or attach_bone)))
                            out["actions"].append("set attach socket property: " + prop)
                            break
                        except Exception:
                            pass
                    if mesh_template and resolved_socket:
                        try:
                            subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
                            library = unreal.SubobjectDataBlueprintFunctionLibrary
                            child_handle, child_data, _child_obj = find_component_handle(bp, component_name, "")
                            if mesh_handle and child_handle and subsystem.attach_subobject(mesh_handle, child_handle):
                                out["validation"]["attached_to_mesh"] = True
                                out["actions"].append("SubobjectDataSubsystem.attach_subobject:Mesh")
                        except Exception as exc:
                            out["warnings"].append("attach_subobject failed: " + str(exc))
                        try:
                            template.set_auto_attachment_parameters(mesh_template, unreal.Name(str(resolved_socket)), unreal.AttachmentRule.SNAP_TO_TARGET, unreal.AttachmentRule.SNAP_TO_TARGET, unreal.AttachmentRule.KEEP_RELATIVE)
                            template.set_use_auto_manage_attachment(True)
                            out["actions"].append("NiagaraComponent.set_auto_attachment_parameters")
                        except Exception as exc:
                            out["warnings"].append("set_auto_attachment_parameters failed: " + str(exc))
                apply_niagara_user_parameters(template, user_parameters)
                try:
                    out["validation"]["readback_socket"] = str(template.get_attach_socket_name())
                except Exception:
                    pass
                try:
                    parent = template.get_attach_parent()
                    out["validation"]["readback_parent"] = parent.get_name() if parent else ""
                except Exception:
                    pass
            if out["validation"]["component_created"]:
                try:
                    if hasattr(unreal.BlueprintEditorLibrary, "mark_blueprint_as_structurally_modified"):
                        unreal.BlueprintEditorLibrary.mark_blueprint_as_structurally_modified(bp)
                        out["actions"].append("mark_blueprint_as_structurally_modified")
                    elif hasattr(bp, "mark_package_dirty"):
                        bp.mark_package_dirty()
                        out["actions"].append("mark_package_dirty")
                except Exception as exc:
                    out["warnings"].append("mark modified failed: " + str(exc))
                try:
                    if hasattr(unreal, "KismetEditorUtilities"):
                        unreal.KismetEditorUtilities.compile_blueprint(bp)
                    else:
                        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
                    out["actions"].append("compile_blueprint")
                except Exception as exc:
                    out["warnings"].append("compile failed: " + str(exc))
                if save:
                    try:
                        unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
                        out["actions"].append("save_loaded_asset")
                    except Exception as exc:
                        out["warnings"].append("save failed: " + str(exc))
                out["ok"] = True
except Exception as exc:
    out["errors"].append(str(exc))

print(json.dumps(out))
"""
                response = self.unreal.execute_python(
                    code, timeout=params.get("timeout", 45), reset_globals=True
                )
                return (
                    "Unreal Add Blueprint Component",
                    bool(response.get("ok")),
                    json.dumps(response, indent=2, default=str),
                )

            if operation_key == "niagara.add_to_level":
                asset_path = params.get("asset_path") or ""
                location = params.get("location")
                attach_to_selected_actor = bool(
                    params.get("attach_to_selected_actor", False)
                )
                code = f"""
import json
import unreal

asset_path = {asset_path!r}
location = {json.dumps(location)!r}
attach_to_selected_actor = {attach_to_selected_actor!r}
out = {{
    "ok": False,
    "operation": "niagara.add_to_level",
    "asset_path": asset_path,
    "spawned_actor": None,
    "selected_actors": [],
    "warnings": [],
    "errors": [],
    "validation": {{"asset_exists": False, "spawn_attempted": False}},
}}

try:
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    out["validation"]["asset_exists"] = bool(asset)
    actor_subsystem = None
    selected = []
    try:
        actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        selected = actor_subsystem.get_selected_level_actors() or []
        out["selected_actors"] = [str(a.get_path_name()) for a in selected]
    except Exception:
        pass
    if not asset:
        out["errors"].append("Niagara asset could not be loaded")
    else:
        out["validation"]["spawn_attempted"] = True
        spawn_location = unreal.Vector(0.0, 0.0, 0.0)
        if isinstance(location, list) and len(location) >= 3:
            spawn_location = unreal.Vector(float(location[0]), float(location[1]), float(location[2]))
        actor = None
        try:
            actor = unreal.EditorLevelLibrary.spawn_actor_from_object(asset, spawn_location)
        except Exception as exc:
            out["errors"].append("spawn_actor_from_object failed: " + str(exc))
        if actor:
            out["ok"] = True
            try:
                out["spawned_actor"] = str(actor.get_path_name())
            except Exception:
                out["spawned_actor"] = str(actor)
            if attach_to_selected_actor and selected:
                out["warnings"].append("Attachment to selected actor is not yet a first-class safe operation; Niagara actor was spawned only.")
except Exception as exc:
    out["errors"].append(str(exc))

print(json.dumps(out))
"""
                response = self.unreal.execute_python(
                    code, timeout=params.get("timeout", 45), reset_globals=True
                )
                return (
                    "Unreal Add Niagara To Level",
                    bool(response.get("ok")),
                    json.dumps(response, indent=2, default=str),
                )

            if operation_key == "project.snapshot":
                mode = params.get("mode", "standard")
                scan = UnrealScanner(project_root=params.get("project_root")).scan_all(
                    mode=mode
                )
                return (
                    "Unreal Project Snapshot",
                    bool(scan.get("ok") or scan.get("cache_used")),
                    json.dumps(scan, indent=2, default=str),
                )

            if operation_key == "project.scan_assets":
                mode = params.get("mode", "standard")
                scan = UnrealScanner(project_root=params.get("project_root")).scan_all(
                    mode=mode
                )
                return (
                    "Unreal Project Asset Scan",
                    bool(scan.get("ok") or scan.get("cache_used")),
                    json.dumps(scan, indent=2, default=str),
                )

            if operation_key == "project.debug":
                directory = params.get("directory", "/Game/")
                report = {
                    "directory": directory,
                    "scope_paths": params.get("paths", []),
                    "snapshot": None,
                    "validation": None,
                    "warnings": [],
                    "next_steps": [
                        "Review validation and Blueprint compiler output.",
                        "Fix missing references before graph or animation changes.",
                        "Re-run project.debug after applying fixes.",
                    ],
                }
                snapshot_label, snapshot_ok, snapshot_result = (
                    self.execute_unreal_operation(
                        "project.snapshot",
                        {"directory": directory},
                    )
                )
                report["snapshot"] = {
                    "label": snapshot_label,
                    "ok": snapshot_ok,
                    "result": snapshot_result,
                }
                if not snapshot_ok:
                    report["warnings"].append("Project snapshot was partial or failed.")

                validation_params = {
                    "paths": params.get("paths", []),
                    "compile_blueprints": params.get("compile_blueprints", True),
                    "save": False,
                }
                validation_payload = unreal_operation_payload(
                    "validate.references", validation_params
                )
                validation_ok, validation_result = self.unreal.call(
                    validation_payload["function"],
                    args=validation_payload["args"],
                    kwargs=validation_payload["kwargs"],
                )
                report["validation"] = {
                    "label": validation_payload["label"],
                    "ok": validation_ok,
                    "result": validation_result,
                }
                if not validation_ok:
                    report["warnings"].append(
                        "Reference validation or Blueprint compilation reported failures."
                    )

                return (
                    "Unreal Project Debug",
                    snapshot_ok and validation_ok,
                    json.dumps(report, indent=2, default=str),
                )

            if operation_key.startswith("navigation."):
                return self._execute_unreal_navigation_operation(operation_key, params)

            payload = unreal_operation_payload(operation_key, params)
            if payload.get("execution_host") == "desktop":
                module_name, separator, function_name = payload["function"].rpartition(".")
                if not separator:
                    raise ValueError("Desktop operation must use a qualified function path")
                function = getattr(importlib.import_module(module_name), function_name)
                result = function(*payload["args"], **payload["kwargs"])
                serialized = json.dumps(result, indent=2, default=str)
                result_ok = not isinstance(result, dict) or result.get("ok", True) is not False
                return payload["label"], bool(result_ok), serialized
            ok, result = self.unreal.call(
                payload["function"],
                args=payload["args"],
                kwargs=payload["kwargs"],
                retry_safe=not bool(payload.get("mutates_project")),
                operation=operation_key,
            )
            if ok and isinstance(result, str):
                try:
                    structured_result = json.loads(result)
                except Exception:
                    structured_result = None
                if isinstance(structured_result, dict) and structured_result.get("ok") is False:
                    ok = False
            if ok and operation_key == "blueprint.scan":
                try:
                    scan_result = json.loads(result) if isinstance(result, str) else result
                except Exception:
                    scan_result = None
                if isinstance(scan_result, dict) and scan_result.get("sufficient") is False:
                    ok = False
            return payload["label"], ok, result
        except Exception as e:
            return "Unreal Operation", False, str(e)

    def _execute_unreal_navigation_operation(self, operation_key: str, params=None) -> tuple[str, bool, str]:
        params = params or {}
        source = f"""
import json
import unreal

operation = {operation_key!r}
params = {params!r}
out = {{
    "ok": False,
    "operation": operation,
    "params": params,
    "actions": [],
    "warnings": [],
    "errors": [],
}}

def _load_asset(path):
    try:
        return unreal.EditorAssetLibrary.load_asset(path)
    except Exception as exc:
        out["warnings"].append("load_asset failed: " + str(exc))
        return None

def _find_asset_by_name(name):
    name = str(name or "").strip()
    if not name:
        return None, ""
    def _compact(value):
        return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = registry.get_assets_by_path("/Game", True) or []
        lowered = name.lower()
        compacted = _compact(name)
        
        query_words = [w for w in lowered.replace("_", " ").replace("-", " ").split() if len(w) > 1]
        
        best = None
        best_score = -1
        candidates = []
        
        for data in assets:
            asset_name = str(getattr(data, "asset_name", "") or "")
            object_path = str(getattr(data, "object_path", "") or "")
            package_name = str(getattr(data, "package_name", "") or "")
            class_path = getattr(data, "asset_class_path", None)
            class_name = str(class_path.asset_name if class_path else getattr(data, "asset_class", ""))
            
            resolved_path = object_path or package_name
            asset_lower = asset_name.lower()
            package_lower = package_name.lower()
            object_lower = object_path.lower()
            
            score = 0
            if asset_lower == lowered or object_lower.endswith("." + lowered) or package_lower.endswith("/" + lowered):
                score += 100
            elif _compact(asset_name) == compacted:
                score += 95
            elif lowered in asset_lower or compacted in _compact(asset_name):
                score += 40
            
            if query_words:
                haystack = " ".join([asset_name, package_name, class_name]).lower()
                matched_words = sum(1 for w in query_words if w in haystack)
                if matched_words == len(query_words):
                    score += 50
                elif matched_words > 0:
                    score += matched_words * 15
            
            if score > best_score:
                best_score = score
                best = (data, resolved_path)
            
            if score >= 30:
                candidates.append((data, resolved_path, asset_name, package_name))
                
        if candidates:
            candidates.sort(key=lambda x: len(x[2]))
            out["candidate_assets"] = [
                {{"asset_name": item[2], "package_name": item[3]}}
                for item in candidates[:8]
            ]
            
        if best_score > 0 and best:
            return best[0], best[1]
            
    except Exception as exc:
        out["warnings"].append("asset registry lookup failed: " + str(exc))
    return None, ""

try:
    if operation == "navigation.open_content_browser":
        folder = str(params.get("folder_path") or "/Game").replace("\\\\", "/").rstrip("/") or "/Game"
        asset_name = str(params.get("asset_name") or "").strip()
        new_browser = bool(params.get("new_browser", False))
        asset_data, object_path = _find_asset_by_name(asset_name)
        subsystem = None
        try:
            subsystem = unreal.get_editor_subsystem(unreal.ContentBrowserSubsystem)
        except Exception as exc:
            out["warnings"].append("ContentBrowserSubsystem unavailable: " + str(exc))
        if asset_data and object_path:
            try:
                unreal.EditorAssetLibrary.sync_browser_to_objects([object_path])
                out["ok"] = True
                out["actions"].append("sync_browser_to_objects")
                out["resolved_asset"] = object_path
            except Exception as exc:
                out["warnings"].append("sync_browser_to_objects asset failed: " + str(exc))
        if not out["ok"] and subsystem and hasattr(subsystem, "sync_browser_to_folders"):
            subsystem.sync_browser_to_folders([folder], new_browser)
            out["ok"] = True
            out["actions"].append("sync_browser_to_folders")
        elif not out["ok"] and hasattr(unreal.EditorAssetLibrary, "sync_browser_to_objects"):
            unreal.EditorAssetLibrary.sync_browser_to_objects([folder])
            out["ok"] = True
            out["actions"].append("sync_browser_to_objects")
        elif not out["ok"]:
            out["errors"].append("No Content Browser sync API is available in this Unreal Python environment.")
        out["folder_path"] = folder
        out["asset_name"] = asset_name
        out["new_browser"] = new_browser

    elif operation == "navigation.open_asset":
        asset_path = str(params.get("asset_path") or "")
        asset_name = str(params.get("asset_name") or "").strip()
        asset = _load_asset(asset_path)
        if not asset and asset_name:
            asset_data, object_path = _find_asset_by_name(asset_name)
            if object_path:
                asset_path = object_path.split(".", 1)[0]
                asset = _load_asset(asset_path)
                out["resolved_asset"] = object_path
        if not asset:
            out["errors"].append("Asset could not be loaded: " + asset_path)
        else:
            opened = False
            try:
                subsystem = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
                subsystem.open_editor_for_assets([asset])
                opened = True
                out["actions"].append("AssetEditorSubsystem.open_editor_for_assets")
            except Exception as exc:
                out["warnings"].append("AssetEditorSubsystem failed: " + str(exc))
            if not opened:
                try:
                    unreal.AssetToolsHelpers.get_asset_tools().open_editor_for_assets([asset])
                    opened = True
                    out["actions"].append("AssetTools.open_editor_for_assets")
                except Exception as exc:
                    out["warnings"].append("AssetTools fallback failed: " + str(exc))
            out["ok"] = opened
        out["asset_path"] = asset_path
        out["asset_name"] = asset_name

    elif operation == "navigation.load_level":
        level_path = str(params.get("level_path") or "")
        loaded = False
        try:
            loaded = bool(unreal.EditorLevelLibrary.load_level(level_path))
            out["actions"].append("EditorLevelLibrary.load_level")
        except Exception as exc:
            out["warnings"].append("EditorLevelLibrary.load_level failed: " + str(exc))
        if not loaded:
            try:
                subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
                if hasattr(subsystem, "load_level"):
                    loaded = bool(subsystem.load_level(level_path))
                    out["actions"].append("LevelEditorSubsystem.load_level")
            except Exception as exc:
                out["warnings"].append("LevelEditorSubsystem fallback failed: " + str(exc))
        out["ok"] = bool(loaded)
        out["level_path"] = level_path
        if not loaded:
            out["errors"].append("Level could not be loaded: " + level_path)

    elif operation == "navigation.open_window":
        window_name = str(params.get("window_name") or "").strip()
        normalized = window_name.lower()
        if "content" in normalized and "browser" in normalized:
            folder = str(params.get("folder_path") or "/Game")
            try:
                subsystem = unreal.get_editor_subsystem(unreal.ContentBrowserSubsystem)
                subsystem.sync_browser_to_folders([folder], bool(params.get("new_browser", False)))
                out["ok"] = True
                out["actions"].append("ContentBrowserSubsystem.sync_browser_to_folders")
            except Exception as exc:
                out["errors"].append("Content Browser open failed: " + str(exc))
        else:
            out["errors"].append("Generic editor tab opening is not exposed by this Unreal Python environment yet.")
            out["warnings"].append("Known deterministic window support currently includes Content Browser. Other tabs need a reflected C++/editor utility wrapper if Python cannot spawn them.")
        out["window_name"] = window_name

    else:
        out["errors"].append("Unknown navigation operation: " + operation)
except Exception as exc:
    out["errors"].append(str(exc))

if not out["ok"] and not out["errors"]:
    out["errors"].append("Navigation operation did not report success.")
print(json.dumps(out, default=str))
"""
        response = self.unreal.execute_python(source, timeout=params.get("timeout", 20), reset_globals=True)
        data = response.get("data") if isinstance(response, dict) else None
        ok = bool(data.get("ok")) if isinstance(data, dict) else bool(response.get("ok")) if isinstance(response, dict) else False
        return "Unreal Navigation", ok, json.dumps(response, indent=2, default=str)

    def execute_unreal_capability_pipeline(
        self,
        request: str,
        params=None,
        *,
        project_root: str | None = None,
        dry_run: bool = False,
        timeout: float = 30.0,
    ) -> tuple[str, bool, str]:
        """Resolve, validate, and execute an Unreal capability from indexed metadata."""
        params = params or {}
        auto_open_path = None
        if not dry_run:
            for p_key in ("asset_path", "blueprint_path", "target_path"):
                if p_key in params and isinstance(params[p_key], str) and params[p_key]:
                    auto_open_path = params[p_key]
                    break

        try:
            from tech_connector.services.unreal.capability_graph_service import execute_unreal_capability

            result = execute_unreal_capability(
                request,
                params,
                project_root,
                timeout=timeout,
                dry_run=dry_run,
            )
            ok = bool(result.get("success"))

            if ok and auto_open_path:
                try:
                    from tech_connector.services.unreal.unreal_operation_service import normalize_unreal_package_path
                    norm_path = normalize_unreal_package_path(auto_open_path, default_name="Asset")
                    self.unreal.execute_python(
                        f"import unreal; unreal.get_editor_subsystem(unreal.AssetEditorSubsystem).open_editor_for_assets([unreal.EditorAssetLibrary.load_asset({norm_path!r})])",
                        timeout=5
                    )
                except Exception:
                    pass

            return (
                "Unreal Capability Pipeline",
                ok,
                json.dumps(result, indent=2, default=str),
            )
        except Exception as exc:
            return "Unreal Capability Pipeline", False, str(exc)

    @staticmethod
    def _normalize_unreal_property_name(name: str) -> str:
        raw = str(name or "").strip().lower()
        aliases = {
            "stiffness": "angular_twist_motion",
            "swing1": "angular_swing1_motion",
            "swing2": "angular_swing2_motion",
            "twist": "angular_twist_motion",
            "collision": "disable_collision",
            "mass": "mass_in_kg_override",
            "lineardamping": "linear_damping",
            "angulardamping": "angular_damping",
            "color": "color",
            "colour": "color",
        }
        collapsed = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
        return aliases.get(collapsed, str(name or "").strip())

    @staticmethod
    def _coerce_unreal_value(value: Any, value_type: str = "auto") -> Any:
        vt = str(value_type or "auto").lower()
        if vt in {"float", "number"}:
            try:
                return float(value)
            except Exception:
                return value
        if vt in {"int", "integer"}:
            try:
                return int(value)
            except Exception:
                return value
        if vt in {"bool", "boolean"}:
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
        if vt in {"color", "colour"}:
            if isinstance(value, str):
                text = value.strip().lower()
                named = {
                    "red": [1.0, 0.0, 0.0, 1.0],
                    "green": [0.0, 1.0, 0.0, 1.0],
                    "blue": [0.0, 0.0, 1.0, 1.0],
                    "white": [1.0, 1.0, 1.0, 1.0],
                    "black": [0.0, 0.0, 0.0, 1.0],
                    "yellow": [1.0, 1.0, 0.0, 1.0],
                    "orange": [1.0, 0.5, 0.0, 1.0],
                    "purple": [0.5, 0.0, 1.0, 1.0],
                }
                if text in named:
                    return named[text]
            return value
        if vt == "vector" and isinstance(value, str):
            try:
                parts = [float(x.strip()) for x in value.split(",")]
                if len(parts) >= 3:
                    return parts[:3]
            except Exception:
                return value
        return value

    def _unreal_blueprint_dynamic_inspect_code(
        self, asset_name: str, allow_cpp_bridge: bool = False
    ) -> str:
        return f"""
import json
import unreal

target = {asset_name!r}.strip()
allow_cpp_bridge = {bool(allow_cpp_bridge)!r}
target_lower = target.lower()
target_key = "".join(ch for ch in target_lower if ch.isalnum())
registry = unreal.AssetRegistryHelpers.get_asset_registry()
editor = unreal.EditorAssetLibrary

def data_path(data):
    try:
        return str(data.get_editor_property("object_path"))
    except Exception:
        pass
    try:
        return str(data.object_path)
    except Exception:
        pass
    try:
        pkg = str(data.package_name)
        name = str(data.asset_name)
        return pkg + "." + name
    except Exception:
        return str(data)

def data_class(data):
    try:
        return str(data.asset_class_path.asset_name)
    except Exception:
        try:
            return str(data.asset_class)
        except Exception:
            return ""

def prop(obj, name):
    try:
        return obj.get_editor_property(name)
    except Exception:
        pass
    try:
        return getattr(obj, name)
    except Exception:
        return None

def pin_type_summary(pin_type):
    try:
        text = pin_type.export_text()
    except Exception:
        return str(pin_type)
    category = ""
    object_type = ""
    for prefix, key in (('PinCategory="', "category"), ('PinSubCategoryObject="', "object")):
        start = text.find(prefix)
        if start >= 0:
            start += len(prefix)
            end = text.find('"', start)
            value = text[start:end] if end >= 0 else text[start:]
            if key == "category":
                category = value
            else:
                object_type = value
    if object_type and "'" in object_type:
        object_type = object_type.split("'")[-2] if object_type.endswith("'") else object_type
    return object_type or category or text

def function_summary(fn):
    text = str(fn)
    item = {{"name": text, "implemented": None}}
    marker = 'name: "'
    start = text.find(marker)
    if start >= 0:
        start += len(marker)
        end = text.find('"', start)
        item["name"] = text[start:end] if end >= 0 else text[start:]
    marker = "is_implemented: "
    start = text.find(marker)
    if start >= 0:
        start += len(marker)
        end = text.find("}}", start)
        raw = (text[start:end] if end >= 0 else text[start:]).strip()
        item["implemented"] = raw.lower().startswith("true")
    return item

assets = registry.get_assets_by_path("/Game", recursive=True)
matches = []
for data in assets:
    name = str(data.asset_name)
    path = data_path(data)
    cls = data_class(data)
    name_lower = name.lower()
    path_lower = path.lower()
    package_lower = path_lower.split(".", 1)[0]
    short_lower = path.split(".")[-1].lower()
    name_key = "".join(ch for ch in name_lower if ch.isalnum())
    path_key = "".join(ch for ch in path_lower if ch.isalnum())
    if target_lower in (name_lower, path_lower, package_lower, short_lower):
        matches.append((name, path, cls, data))
    elif target_key and target_key in (name_key, path_key):
        matches.append((name, path, cls, data))
    elif target_lower and target_lower in name_lower:
        matches.append((name, path, cls, data))

selected = matches[0] if matches else None
if not selected:
    result = {{"found": False, "target": target, "matches": []}}
else:
    name, object_path, asset_class, asset_data = selected
    package_path = object_path.split(".", 1)[0]
    asset = editor.load_asset(package_path)
    info = {{
        "found": True,
        "target": target,
        "asset_name": name,
        "asset_path": package_path,
        "object_path": object_path,
        "asset_class": asset_class,
        "python_class": asset.get_class().get_name() if asset else "",
        "parent_class": "",
        "generated_class": "",
        "skeleton": "",
        "target_skeleton": "",
        "preview_mesh": "",
        "variables": [],
        "inherited_variable_count": 0,
        "functions": [],
        "graphs": [],
        "components": [],
        "dependencies": [],
        "referencers": [],
        "tags": {{}},
        "warnings": [],
        "capability_plan": {{
            "python_reflection": "active",
            "cpp_bridge_allowed": allow_cpp_bridge,
            "cpp_bridge_status": "allowed_if_needed" if allow_cpp_bridge else "disabled_by_user",
            "anim_graph_depth": "partial_python_reflection",
        }},
        "notes": [
            "This is editor Python reflection. Some AnimGraph internals may require C++ or specialized editor APIs.",
            "Observed fields are direct inspection; missing graph details should be treated as unknown, not absent."
        ],
    }}
    try:
        info["tags"] = {{str(k): str(v) for k, v in dict(asset_data.tags_and_values).items()}}
    except Exception as exc:
        info["warnings"].append("tags unavailable: " + str(exc))
    try:
        bp_parent = getattr(asset, "parent_class", None)
        if bp_parent:
            info["parent_class"] = bp_parent.get_name()
    except Exception as exc:
        info["warnings"].append("parent_class unavailable: " + str(exc))
    try:
        bp_parent = unreal.BlueprintEditorLibrary.get_blueprint_parent_class(asset)
        if bp_parent:
            info["parent_class"] = bp_parent.get_name()
    except Exception:
        pass
    for attr_name, out_key in (
        ("generated_class", "generated_class"),
        ("target_skeleton", "target_skeleton"),
        ("skeleton", "skeleton"),
        ("preview_skeletal_mesh", "preview_mesh"),
    ):
        try:
            val = prop(asset, attr_name)
            if callable(val):
                val = val()
            if val:
                info[out_key] = str(val.get_path_name() if hasattr(val, "get_path_name") else val)
        except Exception:
            pass
    try:
        deps = registry.get_dependencies(package_path, unreal.AssetRegistryDependencyOptions())
        refs = registry.get_referencers(package_path, unreal.AssetRegistryDependencyOptions())
        info["dependencies"] = [str(item) for item in deps]
        info["referencers"] = [str(item) for item in refs]
    except Exception as exc:
        info["warnings"].append("dependencies unavailable: " + str(exc))
    try:
        names = unreal.BlueprintEditorLibrary.list_member_variable_names(asset)
        variables = []
        inherited_variable_count = 0
        for var_name in names:
            var_name_str = str(var_name)
            if var_name_str.startswith("/Script/"):
                inherited_variable_count += 1
                continue
            item = {{"name": var_name_str, "type": "", "category": "", "replication": ""}}
            try:
                var_type = unreal.BlueprintEditorLibrary.get_member_variable_type(asset, var_name)
                item["type"] = pin_type_summary(var_type)
            except Exception:
                pass
            try:
                item["category"] = str(unreal.BlueprintEditorLibrary.get_blueprint_variable_category(asset, var_name))
            except Exception:
                pass
            try:
                item["replication"] = str(unreal.BlueprintEditorLibrary.get_blueprint_variable_replication(asset, var_name))
            except Exception:
                pass
            variables.append(item)
        info["variables"] = variables
        info["inherited_variable_count"] = inherited_variable_count
    except Exception as exc:
        info["warnings"].append("variables unavailable: " + str(exc))
    try:
        info["functions"] = [function_summary(item) for item in unreal.BlueprintEditorLibrary.list_functions(asset)]
    except Exception as exc:
        info["warnings"].append("functions unavailable: " + str(exc))
    try:
        graph_values = []
        for graph in unreal.BlueprintEditorLibrary.list_graphs(asset):
            graph_values.append({{
                "name": graph.get_name(),
                "class": graph.get_class().get_name() if graph.get_class() else "",
            }})
        if not graph_values:
            graph_values = [{{"name": str(item), "class": ""}} for item in unreal.BlueprintEditorLibrary.list_graph_names(asset)]
        info["graphs"] = graph_values
    except Exception as exc:
        try:
            graph_values = []
            for attr in ("ubergraph_pages", "function_graphs", "macro_graphs", "delegate_signature_graphs"):
                value = prop(asset, attr)
                if value:
                    for graph in value:
                        graph_values.append({{"bucket": attr, "name": graph.get_name(), "class": graph.get_class().get_name()}})
            info["graphs"] = graph_values
        except Exception:
            info["warnings"].append("graphs unavailable: " + str(exc))
    try:
        scs = prop(asset, "simple_construction_script")
        if scs:
            nodes = scs.get_all_nodes()
            info["components"] = [{{
                "name": str(node.get_variable_name()),
                "component_class": node.get_component_class().get_name() if node.get_component_class() else "",
            }} for node in nodes]
    except Exception as exc:
        info["warnings"].append("components unavailable: " + str(exc))
    result = info
"""

    def unreal_operation_catalog_text(self) -> str:
        lines = [
            "Unreal safe operation catalog:",
            "Use project/level scan operations before proposing generated changes.",
            "Mutating operations should be planned and validated instead of executed as arbitrary Python.",
        ]
        for op in operation_catalog():
            mode = "mutates" if op["mutates_project"] else "read-only"
            required = ", ".join(op["required"]) if op["required"] else "none"
            lines.append(
                f"- {op['key']} ({mode}) -> {op['function']} required: {required}"
            )
        return "\n".join(lines)

    def execute_blender_preset(self, preset: str) -> tuple[str, bool, str]:
        presets = {
            "selection": ("Blender Selection", self.blender.get_selection_code()),
            "file": ("Blender File", self.blender.get_current_file_code()),
            "objects": ("Blender Scene Objects", self.blender.get_scene_objects_code()),
        }
        if preset not in presets:
            return preset, False, f"Unknown Blender preset: {preset}"
        label, code = presets[preset]
        ok, result = self.blender.execute(code)
        return label, ok, result

    def execute_motionbuilder_preset(self, preset: str) -> tuple[str, bool, str]:
        presets = {
            "selection": (
                "MotionBuilder Selection",
                self.motionbuilder.get_selection_code(),
            ),
            "file": ("MotionBuilder File", self.motionbuilder.get_current_file_code()),
            "objects": (
                "MotionBuilder Scene Objects",
                self.motionbuilder.get_scene_objects_code(),
            ),
            "takes": ("MotionBuilder Takes", self.motionbuilder.get_takes_code()),
            "characters": (
                "MotionBuilder Characters",
                self.motionbuilder.get_characters_code(),
            ),
        }
        if preset not in presets:
            return preset, False, f"Unknown MotionBuilder preset: {preset}"
        label, code = presets[preset]
        ok, result = self.motionbuilder.execute(code)
        return label, ok, result

    def motionbuilder_context_summary(self) -> tuple[str, bool, str]:
        try:
            return (
                "MotionBuilder Context Summary",
                True,
                self.motionbuilder_adapter.build_context_summary(),
            )
        except Exception as e:
            return "MotionBuilder Context Summary", False, str(e)

    def execute_substance_painter_from_text(self, text: str) -> tuple[str, bool, str]:
        text = text.strip()
        try:
            mode, data = self.substance_painter.parse_input(text)
            if mode == "function":
                label = "Substance Painter Function"
                ok, result = self.substance_painter.call_function(
                    data["function"],
                    args=data.get("args", []),
                    kwargs=data.get("kwargs", {}),
                )
            else:
                label = "Substance Painter Execute"
                ok, result = self.substance_painter.execute(text)
            return label, ok, result
        except Exception as e:
            return "Substance Painter Direct", False, str(e)

    def execute_substance_painter_preset(self, preset: str) -> tuple[str, bool, str]:
        presets = {
            "project": (
                "Substance Painter Project",
                self.substance_painter.get_current_file_code(),
            ),
            "status": (
                "Substance Painter Status",
                self.substance_painter.get_project_status_code(),
            ),
            "texture_sets": (
                "Substance Painter Texture Sets",
                self.substance_painter.get_scene_objects_code(),
            ),
        }
        if preset not in presets:
            return preset, False, f"Unknown Substance Painter preset: {preset}"
        label, code = presets[preset]
        ok, result = self.substance_painter.execute(code)
        return label, ok, result

    def execute_unity_from_text(self, text: str) -> tuple[str, bool, str]:
        text = text.strip()
        try:
            ok, result = self.unity.execute(text)
            return "Unity Execute", ok, result
        except Exception as e:
            return "Unity Direct", False, str(e)

    def execute_unity_preset(self, preset: str) -> tuple[str, bool, str]:
        presets = {
            "selection": ("Unity Selection", self.unity.get_selection_code()),
            "file": ("Unity Scene File", self.unity.get_current_file_code()),
            "objects": ("Unity Scene Objects", self.unity.get_scene_objects_code()),
        }
        if preset not in presets:
            return preset, False, f"Unknown Unity preset: {preset}"
        label, code = presets[preset]
        ok, result = self.unity.execute(code)
        return label, ok, result

    def get_intent(self, text: str) -> str:
        return IntentRouter.classify_chat_input(text)
