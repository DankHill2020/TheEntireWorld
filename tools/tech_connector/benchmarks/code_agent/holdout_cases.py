"""Diverse holdout cases for measuring general code-repair behavior."""

from __future__ import annotations

from .models import BenchmarkCase


_PACKAGE_INIT = '"""Synthetic Tech Connector benchmark package."""\n'


def _dependency_batches_case() -> BenchmarkCase:
    """Build a deterministic graph-algorithm holdout.

    :return: Dependency batching benchmark case.
    """

    return BenchmarkCase(
        case_id="holdout_dependency_batches",
        title="Build stable dependency execution batches",
        category="novel_algorithm",
        prompt=(
            "Repair pipeline/dependencies.py and modify only that file. Implement "
            "execution_batches(graph), where graph maps each task name to the tasks it depends "
            "on. Return a tuple of tuple batches: every batch contains all currently runnable "
            "tasks in sorted order, and batches are ordered by execution time. Include tasks that "
            "appear only as dependencies. Do not mutate the input or its dependency collections. "
            "An empty graph returns an empty tuple. Raise ValueError for any cycle and include all "
            "tasks still involved in the cycle in the message. Keep the public name and add useful "
            "type hints and a project-style docstring with :param and :return: fields."
        ),
        seed_files={
            "pipeline/__init__.py": _PACKAGE_INIT,
            "pipeline/dependencies.py": '''"""Order pipeline dependencies."""\n\n\ndef execution_batches(graph):\n    """Return one task per batch."""\n\n    return tuple((name,) for name in graph)\n''',
        },
        allowed_paths=("pipeline/dependencies.py",),
        assertion_count=11,
        evaluator_source=r'''from __future__ import annotations
import importlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
function = importlib.import_module("pipeline.dependencies").execution_batches
checks = []

def check(condition, label):
    checks.append((bool(condition), label))

graph = {"build": {"compile", "assets"}, "compile": {"parse"}, "assets": {"parse"}, "parse": set()}
snapshot = {key: set(value) for key, value in graph.items()}
result = function(graph)
check(result == (("parse",), ("assets", "compile"), ("build",)), "stable execution batches")
check(graph == snapshot, "input unchanged")
check(isinstance(result, tuple) and all(isinstance(batch, tuple) for batch in result), "immutable shape")
check(function({"package": ["compile"]}) == (("compile",), ("package",)), "dependency-only task")
check(function({"z": set(), "a": set()}) == (("a", "z"),), "sorted independent tasks")
check(function({}) == (), "empty graph")
try:
    function({"self": {"self"}})
except ValueError as exc:
    check("self" in str(exc), "self cycle reported")
else:
    check(False, "self cycle reported")
try:
    function({"a": {"b"}, "b": {"a"}, "ready": set()})
except ValueError as exc:
    message = str(exc)
    check("a" in message and "b" in message, "cycle members reported")
else:
    check(False, "cycle members reported")
annotations = getattr(function, "__annotations__", {})
check("graph" in annotations and "return" in annotations, "type hints")
docs = function.__doc__ or ""
check(":param graph:" in docs, "parameter documentation")
check(":return:" in docs, "return documentation")
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _json_merge_patch_case() -> BenchmarkCase:
    """Build a recursive data-transformation holdout.

    :return: JSON merge patch benchmark case.
    """

    return BenchmarkCase(
        case_id="holdout_json_merge_patch",
        title="Implement detached JSON merge-patch semantics",
        category="data_correctness",
        prompt=(
            "Repair data/merge_patch.py and modify only that file. Implement merge_patch(document, "
            "patch) with JSON Merge Patch semantics: a non-mapping patch replaces the document; a "
            "mapping patch recursively merges into a mapping document (or an empty mapping when the "
            "document is not a mapping); and a None mapping value deletes that key. False, zero, "
            "empty strings, lists, and dictionaries are data, not deletion markers. Return a fully "
            "detached result: neither inputs nor nested mutable values may be shared with it. Never "
            "mutate either input. Keep the public function name and add useful type hints and a "
            "project-style docstring with :param and :return: fields."
        ),
        seed_files={
            "data/__init__.py": _PACKAGE_INIT,
            "data/merge_patch.py": '''"""Apply configuration patches."""\n\n\ndef merge_patch(document, patch):\n    """Update a document in place."""\n\n    document.update(patch)\n    return document\n''',
        },
        allowed_paths=("data/merge_patch.py",),
        assertion_count=11,
        evaluator_source=r'''from __future__ import annotations
import importlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
function = importlib.import_module("data.merge_patch").merge_patch
checks = []

def check(condition, label):
    checks.append((bool(condition), label))

document = {"remove": 1, "nested": {"x": 1, "y": 2}, "keep": False}
patch = {"remove": None, "nested": {"x": 0, "items": []}, "keep": False}
result = function(document, patch)
expected = {"nested": {"x": 0, "y": 2, "items": []}, "keep": False}
check(result == expected, "recursive merge and deletion")
check(document == {"remove": 1, "nested": {"x": 1, "y": 2}, "keep": False}, "document unchanged")
check(patch == {"remove": None, "nested": {"x": 0, "items": []}, "keep": False}, "patch unchanged")
result["nested"]["items"].append("changed")
check(patch["nested"]["items"] == [], "patch values detached")
result["nested"]["y"] = 99
check(document["nested"]["y"] == 2, "document values detached")
replacement = [1, {"value": 2}]
replaced = function({"old": True}, replacement)
replacement[1]["value"] = 3
check(replaced == [1, {"value": 2}], "nonmapping replacement detached")
check(function(7, {"created": {"ok": True}}) == {"created": {"ok": True}}, "mapping patch over scalar")
check(function({"value": 1}, None) is None, "None replaces outside mapping member")
check(function({}, {"false": False, "zero": 0, "text": "", "list": [], "map": {}}) == {"false": False, "zero": 0, "text": "", "list": [], "map": {}}, "falsey values preserved")
annotations = getattr(function, "__annotations__", {})
check("document" in annotations and "patch" in annotations and "return" in annotations, "type hints")
docs = function.__doc__ or ""
check(":param document:" in docs and ":param patch:" in docs and ":return:" in docs, "documentation")
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _event_journal_case() -> BenchmarkCase:
    """Build a concurrent bounded-state holdout.

    :return: Event journal benchmark case.
    """

    return BenchmarkCase(
        case_id="holdout_event_journal",
        title="Repair a bounded thread-safe event journal",
        category="concurrency_and_state",
        prompt=(
            "Repair runtime/journal.py and modify only that file. Implement EventJournal(capacity). "
            "capacity must be a positive non-bool integer. append(topic, payload) stores a deep copy "
            "and returns a monotonically increasing integer sequence starting at 1. Retain only the "
            "newest capacity events. since(sequence, topic=None) returns an immutable tuple of "
            "(sequence, topic, payload) tuples strictly newer than sequence, optionally filtered by "
            "topic; snapshots must be deep copies. clear() removes retained events without reusing "
            "sequence IDs, and len(journal) reports retained count. All public operations must be "
            "thread-safe and must preserve falsey topics and payloads. Add useful type hints and "
            "project-style public docstrings with :param and :return: fields."
        ),
        seed_files={
            "runtime/__init__.py": _PACKAGE_INIT,
            "runtime/journal.py": '''"""Store recent runtime events."""\n\n\nclass EventJournal:\n    """Store events in a list."""\n\n    def __init__(self, capacity):\n        self.capacity = capacity\n        self.events = []\n\n    def append(self, topic, payload):\n        self.events.append((topic, payload))\n        return len(self.events)\n\n    def since(self, sequence, topic=None):\n        return self.events[sequence:]\n''',
        },
        allowed_paths=("runtime/journal.py",),
        assertion_count=14,
        evaluator_source=r'''from __future__ import annotations
import importlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
EventJournal = importlib.import_module("runtime.journal").EventJournal
checks = []

def check(condition, label):
    checks.append((bool(condition), label))

invalid = []
for value in (0, -1, True, 1.5):
    try:
        EventJournal(value)
    except (TypeError, ValueError):
        invalid.append(value)
check(len(invalid) == 4, "capacity validation")
journal = EventJournal(2)
payload = {"items": [1]}
check([journal.append("a", payload), journal.append("", 0), journal.append("a", False)] == [1, 2, 3], "monotonic append")
payload["items"].append(2)
check(journal.since(0) == ((2, "", 0), (3, "a", False)), "bounded ordered snapshot")
check(journal.since(1, "a") == ((3, "a", False),), "topic filter")
check(journal.since(2) == ((3, "a", False),), "evicted cursor uses stable IDs")
check(journal.since(3) == (), "strictly newer sequence")
snapshot = journal.since(0)
check(isinstance(snapshot, tuple) and all(isinstance(item, tuple) for item in snapshot), "immutable snapshot shape")
detached = EventJournal(2)
source = {"nested": []}
detached.append("x", source)
source["nested"].append(1)
first = detached.since(0)
first[0][2]["nested"].append(2)
check(detached.since(0)[0][2] == {"nested": []}, "deep copy boundaries")
check(len(journal) == 2, "retained length")
journal.clear()
check(len(journal) == 0 and journal.append(None, []) == 4, "clear preserves sequence")
concurrent = EventJournal(250)
with ThreadPoolExecutor(max_workers=8) as pool:
    sequences = list(pool.map(lambda value: concurrent.append(value % 3, value), range(200)))
events = concurrent.since(0)
check(len(set(sequences)) == 200 and [item[0] for item in events] == sorted(sequences), "concurrent append safety")
check({item[2] for item in concurrent.since(0, 0)} == set(range(0, 200, 3)), "falsey topic filter")
method_names = ("__init__", "append", "since", "clear")
check(all((getattr(EventJournal, name).__doc__ or "").strip() for name in method_names), "public docstrings")
check(all(getattr(EventJournal, name).__annotations__ for name in ("append", "since", "clear")), "public type hints")
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _backoff_tracker_case() -> BenchmarkCase:
    """Build a per-key state-machine holdout.

    :return: Backoff tracker benchmark case.
    """

    return BenchmarkCase(
        case_id="holdout_backoff_tracker",
        title="Implement bounded per-key retry backoff",
        category="state_machine",
        prompt=(
            "Repair network/backoff.py and modify only that file. Implement thread-safe "
            "BackoffTracker(max_attempts, base_delay, max_delay). max_attempts is a positive "
            "non-bool integer; delays are nonnegative numbers and max_delay must be at least "
            "base_delay. record_failure(key) increments that key and returns "
            "min(max_delay, base_delay * 2 ** (attempt - 1)); once max_attempts is reached, another "
            "failure raises RuntimeError without changing state. remaining(key) returns available "
            "attempts and can_retry(key) reports whether another failure may be recorded. reset(key) "
            "removes a key and returns whether it existed. len(tracker) reports tracked keys. Falsey "
            "hashable keys are valid and distinct. Add useful type hints and project-style public "
            "docstrings with :param and :return: fields."
        ),
        seed_files={
            "network/__init__.py": _PACKAGE_INIT,
            "network/backoff.py": '''"""Track request retry delays."""\n\n\nclass BackoffTracker:\n    """Track one global attempt count."""\n\n    def __init__(self, max_attempts, base_delay, max_delay):\n        self.attempt = 0\n\n    def record_failure(self, key):\n        self.attempt += 1\n        return self.attempt\n''',
        },
        allowed_paths=("network/backoff.py",),
        assertion_count=11,
        evaluator_source=r'''from __future__ import annotations
import importlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
BackoffTracker = importlib.import_module("network.backoff").BackoffTracker
checks = []

def check(condition, label):
    checks.append((bool(condition), label))

invalid = []
for args in ((True, 1, 2), (0, 1, 2), (2, -1, 2), (2, 3, 2)):
    try:
        BackoffTracker(*args)
    except (TypeError, ValueError):
        invalid.append(args)
check(len(invalid) == 4, "constructor validation")
tracker = BackoffTracker(4, 0.5, 2.0)
check([tracker.record_failure("asset") for _ in range(4)] == [0.5, 1.0, 2.0, 2.0], "exponential capped delays")
check(tracker.remaining("asset") == 0 and not tracker.can_retry("asset"), "exhausted state")
try:
    tracker.record_failure("asset")
except RuntimeError:
    check(tracker.remaining("asset") == 0, "overflow leaves state unchanged")
else:
    check(False, "overflow leaves state unchanged")
check(tracker.reset("asset") is True and tracker.reset("asset") is False, "reset result")
check(tracker.remaining("asset") == 4 and tracker.can_retry("asset"), "unknown key defaults")
tracker.record_failure(0)
tracker.record_failure("")
check(len(tracker) == 2 and tracker.remaining(0) == 3 and tracker.remaining("") == 3, "falsey keys distinct")
concurrent = BackoffTracker(20, 0, 0)
with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(lambda value: concurrent.record_failure(value % 4), range(80)))
check(len(concurrent) == 4 and all(concurrent.remaining(key) == 0 for key in range(4)), "concurrent per-key state")
methods = ("__init__", "record_failure", "remaining", "can_retry", "reset")
check(all((getattr(BackoffTracker, name).__doc__ or "").strip() for name in methods), "public docstrings")
check(all(getattr(BackoffTracker, name).__annotations__ for name in methods[1:]), "public type hints")
docs = BackoffTracker.record_failure.__doc__ or ""
check(":param key:" in docs and ":return:" in docs, "project-style documentation")
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _envelope_codec_case() -> BenchmarkCase:
    """Build a cross-file serialization holdout.

    :return: Envelope codec benchmark case.
    """

    return BenchmarkCase(
        case_id="holdout_envelope_codec",
        title="Harden a canonical JSON envelope codec",
        category="multi_file_serialization",
        prompt=(
            "Repair protocol/models.py and protocol/codec.py; modify only those files. Preserve the "
            "Envelope public dataclass and its version, kind, and payload fields. Implement "
            "encode_envelope(envelope) returning canonical UTF-8 JSON bytes (sorted keys and compact "
            "separators), and decode_envelope(data) accepting bytes, bytearray, or str and returning "
            "an Envelope. Both paths must validate that version is an integer other than bool and "
            "at least 1, kind is a nonblank string, and the JSON object has exactly version, kind, "
            "and payload keys. Invalid UTF-8, malformed JSON, wrong input types, unknown or missing "
            "keys, and non-serializable payloads must raise TypeError or ValueError rather than leak "
            "implementation-specific exceptions. Preserve falsey payloads and do not mutate inputs. "
            "Add useful type hints and project-style public docstrings with :param and :return:."
        ),
        seed_files={
            "protocol/__init__.py": _PACKAGE_INIT,
            "protocol/models.py": '''"""Protocol data models."""\n\nfrom dataclasses import dataclass\n\n\n@dataclass(frozen=True)\nclass Envelope:\n    """Carry a versioned protocol payload."""\n\n    version: int\n    kind: str\n    payload: object\n''',
            "protocol/codec.py": '''"""Encode and decode protocol envelopes."""\n\nimport json\n\nfrom .models import Envelope\n\n\ndef encode_envelope(envelope):\n    return json.dumps(envelope.__dict__).encode()\n\n\ndef decode_envelope(data):\n    return Envelope(**json.loads(data))\n''',
        },
        allowed_paths=("protocol/models.py", "protocol/codec.py"),
        assertion_count=13,
        evaluator_source=r'''from __future__ import annotations
import importlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
models = importlib.import_module("protocol.models")
codec = importlib.import_module("protocol.codec")
Envelope = models.Envelope
encode = codec.encode_envelope
decode = codec.decode_envelope
checks = []

def check(condition, label):
    checks.append((bool(condition), label))

envelope = Envelope(1, "asset", 0)
encoded = encode(envelope)
check(encoded == b'{"kind":"asset","payload":0,"version":1}', "canonical bytes")
check(decode(encoded) == envelope, "bytes round trip")
check(decode(bytearray(encoded)) == envelope and decode(encoded.decode("utf-8")) == envelope, "accepted input forms")
check(decode(encode(Envelope(2, "unicode", {"name": "caf\u00e9"}))) == Envelope(2, "unicode", {"name": "caf\u00e9"}), "unicode round trip")
check(all(decode(encode(Envelope(1, "value", value))).payload == value for value in (False, 0, "", [], {}, None)), "falsey payloads")
invalid_models = (Envelope(True, "x", None), Envelope(0, "x", None), Envelope(1, " ", None))
rejected = 0
for item in invalid_models:
    try:
        encode(item)
    except (TypeError, ValueError):
        rejected += 1
check(rejected == len(invalid_models), "encode field validation")
try:
    encode(Envelope(1, "x", {1, 2}))
except (TypeError, ValueError):
    check(True, "nonserializable payload")
else:
    check(False, "nonserializable payload")
invalid_documents = ('{"version":1,"kind":"x"}', '{"version":1,"kind":"x","payload":null,"extra":1}', '[]', '{"version":true,"kind":"x","payload":null}', '{"version":1,"kind":" ","payload":null}')
rejected = 0
for item in invalid_documents:
    try:
        decode(item)
    except (TypeError, ValueError):
        rejected += 1
check(rejected == len(invalid_documents), "decode schema validation")
bad_inputs = (b"\xff", "{bad", 123)
rejected = 0
for item in bad_inputs:
    try:
        decode(item)
    except (TypeError, ValueError):
        rejected += 1
check(rejected == len(bad_inputs), "decode input errors normalized")
payload = {"nested": []}
original = Envelope(1, "copy", payload)
decode(encode(original)).payload["nested"].append(1)
check(payload == {"nested": []}, "input detached")
check(tuple(Envelope.__dataclass_fields__) == ("version", "kind", "payload"), "public model preserved")
functions = (encode, decode)
check(all(getattr(function, "__annotations__", {}) for function in functions), "type hints")
check(all(":param" in (function.__doc__ or "") and ":return:" in (function.__doc__ or "") for function in functions), "documentation")
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _painter_export_manifest_case() -> BenchmarkCase:
    """Build a Painter-shaped cross-file selection and export holdout.

    :return: Painter export manifest benchmark case.
    """

    return BenchmarkCase(
        case_id="holdout_painter_export_manifest",
        title="Plan Substance Painter texture-set exports",
        category="dcc_multi_file_workflow",
        prompt=(
            "Repair painter_pipeline/texture_sets.py and painter_pipeline/export_plan.py; modify "
            "only those files. These pure-Python helpers consume a Substance Painter project "
            "snapshot, so they must work without Painter installed. Implement "
            "collect_export_sets(texture_sets, selected_names=None): texture_sets is an iterable "
            "of mappings with name (string) and enabled (bool); return a tuple of enabled names "
            "in project order, removing case-insensitive duplicates (first enabled spelling wins). "
            "Names are stripped; reject blank names, path separators, and '.' or '..' with "
            "ValueError. selected_names=None exports all enabled sets; an explicit iterable "
            "of strings matches names case-insensitively while retaining project order, and an "
            "empty selection exports nothing. An unknown or disabled selected name raises ValueError. "
            "Implement build_export_manifest(texture_sets, output_dir, preset, "
            "selected_names=None) in export_plan.py using collect_export_sets. Return a tuple of "
            "dicts with exactly texture_set, output_path, and preset keys. output_dir accepts a "
            "string or pathlib.Path and need not exist yet; output_path is exactly the native "
            "string form of Path(output_dir) / f'<texture_set>.png'. preset is a nonblank string "
            "copied into each row. Reject a blank output_dir or preset with ValueError. Do not "
            "mutate inputs. Add useful type hints and project-style "
            "public docstrings with :param and :return: fields."
        ),
        seed_files={
            "painter_pipeline/__init__.py": _PACKAGE_INIT,
            "painter_pipeline/texture_sets.py": '''"""Select exportable Painter texture sets."""\n\n\ndef collect_export_sets(texture_sets, selected_names=None):\n    """Return every texture set name."""\n\n    return tuple(item["name"] for item in texture_sets)\n''',
            "painter_pipeline/export_plan.py": '''"""Plan Painter texture exports."""\n\n\ndef build_export_manifest(texture_sets, output_dir, preset, selected_names=None):\n    """Return an empty manifest."""\n\n    return ()\n''',
        },
        allowed_paths=("painter_pipeline/texture_sets.py", "painter_pipeline/export_plan.py"),
        assertion_count=15,
        evaluator_source=r'''from __future__ import annotations
import copy
import importlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
selection = importlib.import_module("painter_pipeline.texture_sets")
export_plan = importlib.import_module("painter_pipeline.export_plan")
collect = selection.collect_export_sets
build = export_plan.build_export_manifest
checks = []

def check(condition, label):
    checks.append((bool(condition), label))

failed = object()

def result(call):
    try:
        return call()
    except Exception:
        return failed

def rejects(call, label):
    try:
        call()
    except ValueError:
        check(True, label)
    except Exception:
        check(False, label)
    else:
        check(False, label)

sets = [
    {"name": " Body ", "enabled": True},
    {"name": "Wheels", "enabled": False},
    {"name": "body", "enabled": True},
    {"name": "Glass", "enabled": True},
]
original = copy.deepcopy(sets)
check(result(lambda: collect(sets)) == ("Body", "Glass"), "enabled order, trim, and casefold dedup")
check(result(lambda: collect(sets, ["glass", "BODY"])) == ("Body", "Glass"), "selected names retain project order")
check(result(lambda: collect(sets, [])) == (), "explicit empty selection")
rejects(lambda: collect(sets, ["Missing"]), "unknown selected set rejected")
rejects(lambda: collect(sets, ["Wheels"]), "disabled selected set rejected")
invalid_names = (" ", "../escape", "folder/name", "folder\\name", ".", "..")
rejected = 0
for name in invalid_names:
    try:
        collect([{"name": name, "enabled": True}])
    except ValueError:
        rejected += 1
    except Exception:
        pass
check(rejected == len(invalid_names), "unsafe texture-set names rejected")
check(sets == original, "selection does not mutate snapshot")
output_dir = root / "exports"
manifest = result(lambda: build(sets, output_dir, "PBR Metallic Roughness"))
check(isinstance(manifest, tuple) and len(manifest) == 2, "manifest result shape")
check(manifest == (
    {"texture_set": "Body", "output_path": str(output_dir / "Body.png"), "preset": "PBR Metallic Roughness"},
    {"texture_set": "Glass", "output_path": str(output_dir / "Glass.png"), "preset": "PBR Metallic Roughness"},
), "manifest fields and destinations")
check(result(lambda: build(sets, output_dir, "PBR", ["glass"])) == (
    {"texture_set": "Glass", "output_path": str(output_dir / "Glass.png"), "preset": "PBR"},
), "selection feeds export plan")
rejects(lambda: build(sets, output_dir, "PBR", ["Wheels"]), "export rejects disabled selection")
rejects(lambda: build(sets, "  ", "PBR"), "blank output directory rejected")
rejects(lambda: build(sets, output_dir, "  "), "blank preset rejected")
check(sets == original, "export does not mutate snapshot")
functions = (collect, build)
check(all(getattr(function, "__annotations__", {}) and ":param" in (function.__doc__ or "") and ":return:" in (function.__doc__ or "") for function in functions), "typed public documentation")
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def _motionbuilder_take_export_case() -> BenchmarkCase:
    """Exercise offline MotionBuilder take selection and FBX job planning."""

    return BenchmarkCase(
        case_id="holdout_motionbuilder_take_export",
        title="Plan MotionBuilder take exports for downstream DCC import",
        category="dcc_multi_file_workflow",
        prompt=(
            "Repair mobu_pipeline/takes.py and mobu_pipeline/export_plan.py; modify only "
            "those files. These pure-Python helpers process a MotionBuilder take snapshot "
            "and must work without MotionBuilder installed. Implement "
            "collect_export_takes(takes, selected_names=None): each take is a mapping "
            "with name, enabled, start_frame, and end_frame. Strip names, reject blank "
            "names and names containing / or backslash with ValueError. Require frame "
            "bounds to be integers excluding bool, with start_frame <= end_frame; "
            "invalid bounds raise ValueError. Return a tuple of dicts with exactly "
            "name, start_frame, and end_frame keys for enabled takes, in project order. "
            "Deduplicate names case-insensitively; the first enabled spelling and frame "
            "range wins. None selection includes all enabled takes; an explicit empty "
            "selection returns an empty tuple. Match selected names case-insensitively "
            "but retain project order. Unknown or disabled selections raise ValueError. "
            "Implement plan_fbx_exports(takes, output_dir, selected_names=None) in "
            "export_plan.py using collect_export_takes from takes.py. Reject blank "
            "output_dir with ValueError; it may be a string or pathlib.Path and need "
            "not exist. Return a tuple of dicts with exactly take, output_path, "
            "start_frame, and end_frame keys; each output_path is the native string "
            "form of Path(output_dir) / f'<take>.fbx'. Never mutate input snapshots. "
            "Add useful type hints and public docstrings with :param and :return:."
        ),
        seed_files={
            "mobu_pipeline/__init__.py": _PACKAGE_INIT,
            "mobu_pipeline/takes.py": '''"""Select MotionBuilder takes from an offline snapshot."""\n\n\ndef collect_export_takes(takes, selected_names=None):\n    """Return all take names."""\n\n    return tuple(take["name"] for take in takes)\n''',
            "mobu_pipeline/export_plan.py": '''"""Plan FBX exports from MotionBuilder takes."""\n\n\ndef plan_fbx_exports(takes, output_dir, selected_names=None):\n    """Return no export jobs."""\n\n    return ()\n''',
        },
        allowed_paths=("mobu_pipeline/takes.py", "mobu_pipeline/export_plan.py"),
        assertion_count=15,
        evaluator_source=r'''from __future__ import annotations
import copy
import importlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
collect = importlib.import_module("mobu_pipeline.takes").collect_export_takes
plan = importlib.import_module("mobu_pipeline.export_plan").plan_fbx_exports
checks = []
failed = object()

def check(condition, label):
    checks.append((bool(condition), label))

def result(call):
    try:
        return call()
    except Exception:
        return failed

def rejects(call, label):
    try:
        call()
    except ValueError:
        check(True, label)
    except Exception:
        check(False, label)
    else:
        check(False, label)

takes = [
    {"name": " Walk ", "enabled": True, "start_frame": 1, "end_frame": 24},
    {"name": "Idle", "enabled": False, "start_frame": 5, "end_frame": 20},
    {"name": "walk", "enabled": True, "start_frame": 30, "end_frame": 40},
    {"name": "Run", "enabled": True, "start_frame": 25, "end_frame": 48},
]
original = copy.deepcopy(takes)
expected = (
    {"name": "Walk", "start_frame": 1, "end_frame": 24},
    {"name": "Run", "start_frame": 25, "end_frame": 48},
)
check(result(lambda: collect(takes)) == expected, "enabled ordered typed take records")
check(result(lambda: collect(takes, ["run", "WALK"])) == expected, "selection retains project order")
check(result(lambda: collect(takes, [])) == (), "explicit empty selection")
rejects(lambda: collect(takes, ["Missing"]), "unknown selection rejected")
rejects(lambda: collect(takes, ["Idle"]), "disabled selection rejected")
invalid_names = (" ", "a/b", "a\\b")
check(all(result(lambda name=name: collect([{"name": name, "enabled": True, "start_frame": 1, "end_frame": 2}])) is failed for name in invalid_names), "unsafe names rejected")
invalid_bounds = ((True, 2), (1, False), (4, 3), (1.0, 2))
check(all(result(lambda start=start, end=end: collect([{"name": "Take", "enabled": True, "start_frame": start, "end_frame": end}])) is failed for start, end in invalid_bounds), "invalid frame bounds rejected")
check(takes == original, "selection does not mutate snapshot")
output_dir = root / "exports"
jobs = result(lambda: plan(takes, output_dir))
check(isinstance(jobs, tuple) and len(jobs) == 2, "FBX job result shape")
check(jobs == (
    {"take": "Walk", "output_path": str(output_dir / "Walk.fbx"), "start_frame": 1, "end_frame": 24},
    {"take": "Run", "output_path": str(output_dir / "Run.fbx"), "start_frame": 25, "end_frame": 48},
), "FBX job fields and paths")
check(result(lambda: plan(takes, output_dir, ["run"])) == (
    {"take": "Run", "output_path": str(output_dir / "Run.fbx"), "start_frame": 25, "end_frame": 48},
), "selection feeds FBX plan")
rejects(lambda: plan(takes, output_dir, ["Idle"]), "FBX plan rejects disabled selection")
rejects(lambda: plan(takes, "  "), "blank output directory rejected")
check(takes == original, "FBX planning does not mutate snapshot")
check(all(getattr(function, "__annotations__", {}) and ":param" in (function.__doc__ or "") and ":return:" in (function.__doc__ or "") for function in (collect, plan)), "typed public documentation")
passed = sum(ok for ok, _ in checks)
print(json.dumps({"passed": passed, "total": len(checks), "failures": [label for ok, label in checks if not ok]}))
raise SystemExit(0 if passed == len(checks) else 1)
''',
    )


def holdout_cases() -> tuple[BenchmarkCase, ...]:
    """Return diverse cases excluded from contract-specific generation paths.

    :return: Ordered holdout benchmark cases.
    """

    return (
        _dependency_batches_case(),
        _json_merge_patch_case(),
        _event_journal_case(),
        _backoff_tracker_case(),
        _envelope_codec_case(),
        _painter_export_manifest_case(),
        _motionbuilder_take_export_case(),
    )
