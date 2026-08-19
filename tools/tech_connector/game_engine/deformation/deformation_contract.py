"""Provider-neutral contracts for compact skeletal deformation streaming."""

from __future__ import annotations

from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover - only used by stripped DCC runtimes.
    np = None


DEFORMATION_BINDING_SCHEMA = "tech_connector.scene_deformation_binding.v1"
DEFORMATION_FRAME_SCHEMA = "tech_connector.scene_deformation_frame.v1"
DEFORMATION_MODES = {
    "linear_blend_skinning",
    "dual_quaternion_skinning",
    "point_cache",
    "static",
}


def normalize_deformation_binding(packet: dict[str, Any], provider_id: str = "") -> dict[str, Any]:
    """Promote a provider binding packet without copying its packed buffers."""
    if not isinstance(packet, dict):
        raise TypeError("A deformation binding must be a dictionary.")
    normalized = dict(packet)
    source_schema = str(normalized.get("schema") or "")
    if source_schema and source_schema != DEFORMATION_BINDING_SCHEMA:
        normalized["source_schema"] = source_schema
    normalized["schema"] = DEFORMATION_BINDING_SCHEMA
    normalized["provider_id"] = str(provider_id or normalized.get("provider_id") or "").strip().lower()
    normalized.setdefault("skeletons", [])
    normalized.setdefault("meshes", [])
    normalized["contract_errors"] = validate_deformation_binding(normalized)
    return normalized


def normalize_deformation_frame(packet: dict[str, Any], provider_id: str = "") -> dict[str, Any]:
    """Promote a provider joint-pose packet without copying matrix buffers."""
    if not isinstance(packet, dict):
        raise TypeError("A deformation frame must be a dictionary.")
    normalized = dict(packet)
    source_schema = str(normalized.get("schema") or "")
    if source_schema and source_schema != DEFORMATION_FRAME_SCHEMA:
        normalized["source_schema"] = source_schema
    normalized["schema"] = DEFORMATION_FRAME_SCHEMA
    normalized["provider_id"] = str(provider_id or normalized.get("provider_id") or "").strip().lower()
    normalized.setdefault("skeletons", [])
    normalized["contract_errors"] = validate_deformation_frame(normalized)
    return normalized


def validate_deformation_binding(packet: dict[str, Any]) -> list[str]:
    """Return bounded structural errors for a static skeletal binding."""
    errors: list[str] = []
    if str(packet.get("schema") or "") != DEFORMATION_BINDING_SCHEMA:
        errors.append("unsupported schema")
    if not str(packet.get("provider_id") or ""):
        errors.append("provider_id is required")

    skeletons: dict[str, int] = {}
    for index, skeleton in enumerate(packet.get("skeletons") or []):
        if not isinstance(skeleton, dict):
            errors.append(f"skeleton[{index}] is not a dictionary")
            continue
        native_id = str(skeleton.get("native_id") or "")
        joints = skeleton.get("joints") or []
        if not native_id:
            errors.append(f"skeleton[{index}] has no native_id")
        elif native_id in skeletons:
            errors.append(f"duplicate skeleton {native_id}")
        else:
            skeletons[native_id] = len(joints)
        if not joints:
            errors.append(f"{native_id or index}: skeleton has no joints")
        inverse_bind = skeleton.get("inverse_bind_matrices_f32")
        float_offset = max(0, int(skeleton.get("inverse_bind_float_offset", 0) or 0))
        if inverse_bind is None or _available(inverse_bind, float_offset) < len(joints) * 16:
            errors.append(f"{native_id or index}: inverse bind matrix buffer is truncated")

    for index, mesh in enumerate(packet.get("meshes") or []):
        if not isinstance(mesh, dict):
            errors.append(f"mesh[{index}] is not a dictionary")
            continue
        native_id = str(mesh.get("native_id") or "")
        mode = str(mesh.get("deformation_mode") or "")
        vertex_count = int(mesh.get("vertex_count", 0) or 0)
        if not native_id:
            errors.append(f"mesh[{index}] has no native_id")
        if mode not in DEFORMATION_MODES:
            errors.append(f"{native_id or index}: unsupported deformation mode {mode}")
        if vertex_count < 0:
            errors.append(f"{native_id or index}: negative vertex_count")
        if mode not in {"linear_blend_skinning", "dual_quaternion_skinning"}:
            continue
        skeleton_id = str(mesh.get("skeleton_id") or "")
        joint_count = skeletons.get(skeleton_id, -1)
        if joint_count < 0:
            errors.append(f"{native_id or index}: unknown skeleton {skeleton_id}")
            continue
        bind_points = mesh.get("bind_vertices_f32")
        bind_offset = max(0, int(mesh.get("bind_vertex_float_offset", 0) or 0))
        if bind_points is None or _available(bind_points, bind_offset) < vertex_count * 3:
            errors.append(f"{native_id or index}: bind vertex buffer is truncated")
        bind_geometry_matrix = mesh.get("bind_geometry_matrix")
        if bind_geometry_matrix is not None and _available(bind_geometry_matrix, 0) < 16:
            errors.append(f"{native_id or index}: bind geometry matrix is truncated")
        offsets = mesh.get("influence_offsets_u32")
        offset_start = max(0, int(mesh.get("influence_offset_offset", 0) or 0))
        if offsets is None or _available(offsets, offset_start) < vertex_count + 1:
            errors.append(f"{native_id or index}: influence offset buffer is truncated")
            continue
        try:
            influence_count = int(offsets[offset_start + vertex_count])
        except Exception:
            errors.append(f"{native_id or index}: influence offsets are unreadable")
            continue
        indices = mesh.get("joint_indices_u32")
        weights = mesh.get("weights_f32")
        index_start = max(0, int(mesh.get("joint_index_offset", 0) or 0))
        weight_start = max(0, int(mesh.get("weight_float_offset", 0) or 0))
        if indices is None or _available(indices, index_start) < influence_count:
            errors.append(f"{native_id or index}: joint index buffer is truncated")
        if weights is None or _available(weights, weight_start) < influence_count:
            errors.append(f"{native_id or index}: weight buffer is truncated")
        if indices is not None:
            try:
                if any(int(value) < 0 or int(value) >= joint_count for value in indices[index_start:index_start + influence_count]):
                    errors.append(f"{native_id or index}: joint index is outside the skeleton")
            except Exception:
                errors.append(f"{native_id or index}: joint indices are unreadable")
        if len(errors) >= 32:
            errors.append("additional contract errors omitted")
            break
    return errors


