from __future__ import annotations

"""Unreal typed resolver client.

The desktop app cannot hold live Unreal UObject references. This module sends
small resolver scripts through the existing Unreal HTTP bridge and performs the
actual object lookup inside Unreal's Python interpreter. Returned values are
serializable handles; mutations resolve handles back into live objects in the
same Unreal-side script before calling APIs that require UObject/Actor/etc.
"""

import json
from typing import Any


_UNREAL_RESOLVER_RUNTIME = r'''
import json
import importlib
import unreal


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    try:
        if hasattr(value, "get_path_name"):
            return value.get_path_name()
        if hasattr(value, "get_name"):
            return value.get_name()
    except Exception:
        pass
    return str(value)


def _package_path(path):
    return str(path or "").split(".", 1)[0]


def _asset_name_from_path(path):
    text = str(path or "")
    if "." in text:
        return text.rsplit(".", 1)[-1]
    return text.rstrip("/").rsplit("/", 1)[-1]


def _object_path_from_data(data):
    try:
        object_path = str(data.object_path)
        if object_path:
            return object_path
    except Exception:
        pass
    try:
        package_name = str(data.package_name)
        asset_name = str(data.asset_name)
        if package_name and asset_name:
            return package_name + "." + asset_name
    except Exception:
        pass
    try:
        asset = data.get_asset()
        if asset:
            return asset.get_path_name()
    except Exception:
        pass
    return ""


def _asset_class_name(data_or_asset):
    try:
        return str(data_or_asset.asset_class_path.asset_name)
    except Exception:
        pass
    try:
        return str(data_or_asset.asset_class)
    except Exception:
        pass
    try:
        return data_or_asset.get_class().get_name()
    except Exception:
        return ""


def _load_asset_from_path(path):
    if not path:
        return None
    text = str(path).strip()
    package = _package_path(text)
    for candidate in (text, package):
        try:
            if candidate and unreal.EditorAssetLibrary.does_asset_exist(candidate):
                asset = unreal.EditorAssetLibrary.load_asset(candidate)
                if asset:
                    return asset
        except Exception:
            pass
        try:
            asset = unreal.load_asset(candidate)
            if asset:
                return asset
        except Exception:
            pass
    try:
        return unreal.load_object(None, text)
    except Exception:
        return None


def _asset_handle(asset, source=""):
    if not asset:
        return None
    try:
        path = asset.get_path_name()
    except Exception:
        path = str(asset)
    return {
        "dcc": "unreal",
        "kind": "asset",
        "ref": _package_path(path),
        "path": _package_path(path),
        "object_path": path,
        "name": asset.get_name() if hasattr(asset, "get_name") else _asset_name_from_path(path),
        "class": asset.get_class().get_name() if hasattr(asset, "get_class") else "",
        "source": source,
        "confidence": 1.0,
    }


def _actor_handle(actor, source=""):
    if not actor:
        return None
    try:
        path = actor.get_path_name()
    except Exception:
        path = str(actor)
    try:
        label = actor.get_actor_label()
    except Exception:
        label = ""
    try:
        tags = [str(t) for t in getattr(actor, "tags", [])]
    except Exception:
        tags = []
    return {
        "dcc": "unreal",
        "kind": "actor",
        "ref": path,
        "path": path,
        "name": actor.get_name() if hasattr(actor, "get_name") else path.rsplit('.', 1)[-1],
        "label": label,
        "class": actor.get_class().get_name() if hasattr(actor, "get_class") else "",
        "tags": tags,
        "source": source,
        "confidence": 1.0,
    }


def _component_handle(component, actor=None, source=""):
    if not component:
        return None
    try:
        path = component.get_path_name()
    except Exception:
        path = str(component)
    return {
        "dcc": "unreal",
        "kind": "component",
        "ref": path,
        "path": path,
        "name": component.get_name() if hasattr(component, "get_name") else path.rsplit('.', 1)[-1],
        "class": component.get_class().get_name() if hasattr(component, "get_class") else "",
        "owner": _actor_handle(actor, source="owner") if actor else None,
        "source": source,
        "confidence": 1.0,
    }


def _extract_query_string(query):
    if isinstance(query, str):
        return query
    if isinstance(query, dict):
        for key in ("path", "ref", "asset_path", "created_asset", "target_asset", "actor_path", "actor", "blueprint_path", "name", "label"):
            if key in query and isinstance(query[key], str) and query[key]:
                return query[key]
        for val in query.values():
            if isinstance(val, str) and val:
                return val
    if isinstance(query, list) and query:
        return _extract_query_string(query[0])
    return str(query or "")


def resolve_asset(query, expected_class="", directory="/Game", allow_engine=False):
    text = _extract_query_string(query).strip()
    out = {"query": text, "expected_class": expected_class, "matches": [], "warnings": []}
    if not text:
        out["warnings"].append("empty asset query")
        return out

    loaded = _load_asset_from_path(text)
    if loaded:
        cls = loaded.get_class().get_name() if hasattr(loaded, "get_class") else ""
        if not expected_class or expected_class.lower() in cls.lower() or cls.lower() in expected_class.lower():
            out["matches"].append(_asset_handle(loaded, source="direct_load"))
            return out

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        assets = registry.get_assets_by_path(directory or "/Game", recursive=True)
    except Exception:
        assets = registry.get_all_assets(True)
    needle = text.lower().replace(".uasset", "")
    candidates = []
    for data in assets:
        try:
            package = str(data.package_name)
            name = str(data.asset_name)
            object_path = _object_path_from_data(data)
            cls = _asset_class_name(data)
            if not allow_engine and (package.startswith("/Engine") or "/Engine/" in package):
                continue
            if expected_class and expected_class.lower() not in cls.lower():
                continue
            hay = f"{name} {package} {object_path}".lower()
            score = 0
            if needle == name.lower():
                score += 100
            if needle == package.lower() or needle == object_path.lower():
                score += 90
            if needle in hay:
                score += 25
            if needle.replace("_", "") in hay.replace("_", ""):
                score += 10
            if score:
                candidates.append((score, data))
        except Exception:
            pass
    candidates.sort(key=lambda x: x[0], reverse=True)
    for score, data in candidates[:20]:
        asset = None
        try:
            asset = data.get_asset()
        except Exception:
            pass
        if not asset:
            asset = _load_asset_from_path(_object_path_from_data(data))
        handle = _asset_handle(asset, source="asset_registry") if asset else {
            "dcc": "unreal", "kind": "asset", "ref": str(data.package_name), "path": str(data.package_name),
            "object_path": _object_path_from_data(data), "name": str(data.asset_name), "class": _asset_class_name(data),
            "source": "asset_registry_unloaded", "confidence": min(1.0, float(score) / 100.0)
        }
        if handle:
            handle["score"] = score
            out["matches"].append(handle)
    return out


def _selected_actors():
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        if subsystem:
            return list(subsystem.get_selected_level_actors() or [])
    except Exception:
        pass
    try:
        return list(unreal.EditorLevelLibrary.get_selected_level_actors() or [])
    except Exception:
        return []


def _all_level_actors():
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        if subsystem and hasattr(subsystem, "get_all_level_actors"):
            return list(subsystem.get_all_level_actors() or [])
    except Exception:
        pass
    try:
        return list(unreal.EditorLevelLibrary.get_all_level_actors() or [])
    except Exception:
        return []


def _actor_matches_asset(actor, asset):
    if not actor or not asset:
        return False
    try:
        generated_class = asset.generated_class() if hasattr(asset, "generated_class") else None
        if generated_class and actor.get_class() == generated_class:
            return True
        if generated_class and actor.get_class().is_child_of(generated_class):
            return True
    except Exception:
        pass
    try:
        asset_path = _package_path(asset.get_path_name()).lower()
        for comp in actor.get_components_by_class(unreal.ActorComponent) or []:
            for prop in ("skeletal_mesh", "static_mesh", "mesh", "animation", "anim_class", "niagara_system", "template"):
                try:
                    value = comp.get_editor_property(prop)
                    if value and hasattr(value, "get_path_name") and _package_path(value.get_path_name()).lower() == asset_path:
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    return False


def resolve_actor(query="selected", allow_asset_lookup=True):
    text = _extract_query_string(query or "selected").strip()
    out = {"query": text, "matches": [], "warnings": []}
    q = text.lower()
    if q in {"", "selected", "selection", "current", "same", "same actor", "that", "it"}:
        out["matches"] = [_actor_handle(a, source="selected") for a in _selected_actors() if a]
        return out

    actors = _all_level_actors()
    scored = []
    for actor in actors:
        try:
            name = actor.get_name()
            label = actor.get_actor_label()
            path = actor.get_path_name()
            cls = actor.get_class().get_name()
            tags = [str(t) for t in getattr(actor, "tags", [])]
            hay = f"{name} {label} {path} {cls} {' '.join(tags)}".lower()
            score = 0
            if q == name.lower() or q == label.lower() or q == path.lower():
                score += 100
            if q in hay:
                score += 25
            if q.replace("_", "") in hay.replace("_", ""):
                score += 10
            if score:
                scored.append((score, actor))
        except Exception:
            pass

    if allow_asset_lookup and not scored:
        asset_result = resolve_asset(text, directory="/Game")
        for item in asset_result.get("matches", [])[:5]:
            asset = _load_asset_from_path(item.get("object_path") or item.get("path") or item.get("ref"))
            if not asset:
                continue
            for actor in actors:
                if _actor_matches_asset(actor, asset):
                    scored.append((80, actor))

    scored.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    for score, actor in scored[:20]:
        handle = _actor_handle(actor, source="level_scan")
        if not handle or handle["path"] in seen:
            continue
        seen.add(handle["path"])
        handle["score"] = score
        out["matches"].append(handle)
    return out


def resolve_component(owner_query="selected", component_query="", component_class=""):
    out = {"owner_query": owner_query, "component_query": component_query, "component_class": component_class, "matches": [], "warnings": []}
    owners = resolve_actor(owner_query).get("matches", [])
    actor_paths = [item.get("path") for item in owners]
    actors = []
    for a in _all_level_actors():
        try:
            if a.get_path_name() in actor_paths:
                actors.append(a)
        except Exception:
            pass
    needle = str(component_query or "").lower()
    cls_filter = str(component_class or "").lower()
    for actor in actors:
        try:
            components = actor.get_components_by_class(unreal.ActorComponent) or []
        except Exception:
            components = []
        for comp in components:
            try:
                name = comp.get_name()
                cls = comp.get_class().get_name()
                path = comp.get_path_name()
                hay = f"{name} {cls} {path}".lower()
                if cls_filter and cls_filter not in cls.lower():
                    continue
                if needle and needle not in hay and needle.replace("_", "") not in hay.replace("_", ""):
                    continue
                out["matches"].append(_component_handle(comp, actor=actor, source="component_scan"))
            except Exception:
                pass
    return out


def select_actors(query):
    queries = query if isinstance(query, list) else [query]
    matches = []
    path_to_actor = {}
    for actor in _all_level_actors():
        try:
            path_to_actor[actor.get_path_name()] = actor
        except Exception:
            pass
    for item in queries:
        result = resolve_actor(item)
        for handle in result.get("matches", [])[:1]:
            actor = path_to_actor.get(handle.get("path"))
            if actor and actor not in matches:
                matches.append(actor)
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if subsystem:
        subsystem.set_selected_level_actors(matches)
    else:
        unreal.EditorLevelLibrary.set_selected_level_actors(matches)
    return {"selected_count": len(matches), "selected_actors": [_actor_handle(a, source="selected_after_set") for a in matches]}


def set_actor_property(actor_query, property_name, value):
    result = resolve_actor(actor_query)
    if not result.get("matches"):
        return {"ok": False, "error": "No actor matched", "query": actor_query}
    target_path = result["matches"][0].get("path")
    actor = None
    for candidate in _all_level_actors():
        try:
            if candidate.get_path_name() == target_path:
                actor = candidate
                break
        except Exception:
            pass
    if not actor:
        return {"ok": False, "error": "Resolved actor handle could not be reloaded", "handle": result["matches"][0]}
    try:
        old = actor.get_editor_property(property_name)
    except Exception:
        old = None
    try:
        actor.set_editor_property(property_name, value)
        actor.modify()
        return {"ok": True, "actor": _actor_handle(actor), "property": property_name, "old_value": _jsonable(old), "new_value": _jsonable(value)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "actor": _actor_handle(actor), "property": property_name}


def resolve_control_rig(query):
    asset_result = resolve_asset(query, expected_class="ControlRig")
    if not asset_result.get("matches"):
        asset_result = resolve_asset(query, expected_class="Blueprint")
    matches = []
    for handle in asset_result.get("matches", []):
        asset = _load_asset_from_path(handle.get("object_path") or handle.get("path") or handle.get("ref"))
        if not asset:
            continue
        item = dict(handle)
        try:
            generated = asset.generated_class() if hasattr(asset, "generated_class") else None
            item["generated_class"] = generated.get_name() if generated and hasattr(generated, "get_name") else str(generated or "")
        except Exception as exc:
            item.setdefault("warnings", []).append("generated_class:" + str(exc))
        matches.append(item)
    return {"query": query, "matches": matches}


def _import_function(function_path):
    module_path, func_name = function_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def call_function_resolved(function_path, args=None, kwargs=None, contracts=None):
    args = list(args or [])
    kwargs = dict(kwargs or {})
    contracts = list(contracts or [])
    resolved = {}
    for contract in contracts:
        name = contract.get("name") or contract.get("param")
        kind = contract.get("kind")
        source = contract.get("source", kwargs.get(name, "selected"))
        if not name or not kind:
            continue
        if kind == "asset":
            match = resolve_asset(source, expected_class=contract.get("expected_class", "")).get("matches", [])
            if match:
                kwargs[name] = _load_asset_from_path(match[0].get("object_path") or match[0].get("path"))
                resolved[name] = match[0]
        elif kind == "asset_path":
            match = resolve_asset(source, expected_class=contract.get("expected_class", "")).get("matches", [])
            if match:
                kwargs[name] = match[0].get("path") or match[0].get("ref")
                resolved[name] = match[0]
        elif kind == "actor":
            match = resolve_actor(source).get("matches", [])
            if match:
                actor_path = match[0].get("path")
                for actor in _all_level_actors():
                    try:
                        if actor.get_path_name() == actor_path:
                            kwargs[name] = actor
                            resolved[name] = match[0]
                            break
                    except Exception:
                        pass
        elif kind == "component":
            match = resolve_component(contract.get("owner", "selected"), source, contract.get("component_class", "")).get("matches", [])
            if match:
                comp_path = match[0].get("path")
                owner_path = ((match[0].get("owner") or {}).get("path"))
                found = False
                for actor in _all_level_actors():
                    try:
                        if owner_path and actor.get_path_name() != owner_path:
                            continue
                        for comp in actor.get_components_by_class(unreal.ActorComponent) or []:
                            if comp.get_path_name() == comp_path:
                                kwargs[name] = comp
                                resolved[name] = match[0]
                                found = True
                                break
                        if found:
                            break
                    except Exception:
                        pass
    func = _import_function(function_path)
    result = func(*args, **kwargs)
    return {"ok": True, "function": function_path, "resolved": resolved, "result": _jsonable(result)}
'''


