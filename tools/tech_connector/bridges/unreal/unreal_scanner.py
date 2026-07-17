# unreal_scanner.py
"""Staged Unreal project/context scanner.

The scanner is intentionally fault-tolerant: every stage records its own timing
and error, failures do not stop later stages, and cached project intelligence is
used only when clearly marked as cache.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from tech_connector.dcc_intelligence.runtime import TTLMemoryCache, elapsed_ms, iso_now, stage_result
from tech_connector.router.ai_router import AIRouter
from tech_connector.services.unreal.contexts.selected_context import UnrealSelectedContextService

try:
    from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
except ImportError:
    from unreal_bridge import UnrealBridge


CACHE_FILE = ".project_ai/asset_index.json"
INTELLIGENCE_CACHE_FILE = ".ai_studio/intelligence/latest_unreal_scan.json"
SCAN_TTLS = {"quick": 10.0, "standard": 30.0, "deep": 0.0}
FAST_UNREAL_QUERY_TERMS = (
    "inspect",
    "show",
    "list",
    "find",
    "search",
    "query",
    "what is",
    "what's",
    "selected",
    "current level",
    "loaded level",
)


class UnrealScanner:
    """Wrap UnrealBridge with staged, typed project-state queries."""

    _memory_cache = TTLMemoryCache()

    def __init__(self, project_root: Optional[str] = None):
        self.bridge = UnrealBridge()
        self.project_root = (
            Path(project_root).expanduser().resolve() if project_root else Path.cwd()
        )
        self._cache: Dict[str, Any] = {}

    def _safe(
        self,
        fn: str,
        *args,
        timeout: float = 3.0,
        retries: int = 0,
        label: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        return self.bridge.safe_call(
            fn, list(args), kwargs, timeout=timeout, retries=retries, label=label or fn
        )

    def _value(
        self,
        fn: str,
        *args,
        default: Any = None,
        timeout: float = 3.0,
        retries: int = 0,
        label: str = "",
        **kwargs,
    ) -> Any:
        result = self._safe(
            fn, *args, timeout=timeout, retries=retries, label=label, **kwargs
        )
        return result.get("result") if result.get("ok") else default

    def _run_stage(
        self, name: str, data: Dict[str, Any], stages: list[dict], func
    ) -> None:
        started = time.monotonic()
        try:
            key, value = func()
            data[key] = value
            count = len(value) if isinstance(value, (list, dict)) else None
            stages.append(stage_result(name, True, started, count=count))
        except Exception as exc:
            stages.append(stage_result(name, False, started, error=str(exc)))

    @staticmethod
    def _normalize_list(value: Any, limit: int | None = None) -> List[str]:
        if value is None:
            return []
        if isinstance(value, dict):
            if "assets" in value and isinstance(value["assets"], list):
                value = value["assets"]
            elif "result" in value:
                value = value["result"]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return UnrealScanner._normalize_list(parsed, limit=limit)
            except Exception:
                return [value] if value.strip() else []
        if not isinstance(value, list):
            return [str(value)]
        items = [str(item) for item in value if str(item).strip()]
        return items[:limit] if limit else items

    @staticmethod
    def _project_name_from_dir(project_dir: str | None) -> str | None:
        if not project_dir:
            return None
        try:
            return Path(str(project_dir)).resolve().name
        except Exception:
            return None

    def health_check(self, timeout: float = 1.5) -> Dict[str, Any]:
        return self.bridge.health_check(timeout=timeout)

    def health_summary(self, timeout: float = 1.5) -> Dict[str, Any]:
        health = self.health_check(timeout=timeout)
        checks = health.get("checks") or []
        errors = [str(check.get("error")) for check in checks if check.get("error")]
        warnings = list(health.get("warnings") or [])
        loaded_level = health.get("loaded_level")
        if loaded_level:
            level_text = str(loaded_level).replace("\\", "/")
            loaded_level = level_text.rsplit("/", 1)[-1].split(".")[-1]
        return {
            "ok": bool(health.get("connected")),
            "unreal_reachable": bool(
                health.get("bridge_reachable") or health.get("connected")
            ),
            "python_available": bool(health.get("python_available")),
            "project_name": health.get("project_name"),
            "engine_version": health.get("engine_version"),
            "loaded_level": loaded_level,
            "errors": errors,
            "warnings": warnings,
        }

    def get_project_info(self) -> Dict[str, Any]:
        health = self.health_check()
        project_dir = health.get("project_dir")
        return {
            "project_dir": project_dir,
            "project_name": health.get("project_name")
            or self._project_name_from_dir(project_dir),
            "engine_version": health.get("engine_version"),
        }

    def get_open_project(self) -> Dict[str, Any]:
        return self.get_project_info()

    def get_open_level(self) -> str:
        health = self.health_check()
        if health.get("loaded_level"):
            return str(health["loaded_level"])
        value = self._value(
            "unreal_tools.level.scan_loaded_level",
            default="Unknown",
            timeout=1.0,
            label="open_level",
            include_components=False,
            max_actors=1,
        )
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                pass
        if isinstance(value, dict):
            return str(
                value.get("current_level") or value.get("level_name") or "Unknown"
            )
        return str(value or "Unknown")

    def get_loaded_level(self) -> str:
        return self.get_open_level()

    def get_selected_assets(self) -> List[str]:
        snippets = [
            "import json\nassets = unreal.EditorUtilityLibrary.get_selected_assets()\nresult = [str(a.get_path_name()) if hasattr(a, 'get_path_name') else str(a) for a in assets]\nprint(json.dumps(result))",
            "import json\nassets = unreal.EditorUtilityLibrary.get_selected_assets()\nprint(json.dumps([str(a) for a in assets]))",
        ]
        for snippet in snippets:
            result = self.bridge.execute_python(snippet, timeout=1.0)
            if result["ok"]:
                return self._normalize_list(result.get("data"), limit=200)
        return []

    def get_selected_actors(self) -> List[str]:
        snippets = [
            "import json\nactors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_selected_level_actors()\nprint(json.dumps([str(a.get_path_name()) for a in actors]))",
            "import json\nactors = unreal.EditorLevelLibrary.get_selected_level_actors()\nprint(json.dumps([str(a.get_path_name()) for a in actors]))",
        ]
        for snippet in snippets:
            result = self.bridge.execute_python(snippet, timeout=1.0)
            if result["ok"]:
                return self._normalize_list(result.get("data"), limit=200)
        return []

    def get_selected_folders(self) -> List[str]:
        snippet = (
            "import json\n"
            "folders = list(unreal.EditorUtilityLibrary.get_selected_folder_paths())\n"
            "if not folders:\n"
            "    assets = unreal.EditorUtilityLibrary.get_selected_assets()\n"
            "    if assets:\n"
            "        folders = [assets[0].get_package().get_name().rsplit('/', 1)[0]]\n"
            "if not folders:\n"
            "    folders = ['/Game']\n"
            "print(json.dumps(folders))"
        )
        result = self.bridge.execute_python(snippet, timeout=1.0)
        if result["ok"]:
            return self._normalize_list(result.get("data"), limit=50)
        return ["/Game"]

    def build_selected_context(self, task_text: str = "") -> Dict[str, Any]:
        return UnrealSelectedContextService(self).build_selected_context(task_text)

    def list_assets_by_class(
        self, class_name: str, limit: int = 200, timeout: float = 2.0
    ) -> List[str]:
        known_tool = self._safe(
            "unreal_tools.get_skeletons.get_all_assets_of_type",
            class_name,
            "/Game/",
            timeout=timeout,
            label=f"assets:{class_name}:known_tool",
        )
        if known_tool["ok"]:
            value = known_tool.get("result")
            if isinstance(value, dict):
                return list(value.keys())[:limit]
            return self._normalize_list(value, limit=limit)

        snippets = [
            (
                "[(str(a.package_name) + '.' + str(a.asset_name)) for a in "
                "unreal.AssetRegistryHelpers.get_asset_registry().get_assets_by_class("
                f"unreal.TopLevelAssetPath('/Script/Engine', '{class_name}'))]"
            ),
            (
                "[(str(a.package_name) + '.' + str(a.asset_name)) for a in "
                "unreal.AssetRegistryHelpers.get_asset_registry().get_assets_by_class("
                f"'{class_name}')]"
            ),
            (
                "[str(a.object_path) for a in unreal.AssetRegistryHelpers.get_asset_registry().get_assets_by_path('/Game', recursive=True) "
                f"if str(a.asset_class_path.asset_name if hasattr(a, 'asset_class_path') else a.asset_class) == '{class_name}']"
            ),
        ]
        for snippet in snippets:
            result = self._safe(snippet, timeout=timeout, label=f"assets:{class_name}")
            if result["ok"]:
                return self._normalize_list(result.get("result"), limit=limit)
        return []

    def get_asset_counts(
        self, classes: List[str] | None = None, timeout: float = 0.8
    ) -> Dict[str, int]:
        classes = classes or [
            "Blueprint",
            "SkeletalMesh",
            "AnimSequence",
            "StaticMesh",
            "Material",
            "World",
        ]
        return {
            class_name: len(
                self.list_assets_by_class(class_name, limit=500, timeout=timeout)
            )
            for class_name in classes
        }

    def list_skeletal_meshes(self) -> List[str]:
        return self.list_assets_by_class("SkeletalMesh")

    def list_animations(self) -> List[str]:
        return self.list_assets_by_class("AnimSequence")

    def list_blueprints(self) -> List[str]:
        return self.list_assets_by_class("Blueprint")

    def list_enabled_plugins(self) -> List[str]:
        snippets = [
            "import json\nplugins = unreal.PluginBlueprintLibrary.get_enabled_plugins()\nprint(json.dumps([p.get_name() if hasattr(p, 'get_name') else str(p.name) for p in plugins]))",
            "import json\nplugins = unreal.PluginBlueprintLibrary.get_enabled_plugins()\nprint(json.dumps([str(p.name) for p in plugins]))",
        ]
        for snippet in snippets:
            result = self.bridge.execute_python(snippet, timeout=3.0)
            if result["ok"]:
                return self._normalize_list(result.get("data"), limit=500)
        return []

    def get_available_tools(self) -> List[str]:
        return self.list_assets_by_class("EditorUtilityBlueprint")

    def scan_all(self, mode: str = "quick", force: bool = False) -> Dict[str, Any]:
        mode = mode if mode in {"quick", "standard", "deep"} else "quick"
        ttl = SCAN_TTLS[mode]
        cache_key = f"scan:{self.project_root}:{mode}"
        if not force and ttl > 0:
            cached = self._memory_cache.get(cache_key, ttl)
            if cached is not None:
                data = copy.deepcopy(cached)
                data["used_memory_cache"] = True
                stages = [
                    stage
                    for stage in data.get("stages", [])
                    if stage.get("name") != "cache_status"
                ]
                for stage in stages:
                    stage["used_cache"] = True
                data["stages"] = stages
                data["stages"].append(
                    {
                        "name": "cache_status",
                        "ok": True,
                        "duration_ms": 0.0,
                        "count": None,
                        "error": None,
                        "used_cache": True,
                        "detail": f"memory cache hit for {mode} scan",
                    }
                )
                return data
        if not force and mode == "standard":
            persistent = self.load_cached()
            if self._cached_index_satisfies_mode(persistent, mode):
                return self._cached_scan_result(mode, persistent, source="persistent_asset_index")

        started = time.monotonic()
        stages: list[dict] = []
        warnings: list[str] = []
        data: Dict[str, Any] = {}

        health_started = time.monotonic()
        health = self.health_check()
        data["health"] = health
        connected = bool(health.get("connected"))
        for check in health.get("checks") or []:
            stages.append(
                {
                    "name": check.get("name") or "health_check",
                    "ok": bool(check.get("ok")),
                    "duration_ms": check.get("duration_ms"),
                    "count": check.get("count"),
                    "error": check.get("error"),
                    "used_cache": bool(health.get("used_memory_cache")),
                }
            )
        if not health.get("checks"):
            stages.append(
                stage_result(
                    "bridge_health",
                    connected,
                    health_started,
                    error=health.get("error"),
                )
            )
        stages.append(
            {
                "name": "cache_status",
                "ok": True,
                "duration_ms": 0.0,
                "count": None,
                "error": None,
                "used_cache": False,
                "detail": f"{mode} scan cache miss or forced refresh",
            }
        )

        if not connected:
            cached = self.load_cached()
            if cached:
                warnings.append(
                    "Unreal live bridge unavailable. Using cached project intelligence from "
                    f"{cached.get('scanned_at') or cached.get('checked_at') or 'unknown time'}."
                )
                result = self._result(
                    mode,
                    started,
                    stages,
                    cached,
                    warnings,
                    connected=False,
                    cache_used=True,
                )
                result["used_memory_cache"] = False
                return result
            warnings.append(
                health.get("error")
                or "Unreal live bridge unavailable and no cached asset index was found."
            )
            return self._result(
                mode, started, stages, data, warnings, connected=False, cache_used=False
            )

        self._run_stage(
            "project_info",
            data,
            stages,
            lambda: ("open_project", self.get_project_info()),
        )
        self._run_stage(
            "loaded_level",
            data,
            stages,
            lambda: ("loaded_level", self.get_open_level()),
        )
        if mode == "quick":
            self._run_stage(
                "selected_assets",
                data,
                stages,
                lambda: ("selected_assets", health.get("selected_assets") or []),
            )
            self._run_stage(
                "selected_actors",
                data,
                stages,
                lambda: ("selected_actors", health.get("selected_actors") or []),
            )
            self._run_stage(
                "selected_folders",
                data,
                stages,
                lambda: ("selected_folders", health.get("selected_folders") or ["/Game"]),
            )
            self._run_stage(
                "skeleton_assets",
                data,
                stages,
                lambda: ("skeletons", health.get("bridge_probe_assets") or []),
            )
            self._run_stage(
                "enabled_plugins",
                data,
                stages,
                lambda: (
                    "enabled_plugins",
                    (health.get("plugin_info") or {}).get("enabled_plugins") or [],
                ),
            )
        else:
            self._run_stage(
                "selected_assets",
                data,
                stages,
                lambda: ("selected_assets", self.get_selected_assets()),
            )
            self._run_stage(
                "selected_actors",
                data,
                stages,
                lambda: ("selected_actors", self.get_selected_actors()),
            )
            self._run_stage(
                "selected_folders",
                data,
                stages,
                lambda: ("selected_folders", self.get_selected_folders()),
            )
        if mode == "quick":
            self._run_stage(
                "asset_registry_counts",
                data,
                stages,
                lambda: (
                    "asset_counts",
                    {"Skeleton": int((health.get("bridge_probe_count") or 0))},
                ),
            )
        else:
            count_classes = [
                "Blueprint",
                "SkeletalMesh",
                "AnimSequence",
                "StaticMesh",
                "Material",
                "World",
            ]
            self._run_stage(
                "asset_registry_counts",
                data,
                stages,
                lambda: (
                    "asset_counts",
                    self.get_asset_counts(count_classes, timeout=0.8),
                ),
            )

        if mode in {"standard", "deep"}:
            self._run_stage(
                "blueprints",
                data,
                stages,
                lambda: ("blueprints", self.list_blueprints()),
            )
            self._run_stage(
                "skeletal_meshes",
                data,
                stages,
                lambda: ("skeletal_meshes", self.list_skeletal_meshes()),
            )
            self._run_stage(
                "animations",
                data,
                stages,
                lambda: ("animations", self.list_animations()),
            )
            self._run_stage(
                "enabled_plugins",
                data,
                stages,
                lambda: ("enabled_plugins", self.list_enabled_plugins()),
            )
            self._run_stage(
                "editor_utility_tools",
                data,
                stages,
                lambda: ("available_tools", self.get_available_tools()),
            )

        if mode == "deep":
            self._run_stage(
                "blueprint_metadata",
                data,
                stages,
                lambda: (
                    "blueprint_metadata",
                    {"indexed": len(data.get("blueprints", []))},
                ),
            )

        intel_started = time.monotonic()
        try:
            self._persist_cache(data)
            self._persist_intelligence(data)
            stages.append(stage_result("local_intelligence_write", True, intel_started))
        except Exception as exc:
            warnings.append(f"Local intelligence write failed: {exc}")
            stages.append(
                stage_result(
                    "local_intelligence_write", False, intel_started, error=str(exc)
                )
            )

        result = self._result(
            mode, started, stages, data, warnings, connected=True, cache_used=False
        )
        result["used_memory_cache"] = False
        self._cache = data
        if ttl > 0:
            self._memory_cache.set(cache_key, copy.deepcopy(result))
        return result

    def _result(
        self,
        mode: str,
        started: float,
        stages: list[dict],
        data: Dict[str, Any],
        warnings: list[str],
        *,
        connected: bool,
        cache_used: bool,
    ) -> Dict[str, Any]:
        ok = bool(connected) and all(
            stage["ok"]
            for stage in stages
            if stage["name"] != "local_intelligence_write"
        )
        result = {
            "ok": ok,
            "connected": bool(connected),
            "mode": mode,
            "scanned_at": iso_now(),
            "duration_ms": elapsed_ms(started),
            "stages": stages,
            "data": data,
            "warnings": warnings,
            "cache_used": bool(cache_used),
        }
        for key in (
            "open_project",
            "loaded_level",
            "selected_assets",
            "selected_actors",
            "asset_counts",
            "skeletons",
            "skeletal_meshes",
            "animations",
            "blueprints",
            "enabled_plugins",
            "available_tools",
        ):
            if key in data:
                result[key] = data[key]
        print(
            f"[UnrealScan] mode={mode} duration_ms={result['duration_ms']} "
            f"connected={str(connected).lower()} cache_used={str(cache_used).lower()} "
            f"stages={len(stages)} ok={sum(1 for s in stages if s['ok'])} "
            f"failed={sum(1 for s in stages if not s['ok'])}"
        )
        health = data.get("health") or {}
        print(
            f"[UnrealHealth] connected={str(health.get('connected', connected)).lower()} "
            f"port={health.get('port')} latency_ms={health.get('latency_ms')} "
            f"engine={health.get('engine_version')} level={data.get('loaded_level') or health.get('loaded_level')}"
        )
        return result

    def _persist_cache(self, index: Dict[str, Any]) -> None:
        cache_path = self.project_root / CACHE_FILE
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(index, indent=2, default=str), encoding="utf-8"
        )

    def _persist_intelligence(self, index: Dict[str, Any]) -> None:
        cache_path = self.project_root / INTELLIGENCE_CACHE_FILE
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(index, indent=2, default=str), encoding="utf-8"
            )
        except Exception:
            pass

        try:
            from tech_connector.bridges.unreal.unreal_intelligence import ingest_scan
        except Exception:
            try:
                from unreal_intelligence import ingest_scan
            except Exception:
                return
        try:
            ingest_scan(index, project_root=str(self.project_root))
        except Exception:
            pass

    def load_cached(self) -> Dict[str, Any]:
        cache_path = self.project_root / CACHE_FILE
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    @staticmethod
    def _cached_index_satisfies_mode(index: Dict[str, Any], mode: str) -> bool:
        if not isinstance(index, dict) or mode != "standard":
            return False
        return any(index.get(key) for key in ("blueprints", "skeletal_meshes", "animations", "asset_counts"))

    def _cached_scan_result(self, mode: str, index: Dict[str, Any], *, source: str) -> Dict[str, Any]:
        stages = [
            {
                "name": "cache_status",
                "ok": True,
                "duration_ms": 0.0,
                "count": None,
                "error": None,
                "used_cache": True,
                "detail": f"{source} hit for {mode} scan",
            }
        ]
        result = self._result(
            mode,
            time.monotonic(),
            stages,
            copy.deepcopy(index),
            [f"Using cached Unreal asset intelligence from {source}."],
            connected=bool((index.get("health") or {}).get("connected")),
            cache_used=True,
        )
        result["used_memory_cache"] = False
        result["cache_source"] = source
        self._cache = copy.deepcopy(index)
        return result

    def build_local_intelligence_context(self, request: str = "") -> str:
        try:
            from tech_connector.bridges.unreal.unreal_intelligence import build_context, ingest_scan
        except Exception:
            try:
                from unreal_intelligence import build_context, ingest_scan
            except Exception:
                return self.build_context_summary()
        try:
            idx = self._cache or self.load_cached()
            if idx:
                ingest_scan(idx, project_root=str(self.project_root))
            return build_context(
                request or "unreal project context", project_root=str(self.project_root)
            )
        except Exception:
            return self.build_context_summary()

    def context_status(self, request: str = "", mode: str = "quick") -> Dict[str, Any]:
        scan = self.scan_all(mode=mode)
        data = scan.get("data", {})
        intelligence = {}
        try:
            from tech_connector.bridges.unreal.unreal_intelligence import status as intelligence_status

            intelligence = intelligence_status(str(self.project_root))
        except Exception as exc:
            intelligence = {"error": str(exc)}
        selected_assets = (
            data.get("selected_assets") or scan.get("selected_assets") or []
        )
        selected_actors = (
            data.get("selected_actors") or scan.get("selected_actors") or []
        )
        blueprint_count = len(data.get("blueprints") or scan.get("blueprints") or [])
        last_request = self.bridge.get_last_request_status() or {}
        route = AIRouter.route_prompt(request or "unreal project context")
        return {
            "unreal_live_context": bool(scan.get("connected")),
            "cache_used": bool(scan.get("cache_used")),
            "used_memory_cache": bool(scan.get("used_memory_cache")),
            "scan_mode": scan.get("mode", mode),
            "intelligence_db": "ready"
            if intelligence and not intelligence.get("error")
            else ("error" if intelligence.get("error") else "missing"),
            "selected_assets": len(selected_assets),
            "selected_actors": len(selected_actors),
            "blueprint_index": "ready" if blueprint_count else "missing",
            "warnings": scan.get("warnings", []),
            "stages": scan.get("stages", []),
            "stage_summary": self.format_stage_summary(scan),
            "intelligence": intelligence,
            "last_request": last_request,
            "recommended_model": route.model,
            "recommended_model_tier": route.tier,
            "recommended_model_reason": route.reason,
        }

    @staticmethod
    def format_stage_summary(scan: Dict[str, Any]) -> str:
        labels = {
            "bridge_connected": "Bridge connected",
            "python_available": "Python",
            "package_import": "Package import",
            "skeleton_probe": "Skeleton probe",
            "level_scan": "Level scan",
            "trivial_command": "Trivial command",
            "editor_state": "Editor state",
            "cache_status": "Cache",
        }
        parts = []
        for stage in scan.get("stages", []):
            name = stage.get("name")
            if name not in labels:
                continue
            label = labels[name]
            if name == "cache_status":
                state = "used" if stage.get("used_cache") else "fresh"
            else:
                state = "OK" if stage.get("ok") else "failed"
            if stage.get("count") is not None:
                state += f" ({stage.get('count')})"
            parts.append(f"{label}: {state}")
        return " -> ".join(parts)

    def should_use_fast_path(self, task_text: str) -> bool:
        text = (task_text or "").lower()
        return any(term in text for term in FAST_UNREAL_QUERY_TERMS)

    def build_unreal_context_fast(
        self, task_text: str, max_tokens: int = 4000
    ) -> Dict[str, Any]:
        route = AIRouter.route_prompt(task_text or "unreal task")
        cached_scan = self._memory_cache.get(
            f"scan:{self.project_root}:quick", SCAN_TTLS["quick"]
        )
        scan = copy.deepcopy(cached_scan) if isinstance(cached_scan, dict) else None
        if not scan:
            scan = self.load_cached() or {
                "data": {},
                "connected": False,
                "cache_used": True,
                "mode": "cached_fast",
            }
        data = (
            scan.get("data")
            if isinstance(scan, dict) and isinstance(scan.get("data"), dict)
            else scan
        )
        data = data if isinstance(data, dict) else {}
        health = data.get("health") or {}
        selected_assets = list(data.get("selected_assets") or [])[:12]
        selected_actors = list(data.get("selected_actors") or [])[:12]
        relevant_blueprints = [str(x) for x in (data.get("blueprints") or [])[:6]]
        relevant_assets = [
            str(x)
            for x in (
                (data.get("selected_assets") or [])[:6]
                or (data.get("skeletal_meshes") or [])[:6]
            )
        ]
        
        candidate_funcs = []
        try:
            from tech_connector.services.workflow_service import resolve_workflow_intent
            plan_res = resolve_workflow_intent(task_text, [str(self.project_root)])
            if plan_res and plan_res.get("steps"):
                for step in plan_res["steps"]:
                    sym = step.get("symbol") or {}
                    if sym.get("name"):
                        candidate_funcs.append({
                            "name": sym.get("name"),
                            "qualified_name": sym.get("qualified_name") or sym.get("name"),
                            "file_path": sym.get("file_path"),
                            "signature": sym.get("signature") or "",
                            "docstring": sym.get("docstring") or "",
                        })
        except Exception:
            pass

        selected_folders = list(data.get("selected_folders") or scan.get("selected_folders") or ["/Game"])
        summary_items = [
            f"Unreal {'connected' if scan.get('connected') else 'cached'}",
            f"Project: {(data.get('open_project') or {}).get('project_name') or health.get('project_name') or 'unknown'}",
            f"Level: {data.get('loaded_level') or health.get('loaded_level') or 'unknown'}",
            f"Selected assets: {len(selected_assets)}",
            f"Selected actors: {len(selected_actors)}",
            f"Selected folders: {len(selected_folders)}",
        ]
        if candidate_funcs:
            summary_items.append(f"Candidate functions: {', '.join(f['name'] for f in candidate_funcs[:3])}")

        return {
            "summary": " | ".join(summary_items),
            "engine_version": health.get("engine_version"),
            "loaded_level": data.get("loaded_level") or health.get("loaded_level"),
            "selected_assets": selected_assets,
            "selected_actors": selected_actors,
            "selected_folders": selected_folders,
            "relevant_assets": relevant_assets,
            "relevant_blueprints": relevant_blueprints,
            "candidate_functions": candidate_funcs,
            "available_capabilities": list(data.get("available_tools") or [])[:12],
            "recent_errors": [str(x) for x in (scan.get("warnings") or [])[:6]],
            "enabled_plugins": list(data.get("enabled_plugins") or [])[:20],
            "recommended_model": route.tier,
            "recommended_model_name": route.model,
            "request_id": (self.bridge.get_last_request_status() or {}).get(
                "request_id"
            ),
            "health": self.health_summary(),
            "cache_used": True,
            "fast_path": True,
        }

    def build_unreal_context(
        self, task_text: str, max_tokens: int = 8000
    ) -> Dict[str, Any]:
        mode = (
            "quick"
            if self.should_use_fast_path(task_text)
            else ("standard" if max_tokens >= 4000 else "quick")
        )
        scan = self.scan_all(mode=mode)
        data = scan.get("data") or {}
        health = data.get("health") or {}
        selected_assets = list(data.get("selected_assets") or [])[:25]
        selected_actors = list(data.get("selected_actors") or [])[:25]
        relevant_assets: list[str] = []
        relevant_blueprints: list[str] = []
        keywords = [
            term.lower() for term in (task_text or "").split() if len(term) > 2
        ][:16]
        for asset in data.get("blueprints") or []:
            text = str(asset)
            if any(term in text.lower() for term in keywords):
                relevant_blueprints.append(text)
        for bucket in (
            (data.get("skeletal_meshes") or [])
            + (data.get("animations") or [])
            + (data.get("selected_assets") or [])
        ):
            text = str(bucket)
            if any(term in text.lower() for term in keywords):
                relevant_assets.append(text)
        if not relevant_assets:
            relevant_assets = [str(x) for x in (data.get("selected_assets") or [])[:10]]
        if not relevant_blueprints:
            relevant_blueprints = [str(x) for x in (data.get("blueprints") or [])[:10]]
        route = AIRouter.route_prompt(task_text or "unreal task")
        
        candidate_funcs = []
        try:
            from tech_connector.services.workflow_service import resolve_workflow_intent
            plan_res = resolve_workflow_intent(task_text, [str(self.project_root)])
            if plan_res and plan_res.get("steps"):
                for step in plan_res["steps"]:
                    sym = step.get("symbol") or {}
                    if sym.get("name"):
                        candidate_funcs.append({
                            "name": sym.get("name"),
                            "qualified_name": sym.get("qualified_name") or sym.get("name"),
                            "file_path": sym.get("file_path"),
                            "signature": sym.get("signature") or "",
                            "docstring": sym.get("docstring") or "",
                        })
        except Exception:
            pass

        selected_folders = list(data.get("selected_folders") or scan.get("selected_folders") or ["/Game"])
        summary_parts = [
            f"Unreal {'connected' if scan.get('connected') else 'offline'}",
            f"Project: {(data.get('open_project') or {}).get('project_name') or health.get('project_name') or 'unknown'}",
            f"Level: {data.get('loaded_level') or health.get('loaded_level') or 'unknown'}",
            f"Selected assets: {len(selected_assets)}",
            f"Selected actors: {len(selected_actors)}",
            f"Selected folders: {len(selected_folders)}",
            f"Relevant blueprints: {len(relevant_blueprints)}",
            f"Relevant assets: {len(relevant_assets)}",
        ]
        if candidate_funcs:
            summary_parts.append(f"Candidate functions: {', '.join(f['name'] for f in candidate_funcs[:3])}")

        return {
            "summary": " | ".join(summary_parts),
            "engine_version": health.get("engine_version"),
            "loaded_level": data.get("loaded_level") or health.get("loaded_level"),
            "selected_assets": selected_assets,
            "selected_actors": selected_actors,
            "selected_folders": selected_folders,
            "relevant_assets": relevant_assets[:20],
            "relevant_blueprints": relevant_blueprints[:20],
            "candidate_functions": candidate_funcs,
            "available_capabilities": list(data.get("available_tools") or [])[:20],
            "recent_errors": [str(x) for x in (scan.get("warnings") or [])[:10]],
            "enabled_plugins": list(data.get("enabled_plugins") or [])[:50],
            "recommended_model": route.tier,
            "recommended_model_name": route.model,
            "request_id": (self.bridge.get_last_request_status() or {}).get(
                "request_id"
            ),
            "health": self.health_summary(),
        }

    def build_context_summary(self) -> str:
        idx = self._cache or self.load_cached()
        if not idx:
            scan = self.scan_all(mode="quick")
            idx = scan.get("data") or scan
        if not idx:
            return "Unreal context summary:\n- Live bridge: unavailable\n- Cache used: no\n- Warnings: no project state available"

        health = idx.get("health") or {}
        counts = idx.get("asset_counts") or {}
        selected_assets = idx.get("selected_assets") or []
        selected_actors = idx.get("selected_actors") or []
        warnings = idx.get("warnings") or []
        lines = [
            "Unreal context summary:",
            f"- Live bridge: {'connected' if health.get('connected') else 'not connected'}",
            f"- Scan mode: {idx.get('mode', 'cached')}",
            f"- Project: {(idx.get('open_project') or {}).get('project_name') or health.get('project_name') or 'unknown'}",
            f"- Level: {idx.get('loaded_level') or health.get('loaded_level') or 'unknown'}",
            f"- Selected actors: {len(selected_actors)}",
            f"- Selected assets: {len(selected_assets)}",
            f"- Asset counts: Blueprints {counts.get('Blueprint', len(idx.get('blueprints') or []))}, "
            f"Skeletal Meshes {counts.get('SkeletalMesh', len(idx.get('skeletal_meshes') or []))}, "
            f"Animations {counts.get('AnimSequence', len(idx.get('animations') or []))}",
            f"- Intelligence DB: {'ready' if (self.project_root / INTELLIGENCE_CACHE_FILE).exists() else 'missing'}",
            f"- Cache used: {'yes' if idx.get('cache_used') else 'no'}",
        ]
        if warnings:
            lines.append("- Warnings: " + "; ".join(str(w) for w in warnings[:3]))
        return "\n".join(lines)


if __name__ == "__main__":
    scanner = UnrealScanner()
    print("Scanning Unreal project state...")
    result = scanner.scan_all(mode="quick")
    print(json.dumps(result, indent=2, default=str))
    print(scanner.build_context_summary())
