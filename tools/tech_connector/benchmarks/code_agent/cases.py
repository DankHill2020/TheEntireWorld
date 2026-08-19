"""Product-relevant, deterministic code-agent benchmark cases."""

from __future__ import annotations

from .holdout_cases import holdout_cases
from .models import BenchmarkCase


_PACKAGE_INIT = '"""Synthetic Tech Connector benchmark package."""\n'


def _dcc_falsey_case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="dcc_falsey_result",
        title="Preserve valid falsey DCC command results",
        category="dcc_correctness",
        prompt=(
            "Fix connector/dcc/result.py. Modify only that file. "
            "normalize_command_result must treat only None as a missing result; valid falsey "
            "values such as False, 0, an empty string, empty list, and empty dict are successful "
            "values. A mapping with an explicit 'ok' field is already an envelope: return a new "
            "normalized dictionary with exactly ok, value, and error keys, defaulting missing value "
            "to None and missing error to an empty string. Other values become successful envelopes. "
            "Do not mutate input mappings. Keep the public function name and add clear type hints "
            "and a project-style docstring."
        ),
        seed_files={
            "connector/__init__.py": _PACKAGE_INIT,
            "connector/dcc/__init__.py": _PACKAGE_INIT,
            "connector/dcc/result.py": '''"""Normalize replies returned by DCC bridges."""\n\n\ndef normalize_command_result(payload):\n    """Return a common command envelope."""\n\n    if not payload:\n        return {"ok": False, "value": None, "error": "empty result"}\n    if isinstance(payload, dict):\n        return payload\n    return {"ok": True, "value": payload, "error": ""}\n''',
        },
        allowed_paths=("connector/dcc/result.py",),
        assertion_count=12,
        evaluator_source=r'''from __future__ import annotations
import importlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
module = importlib.import_module("connector.dcc.result")
normalize = module.normalize_command_result
checks = []

def check(condition, label):
    checks.append((bool(condition), label))

missing = normalize(None)
check(missing == {"ok": False, "value": None, "error": "empty result"}, "None is missing")
for value, label in [(False, "false"), (0, "zero"), ("", "empty string"), ([], "empty list"), ({}, "empty mapping")]:
    result = normalize(value)
    check(result == {"ok": True, "value": value, "error": ""}, label)
source = {"ok": False, "error": "host failed", "ignored": 7}
result = normalize(source)
check(result == {"ok": False, "value": None, "error": "host failed"}, "explicit failure envelope")
check(result is not source, "envelope copied")
check(source == {"ok": False, "error": "host failed", "ignored": 7}, "input unchanged")
check(normalize({"ok": True, "value": 0}) == {"ok": True, "value": 0, "error": ""}, "success envelope")
check(normalize((1, 2)) == {"ok": True, "value": (1, 2), "error": ""}, "tuple payload")
annotations = getattr(normalize, "__annotations__", {})
check("payload" in annotations and "return" in annotations, "type hints")
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _shared_path_case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="dcc_shared_path_policy",
        title="Consolidate Blender and Maya export path validation",
        category="dcc_consolidation",
        prompt=(
            "Consolidate the duplicated Blender and Maya export-path logic. Add "
            "connector/dcc/path_policy.py with normalize_export_path(project_root, requested). "
            "Update connector/dcc/blender_adapter.py and connector/dcc/maya_adapter.py to delegate "
            "to it while preserving blender_export_path and maya_export_path. The shared function "
            "must accept str or Path inputs, resolve relative paths below project_root, append .fbx "
            "when the suffix is absent (case-insensitive), reject absolute or relative paths that "
            "escape the resolved project root with ValueError, and return a resolved Path. Do not "
            "touch files outside these three paths. Add type hints and project-style docstrings "
            "using reStructuredText fields (:param name: and :return:)."
        ),
        seed_files={
            "connector/__init__.py": _PACKAGE_INIT,
            "connector/dcc/__init__.py": _PACKAGE_INIT,
            "connector/dcc/blender_adapter.py": '''"""Blender export path helpers."""\nfrom pathlib import Path\n\n\ndef blender_export_path(project_root, requested):\n    path = Path(project_root) / requested\n    if path.suffix != ".fbx":\n        path = path.with_suffix(".fbx")\n    return path\n''',
            "connector/dcc/maya_adapter.py": '''"""Maya export path helpers."""\nfrom pathlib import Path\n\n\ndef maya_export_path(project_root, requested):\n    path = Path(requested)\n    if not path.is_absolute():\n        path = Path(project_root) / path\n    return path.resolve()\n''',
        },
        allowed_paths=(
            "connector/dcc/path_policy.py",
            "connector/dcc/blender_adapter.py",
            "connector/dcc/maya_adapter.py",
        ),
        assertion_count=21,
        evaluator_source=r'''from __future__ import annotations
import importlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

workspace = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(workspace))
policy = importlib.import_module("connector.dcc.path_policy")
blender = importlib.import_module("connector.dcc.blender_adapter")
maya = importlib.import_module("connector.dcc.maya_adapter")
checks = []

def check(condition, label):
    checks.append((bool(condition), label))

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp).resolve()
    expected = (root / "exports" / "hero.fbx").resolve()
    check(policy.normalize_export_path(root, "exports/hero") == expected, "relative suffix")
    mixed_case = policy.normalize_export_path(str(root), Path("exports/hero.FBX"))
    check(mixed_case.name == "hero.FBX", "case-insensitive suffix preserved")
    check(policy.normalize_export_path(root, "exports/hero.obj") == (root / "exports" / "hero.obj").resolve(), "existing non-FBX suffix preserved")
    previous_cwd = Path.cwd()
    os.chdir(root)
    try:
        relative_root_result = policy.normalize_export_path("relative_project", "exports/hero")
    except Exception:
        check(False, "relative project root")
    else:
        check(relative_root_result == (root / "relative_project" / "exports" / "hero.fbx").resolve(), "relative project root")
    finally:
        os.chdir(previous_cwd)
    check(blender.blender_export_path(root, "exports/hero") == expected, "blender delegates")
    check(maya.maya_export_path(root, "exports/hero") == expected, "maya delegates")
    check(isinstance(blender.blender_export_path(root, "hero"), Path), "blender returns Path")
    check(isinstance(maya.maya_export_path(root, Path("hero")), Path), "maya accepts Path")
    for function, label in [
        (policy.normalize_export_path, "policy relative escape"),
        (blender.blender_export_path, "blender relative escape"),
        (maya.maya_export_path, "maya relative escape"),
    ]:
        try:
            function(root, "../outside")
        except ValueError:
            check(True, label)
        else:
            check(False, label)
    outside = root.parent / "outside.fbx"
    try:
        policy.normalize_export_path(root, outside)
    except ValueError:
        check(True, "absolute escape")
    else:
        check(False, "absolute escape")
    check("normalize_export_path" in Path(blender.__file__).read_text(encoding="utf-8"), "blender shared import")
    check("normalize_export_path" in Path(maya.__file__).read_text(encoding="utf-8"), "maya shared import")
    annotations = policy.normalize_export_path.__annotations__
    check("project_root" in annotations and "requested" in annotations, "parameter hints")
    check("return" in annotations, "return hint")
    for function, label in [
        (blender.blender_export_path, "blender useful path hints"),
        (maya.maya_export_path, "maya useful path hints"),
    ]:
        adapter_annotations = function.__annotations__
        parameter_hints = " ".join(
            str(adapter_annotations.get(name, ""))
            for name in ("project_root", "requested")
        )
        return_hint = str(adapter_annotations.get("return", ""))
        check(
            "str" in parameter_hints
            and "Path" in parameter_hints
            and "Path" in return_hint
            and "object" not in parameter_hints,
            label,
        )
    for function, label in [
        (policy.normalize_export_path, "policy project docstring"),
        (blender.blender_export_path, "blender project docstring"),
        (maya.maya_export_path, "maya project docstring"),
    ]:
        docstring = inspect.getdoc(function) or ""
        check(
            ":param project_root:" in docstring
            and ":param requested:" in docstring
            and ":return:" in docstring,
            label,
        )
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _image_cache_case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="image_viewer_lru_cache",
        title="Repair the image viewer LRU cache",
        category="image_viewer_performance",
        prompt=(
            "Repair connector/image_viewer/cache.py without changing its public class name. "
            "ImageCache(capacity, ttl_seconds, clock=time.monotonic) must reject capacities below "
            "one, provide thread-safe put(key, value), get(key, default=None), clear(), and __len__(), "
            "preserve falsey values, expire entries lazily when age is at least ttl_seconds, and "
            "evict the least-recently-used live entry when capacity is exceeded. A successful get "
            "refreshes recency but not the TTL timestamp. Keep operations effectively O(1), add type "
            "hints and project-style docstrings, and modify only this file."
        ),
        seed_files={
            "connector/__init__.py": _PACKAGE_INIT,
            "connector/image_viewer/__init__.py": _PACKAGE_INIT,
            "connector/image_viewer/cache.py": '''"""Small image preview cache."""\n\n\nclass ImageCache:\n    def __init__(self, capacity=16):\n        self.capacity = capacity\n        self.items = {}\n\n    def put(self, key, value):\n        self.items[key] = value\n\n    def get(self, key, default=None):\n        return self.items.get(key) or default\n''',
        },
        allowed_paths=("connector/image_viewer/cache.py",),
        assertion_count=15,
        evaluator_source=r'''from __future__ import annotations
import importlib
import json
import sys
import threading
import time
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
ImageCache = importlib.import_module("connector.image_viewer.cache").ImageCache
checks = []
def check(condition, label): checks.append((bool(condition), label))

try:
    ImageCache(0, 1)
except ValueError: check(True, "capacity validation")
else: check(False, "capacity validation")
now = [10.0]
cache = ImageCache(2, 5.0, clock=lambda: now[0])
cache.put("zero", 0); cache.put("false", False)
check(cache.get("zero", 9) == 0, "zero preserved")
check(cache.get("false", True) is False, "false preserved")
check(len(cache) == 2, "length")
cache.get("zero"); cache.put("third", 3)
check(cache.get("false", "miss") == "miss", "LRU eviction")
check(cache.get("zero") == 0 and cache.get("third") == 3, "live entries")
now[0] = 15.0
check(cache.get("zero", "expired") == "expired", "TTL boundary")
check(cache.get("third", "expired") == "expired", "lazy expiry")
check(len(cache) == 0, "expired length cleanup")
cache.put("x", 1); cache.clear(); check(len(cache) == 0, "clear")
cache = ImageCache(64, 60.0)
errors = []
def worker(offset):
    try:
        for index in range(1000):
            key = (offset + index) % 128
            cache.put(key, index)
            cache.get(key)
    except Exception as exc: errors.append(repr(exc))
threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
started = time.perf_counter()
for thread in threads: thread.start()
for thread in threads: thread.join(3)
elapsed = time.perf_counter() - started
check(not errors, "concurrent errors")
check(all(not thread.is_alive() for thread in threads), "no deadlock")
check(len(cache) <= 64, "bounded capacity")
check(elapsed < 3.0, "operation performance")
annotations = ImageCache.get.__annotations__
check("key" in annotations and "return" in annotations, "method type hints")
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok], "concurrency_seconds": elapsed}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _command_registry_case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="game_engine_command_registry",
        title="Harden the game-engine command registry",
        category="game_engine_functionality",
        prompt=(
            "Complete connector/game_engine/command_registry.py. CommandRegistry.register(name, "
            "handler, aliases=(), capabilities=()) must normalize names with strip and casefold, "
            "reject blank names, non-callable handlers, and duplicate canonical names or aliases "
            "with ValueError, and atomically register a command. resolve(name, available_capabilities=()) "
            "must resolve aliases, raise KeyError for unknown commands, raise PermissionError listing "
            "missing capabilities, and return the handler. list_commands() returns sorted canonical "
            "names only. Make registration, resolution, and listing thread-safe, preserve the public "
            "class and method names, add type hints and project-style docstrings, and modify only this file."
        ),
        seed_files={
            "connector/__init__.py": _PACKAGE_INIT,
            "connector/game_engine/__init__.py": _PACKAGE_INIT,
            "connector/game_engine/command_registry.py": '''"""Runtime command registry."""\n\n\nclass CommandRegistry:\n    def __init__(self):\n        self.commands = {}\n\n    def register(self, name, handler, aliases=(), capabilities=()):\n        self.commands[name] = handler\n\n    def resolve(self, name, available_capabilities=()):\n        return self.commands[name]\n\n    def list_commands(self):\n        return list(self.commands)\n''',
        },
        allowed_paths=("connector/game_engine/command_registry.py",),
        assertion_count=15,
        evaluator_source=r'''from __future__ import annotations
