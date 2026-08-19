import array
import unittest

import numpy as np

from tech_connector.services.dcc.deformation_contract import (
    DEFORMATION_BINDING_SCHEMA,
    DEFORMATION_FRAME_SCHEMA,
    build_top4_skinning_buffers,
    build_top8_skinning_buffers,
    deformation_parity_metrics,
    deformation_frame_has_joint_poses,
    normalize_deformation_binding,
    normalize_deformation_frame,
    reconstruct_linear_blend_positions,
    reconstruct_top4_linear_blend_positions,
    reconstruct_top8_linear_blend_positions,
    select_lossless_gpu_influence_width,
)
from tech_connector.services.dcc.gpu_skinning_contract import (
    GpuSkinMeshSpec,
    build_skin_matrix_palette,
    emulate_gpu_skin_positions,
    emulate_sparse_gpu_skin_positions,
    fixed_width_render_influence_texels,
    select_exact_gpu_skinning_mode,
    sparse_render_influence_texels,
)


class DeformationContractTests(unittest.TestCase):
    def test_preserves_shared_sparse_skin_buffers(self):
        floats = array.array("f", [1.0] * (16 + 6 + 2))
        integers = array.array("I", [0, 1, 2, 0, 0])
        packet = normalize_deformation_binding(
            {
                "provider_id": "maya:7001",
                "skeletons": [{
                    "native_id": "skinCluster1",
                    "joints": [{"native_id": "|root"}],
                    "inverse_bind_matrices_f32": floats,
                }],
                "meshes": [{
                    "native_id": "|mesh",
                    "deformation_mode": "linear_blend_skinning",
                    "skeleton_id": "skinCluster1",
                    "vertex_count": 2,
                    "bind_vertices_f32": floats,
                    "bind_vertex_float_offset": 16,
                    "influence_offsets_u32": integers,
                    "influence_offset_offset": 0,
                    "joint_indices_u32": integers,
                    "joint_index_offset": 3,
                    "weights_f32": floats,
                    "weight_float_offset": 22,
                }],
            }
        )

        self.assertEqual(packet["schema"], DEFORMATION_BINDING_SCHEMA)
        self.assertEqual(packet["contract_errors"], [])
        self.assertIs(packet["meshes"][0]["weights_f32"], floats)

    def test_rejects_out_of_range_joint_index(self):
        packet = normalize_deformation_binding(
            {
                "provider_id": "maya",
                "skeletons": [{
                    "native_id": "skin",
                    "joints": [{"native_id": "root"}],
                    "inverse_bind_matrices_f32": array.array("f", [0.0] * 16),
                }],
                "meshes": [{
                    "native_id": "mesh",
                    "deformation_mode": "linear_blend_skinning",
                    "skeleton_id": "skin",
                    "vertex_count": 1,
                    "bind_vertices_f32": array.array("f", [0.0, 0.0, 0.0]),
                    "influence_offsets_u32": array.array("I", [0, 1]),
                    "joint_indices_u32": array.array("I", [2]),
                    "weights_f32": array.array("f", [1.0]),
                }],
            }
        )

        self.assertTrue(any("outside the skeleton" in error for error in packet["contract_errors"]))

    def test_accepts_compact_joint_pose(self):
        matrices = array.array("f", [1.0] * 32)
        packet = normalize_deformation_frame(
            {
                "provider_id": "maya:7001",
                "skeletons": [{
                    "native_id": "skin",
                    "joint_count": 2,
                    "joint_matrices_f32": matrices,
                }],
            }
        )

        self.assertEqual(packet["schema"], DEFORMATION_FRAME_SCHEMA)
        self.assertEqual(packet["contract_errors"], [])
        self.assertTrue(deformation_frame_has_joint_poses(packet))
        self.assertIs(packet["skeletons"][0]["joint_matrices_f32"], matrices)

    def test_reconstructs_sparse_linear_skin_and_measures_parity(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        translated = identity[:]
        translated[12] = 2.0
        binding = normalize_deformation_binding({
            "provider_id": "maya",
            "skeletons": [{
                "native_id": "skin",
                "joints": [{"native_id": "joint"}],
                "inverse_bind_matrices_f32": array.array("f", identity),
            }],
            "meshes": [{
                "native_id": "mesh",
                "deformation_mode": "linear_blend_skinning",
                "skeleton_id": "skin",
                "vertex_count": 2,
                "bind_vertices_f32": array.array("f", [0, 0, 0, 1, 0, 0]),
                "influence_offsets_u32": array.array("I", [0, 1, 2]),
                "joint_indices_u32": array.array("I", [0, 0]),
                "weights_f32": array.array("f", [1, 1]),
            }],
        })
        frame = normalize_deformation_frame({
            "provider_id": "maya",
            "skeletons": [{
                "native_id": "skin",
                "joint_count": 1,
                "joint_matrices_f32": array.array("f", translated),
            }],
        })

        positions = reconstruct_linear_blend_positions(binding, frame, "mesh")
        self.assertEqual(positions.tolist(), [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0]])
        metrics = deformation_parity_metrics(positions, positions)
        self.assertTrue(metrics["accepted"])
        self.assertEqual(metrics["max_error"], 0.0)

    def test_geometry_bind_space_matches_cpu_and_gpu_skinning(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        bind_geometry = identity[:]
        bind_geometry[14] = 2.0
        joint = identity[:]
        joint[0] = 0.0
        joint[2] = -1.0
        joint[8] = 1.0
        joint[10] = 0.0
        object_world = bind_geometry[:]
        binding = normalize_deformation_binding({
            "provider_id": "maya",
            "unit_linear": "cm",
            "up_axis": "y",
            "skeletons": [{
                "native_id": "skin",
                "joints": [{"native_id": "joint"}],
                "inverse_bind_matrices_f32": array.array("f", identity),
            }],
            "meshes": [{
                "native_id": "mesh",
                "deformation_mode": "linear_blend_skinning",
                "skeleton_id": "skin",
                "vertex_count": 1,
                "bind_geometry_matrix": bind_geometry,
                "bind_vertices_f32": array.array("f", [1, 0, 0]),
                "influence_offsets_u32": array.array("I", [0, 1]),
                "joint_indices_u32": array.array("I", [0]),
                "weights_f32": array.array("f", [1]),
                "max_influences_per_vertex": 1,
            }],
        })
        frame = normalize_deformation_frame({
            "provider_id": "maya",
            "skeletons": [{
                "native_id": "skin",
                "joint_count": 1,
                "joint_matrices_f32": array.array("f", joint),
            }],
            "objects": [{"native_id": "mesh", "world_matrix": object_world}],
        })
        mesh = binding["meshes"][0]
        packed = build_top4_skinning_buffers(mesh, 1)
        mesh["gpu_joint_indices_u16"] = packed["joint_indices_u16"]
        mesh["gpu_weights_f32"] = packed["weights_f32"]
        mesh["gpu_influence_width"] = 4
        texels = fixed_width_render_influence_texels(mesh, [0])
        palette = build_skin_matrix_palette(
            binding,
            frame,
            [GpuSkinMeshSpec("maya", "mesh", "skin", 0, 1, 0, 1, 4)],
            scene_center=(0, 0, 0),
            scene_scale=1.0,
        )
        exact_object = reconstruct_linear_blend_positions(binding, frame, "mesh")
        object_world_matrix = np.asarray(object_world, dtype=np.float32).reshape((4, 4))
        exact_world = exact_object @ object_world_matrix[:3, :3] + object_world_matrix[3, :3]
        gpu = emulate_gpu_skin_positions([[1, 0, 0]], texels, palette)
        self.assertLess(float(abs(gpu - exact_world).max()), 1.0e-5)

    def test_top4_gpu_buffers_keep_largest_weights_and_match_their_cpu_reference(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        frame_matrices = []
        for translation in range(5):
            matrix = identity[:]
            matrix[12] = float(translation)
            frame_matrices.extend(matrix)
        binding = normalize_deformation_binding({
            "provider_id": "maya",
            "skeletons": [{
                "native_id": "skin",
                "joints": [{"native_id": f"joint{index}"} for index in range(5)],
                "inverse_bind_matrices_f32": array.array("f", identity * 5),
            }],
            "meshes": [{
                "native_id": "mesh",
                "deformation_mode": "linear_blend_skinning",
                "skeleton_id": "skin",
                "vertex_count": 1,
                "bind_vertices_f32": array.array("f", [0, 0, 0]),
                "influence_offsets_u32": array.array("I", [0, 5]),
                "joint_indices_u32": array.array("I", [0, 1, 2, 3, 4]),
                "weights_f32": array.array("f", [0.4, 0.3, 0.2, 0.09, 0.01]),
            }],
        })
        frame = normalize_deformation_frame({
            "provider_id": "maya",
            "skeletons": [{
                "native_id": "skin",
                "joint_count": 5,
                "joint_matrices_f32": array.array("f", frame_matrices),
            }],
        })
        mesh = binding["meshes"][0]
        packed = build_top4_skinning_buffers(mesh, 5)
        mesh["gpu_joint_indices_u16"] = packed["joint_indices_u16"]
        mesh["gpu_weights_f32"] = packed["weights_f32"]

        self.assertEqual(packed["vertices_reduced"], 1)
        self.assertNotIn(4, packed["joint_indices_u16"].tolist())
        self.assertAlmostEqual(sum(packed["weights_f32"]), 1.0, places=6)
        positions = reconstruct_top4_linear_blend_positions(binding, frame, "mesh")
        self.assertAlmostEqual(float(positions[0, 0]), 0.97 / 0.99, places=6)

        packed8 = build_top8_skinning_buffers(mesh, 5)
        mesh["gpu_joint_indices_u16_8"] = packed8["joint_indices_u16"]
        mesh["gpu_weights_f32_8"] = packed8["weights_f32"]
        positions8 = reconstruct_top8_linear_blend_positions(binding, frame, "mesh")
        exact = reconstruct_linear_blend_positions(binding, frame, "mesh")
        self.assertEqual(packed8["vertices_reduced"], 0)
        self.assertAlmostEqual(float(positions8[0, 0]), float(exact[0, 0]), places=6)

    def test_vectorized_fixed_width_packing_matches_vertex_reference(self):
        counts = np.asarray([0, 2, 6, 1, 5], dtype=np.uint32)
        offsets = np.concatenate(([0], np.cumsum(counts))).astype(np.uint32)
        indices = np.asarray([1, 3, 0, 1, 2, 3, 4, 5, 2, 0, 1, 2, 3, 4], dtype=np.uint32)
        weights = np.asarray(
            [0.25, 0.75, 0.06, 0.11, 0.17, 0.21, 0.19, 0.26, 1.0, 0.05, 0.15, 0.25, 0.2, 0.35],
            dtype=np.float32,
        )
        mesh = {
            "vertex_count": len(counts),
            "influence_offsets_u32": offsets,
            "joint_indices_u32": indices,
            "weights_f32": weights,
        }

        packed = build_top4_skinning_buffers(mesh, 6)
        actual_indices = np.asarray(packed["joint_indices_u16"]).reshape((-1, 4))
        actual_weights = np.asarray(packed["weights_f32"]).reshape((-1, 4))
        expected_indices = np.zeros_like(actual_indices)
        expected_weights = np.zeros_like(actual_weights)
        discarded = 0.0
        reduced = 0
        for vertex in range(len(counts)):
            start, end = int(offsets[vertex]), int(offsets[vertex + 1])
            if end <= start:
                expected_weights[vertex, 0] = 1.0
                continue
            order = np.argsort(weights[start:end])[::-1]
            if len(order) > 4:
                discarded += float(weights[start:end][order[4:]].sum())
                reduced += 1
            order = order[:4]
            chosen = weights[start:end][order]
            expected_indices[vertex, :len(order)] = indices[start:end][order]
            expected_weights[vertex, :len(order)] = chosen / chosen.sum()

        np.testing.assert_array_equal(actual_indices, expected_indices)
        np.testing.assert_allclose(actual_weights, expected_weights, rtol=1.0e-6, atol=1.0e-7)
        self.assertEqual(packed["vertices_reduced"], reduced)
        self.assertAlmostEqual(packed["discarded_weight"], discarded, places=6)

    def test_lossless_gpu_width_never_truncates_eight_or_higher_influence_assets(self):
        mesh = {
            "max_influences_per_vertex": 7,
            "gpu_weight_reduction": {"vertices_reduced": 12},
            "gpu_weight_reduction_8": {"vertices_reduced": 0},
        }
        self.assertEqual(
            select_lossless_gpu_influence_width(
                mesh,
                top4_parity_accepted=True,
                top8_parity_accepted=True,
            ),
            8,
        )
        mesh["max_influences_per_vertex"] = 10
        mesh["gpu_weight_reduction_8"] = {"vertices_reduced": 2}
        self.assertEqual(
            select_lossless_gpu_influence_width(
                mesh,
                top4_parity_accepted=True,
                top8_parity_accepted=True,
            ),
            0,
        )

    def test_eight_influence_gpu_packet_matches_exact_sparse_skinning(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        joint_matrices = []
        for index in range(8):
            matrix = identity[:]
            matrix[12] = float(index) * 0.25
            matrix[13] = float(index % 3) * -0.125
            joint_matrices.extend(matrix)
        weights = [0.22, 0.18, 0.16, 0.14, 0.12, 0.08, 0.06, 0.04]
        binding = normalize_deformation_binding({
            "provider_id": "maya",
            "unit_linear": "cm",
            "up_axis": "y",
            "skeletons": [{
                "native_id": "skin",
                "joints": [{"native_id": f"joint{index}"} for index in range(8)],
                "inverse_bind_matrices_f32": array.array("f", identity * 8),
            }],
            "meshes": [{
                "native_id": "mesh",
                "deformation_mode": "linear_blend_skinning",
                "skeleton_id": "skin",
                "vertex_count": 2,
                "bind_vertices_f32": array.array("f", [1, 2, 3, -2, 0.5, 4]),
                "influence_offsets_u32": array.array("I", [0, 8, 16]),
                "joint_indices_u32": array.array("I", list(range(8)) * 2),
                "weights_f32": array.array("f", weights * 2),
                "max_influences_per_vertex": 8,
            }],
        })
        world = identity[:]
        world[12:15] = [4.0, -2.0, 1.0]
        frame = normalize_deformation_frame({
            "provider_id": "maya",
            "skeletons": [{
                "native_id": "skin",
                "joint_count": 8,
                "joint_matrices_f32": array.array("f", joint_matrices),
            }],
            "objects": [{"native_id": "mesh", "world_matrix": world}],
        })
        mesh = binding["meshes"][0]
        packed = build_top8_skinning_buffers(mesh, 8)
        mesh["gpu_joint_indices_u16_8"] = packed["joint_indices_u16"]
        mesh["gpu_weights_f32_8"] = packed["weights_f32"]
        mesh["gpu_influence_width"] = 8
        texels = fixed_width_render_influence_texels(mesh, [0, 1], palette_offset=0)
        specs = [GpuSkinMeshSpec("maya", "mesh", "skin", 0, 8, 0, 2, 8)]
        palette = build_skin_matrix_palette(
            binding,
            frame,
            specs,
            scene_center=(1.0, 2.0, 3.0),
            scene_scale=0.5,
        )
        gpu = emulate_gpu_skin_positions([[1, 2, 3], [-2, 0.5, 4]], texels, palette)

        exact_object = reconstruct_linear_blend_positions(binding, frame, "mesh")
        exact_world = exact_object.copy()
        exact_world[:, 0] += 4.0
        exact_world[:, 1] -= 2.0
        exact_world[:, 2] += 1.0
        expected = (exact_world - [1.0, 2.0, 3.0]) * 0.5
        self.assertEqual(texels.shape, (2, 4, 4))
        self.assertEqual(texels[0, 2].tolist(), [4.0, 5.0, 6.0, 7.0])
        self.assertLess(float(abs(gpu - expected).max()), 1.0e-5)

    def test_sparse_gpu_packet_preserves_twenty_three_influences(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        matrices = []
        for index in range(23):
            matrix = identity[:]
            matrix[12] = index * 0.1
            matrices.extend(matrix)
        weights = [float(index + 1) for index in range(23)]
        total = sum(weights)
        weights = [value / total for value in weights]
        binding = normalize_deformation_binding({
            "provider_id": "maya",
            "unit_linear": "cm",
            "up_axis": "y",
            "skeletons": [{
                "native_id": "skin",
                "joints": [{"native_id": f"joint{index}"} for index in range(23)],
                "inverse_bind_matrices_f32": array.array("f", identity * 23),
            }],
            "meshes": [{
                "native_id": "mesh",
                "deformation_mode": "linear_blend_skinning",
                "skeleton_id": "skin",
                "vertex_count": 1,
                "bind_vertices_f32": array.array("f", [2, 3, 4]),
                "influence_offsets_u32": array.array("I", [0, 23]),
                "joint_indices_u32": array.array("I", list(range(23))),
                "weights_f32": array.array("f", weights),
                "max_influences_per_vertex": 23,
            }],
        })
        frame = normalize_deformation_frame({
            "provider_id": "maya",
            "skeletons": [{
                "native_id": "skin",
                "joint_count": 23,
                "joint_matrices_f32": array.array("f", matrices),
            }],
            "objects": [{"native_id": "mesh", "world_matrix": identity}],
        })
        mesh = binding["meshes"][0]
        mode, width = select_exact_gpu_skinning_mode(
            mesh,
            exact_parity_accepted=True,
            top4_parity_accepted=False,
            top8_parity_accepted=False,
        )
        metadata, texels, maximum = sparse_render_influence_texels(mesh, [0])
        palette = build_skin_matrix_palette(
            binding,
            frame,
            [GpuSkinMeshSpec("maya", "mesh", "skin", 0, 23, 0, 1, width)],
            scene_center=(0, 0, 0),
            scene_scale=1.0,
        )
        gpu = emulate_sparse_gpu_skin_positions([[2, 3, 4]], metadata, texels, palette)
        exact = reconstruct_linear_blend_positions(binding, frame, "mesh")
        self.assertEqual((mode, width, maximum), ("sparse", 0, 23))
        self.assertEqual(texels.shape, (12, 4))
        self.assertLess(float(abs(gpu - exact).max()), 1.0e-5)


if __name__ == "__main__":
    unittest.main()