class UnrealObjectResolver:
    def __init__(self, bridge):
        self.bridge = bridge

    def _run(self, expression: str, *, timeout: float = 8.0) -> dict[str, Any]:
        source = _UNREAL_RESOLVER_RUNTIME + "\n" + expression
        response = self.bridge.execute_python(source, timeout=timeout, reset_globals=True)
        data = response.get("data")
        if isinstance(data, dict):
            return data
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        stdout = response.get("python_stdout") or ""
        for line in reversed(str(stdout).splitlines()):
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {"ok": bool(response.get("ok")), "data": data, "error": response.get("error"), "raw": response}

    def resolve_asset(self, query: str, *, expected_class: str = "", directory: str = "/Game", timeout: float = 8.0) -> dict[str, Any]:
        return self._run(
            "print(json.dumps(resolve_asset(%r, expected_class=%r, directory=%r)))" % (query, expected_class, directory),
            timeout=timeout,
        )

    def resolve_actor(self, query: str = "selected", *, timeout: float = 5.0) -> dict[str, Any]:
        return self._run("print(json.dumps(resolve_actor(%r)))" % (query,), timeout=timeout)

    def resolve_component(self, owner_query: str = "selected", component_query: str = "", component_class: str = "", *, timeout: float = 6.0) -> dict[str, Any]:
        return self._run(
            "print(json.dumps(resolve_component(%r, %r, %r)))" % (owner_query, component_query, component_class),
            timeout=timeout,
        )

    def resolve_control_rig(self, query: str, *, timeout: float = 8.0) -> dict[str, Any]:
        return self._run("print(json.dumps(resolve_control_rig(%r)))" % (query,), timeout=timeout)

    def select_actors(self, query: str | list[str], *, timeout: float = 5.0) -> dict[str, Any]:
        return self._run("print(json.dumps(select_actors(%s)))" % json.dumps(query), timeout=timeout)

    def set_actor_property(self, actor_query: str, property_name: str, value: Any, *, timeout: float = 5.0) -> dict[str, Any]:
        return self._run(
            "print(json.dumps(set_actor_property(%r, %r, %s)))" % (actor_query, property_name, json.dumps(value)),
            timeout=timeout,
        )

    def call_function_resolved(self, function_path: str, *, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None, contracts: list[dict[str, Any]] | None = None, timeout: float = 30.0) -> dict[str, Any]:
        return self._run(
            "print(json.dumps(call_function_resolved(%r, args=%s, kwargs=%s, contracts=%s)))" % (
                function_path,
                json.dumps(args or []),
                json.dumps(kwargs or {}),
                json.dumps(contracts or []),
            ),
            timeout=timeout,
        )


def _extract_query_string(query: Any) -> str:
    if isinstance(query, str):
        return query
    if isinstance(query, dict):
        for key in ("path", "ref", "asset_path", "created_asset", "target_asset", "actor_path", "actor", "blueprint_path", "name", "label"):
            if key in query and isinstance(query[key], str) and query[key]:
                return query[key]
        for val in query.values():
            if isinstance(val, str) and val:
                return val
    if isinstance(query, list) and query:
        return _extract_query_string(query[0])
    return str(query or "")