import importlib, json, sys, threading
from pathlib import Path
root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
Registry = importlib.import_module("connector.game_engine.command_registry").CommandRegistry
checks = []
def check(condition, label): checks.append((bool(condition), label))
registry = Registry(); alpha = lambda: "a"; beta = lambda: "b"
registry.register(" Spawn ", alpha, aliases=("Create",), capabilities=("world.write",))
check(registry.list_commands() == ["spawn"], "canonical listing")
check(registry.resolve(" CREATE ", ("world.write",)) is alpha, "alias normalization")
try: registry.resolve("spawn")
except PermissionError as exc: check("world.write" in str(exc), "capability error")
else: check(False, "capability error")
for action, label in [
    (lambda: registry.register("spawn", beta), "duplicate name"),
    (lambda: registry.register("other", beta, aliases=("create",)), "duplicate alias"),
    (lambda: registry.register("", beta), "blank name"),
    (lambda: registry.register("bad", 4), "callable validation"),
]:
    try: action()
    except ValueError: check(True, label)
    else: check(False, label)
check(registry.list_commands() == ["spawn"], "atomic rejected registration")
try: registry.resolve("missing")
except KeyError: check(True, "unknown command")
else: check(False, "unknown command")
registry.register("beta", beta); check(registry.list_commands() == ["beta", "spawn"], "sorted listing")
errors = []
def add(index):
    try: registry.register(f"cmd-{index}", lambda: None, aliases=(f"alias-{index}",))
    except Exception as exc: errors.append(repr(exc))
