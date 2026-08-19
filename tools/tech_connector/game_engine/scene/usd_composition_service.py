"""OpenUSD composition contracts and isolated runtime dispatch."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Any

from tech_connector.game_engine.scene.federated_scene_service import (
    FederatedSceneDocument,
    source_file_fingerprint,
)
from tech_connector.game_engine.scene.native_fbx_service import (
    _stop_subprocess,
    find_blender_executable,
)


USD_COMPOSITION_SCHEMA = "tech_connector.usd_composition.v1"
USD_EXTENSIONS = frozenset({".usd", ".usda", ".usdc", ".usdz"})


@dataclass(frozen=True)
class UsdLayerSpec:
    path: str
    role: str = "source"
    muted: bool = False
    offset: float = 0.0
    scale: float = 1.0
    required: bool = True
    fingerprint: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", source_file_fingerprint(self.path))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fingerprint"] = dict(self.fingerprint)
        return data


@dataclass(frozen=True)
class UsdVariantSelection:
    prim_path: str
    variant_set: str
    selection: str


@dataclass(frozen=True)
class UsdPayloadRule:
    prim_path: str
    loaded: bool = True


@dataclass(frozen=True)
class UsdPropertyOverride:
    prim_path: str
    property_name: str
    value: Any
    value_type: str = "string"
    time_code: float | None = None


@dataclass
class UsdComposition:
    layers: list[UsdLayerSpec]
    variants: list[UsdVariantSelection] = field(default_factory=list)
    payload_rules: list[UsdPayloadRule] = field(default_factory=list)
    overrides: list[UsdPropertyOverride] = field(default_factory=list)
    load_policy: str = "all"
    flatten: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    schema: str = USD_COMPOSITION_SCHEMA

    def validate(self) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        if self.load_policy not in {"all", "none"}:
            errors.append("load_policy must be 'all' or 'none'")
        for index, layer in enumerate(self.layers):
            path = Path(layer.path).expanduser()
            key = os.path.normcase(str(path.resolve()))
            if key in seen:
                errors.append(f"layer[{index}] duplicates {path}")
            seen.add(key)
            if path.suffix.lower() not in USD_EXTENSIONS:
                errors.append(f"layer[{index}] is not an OpenUSD file: {path}")
            if layer.required and not path.is_file():
                errors.append(f"layer[{index}] is missing: {path}")
            if abs(float(layer.scale)) < 1.0e-12:
                errors.append(f"layer[{index}] scale cannot be zero")
        for label, rows in (("variant", self.variants), ("payload", self.payload_rules), ("override", self.overrides)):
            for index, row in enumerate(rows):
                if not _valid_prim_path(row.prim_path):
                    errors.append(f"{label}[{index}] has an invalid absolute prim path: {row.prim_path}")
        for index, row in enumerate(self.variants):
            if not row.variant_set or not row.selection:
                errors.append(f"variant[{index}] requires a set and selection")
        for index, row in enumerate(self.overrides):
            if not row.property_name:
                errors.append(f"override[{index}] requires property_name")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "layers": [layer.to_dict() for layer in self.layers],
            "variants": [asdict(item) for item in self.variants],
            "payload_rules": [asdict(item) for item in self.payload_rules],
            "overrides": [asdict(item) for item in self.overrides],
            "load_policy": self.load_policy,
            "flatten": bool(self.flatten),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UsdComposition":
        return cls(
            layers=[UsdLayerSpec(**dict(item)) for item in data.get("layers") or []],
            variants=[UsdVariantSelection(**dict(item)) for item in data.get("variants") or []],
            payload_rules=[UsdPayloadRule(**dict(item)) for item in data.get("payload_rules") or []],
            overrides=[UsdPropertyOverride(**dict(item)) for item in data.get("overrides") or []],
            load_policy=str(data.get("load_policy") or "all"),
            flatten=bool(data.get("flatten", False)),
            metadata=dict(data.get("metadata") or {}),
            schema=str(data.get("schema") or USD_COMPOSITION_SCHEMA),
        )

    def source_changes(self) -> list[dict[str, Any]]:
        changes = []
        for layer in self.layers:
            saved = dict(layer.fingerprint or {})
            current = source_file_fingerprint(layer.path)
            changed = bool(saved and any(
                saved.get(key) != current.get(key)
                for key in ("exists", "size", "mtime_ns", "head_sha256")
                if saved.get(key) is not None
            ))
            changes.append({"path": layer.path, "changed": changed, "saved": saved, "current": current})
        return changes


@dataclass(frozen=True)
class UsdCompositionResult:
    output_path: str
    manifest: dict[str, Any]

    @property
    def prim_count(self) -> int:
        return int(self.manifest.get("prim_count", 0) or 0)


def find_blender_usd_worker() -> Path | None:
    configured = os.environ.get("TECH_CONNECTOR_BLENDER_USD_COMPOSITOR")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(__file__).resolve().parents[1] / "integration" / "blender_usd_compose.py",
        Path(__file__).resolve().parents[2] / "services" / "dcc" / "blender_usd_compose.py",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    return None


def usd_composition_capabilities() -> dict[str, Any]:
    blender = find_blender_executable()
    worker = find_blender_usd_worker()
    return {
        "schema": "tech_connector.usd_composition_capabilities.v1",
        "available": bool(blender and worker),
        "backend": "blender_openusd_isolated",
        "blender_executable": str(blender or ""),
        "worker": str(worker or ""),
        "features": {
            "sublayers": True,
            "layer_offsets": True,
            "variants": True,
            "payload_load_rules": True,
            "property_overrides": True,
            "flatten": True,
            "dependency_inventory": True,
        },
    }


def compose_usd_stage(
    composition: UsdComposition,
    output_path: str | os.PathLike[str],
    *,
    blender_executable: str | os.PathLike[str] | None = None,
    timeout: float = 180.0,
    cancel_event: threading.Event | None = None,
    prim_limit: int = 10000,
) -> UsdCompositionResult:
    errors = composition.validate()
    if errors:
        raise ValueError("Invalid USD composition: " + "; ".join(errors))
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("USD composition canceled.")
    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() not in {".usd", ".usda", ".usdc"}:
        raise ValueError("USD composition output must use .usd, .usda, or .usdc.")
    blender = Path(blender_executable).resolve() if blender_executable else find_blender_executable()
    worker = find_blender_usd_worker()
    if blender is None or not blender.is_file() or worker is None:
        raise RuntimeError("No isolated Blender OpenUSD composition backend is available.")
    with tempfile.TemporaryDirectory(prefix="tech_connector_usd_") as directory:
        temporary = Path(directory)
        request_path = temporary / "request.json"
        result_path = temporary / "result.json"
        request = composition.to_dict()
        request.update({"output_path": str(output), "prim_limit": max(1, int(prim_limit))})
        request_path.write_text(json.dumps(request, separators=(",", ":")), encoding="utf-8")
        startup = getattr(subprocess, "STARTUPINFO", None)
        startup_info = startup() if startup is not None else None
        if startup_info is not None:
            startup_info.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        command = [
            str(blender), "--background", "--factory-startup", "--python", str(worker), "--",
            "--request", str(request_path), "--result", str(result_path),
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=startup_info,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + max(0.1, float(timeout))
        stdout = ""
        stderr = ""
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _stop_subprocess(process)
                raise RuntimeError("USD composition canceled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                _stop_subprocess(process)
                raise TimeoutError(f"USD composition exceeded {float(timeout):g} seconds.")
            try:
                stdout, stderr = process.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode != 0 or not result_path.is_file() or not output.is_file():
            detail = (stderr or stdout or "Blender returned no OpenUSD diagnostics.")[-6000:]
            raise RuntimeError("OpenUSD composition failed:\n" + detail)
        manifest = json.loads(result_path.read_text(encoding="utf-8"))
    if str(manifest.get("schema") or "") != "tech_connector.usd_composition_result.v1":
        raise ValueError("The OpenUSD compositor returned an unsupported result schema.")
    return UsdCompositionResult(str(output), manifest)


def attach_usd_composition(
    document: FederatedSceneDocument,
    composition: UsdComposition,
    result: UsdCompositionResult | None = None,
) -> None:
    payload = composition.to_dict()
    if result is not None:
        payload["last_result"] = dict(result.manifest)
    document.metadata["usd_composition"] = payload


def usd_composition_from_document(document: FederatedSceneDocument) -> UsdComposition | None:
    payload = document.metadata.get("usd_composition")
    return UsdComposition.from_dict(payload) if isinstance(payload, dict) else None


def _valid_prim_path(path: str) -> bool:
    value = str(path or "")
    return value.startswith("/") and "//" not in value and "/../" not in value and not value.endswith("/..")


__all__ = [
    "USD_COMPOSITION_SCHEMA", "UsdComposition", "UsdCompositionResult", "UsdLayerSpec",
    "UsdPayloadRule", "UsdPropertyOverride", "UsdVariantSelection", "attach_usd_composition",
    "compose_usd_stage", "usd_composition_capabilities", "usd_composition_from_document",
]