def validate_deformation_frame(packet: dict[str, Any]) -> list[str]:
    """Return bounded structural errors for a per-frame joint pose."""
    errors: list[str] = []
    if str(packet.get("schema") or "") != DEFORMATION_FRAME_SCHEMA:
        errors.append("unsupported schema")
    if not str(packet.get("provider_id") or ""):
        errors.append("provider_id is required")
    for index, skeleton in enumerate(packet.get("skeletons") or []):
        if not isinstance(skeleton, dict):
            errors.append(f"skeleton[{index}] is not a dictionary")
            continue
        native_id = str(skeleton.get("native_id") or "")
        joint_count = int(skeleton.get("joint_count", 0) or 0)
        matrices = skeleton.get("joint_matrices_f32")
        float_offset = max(0, int(skeleton.get("joint_matrix_float_offset", 0) or 0))
        if not native_id:
            errors.append(f"skeleton[{index}] has no native_id")
        if joint_count <= 0:
            errors.append(f"{native_id or index}: joint_count must be positive")
        if matrices is None or _available(matrices, float_offset) < joint_count * 16:
            errors.append(f"{native_id or index}: joint matrix buffer is truncated")
        if len(errors) >= 32:
            errors.append("additional contract errors omitted")
            break
    return errors


def deformation_frame_has_joint_poses(packet: dict[str, Any]) -> bool:
    return not packet.get("contract_errors") and bool(packet.get("skeletons"))