threads = [threading.Thread(target=add, args=(i,)) for i in range(20)]
for thread in threads: thread.start()
for thread in threads: thread.join(2)
check(not errors, "concurrent registration")
check(all(not thread.is_alive() for thread in threads), "no deadlock")
check(len(registry.list_commands()) == 22, "all registrations retained")
check(registry.resolve("ALIAS-19")() is None, "concurrent alias")
annotations = Registry.register.__annotations__
check("name" in annotations and "return" in annotations, "type hints")
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _operation_contract_case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="game_engine_operation_contract",
        title="Align game-engine planner, registry, wrapper, and executor contracts",
        category="game_engine_integration",
        prompt=(
            "Repair the asset-configuration operation contract across "
            "connector/game_engine/operations.py, planner.py, wrappers.py, and executor.py. "
            "Keep the existing public names. OPERATIONS['asset.configure'] must target "
            "connector.game_engine.wrappers.configure_asset, require exactly asset_path and "
            "value, and default save to True. plan_asset_configuration must return a fresh "
            "request containing that operation and canonical parameters without pre-serializing "
            "value. build_operation_call must reject unknown operations with KeyError, report "
            "all missing or unexpected parameter names with TypeError, apply optional defaults, "
            "and never mutate either caller parameters or shared defaults. execute_operation must "
            "resolve and call the registered wrapper rather than a native host method. The wrapper "
            "must reject a blank/non-string asset_path, JSON-serialize value exactly once, forward "
            "save as bool, and call host_api.NativeLibrary.configure_asset. Preserve native return "
            "values including falsey ones. Modify only these four files and add useful type hints "
            "and reStructuredText-style project docstrings using :param name: and :return: "
            "fields."
        ),
        seed_files={
            "connector/__init__.py": _PACKAGE_INIT,
            "connector/game_engine/__init__.py": _PACKAGE_INIT,
            "connector/game_engine/operations.py": '''"""Game-engine operation metadata."""\n\nfrom dataclasses import dataclass\nfrom typing import Any\n\n\n@dataclass(frozen=True)\nclass OperationSpec:\n    function_path: str\n    required: tuple[str, ...]\n    optional: dict[str, Any]\n\n\nOPERATIONS = {\n    "asset.configure": OperationSpec(\n        "host_api.NativeLibrary.configure_asset",\n        ("asset", "value_json"),\n        {"save": True},\n    )\n}\n\n\ndef build_operation_call(name, params):\n    spec = OPERATIONS[name]\n    kwargs = spec.optional\n    kwargs.update(params)\n    return spec.function_path, kwargs\n''',
            "connector/game_engine/planner.py": '''"""Build game-engine operation requests."""\n\nimport json\n\n\ndef plan_asset_configuration(asset_path, value, save=True):\n    return {\n        "operation": "asset.configure",\n        "params": {\n            "asset": asset_path,\n            "value_json": json.dumps(value),\n            "save": save,\n        },\n    }\n''',
            "connector/game_engine/wrappers.py": '''"""Validated wrappers around native game-engine APIs."""\n\nimport json\n\n\ndef configure_asset(asset_path, value, save=True):\n    import host_api\n\n    return host_api.NativeLibrary.configure_asset(\n        asset_path, json.dumps(value), save\n    )\n''',
            "connector/game_engine/executor.py": '''"""Execute registered game-engine operations."""\n\nimport importlib\n\nfrom .operations import build_operation_call\n\n\ndef execute_operation(request):\n    function_path, kwargs = build_operation_call(\n        request["operation"], request["params"]\n    )\n    module_name, function_name = function_path.rsplit(".", 1)\n    function = getattr(importlib.import_module(module_name), function_name)\n    return function(**kwargs)\n''',
        },
        allowed_paths=(
            "connector/game_engine/operations.py",
            "connector/game_engine/planner.py",
            "connector/game_engine/wrappers.py",
            "connector/game_engine/executor.py",
        ),
        assertion_count=26,
        evaluator_source=r'''from __future__ import annotations
import importlib
import inspect
import json
import sys
import types
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
operations = importlib.import_module("connector.game_engine.operations")
planner = importlib.import_module("connector.game_engine.planner")
wrappers = importlib.import_module("connector.game_engine.wrappers")
executor = importlib.import_module("connector.game_engine.executor")
checks = []

def check(condition, label):
    checks.append((bool(condition), label))

spec = operations.OPERATIONS["asset.configure"]
check(spec.function_path == "connector.game_engine.wrappers.configure_asset", "wrapper target")
check(tuple(spec.required) == ("asset_path", "value"), "canonical required parameters")
check(dict(spec.optional) == {"save": True}, "optional default")

value = {"lod": 2}
request = planner.plan_asset_configuration("/Game/Hero", value, False)
check(request == {"operation": "asset.configure", "params": {"asset_path": "/Game/Hero", "value": value, "save": False}}, "canonical planner request")
check(request["params"]["value"] is value, "planner does not serialize value")
second = planner.plan_asset_configuration("/Game/Other", 0)
check(second["params"] == {"asset_path": "/Game/Other", "value": 0, "save": True}, "fresh planner defaults")

params = {"asset_path": "/Game/Hero", "value": False}
function_path, kwargs = operations.build_operation_call("asset.configure", params)
check(function_path == spec.function_path, "operation call path")
check(kwargs == {"asset_path": "/Game/Hero", "value": False, "save": True}, "operation defaults applied")
check(params == {"asset_path": "/Game/Hero", "value": False}, "caller parameters unchanged")
operations.build_operation_call("asset.configure", {"asset_path": "/Game/A", "value": 1, "save": False})
_, repeated_kwargs = operations.build_operation_call("asset.configure", {"asset_path": "/Game/B", "value": 2})
check(repeated_kwargs["save"] is True and dict(spec.optional) == {"save": True}, "shared defaults unchanged")

try:
    operations.build_operation_call("missing", {})
except KeyError:
    check(True, "unknown operation")
else:
    check(False, "unknown operation")
try:
    operations.build_operation_call("asset.configure", {"save": False})
except TypeError as exc:
    message = str(exc)
    check("asset_path" in message and "value" in message, "all missing parameters reported")
else:
    check(False, "all missing parameters reported")
try:
    operations.build_operation_call("asset.configure", {"asset_path": "x", "value": 1, "extra": 2})
except TypeError as exc:
    check("extra" in str(exc), "unexpected parameter reported")
else:
    check(False, "unexpected parameter reported")

captured = []
original_wrapper = wrappers.configure_asset
def replacement(**received):
    captured.append(received)
    return 0
wrappers.configure_asset = replacement
try:
    executed = executor.execute_operation(request)
finally:
    wrappers.configure_asset = original_wrapper
check(executed == 0, "falsey wrapper return preserved")
check(captured == [{"asset_path": "/Game/Hero", "value": value, "save": False}], "executor routes canonical kwargs")

host_calls = []
class NativeLibrary:
    @staticmethod
    def configure_asset(asset_path, value_json, save):
        host_calls.append((asset_path, value_json, save))
        return False
sys.modules["host_api"] = types.SimpleNamespace(NativeLibrary=NativeLibrary)
check(original_wrapper("/Game/Hero", value, False) is False, "native falsey return preserved")
check(host_calls == [("/Game/Hero", json.dumps(value), False)], "wrapper serializes and forwards once")
before_invalid = list(host_calls)
for invalid in ("", "   ", None, 42):
    try:
        original_wrapper(invalid, value)
    except (TypeError, ValueError):
        pass
    else:
        check(False, "asset path validation")
        break
else:
    check(True, "asset path validation")
check(host_calls == before_invalid, "invalid paths do not call host")
try:
    original_wrapper("/Game/Hero", {object()})
except TypeError:
    check(True, "JSON validation")
else:
    check(False, "JSON validation")
check(host_calls == before_invalid, "invalid values do not call host")

functions = [
    operations.build_operation_call,
    planner.plan_asset_configuration,
    wrappers.configure_asset,
    executor.execute_operation,
]
check(all("return" in function.__annotations__ for function in functions), "return type hints")
check(all(len(inspect.signature(function).parameters) == len(function.__annotations__) - 1 for function in functions), "parameter type hints")
check(all(":return:" in (inspect.getdoc(function) or "") for function in functions), "return docstrings")
check(":param params:" in (inspect.getdoc(operations.build_operation_call) or ""), "operation parameter docstring")
check(":param request:" in (inspect.getdoc(executor.execute_operation) or ""), "executor parameter docstring")

passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _priority_queue_case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="prompt_priority_job_queue",
        title="Repair the prompt job priority queue",
        category="prompt_queue_reliability",
        prompt=(
            "Repair connector/prompt/queue.py and modify only that file. "
            "PriorityJobQueue must provide thread-safe enqueue(job_id, payload, priority=0), "
            "cancel(job_id), pop_next(default=None), and __len__ operations. Job IDs must be "
            "non-blank strings and unique while pending. Priority must be an int but not bool; "
            "lower numeric priorities run first and equal priorities remain FIFO. cancel returns "
            "True only when it removes a pending job, cancelled IDs may be enqueued again, and "
            "pop_next returns the payload while preserving falsey values or returns default when "
            "empty. Keep enqueue and pop effectively O(log n), avoid deadlocks under concurrent "
            "producers, preserve the public class and method names, and add complete type hints "
            "and useful reStructuredText-style docstrings."
        ),
        seed_files={
            "connector/__init__.py": _PACKAGE_INIT,
            "connector/prompt/__init__.py": _PACKAGE_INIT,
            "connector/prompt/queue.py": '''"""Pending prompt jobs."""


