"""Provider-neutral contracts for low-latency DCC scene frame deltas."""

from __future__ import annotations

from typing import Any


FRAME_DELTA_SCHEMA = "tech_connector.scene_frame_delta.v1"
SUPPORTED_VERTEX_ENCODINGS = {
    "f32-array",
    "f32-base64",
    "f32-file-array",
    "f32-memoryview",
    "f32-shared-memory",
    "f32-zlib-base64",
}
SUPPORTED_COORDINATE_SPACES = {"object", "world", "shared"}


def normalize_frame_delta(snapshot: dict[str, Any], provider_id: str = "") -> dict[str, Any]:
    """Promote a provider packet to the shared delta schema without copying buffers."""
    if not isinstance(snapshot, dict):
        raise TypeError("A scene frame delta must be a dictionary.")
    packet = dict(snapshot)
    source_schema = str(packet.get("schema") or "")
    if source_schema and source_schema != FRAME_DELTA_SCHEMA:
        packet["source_schema"] = source_schema
    packet["schema"] = FRAME_DELTA_SCHEMA
    packet["packet_kind"] = "frame_delta"
    packet["provider_id"] = str(provider_id or packet.get("provider_id") or "").strip().lower()
    packet.setdefault("topology_included", False)
    packet.setdefault("materials_included", False)

    objects = []
    for source_object in packet.get("objects") or []:
        if not isinstance(source_object, dict):
            continue
        item = dict(source_object)
        geometry = item.get("geometry")
        if isinstance(geometry, dict):
            geometry = dict(geometry)
            encoding = str(geometry.get("vertex_encoding") or "")
            if geometry.get("vertices_f32") is not None and not encoding:
                geometry["vertex_encoding"] = "f32-array"
            geometry.setdefault("coordinate_space", "world")
            geometry.setdefault("topology_included", False)
            item["geometry"] = geometry
        objects.append(item)
    packet["objects"] = objects
    packet["contract_errors"] = validate_frame_delta(packet)
    return packet


def validate_frame_delta(packet: dict[str, Any]) -> list[str]:
    """Return bounded validation errors suitable for telemetry and fallbacks."""
    errors: list[str] = []
    if str(packet.get("schema") or "") != FRAME_DELTA_SCHEMA:
        errors.append("unsupported schema")
    if not str(packet.get("provider_id") or ""):
        errors.append("provider_id is required")
    for index, item in enumerate(packet.get("objects") or []):
        if not isinstance(item, dict):
            errors.append(f"object[{index}] is not a dictionary")
            continue
        native_id = str(item.get("native_id") or "")
        if not native_id:
            errors.append(f"object[{index}] has no native_id")
        geometry = item.get("geometry")
        if not isinstance(geometry, dict):
            continue
        encoding = str(geometry.get("vertex_encoding") or "")
        if encoding and encoding not in SUPPORTED_VERTEX_ENCODINGS:
            errors.append(f"{native_id or index}: unsupported vertex encoding {encoding}")
        coordinate_space = str(geometry.get("coordinate_space") or "world").lower()
        if coordinate_space not in SUPPORTED_COORDINATE_SPACES:
            errors.append(f"{native_id or index}: unsupported coordinate space {coordinate_space}")
        vertex_count = int(geometry.get("vertex_count", 0) or 0)
        if vertex_count < 0:
            errors.append(f"{native_id or index}: negative vertex_count")
        if coordinate_space == "object":
            matrix = item.get("world_matrix")
            if not isinstance(matrix, (list, tuple)) or len(matrix) < 16:
                errors.append(f"{native_id or index}: object-space points require world_matrix")
        packed = geometry.get("vertices_f32")
        if packed is not None and vertex_count > 0:
            float_offset = max(0, int(geometry.get("vertex_float_offset", 0) or 0))
            try:
                available = len(packed) - float_offset
            except TypeError:
                available = -1
            if available < vertex_count * 3:
                errors.append(f"{native_id or index}: packed vertex buffer is truncated")
        if len(errors) >= 32:
            errors.append("additional contract errors omitted")
            break
    return errors


def frame_delta_has_gpu_points(packet: dict[str, Any]) -> bool:
    """Whether at least one valid object contains a directly uploadable float buffer."""
    if packet.get("contract_errors"):
        return False
    for item in packet.get("objects") or []:
        geometry = item.get("geometry") if isinstance(item, dict) else None
        if isinstance(geometry, dict) and geometry.get("vertices_f32") is not None:
            return True
    return False