def reconstruct_linear_blend_positions(
    binding: dict[str, Any],
    frame: dict[str, Any],
    mesh_native_id: str,
):
    """Evaluate one exact sparse LBS mesh using Maya-compatible row matrices."""
    if np is None:
        raise RuntimeError("NumPy is required for real-time skeletal reconstruction.")
    if binding.get("contract_errors"):
        raise ValueError("The deformation binding has contract errors.")
    if frame.get("contract_errors"):
        raise ValueError("The deformation frame has contract errors.")
    mesh = next(
        (item for item in binding.get("meshes") or [] if str(item.get("native_id") or "") == str(mesh_native_id)),
        None,
    )
    if mesh is None:
        raise KeyError(f"No deformation binding exists for {mesh_native_id}")
    if mesh.get("deformation_mode") != "linear_blend_skinning":
        raise ValueError(f"{mesh_native_id} is not a linear blend skin")
    skeleton_id = str(mesh.get("skeleton_id") or "")
    skeleton = next(
        (item for item in binding.get("skeletons") or [] if str(item.get("native_id") or "") == skeleton_id),
        None,
    )
    pose = next(
        (item for item in frame.get("skeletons") or [] if str(item.get("native_id") or "") == skeleton_id),
        None,
    )
    if skeleton is None or pose is None:
        raise KeyError(f"No skeleton pose exists for {skeleton_id}")

    vertex_count = int(mesh.get("vertex_count", 0) or 0)
    joint_count = len(skeleton.get("joints") or [])
    bind_offset = int(mesh.get("bind_vertex_float_offset", 0) or 0)
    inverse_offset = int(skeleton.get("inverse_bind_float_offset", 0) or 0)
    matrix_offset = int(pose.get("joint_matrix_float_offset", 0) or 0)
    offset_start = int(mesh.get("influence_offset_offset", 0) or 0)
    index_start = int(mesh.get("joint_index_offset", 0) or 0)
    weight_start = int(mesh.get("weight_float_offset", 0) or 0)

    points = _float_view(mesh["bind_vertices_f32"], bind_offset, vertex_count * 3).reshape((vertex_count, 3))
    inverse_bind = _float_view(
        skeleton["inverse_bind_matrices_f32"], inverse_offset, joint_count * 16
    ).reshape((joint_count, 4, 4))
    joint_matrices = _float_view(
        pose["joint_matrices_f32"], matrix_offset, joint_count * 16
    ).reshape((joint_count, 4, 4))
    offsets = _uint_view(mesh["influence_offsets_u32"], offset_start, vertex_count + 1)
    influence_count = int(offsets[-1]) if len(offsets) else 0
    joint_indices = _uint_view(mesh["joint_indices_u32"], index_start, influence_count).astype(np.int64, copy=False)
    weights = _float_view(mesh["weights_f32"], weight_start, influence_count)
    if influence_count == 0:
        return points.copy()

    counts = np.diff(offsets.astype(np.int64, copy=False))
    vertex_indices = np.repeat(np.arange(vertex_count, dtype=np.int64), counts)
    points_h = np.empty((vertex_count, 4), dtype=np.float32)
    points_h[:, :3] = points
    points_h[:, 3] = 1.0
    skin_matrices = _object_space_skin_matrices(mesh, frame, inverse_bind, joint_matrices)
    transformed = np.einsum(
        "ni,nij->nj",
        points_h[vertex_indices],
        skin_matrices[joint_indices],
        optimize=True,
    )
    output = np.zeros((vertex_count, 3), dtype=np.float32)
    np.add.at(output, vertex_indices, transformed[:, :3] * weights[:, None])
    return output