class PriorityJobQueue:
    def __init__(self):
        self.jobs = []

    def enqueue(self, job_id, payload, priority=0):
        self.jobs.append((priority, job_id, payload))

    def cancel(self, job_id):
        return False

    def pop_next(self, default=None):
        if not self.jobs:
            return default
        self.jobs.sort()
        return self.jobs.pop(0)[2]

    def __len__(self):
        return len(self.jobs)
''',
        },
        allowed_paths=("connector/prompt/queue.py",),
        assertion_count=18,
        evaluator_source=r'''from __future__ import annotations
import importlib
import inspect
import json
import sys
import threading
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
Queue = importlib.import_module("connector.prompt.queue").PriorityJobQueue
checks = []
def check(condition, label): checks.append((bool(condition), label))

queue = Queue()
for action, label, error_type in [
    (lambda: queue.enqueue("", 1), "blank id", ValueError),
    (lambda: queue.enqueue(4, 1), "non-string id", (TypeError, ValueError)),
    (lambda: queue.enqueue("bad-priority", 1, True), "boolean priority", TypeError),
]:
    try: action()
    except error_type: check(True, label)
    else: check(False, label)

queue.enqueue("later", "later", 5)
queue.enqueue("first-a", 0, 1)
queue.enqueue("first-b", False, 1)
check(queue.pop_next() == 0, "lower priority first")
check(queue.pop_next("missing") is False, "equal priority FIFO and falsey payload")
check(queue.pop_next() == "later", "remaining priority")
check(queue.pop_next("empty") == "empty", "empty default")

