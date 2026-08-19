"""GPU-ready, lossless fixed-width skinning packets for the compiled viewport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tech_connector.game_engine.scene.coordinate_space_service import provider_axis_basis, unit_to_centimeters
from tech_connector.game_engine.deformation.deformation_contract import select_lossless_gpu_influence_width

try:
    import numpy as np
except Exception:  # pragma: no cover - stripped DCC runtimes use point fallback.
    np = None


@dataclass(frozen=True)
class GpuSkinMeshSpec:
    provider_id: str
    native_id: str
    skeleton_id: str
    palette_offset: int
    joint_count: int
    vertex_start: int
    vertex_count: int
    influence_width: int


MAX_GPU_SPARSE_INFLUENCES = 32


def _float_view(source: Any, offset: int, count: int):
    if np is None:
        raise RuntimeError("NumPy is required for GPU skinning packet construction.")
    if isinstance(source, np.ndarray):
        return source.reshape(-1)[offset : offset + count].astype(np.float32, copy=False)
    try:
        return np.frombuffer(source, dtype=np.float32, count=count, offset=offset * 4)
    except (TypeError, ValueError):
        return np.asarray(source[offset : offset + count], dtype=np.float32)


def fixed_width_render_influence_texels(
    mesh: dict[str, Any],
    source_vertex_indices: list[int] | tuple[int, ...] | Any,
    *,
    palette_offset: int = 0,
) -> Any:
    """Expand a lossless 4/8 cache into four RGBA32F texels per render vertex."""
    if np is None:
        raise RuntimeError("NumPy is required for GPU skinning packet construction.")
    width = int(mesh.get("gpu_influence_width", 0) or 0)
    if width not in {4, 8}:
        raise ValueError("Only calibrated 4- or 8-influence meshes can enter the GPU skin path.")
    suffix = "_8" if width == 8 else ""
    indices = mesh.get(f"gpu_joint_indices_u16{suffix}")
    weights = mesh.get(f"gpu_weights_f32{suffix}")
    vertex_count = int(mesh.get("vertex_count", 0) or 0)
    if indices is None or weights is None or vertex_count <= 0:
        raise ValueError("The calibrated fixed-width skin cache is incomplete.")
    source_indices = np.asarray(source_vertex_indices, dtype=np.int64).reshape(-1)
    if not len(source_indices):
        return np.empty((0, 4, 4), dtype=np.float32)
    if int(source_indices.min(initial=0)) < 0 or int(source_indices.max(initial=0)) >= vertex_count:
        raise ValueError("A render vertex references a source vertex outside the skin binding.")
    packed_indices = np.asarray(indices, dtype=np.uint16).reshape((vertex_count, width))[source_indices]
    packed_weights = np.asarray(weights, dtype=np.float32).reshape((vertex_count, width))[source_indices]
    texels = np.zeros((len(source_indices), 4, 4), dtype=np.float32)
    texels[:, 0, :] = packed_indices[:, :4].astype(np.float32) + float(palette_offset)
    texels[:, 1, :] = packed_weights[:, :4]
    if width == 8:
        texels[:, 2, :] = packed_indices[:, 4:8].astype(np.float32) + float(palette_offset)
        texels[:, 3, :] = packed_weights[:, 4:8]
    return texels


def sparse_render_influence_texels(
    mesh: dict[str, Any],
    source_vertex_indices: list[int] | tuple[int, ...] | Any,
    *,
    palette_offset: int = 0,
    max_influences: int = MAX_GPU_SPARSE_INFLUENCES,
) -> tuple[Any, Any, int]:
    """Pack authoritative sparse weights as two (joint, weight) pairs per RGBA32F texel."""
    if np is None:
        raise RuntimeError("NumPy is required for GPU skinning packet construction.")
    vertex_count = int(mesh.get("vertex_count", 0) or 0)
    source_map = np.asarray(source_vertex_indices, dtype=np.int64).reshape(-1)
    if not len(source_map):
        return np.empty((0, 2), dtype=np.float32), np.empty((0, 4), dtype=np.float32), 0
    if int(source_map.min(initial=0)) < 0 or int(source_map.max(initial=0)) >= vertex_count:
        raise ValueError("A render vertex references a source vertex outside the sparse skin binding.")
    offset_start = int(mesh.get("influence_offset_offset", 0) or 0)
    index_start = int(mesh.get("joint_index_offset", 0) or 0)
    weight_start = int(mesh.get("weight_float_offset", 0) or 0)
    offsets = np.asarray(mesh["influence_offsets_u32"], dtype=np.uint32).reshape(-1)[
        offset_start : offset_start + vertex_count + 1
    ]
    influence_count = int(offsets[-1]) if len(offsets) else 0
    joint_indices = np.asarray(mesh["joint_indices_u32"], dtype=np.uint32).reshape(-1)[
        index_start : index_start + influence_count
    ]
    weights = _float_view(mesh["weights_f32"], weight_start, influence_count)
    metadata = np.zeros((len(source_map), 2), dtype=np.float32)
    texels: list[tuple[float, float, float, float]] = []
    maximum = 0
    for render_index, source_index in enumerate(source_map):
        start = int(offsets[int(source_index)])
        end = int(offsets[int(source_index) + 1])
        count = end - start
        if count <= 0:
            raise ValueError("A zero-influence vertex requires exact point fallback.")
        if count > int(max_influences):
            raise ValueError(f"A vertex has {count} influences; the GPU sparse limit is {max_influences}.")
        metadata[render_index] = (float(len(texels)), float(count))
        maximum = max(maximum, count)
        for influence_index in range(start, end, 2):
            first_joint = float(int(joint_indices[influence_index]) + int(palette_offset))
            first_weight = float(weights[influence_index])
            if influence_index + 1 < end:
                second_joint = float(int(joint_indices[influence_index + 1]) + int(palette_offset))
                second_weight = float(weights[influence_index + 1])
            else:
                second_joint = 0.0
                second_weight = 0.0
            texels.append((first_joint, first_weight, second_joint, second_weight))
    return metadata, np.asarray(texels, dtype=np.float32), maximum


def select_exact_gpu_skinning_mode(
    mesh: dict[str, Any],
    *,
    exact_parity_accepted: bool,
    top4_parity_accepted: bool,
    top8_parity_accepted: bool,
    sparse_limit: int = MAX_GPU_SPARSE_INFLUENCES,
) -> tuple[str, int]:
    """Choose a lossless fixed or sparse GPU representation without discarding weights."""
    fixed_width = select_lossless_gpu_influence_width(
        mesh,
        top4_parity_accepted=top4_parity_accepted,
        top8_parity_accepted=top8_parity_accepted,
    )
    if fixed_width in {4, 8}:
        return f"fixed{fixed_width}", fixed_width
    maximum = int(mesh.get("max_influences_per_vertex", 0) or 0)
    if bool(exact_parity_accepted) and 0 < maximum <= int(sparse_limit):
        return "sparse", 0
    return "point_cache", 0


def provider_to_viewer_row_matrix(
    provider_id: str,
    *,
    up_axis: str | None,
    unit_linear: str | None,
    scene_center: tuple[float, float, float],
    scene_scale: float,
) -> Any:
    """Return a row-vector matrix from provider world space to viewer-local space."""
    if np is None:
        raise RuntimeError("NumPy is required for GPU skinning packet construction.")
    provider = str(provider_id or "").lower().split(":", 1)[0]
    basis = provider_axis_basis(provider, up_axis)
    axes = (basis.shared_x_from_native, basis.shared_y_from_native, basis.shared_z_from_native)
    unit_scale = float(unit_to_centimeters(unit_linear, provider))
    to_shared = np.eye(4, dtype=np.float32)
    to_shared[:3, :3] = 0.0
    for shared_axis, (native_axis, sign) in enumerate(axes):
        to_shared[int(native_axis), shared_axis] = float(sign) * unit_scale
    normalization = np.eye(4, dtype=np.float32)
    normalization[0, 0] = normalization[1, 1] = normalization[2, 2] = float(scene_scale)
    normalization[3, :3] = -np.asarray(scene_center[:3], dtype=np.float32) * float(scene_scale)
    return to_shared @ normalization


def build_skin_matrix_palette(
    binding: dict[str, Any],
    frame: dict[str, Any],
    mesh_specs: list[GpuSkinMeshSpec],
    *,
    scene_center: tuple[float, float, float],
    scene_scale: float,
) -> Any:
    """Build shader matrices whose column-vector result matches the exact CPU row contract."""
    if np is None:
        raise RuntimeError("NumPy is required for GPU skinning packet construction.")
    skeletons = {
        str(item.get("native_id") or ""): item
        for item in binding.get("skeletons") or []
        if isinstance(item, dict)
    }
    poses = {
        str(item.get("native_id") or ""): item
        for item in frame.get("skeletons") or []
        if isinstance(item, dict)
    }
    objects = {
        str(item.get("native_id") or ""): item
        for item in frame.get("objects") or []
        if isinstance(item, dict)
    }
    palette_count = max((spec.palette_offset + spec.joint_count for spec in mesh_specs), default=0)
    palette = np.zeros((palette_count, 4, 4), dtype=np.float32)
    provider_to_viewer = provider_to_viewer_row_matrix(
        str(binding.get("provider_id") or ""),
        up_axis=binding.get("up_axis"),
        unit_linear=binding.get("unit_linear"),
        scene_center=scene_center,
        scene_scale=scene_scale,
    )
    for spec in mesh_specs:
        skeleton = skeletons.get(spec.skeleton_id)
        pose = poses.get(spec.skeleton_id)
        object_pose = objects.get(spec.native_id) or {}
        if skeleton is None or pose is None:
            raise KeyError(f"No pose exists for GPU skin {spec.provider_id}:{spec.native_id}")
        inverse_offset = int(skeleton.get("inverse_bind_float_offset", 0) or 0)
        pose_offset = int(pose.get("joint_matrix_float_offset", 0) or 0)
        inverse_bind = _float_view(
            skeleton["inverse_bind_matrices_f32"], inverse_offset, spec.joint_count * 16
        ).reshape((spec.joint_count, 4, 4))
        joint_world = _float_view(
            pose["joint_matrices_f32"], pose_offset, spec.joint_count * 16
        ).reshape((spec.joint_count, 4, 4))
        mesh = next(
            (
                item
                for item in binding.get("meshes") or []
                if str(item.get("native_id") or "") == spec.native_id
                and str(item.get("skeleton_id") or "") == spec.skeleton_id
            ),
            None,
        )
        bind_geometry_values = (mesh or {}).get("bind_geometry_matrix")
        if bind_geometry_values is not None:
            bind_geometry = np.asarray(bind_geometry_values, dtype=np.float32).reshape((4, 4))
            row_matrices = bind_geometry @ inverse_bind @ joint_world @ provider_to_viewer
        else:
            world_values = object_pose.get("world_matrix")
            if not isinstance(world_values, (list, tuple)) or len(world_values) < 16:
                raise ValueError(f"GPU skin pose for {spec.native_id} has no object world matrix.")
            object_world = np.asarray(world_values[:16], dtype=np.float32).reshape((4, 4))
            row_matrices = inverse_bind @ joint_world @ object_world @ provider_to_viewer
        # GLSL multiplies column vectors, so each uploaded matrix is the row contract transposed.
        palette[spec.palette_offset : spec.palette_offset + spec.joint_count] = row_matrices.transpose((0, 2, 1))
    return palette


def emulate_gpu_skin_positions(
    bind_positions: Any,
    influence_texels: Any,
    matrix_palette: Any,
) -> Any:
    """CPU emulation of the custom shader, used for parity tests and calibration."""
    if np is None:
        raise RuntimeError("NumPy is required for GPU skinning packet construction.")
    points = np.asarray(bind_positions, dtype=np.float32).reshape((-1, 3))
    texels = np.asarray(influence_texels, dtype=np.float32).reshape((-1, 4, 4))
    palette = np.asarray(matrix_palette, dtype=np.float32).reshape((-1, 4, 4))
    if len(points) != len(texels):
        raise ValueError("Bind positions and influence texels must have matching vertex counts.")
    ids = np.concatenate((texels[:, 0, :], texels[:, 2, :]), axis=1).astype(np.int64)
    weights = np.concatenate((texels[:, 1, :], texels[:, 3, :]), axis=1)
    points_h = np.empty((len(points), 4), dtype=np.float32)
    points_h[:, :3] = points
    points_h[:, 3] = 1.0
    transformed = np.einsum("nkij,nj->nki", palette[ids], points_h, optimize=True)
    return np.sum(transformed[:, :, :3] * weights[:, :, None], axis=1)


def emulate_sparse_gpu_skin_positions(
    bind_positions: Any,
    influence_metadata: Any,
    influence_texels: Any,
    matrix_palette: Any,
) -> Any:
    """CPU emulation of the sparse shader path for exact regression tests."""
    if np is None:
        raise RuntimeError("NumPy is required for GPU skinning packet construction.")
    points = np.asarray(bind_positions, dtype=np.float32).reshape((-1, 3))
    metadata = np.asarray(influence_metadata, dtype=np.float32).reshape((-1, 2))
    texels = np.asarray(influence_texels, dtype=np.float32).reshape((-1, 4))
    palette = np.asarray(matrix_palette, dtype=np.float32).reshape((-1, 4, 4))
    if len(points) != len(metadata):
        raise ValueError("Bind positions and sparse metadata must have matching vertex counts.")
    output = np.zeros((len(points), 3), dtype=np.float32)
    for vertex_index, point in enumerate(points):
        texel_offset = int(metadata[vertex_index, 0])
        count = int(metadata[vertex_index, 1])
        point_h = np.asarray((point[0], point[1], point[2], 1.0), dtype=np.float32)
        for influence_index in range(count):
            texel = texels[texel_offset + influence_index // 2]
            pair_offset = 0 if influence_index % 2 == 0 else 2
            joint = int(texel[pair_offset] + 0.5)
            weight = float(texel[pair_offset + 1])
            output[vertex_index] += (palette[joint] @ point_h)[:3] * weight
    return output