def build_fixed_width_skinning_buffers(
    mesh: dict[str, Any],
    joint_count: int,
    *,
    influence_width: int,
) -> dict[str, Any]:
    """Pack sparse influences without making the fixed-width cache authoritative."""
    if np is None:
        raise RuntimeError("NumPy is required for GPU skinning buffer construction.")
    vertex_count = int(mesh.get("vertex_count", 0) or 0)
    if vertex_count <= 0 or int(joint_count) <= 0:
        raise ValueError("A non-empty mesh and skeleton are required for GPU skinning.")
    width = int(influence_width)
    if width <= 0 or width > 32:
        raise ValueError("GPU influence width must be between 1 and 32.")
    if int(joint_count) > 65535:
        raise ValueError("The compact GPU joint-index cache supports at most 65,535 joints per skin.")
    offset_start = int(mesh.get("influence_offset_offset", 0) or 0)
    index_start = int(mesh.get("joint_index_offset", 0) or 0)
    weight_start = int(mesh.get("weight_float_offset", 0) or 0)
    offsets = _uint_view(mesh["influence_offsets_u32"], offset_start, vertex_count + 1)
    influence_count = int(offsets[-1]) if len(offsets) else 0
    indices = _uint_view(mesh["joint_indices_u32"], index_start, influence_count)
    weights = _float_view(mesh["weights_f32"], weight_start, influence_count)
    packed_indices = np.zeros((vertex_count, width), dtype=np.uint16)
    packed_weights = np.zeros((vertex_count, width), dtype=np.float32)
    discarded_weight = 0.0
    vertices_reduced = 0
    counts = np.diff(offsets.astype(np.int64, copy=False))
    source_indices = indices.astype(np.int64, copy=False)
    source_weights = weights.astype(np.float32, copy=False)
    max_count = int(counts.max(initial=0))
    csr_valid = bool(
        len(offsets) == vertex_count + 1
        and int(offsets[0]) == 0
        and int(offsets[-1]) == influence_count
        and np.all(counts >= 0)
        and np.all((source_indices >= 0) & (source_indices < int(joint_count)))
        and np.all(np.isfinite(source_weights) & (source_weights > 0.0))
    )
    padded_cell_count = int(vertex_count) * max(1, max_count)
    if csr_valid and max_count <= 256 and padded_cell_count <= 16_000_000:
        if influence_count == 0:
            packed_weights[:, 0] = 1.0
        else:
            row_indices = np.repeat(np.arange(vertex_count, dtype=np.int64), counts)
            source_starts = np.repeat(offsets[:-1].astype(np.int64, copy=False), counts)
            slots = np.arange(influence_count, dtype=np.int64) - source_starts
            padded_indices = np.zeros((vertex_count, max_count), dtype=np.uint16)
            padded_weights = np.zeros((vertex_count, max_count), dtype=np.float32)
            padded_indices[row_indices, slots] = source_indices.astype(np.uint16, copy=False)
            padded_weights[row_indices, slots] = source_weights
            if max_count <= width:
                packed_indices[:, :max_count] = padded_indices
                packed_weights[:, :max_count] = padded_weights
            else:
                order = np.argsort(padded_weights, axis=1)[:, ::-1][:, :width]
                packed_indices[:] = np.take_along_axis(padded_indices, order, axis=1)
                packed_weights[:] = np.take_along_axis(padded_weights, order, axis=1)
                source_totals = np.bincount(
                    row_indices,
                    weights=source_weights.astype(np.float64, copy=False),
                    minlength=vertex_count,
                )
                retained_totals = packed_weights.sum(axis=1, dtype=np.float64)
                discarded_weight = float(np.maximum(0.0, source_totals - retained_totals).sum())
                vertices_reduced = int(np.count_nonzero(counts > width))
            totals = packed_weights.sum(axis=1, dtype=np.float64)
            populated = totals > 1.0e-12
            packed_weights[populated] /= totals[populated, None].astype(np.float32)
            packed_weights[~populated, 0] = 1.0
        return {
            "joint_indices_u16": packed_indices.reshape(-1),
            "weights_f32": packed_weights.reshape(-1),
            "vertices_reduced": int(vertices_reduced),
            "discarded_weight": float(discarded_weight),
            "max_discarded_weight_per_vertex": float(discarded_weight / max(1, vertices_reduced)),
            "influence_width": width,
        }

    for vertex_index in range(vertex_count):
        start = int(offsets[vertex_index])
        end = int(offsets[vertex_index + 1])
        if end <= start:
            packed_weights[vertex_index, 0] = 1.0
            continue
        source_indices = indices[start:end].astype(np.int64, copy=False)
        source_weights = weights[start:end].astype(np.float64, copy=False)
        valid = (
            (source_indices >= 0)
            & (source_indices < int(joint_count))
            & np.isfinite(source_weights)
            & (source_weights > 0.0)
        )
        source_indices = source_indices[valid]
        source_weights = source_weights[valid]
        if not len(source_weights):
            packed_weights[vertex_index, 0] = 1.0
            continue
        order = np.argsort(source_weights)[::-1]
        if len(order) > width:
            discarded_weight += float(source_weights[order[width:]].sum())
            vertices_reduced += 1
        order = order[:width]
        chosen_indices = source_indices[order]
        chosen_weights = source_weights[order]
        total = float(chosen_weights.sum())
        if total <= 1.0e-12:
            packed_weights[vertex_index, 0] = 1.0
            continue
        count = len(chosen_weights)
        packed_indices[vertex_index, :count] = chosen_indices.astype(np.uint16, copy=False)
        packed_weights[vertex_index, :count] = (chosen_weights / total).astype(np.float32, copy=False)
    return {
        "joint_indices_u16": packed_indices.reshape(-1),
        "weights_f32": packed_weights.reshape(-1),
        "vertices_reduced": int(vertices_reduced),
        "discarded_weight": float(discarded_weight),
        "max_discarded_weight_per_vertex": float(discarded_weight / max(1, vertices_reduced)),
        "influence_width": width,
    }


