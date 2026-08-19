import tempfile
from pathlib import Path
import array
import math
import unittest
import zipfile

from tech_connector.services.dcc.federated_scene_service import (
    EditableRigGraph,
    FederatedSceneDocument,
    load_federated_scene,
    reconcile_scene_sources,
    save_federated_scene,
    source_snapshot_blob_name,
    stable_scene_source_id,
)
from tech_connector.services.dcc.rig_topology_contract import (
    dependency_evaluation_order,
    normalize_rig_topology,
)
from tech_connector.services.dcc.rig_evaluation_service import rig_runtime_capabilities


class FederatedSceneServiceTests(unittest.TestCase):
    def test_editable_rig_prevents_cycles_and_normalizes_weight_edits(self):
        graph = EditableRigGraph()
        root = graph.add_joint("root", joint_id="root")
        child = graph.add_joint("child", parent_id=root, joint_id="child")
        skin = graph.add_skin("mesh", [root, child], skin_id="skin")
        graph.set_vertex_weights(skin, 12, {root: 2.0, child: 1.0})

        weights = graph.skins[skin]["weight_overrides"]["12"]
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        with self.assertRaises(ValueError):
            graph.reparent_joint(root, child)

    def test_tcscene_roundtrip_preserves_sources_rig_and_binary_blobs(self):
        graph = EditableRigGraph()
        graph.add_joint("root", joint_id="root")
        document = FederatedSceneDocument(
            name="Shot 010",
            sources=[{"provider": "maya", "session_key": "maya:7001", "source_path": "C:/show/shot.ma"}],
            rig_graph=graph,
            timeline={"frame": 24, "start": 1, "end": 120},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shot.tcscene"
            save_federated_scene(path, document, blobs={"skin/weights.f32": b"weights"})
            loaded, blobs = load_federated_scene(path)

        self.assertEqual(loaded.name, "Shot 010")
        self.assertIn("root", loaded.rig_graph.joints)
        self.assertEqual(loaded.timeline["frame"], 24)
        self.assertEqual(blobs["skin/weights.f32"], b"weights")

    def test_tcscene_roundtrip_preserves_restoration_manifest_and_cached_source(self):
        source_id = stable_scene_source_id("maya", "C:/show/shot.ma", "maya:7001")
        snapshot_blob = source_snapshot_blob_name(source_id)
        document = FederatedSceneDocument(
            sources=[{
                "source_id": source_id,
                "provider": "maya",
                "session_key": "maya:7001",
                "source_path": "C:/show/shot.ma",
                "snapshot_blob": snapshot_blob,
                "relaunchable": True,
            }],
            restoration={
                "policy": "inherit",
                "cached_sources": True,
                "launch_missing_sources": True,
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restore.tcscene"
            save_federated_scene(path, document, blobs={snapshot_blob: b'{"objects":[]}'})
            loaded, blobs = load_federated_scene(path)

        self.assertEqual(loaded.restoration["policy"], "inherit")
        self.assertTrue(loaded.restoration["cached_sources"])
        self.assertEqual(loaded.sources[0]["source_id"], source_id)
        self.assertEqual(blobs[snapshot_blob], b'{"objects":[]}')

    def test_tcscene_compresses_json_blobs_but_stores_binary_buffers(self):
        document = FederatedSceneDocument(name="Compression")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compression.tcscene"
            save_federated_scene(
                path,
                document,
                blobs={
                    "conversion/scene.json": b'{"objects":[]}' * 100,
                    "rig/weights.f32": b"\x00" * 400,
                },
            )
            with zipfile.ZipFile(path, "r") as archive:
                json_info = archive.getinfo("blobs/conversion/scene.json")
                binary_info = archive.getinfo("blobs/rig/weights.f32")

        self.assertEqual(json_info.compress_type, zipfile.ZIP_DEFLATED)
        self.assertEqual(binary_info.compress_type, zipfile.ZIP_STORED)

    def test_reconcile_prefers_matching_file_over_old_port(self):
        with tempfile.TemporaryDirectory() as directory:
            scene_path = Path(directory) / "character.ma"
            scene_path.write_text("// maya", encoding="ascii")
            document = FederatedSceneDocument(sources=[{
                "provider": "maya",
                "session_key": "maya:7001",
                "source_path": str(scene_path),
            }])
            result = reconcile_scene_sources(document, [
                {"provider": "maya", "key": "maya:7001", "scene": "C:/other.ma"},
                {"provider": "maya", "key": "maya:7004", "scene": str(scene_path)},
            ])

        self.assertEqual(result[0]["action"], "attach")
        self.assertEqual(result[0]["session_key"], "maya:7004")

    def test_deformation_binding_becomes_editable_rig_and_binary_sidecars(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        floats = array.array("f", identity + identity + [0, 0, 0, 1, 0, 0] + [1, 1])
        integers = array.array("I", [0, 1, 2, 0, 1])
        binding = {
            "provider_id": "maya:7001",
            "skeletons": [{
                "native_id": "skinCluster1",
                "joints": [
                    {"native_id": "|root", "name": "root", "parent_native_id": ""},
                    {"native_id": "|root|child", "name": "child", "parent_native_id": "|root"},
                ],
                "inverse_bind_matrices_f32": floats,
                "inverse_bind_float_offset": 0,
            }],
            "meshes": [{
                "native_id": "|mesh",
                "skeleton_id": "skinCluster1",
                "deformation_mode": "linear_blend_skinning",
                "runtime_mode": "skeletal",
                "vertex_count": 2,
                "bind_geometry_matrix": [
                    1, 0, 0, 0,
                    0, 1, 0, 0,
                    0, 0, 1, 0,
                    0, 0, 2, 1,
                ],
                "bind_vertices_f32": floats,
                "bind_vertex_float_offset": 32,
                "influence_offsets_u32": integers,
                "influence_offset_offset": 0,
                "joint_indices_u32": integers,
                "joint_index_offset": 3,
                "weights_f32": floats,
                "weight_float_offset": 38,
                "sparse_influence_count": 2,
            }],
        }
        graph = EditableRigGraph()
        blobs = graph.merge_deformation_binding(binding)

        self.assertIn("maya:7001::|root", graph.joints)
        self.assertEqual(graph.joints["maya:7001::|root|child"]["parent_id"], "maya:7001::|root")
        self.assertEqual(graph.joint_edit_policy("maya:7001::|root"), "source_driven")
        with self.assertRaises(PermissionError):
            graph.reparent_joint("maya:7001::|root|child", "")
        self.assertEqual(len(graph.skins), 1)
        imported_skin = next(iter(graph.skins.values()))
        self.assertEqual(imported_skin["ownership"], "linked")
        self.assertEqual(imported_skin["bind_geometry_matrix"][14], 2.0)
        self.assertEqual(len(blobs), 5)
        self.assertTrue(any(name.endswith("weights.f32") for name in blobs))

    def test_native_fbx_and_local_rig_elements_remain_fully_editable(self):
        graph = EditableRigGraph()
        native_root = graph.add_joint(
            "root",
            joint_id="native_fbx::root",
            source_ref={"provider_id": "native_fbx", "native_id": "root"},
        )
        local_child = graph.add_joint("extra", parent_id=native_root, joint_id="local::extra")

        self.assertEqual(graph.joint_edit_policy(native_root), "full")
        self.assertEqual(graph.joint_edit_policy(local_child), "full")
        graph.reparent_joint(local_child, "")
        self.assertEqual(graph.joints[local_child]["parent_id"], "")

    def test_rig_topology_preserves_dag_order_and_attribute_connections(self):
        topology = normalize_rig_topology({
            "provider_id": "maya:7001",
            "nodes": [
                {
                    "native_id": "|Rig",
                    "name": "Rig",
                    "node_type": "dag.transform",
                    "source_type": "transform",
                    "source_order": 0,
                    "portable": True,
                },
                {
                    "native_id": "|Rig|Scene_ctrl",
                    "name": "Scene_ctrl",
                    "node_type": "dag.transform",
                    "source_type": "transform",
                    "dag_parent_native_id": "|Rig",
                    "source_order": 3,
                    "portable": True,
                },
                {
                    "native_id": "multiplyDivide1",
                    "name": "multiplyDivide1",
                    "node_type": "math.multiply_divide_power",
                    "source_type": "multiplyDivide",
                    "portable": True,
                },
            ],
            "connections": [{
                "source_node": "|Rig|Scene_ctrl",
                "source_attribute": "globalScale",
                "target_node": "multiplyDivide1",
                "target_attribute": "input1X",
            }],
        })
        self.assertEqual(topology["contract_errors"], [])

        graph = EditableRigGraph()
        graph.merge_rig_topology(topology, provider_id="maya:7001")
        scene_id = "maya:7001::|Rig|Scene_ctrl"
        self.assertEqual(graph.nodes[scene_id]["source_order"], 3)
        self.assertEqual(graph.nodes[scene_id]["dag_parent_id"], "maya:7001::|Rig")
        connection = next(iter(graph.connections.values()))
        self.assertEqual(connection["source_node"], scene_id)
        self.assertEqual(connection["target_attribute"], "input1X")

        restored = EditableRigGraph.from_dict(graph.to_dict())
        self.assertIn(scene_id, restored.nodes)
        self.assertEqual(len(restored.connections), 1)

        graph.merge_rig_topology({
            "provider_id": "maya:7001",
            "nodes": [{
                "native_id": "|Rig",
                "name": "Rig",
                "node_type": "dag.transform",
                "source_type": "transform",
            }],
            "connections": [],
        })
        self.assertNotIn(scene_id, graph.nodes)
        self.assertEqual(graph.connections, {})

    def test_native_rig_nodes_are_authorable_and_prevent_dag_cycles(self):
        graph = EditableRigGraph()
        root = graph.add_node("Scene", "dag.transform", node_id="scene")
        child = graph.add_node("Control", "dag.transform", parent_id=root, node_id="control")
        math_node = graph.add_node("Scale Math", "math.multiply_divide_power", node_id="scale_math")
        connection = graph.connect_attributes(child, "globalScale", math_node, "input1X")

        self.assertEqual(graph.nodes[child]["evaluation_mode"], "local")
        self.assertIn(connection, graph.connections)
        graph.set_node_attribute(child, "globalScale", 2.5)
        self.assertEqual(graph.evaluate_direct_attribute_connections(), [])
        self.assertEqual(graph.nodes[math_node]["attributes"]["input1X"], 2.5)
        with self.assertRaises(ValueError):
            graph.reparent_node(root, child)

    def test_local_rig_evaluator_propagates_math_into_transform_hierarchy(self):
        graph = EditableRigGraph()
        root = graph.add_node(
            "Scene",
            "dag.transform",
            node_id="scene",
            attributes={"translate": [10, 0, 0], "globalScale": 2.0},
        )
        math_node = graph.add_node(
            "Scale Math",
            "math.multiply_divide_power",
            node_id="scale_math",
            attributes={"operation": "multiply", "input2X": 3.0},
        )
        child = graph.add_node(
            "Control",
            "dag.transform",
            parent_id=root,
            node_id="control",
            attributes={"translate": [0, 0, 0]},
        )
        graph.connect_attributes(root, "globalScale", math_node, "input1X")
        graph.connect_attributes(math_node, "outputX", child, "translateX")

        evaluated = graph.evaluate_local()

        self.assertTrue(evaluated.ok)
        self.assertEqual(evaluated.attributes[math_node]["outputX"], 6.0)
        self.assertEqual(evaluated.local_matrices[child][12:15], [6.0, 0.0, 0.0])
        self.assertEqual(evaluated.world_matrices[child][12:15], [16.0, 0.0, 0.0])

    def test_local_rig_evaluator_samples_driven_key_curve(self):
        graph = EditableRigGraph()
        driver = graph.add_node("Driver", "dag.control", node_id="driver", attributes={"curl": 0.25})
        curve = graph.add_node(
            "Driven Key",
            "animation.curve",
            node_id="driven_key",
            attributes={
                "input_domain": "unitless",
                "keys": [
                    {"frame": 0.0, "value": 0.0, "interpolation": "linear"},
                    {"frame": 1.0, "value": 90.0, "interpolation": "linear"},
                ],
            },
        )
        target = graph.add_node("Finger", "dag.joint", node_id="finger", attributes={"rotate": [0, 0, 0]})
        graph.connect_attributes(driver, "curl", curve, "input")
        graph.connect_attributes(curve, "output", target, "rotateZ")

        evaluated = graph.evaluate_local()

        self.assertTrue(evaluated.ok)
        self.assertEqual(evaluated.attributes[curve]["output"], 22.5)
        self.assertEqual(evaluated.attributes[target]["rotateZ"], 22.5)

    def test_local_point_constraint_blends_source_translation(self):
        graph = EditableRigGraph()
        first = graph.add_node("A", "dag.transform", node_id="a", attributes={"translate": [0, 0, 0]})
        second = graph.add_node("B", "dag.transform", node_id="b", attributes={"translate": [10, 0, 0]})
        target = graph.add_node("Driven", "dag.transform", node_id="driven", attributes={"translate": [2, 5, 0]})
        graph.add_constraint("point", [first, second], target, settings={"weights": [1, 1]})

        evaluated = graph.evaluate_local()

        self.assertTrue(evaluated.ok)
        self.assertEqual(evaluated.world_matrices[target][12:15], [5.0, 0.0, 0.0])

    def test_local_evaluator_reports_unimplemented_solver_without_approximation(self):
        graph = EditableRigGraph()
        solver = graph.add_node("Leg IK", "solver.ik_rotate_plane", node_id="leg_ik")

        capabilities = rig_runtime_capabilities(graph)
        evaluated = graph.evaluate_local()

        self.assertTrue(capabilities["requires_source_or_baked_evaluation"])
        self.assertEqual(capabilities["unsupported_local_node_types"], ["solver.ik_rotate_plane"])
        self.assertIn(solver, evaluated.unsupported_local_node_ids)
        self.assertFalse(evaluated.ok)

    def test_source_proxy_nodes_explicitly_require_source_evaluation(self):
        graph = EditableRigGraph()
        graph.add_node(
            "Maya Control",
            "dag.transform",
            node_id="maya:7001::|control",
            source_ref={"provider_id": "maya:7001", "native_id": "|control"},
        )

        capabilities = rig_runtime_capabilities(graph)
        evaluated = graph.evaluate_local()

        self.assertEqual(capabilities["source_proxy_node_count"], 1)
        self.assertTrue(capabilities["requires_source_or_baked_evaluation"])
        self.assertEqual(evaluated.source_proxy_node_ids, ["maya:7001::|control"])

    def test_parent_orient_and_scale_constraints_preserve_matrix_channels(self):
        graph = EditableRigGraph()
        source = graph.add_node(
            "Source",
            "dag.transform",
            node_id="source",
            attributes={"translate": [4, 5, 6], "rotate": [0, 0, 90], "scale": [2, 3, 4]},
        )
        parent_target = graph.add_node("Parent Driven", "dag.transform", node_id="parent_target")
        orient_target = graph.add_node(
            "Orient Driven",
            "dag.transform",
            node_id="orient_target",
            attributes={"translate": [1, 2, 3], "scale": [5, 6, 7]},
        )
        scale_target = graph.add_node(
            "Scale Driven",
            "dag.transform",
            node_id="scale_target",
            attributes={"translate": [7, 8, 9], "rotate": [0, 45, 0]},
        )
        graph.add_constraint("parent", [source], parent_target)
        graph.add_constraint("orient", [source], orient_target)
        graph.add_constraint("scale", [source], scale_target)

        evaluated = graph.evaluate_local()

        self.assertTrue(evaluated.ok)
        self.assertEqual(evaluated.world_matrices[parent_target][12:15], [4.0, 5.0, 6.0])
        self.assertEqual(evaluated.world_matrices[orient_target][12:15], [1.0, 2.0, 3.0])
        self.assertEqual(evaluated.world_matrices[scale_target][12:15], [7.0, 8.0, 9.0])
        parent_linear = [evaluated.world_matrices[parent_target][index] for index in (0, 1, 4, 5)]
        self.assertAlmostEqual(parent_linear[0], 0.0, places=6)
        self.assertAlmostEqual(parent_linear[1], 2.0, places=6)
        self.assertAlmostEqual(parent_linear[2], -3.0, places=6)
        self.assertAlmostEqual(parent_linear[3], 0.0, places=6)

    def test_native_rotate_plane_ik_reaches_target_and_preserves_bone_lengths(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        offset = identity[:]
        offset[12] = 5.0
        graph = EditableRigGraph()
        start = graph.add_joint("Upper", joint_id="upper", local_matrix=identity)
        mid = graph.add_joint("Lower", joint_id="lower", parent_id=start, local_matrix=offset)
        end = graph.add_joint("Ankle", joint_id="ankle", parent_id=mid, local_matrix=offset)
        target = graph.add_node(
            "IK Target", "dag.transform", node_id="ik_target", attributes={"translate": [6, 6, 0]}
        )
        pole = graph.add_node(
            "Pole", "dag.transform", node_id="pole", attributes={"translate": [0, 0, 10]}
        )
        solver = graph.add_ik_solver(start, mid, end, target, pole_node_id=pole, solver_id="leg_ik")

        evaluated = graph.evaluate_local()

        self.assertTrue(evaluated.ok, evaluated.errors)
        self.assertIn(solver, evaluated.evaluated_node_ids)
        positions = {
            node_id: evaluated.world_matrices[node_id][12:15]
            for node_id in (start, mid, end)
        }
        self.assertAlmostEqual(math.dist(positions[start], positions[mid]), 5.0, places=5)
        self.assertAlmostEqual(math.dist(positions[mid], positions[end]), 5.0, places=5)
        self.assertAlmostEqual(math.dist(positions[end], [6, 6, 0]), 0.0, places=5)
        self.assertGreater(positions[mid][2], 0.0)
        capabilities = rig_runtime_capabilities(graph)
        self.assertFalse(capabilities["requires_source_or_baked_evaluation"])

    def test_native_motion_path_uses_arc_length_and_orients_the_target(self):
        graph = EditableRigGraph()
        target = graph.add_node("Camera Dolly", "dag.transform", node_id="dolly")
        solver = graph.add_motion_path(
            target,
            [[0, 0, 0], [10, 0, 0], [10, 30, 0]],
            parameter=0.5,
            solver_id="dolly_path",
        )

        evaluated = graph.evaluate_local()

        self.assertTrue(evaluated.ok, evaluated.errors)
        self.assertIn(solver, evaluated.evaluated_node_ids)
        self.assertEqual(evaluated.world_matrices[target][12:15], [10.0, 10.0, 0.0])
        self.assertFalse(rig_runtime_capabilities(graph)["requires_source_or_baked_evaluation"])

    def test_native_ribbon_attachment_samples_uv_surface(self):
        graph = EditableRigGraph()
        target = graph.add_node("Ribbon Joint", "dag.transform", node_id="ribbon_joint")
        graph.add_ribbon_attachment(
            target,
            [
                [[0, 0, 0], [10, 0, 0]],
                [[0, 10, 5], [10, 10, 5]],
            ],
            u=0.25,
            v=0.5,
            solver_id="spine_ribbon",
        )

        evaluated = graph.evaluate_local()

        self.assertTrue(evaluated.ok, evaluated.errors)
        self.assertEqual(evaluated.world_matrices[target][12:15], [2.5, 5.0, 2.5])

    def test_deformer_stack_preserves_order_and_reports_source_evaluation(self):
        graph = EditableRigGraph()
        skin = graph.add_deformer("body", "linear_blend_skinning", deformer_id="skin")
        lattice = graph.add_deformer("body", "lattice", deformer_id="lattice")

        restored = EditableRigGraph.from_dict(graph.to_dict())
        capabilities = rig_runtime_capabilities(restored)

        self.assertEqual(restored.deformers[skin]["order"], 0)
        self.assertEqual(restored.deformers[lattice]["order"], 1)
        self.assertEqual(capabilities["unsupported_local_deformer_types"], ["lattice"])
        self.assertTrue(capabilities["requires_source_or_baked_evaluation"])

    def test_matrix_node_accepts_one_flat_matrix_value(self):
        matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 7, 8, 9, 1]
        graph = EditableRigGraph()
        node = graph.add_node(
            "Matrix",
            "matrix.multiply",
            node_id="matrix",
            attributes={"matrixIn": matrix},
        )

        evaluated = graph.evaluate_local()

        self.assertTrue(evaluated.ok, evaluated.errors)
        self.assertEqual(evaluated.attributes[node]["output"], matrix)

    def test_dependency_cycles_are_reported_without_invalidating_source_rigs(self):
        packet = normalize_rig_topology({
            "provider_id": "maya:7001",
            "nodes": [
                {"native_id": "a", "node_type": "math.sum_subtract_average"},
                {"native_id": "b", "node_type": "math.multiply_divide_power"},
            ],
            "connections": [
                {"source_node": "a", "source_attribute": "output", "target_node": "b", "target_attribute": "input"},
                {"source_node": "b", "source_attribute": "output", "target_node": "a", "target_attribute": "input"},
            ],
        })
        order, cyclic = dependency_evaluation_order(packet)
        self.assertEqual(order, [])
        self.assertEqual(set(cyclic), {"a", "b"})
        self.assertEqual(packet["contract_errors"], [])


if __name__ == "__main__":
    unittest.main()