queue.enqueue("duplicate", 1)
try: queue.enqueue("duplicate", 2)
except ValueError: check(True, "duplicate pending id")
else: check(False, "duplicate pending id")
check(queue.cancel("duplicate") is True, "cancel pending")
check(queue.cancel("duplicate") is False, "cancel missing")
queue.enqueue("duplicate", 3)
check(queue.pop_next() == 3, "reenqueue cancelled id")

queue = Queue()
errors = []
def producer(offset):
    try:
        for index in range(100):
            queue.enqueue(f"{offset}-{index}", (offset, index), index % 7)
    except Exception as exc:
        errors.append(repr(exc))
threads = [threading.Thread(target=producer, args=(offset,)) for offset in range(6)]
for thread in threads: thread.start()
for thread in threads: thread.join(3)
check(not errors, "concurrent producer errors")
check(all(not thread.is_alive() for thread in threads), "no producer deadlock")
check(len(queue) == 600, "all concurrent jobs retained")
received = [queue.pop_next() for _ in range(600)]
check(len(set(received)) == 600 and len(queue) == 0, "unique concurrent jobs drained")

annotations = Queue.enqueue.__annotations__
check(all(name in annotations for name in ("job_id", "payload", "priority", "return")), "enqueue type hints")
docs = [inspect.getdoc(getattr(Queue, name)) or "" for name in ("enqueue", "cancel", "pop_next")]
check(all(":return:" in doc for doc in docs), "return docstrings")
check(":param job_id:" in docs[0] and ":param payload:" in docs[0] and ":param priority:" in docs[0], "parameter docstrings")

passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def benchmark_cases() -> tuple[BenchmarkCase, ...]:
    """Return the versioned benchmark case collection.

    :return: Ordered benchmark cases.
    """

    return (
        _dcc_falsey_case(),
        _shared_path_case(),
        _image_cache_case(),
        _command_registry_case(),
        _operation_contract_case(),
        _priority_queue_case(),
        *holdout_cases(),
    )