def build_top4_skinning_buffers(mesh: dict[str, Any], joint_count: int) -> dict[str, Any]:
    """Build an optional four-influence cache for Qt's built-in skin path."""
    return build_fixed_width_skinning_buffers(mesh, joint_count, influence_width=4)


def build_top8_skinning_buffers(mesh: dict[str, Any], joint_count: int) -> dict[str, Any]:
    """Build an eight-influence cache for the custom high-fidelity GPU path."""
    return build_fixed_width_skinning_buffers(mesh, joint_count, influence_width=8)


def select_lossless_gpu_influence_width(
    mesh: dict[str, Any],
    *,
    top4_parity_accepted: bool,
    top8_parity_accepted: bool,
) -> int:
    """Select only a fixed-width cache that retains every authoritative influence."""
    max_influences = int(mesh.get("max_influences_per_vertex", 0) or 0)
    reduction4 = mesh.get("gpu_weight_reduction") or {}
    reduction8 = mesh.get("gpu_weight_reduction_8") or {}
    if (
        max_influences <= 4
        and int(reduction4.get("vertices_reduced", 0) or 0) == 0
        and bool(top4_parity_accepted)
    ):
        return 4
    if (
        max_influences <= 8
        and int(reduction8.get("vertices_reduced", 0) or 0) == 0
        and bool(top8_parity_accepted)
    ):
        return 8
    return 0


def reconstruct_fixed_width_linear_blend_positions(
    binding: dict[str, Any],
    frame: dict[str, Any],
    mesh_native_id: str,
    *,
    influence_width: int,
    joint_indices_key: str,
    weights_key: str,
):
    """Evaluate the exact fixed-width buffers intended for a GPU skin path."""
    if np is None:
        raise RuntimeError("NumPy is required for GPU skinning parity checks.")
    mesh = next(
        (item for item in binding.get("meshes") or [] if str(item.get("native_id") or "") == str(mesh_native_id)),
        None,
    )
    if mesh is None:
        raise KeyError(f"No deformation binding exists for {mesh_native_id}")
    skeleton_id = str(mesh.get("skeleton_id") or "")
    skeleton = next(
        (item for item in binding.get("skeletons") or [] if str(item.get("native_id") or "") == skeleton_id),
        None,
    )
    pose = next(
        (item for item in frame.get("skeletons") or [] if str(item.get("native_id") or "") == skeleton_id),
        None,
    )
    if skeleton is None or pose is None:
        raise KeyError(f"No skeleton pose exists for {skeleton_id}")
    vertex_count = int(mesh.get("vertex_count", 0) or 0)
    joint_count = len(skeleton.get("joints") or [])
    width = int(influence_width)
    packed_indices = mesh.get(joint_indices_key)
    packed_weights = mesh.get(weights_key)
    if packed_indices is None or packed_weights is None:
        packed = build_fixed_width_skinning_buffers(mesh, joint_count, influence_width=width)
        packed_indices = packed["joint_indices_u16"]
        packed_weights = packed["weights_f32"]
    indices = np.asarray(packed_indices, dtype=np.uint16).reshape((vertex_count, width)).astype(np.int64, copy=False)
    weights = np.asarray(packed_weights, dtype=np.float32).reshape((vertex_count, width))
    bind_offset = int(mesh.get("bind_vertex_float_offset", 0) or 0)
    inverse_offset = int(skeleton.get("inverse_bind_float_offset", 0) or 0)
    matrix_offset = int(pose.get("joint_matrix_float_offset", 0) or 0)
    points = _float_view(mesh["bind_vertices_f32"], bind_offset, vertex_count * 3).reshape((vertex_count, 3))
    inverse_bind = _float_view(
        skeleton["inverse_bind_matrices_f32"], inverse_offset, joint_count * 16
    ).reshape((joint_count, 4, 4))
    joint_matrices = _float_view(
        pose["joint_matrices_f32"], matrix_offset, joint_count * 16
    ).reshape((joint_count, 4, 4))
    points_h = np.empty((vertex_count, 4), dtype=np.float32)
    points_h[:, :3] = points
    points_h[:, 3] = 1.0
    skin_matrices = _object_space_skin_matrices(mesh, frame, inverse_bind, joint_matrices)
    transformed = np.einsum(
        "ni,nkij->nkj",
        points_h,
        skin_matrices[indices],
        optimize=True,
    )
    return np.sum(transformed[:, :, :3] * weights[:, :, None], axis=1, dtype=np.float32)


def reconstruct_top4_linear_blend_positions(
    binding: dict[str, Any],
    frame: dict[str, Any],
    mesh_native_id: str,
):
    return reconstruct_fixed_width_linear_blend_positions(
        binding,
        frame,
        mesh_native_id,
        influence_width=4,
        joint_indices_key="gpu_joint_indices_u16",
        weights_key="gpu_weights_f32",
    )


def reconstruct_top8_linear_blend_positions(
    binding: dict[str, Any],
    frame: dict[str, Any],
    mesh_native_id: str,
):
    return reconstruct_fixed_width_linear_blend_positions(
        binding,
        frame,
        mesh_native_id,
        influence_width=8,
        joint_indices_key="gpu_joint_indices_u16_8",
        weights_key="gpu_weights_f32_8",
    )


def deformation_parity_metrics(
    reconstructed: Any,
    evaluated: Any,
    *,
    relative_rms_tolerance: float = 5.0e-5,
    relative_max_tolerance: float = 2.0e-4,
    absolute_tolerance: float = 1.0e-4,
) -> dict[str, float | bool]:
    """Measure reconstruction error and decide whether point streaming can be skipped."""
    if np is None:
        raise RuntimeError("NumPy is required for deformation parity measurement.")
    source = np.asarray(reconstructed, dtype=np.float64).reshape((-1, 3))
    target = np.asarray(evaluated, dtype=np.float64).reshape((-1, 3))
    if source.shape != target.shape or not len(source):
        raise ValueError("Parity samples must contain matching non-empty vertex arrays.")
    distance = np.linalg.norm(source - target, axis=1)
    bounds = np.ptp(target, axis=0)
    diagonal = max(float(np.linalg.norm(bounds)), float(absolute_tolerance))
    rms_error = float(np.sqrt(np.mean(distance * distance)))
    max_error = float(np.max(distance))
    rms_limit = max(float(absolute_tolerance), diagonal * float(relative_rms_tolerance))
    max_limit = max(float(absolute_tolerance), diagonal * float(relative_max_tolerance))
    return {
        "accepted": bool(rms_error <= rms_limit and max_error <= max_limit),
        "rms_error": rms_error,
        "max_error": max_error,
        "bounds_diagonal": diagonal,
        "relative_rms_error": rms_error / diagonal,
        "relative_max_error": max_error / diagonal,
        "rms_limit": rms_limit,
        "max_limit": max_limit,
    }


def _available(buffer: Any, offset: int) -> int:
    try:
        return len(buffer) - int(offset)
    except TypeError:
        return -1


def _object_space_skin_matrices(mesh: dict[str, Any], frame: dict[str, Any], inverse_bind: Any, joint_matrices: Any):
    """Build provider-local skin matrices, including a DCC's geometry bind space when supplied."""
    bind_geometry_values = mesh.get("bind_geometry_matrix")
    if bind_geometry_values is None:
        return inverse_bind @ joint_matrices
    bind_geometry = np.asarray(bind_geometry_values, dtype=np.float32).reshape((4, 4))
    native_id = str(mesh.get("native_id") or "")
    object_pose = next(
        (item for item in frame.get("objects") or [] if str(item.get("native_id") or "") == native_id),
        None,
    )
    world_values = (object_pose or {}).get("world_matrix")
    if not isinstance(world_values, (list, tuple)) or len(world_values) < 16:
        raise ValueError(f"Skin pose for {native_id} has no current geometry world matrix.")
    object_world_inverse = np.linalg.inv(np.asarray(world_values[:16], dtype=np.float32).reshape((4, 4)))
    return bind_geometry @ inverse_bind @ joint_matrices @ object_world_inverse


def _float_view(buffer: Any, offset: int, count: int):
    try:
        return np.frombuffer(buffer, dtype=np.float32, count=int(count), offset=int(offset) * 4)
    except (TypeError, ValueError):
        return np.asarray(buffer[int(offset):int(offset) + int(count)], dtype=np.float32)


def _uint_view(buffer: Any, offset: int, count: int):
    try:
        return np.frombuffer(buffer, dtype=np.uint32, count=int(count), offset=int(offset) * 4)
    except (TypeError, ValueError):
        return np.asarray(buffer[int(offset):int(offset) + int(count)], dtype=np.uint32)
