import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from tech_connector.packaging.stage_package import copy_tree_entry, matches_any, stage_package
from tech_connector.packaging.smoke_test_package import smoke_import


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PACKAGE_ROOT.parent


def test_core_includes_current_application_packages_and_legacy_alias() -> None:
    manifest = json.loads(
        (PACKAGE_ROOT / "packaging" / "package_tiers.json").read_text(encoding="utf-8")
    )
    assert manifest["aliases"]["reasoning-runtime"] == "core"
    assert manifest["aliases"]["full-tools"] == "combined"
    includes = manifest["tiers"]["core"]["include"]
    assert "tech_connector/game_engine" in includes
    assert "tech_connector/installers" in includes
    assert "tech_connector/project_analysis" in includes


def test_official_tools_is_one_separate_composable_bundle() -> None:
    manifest = json.loads(
        (PACKAGE_ROOT / "packaging" / "package_tiers.json").read_text(encoding="utf-8")
    )
    tier = manifest["tiers"]["official-tools"]
    includes = set(tier["include"])

    assert tier["required_capability"] == "official_tools_bundle"
    assert "official_tools_bundle.json" in includes
    assert "maya_tools" in includes
    assert "blender_tools" in includes
    assert "unreal_tools" in includes
    assert "tech_connector" not in includes
    assert not any(name.startswith("toolpack.") for name in manifest["tiers"])


def test_windows_release_requires_current_python_and_bundles_native_runtime() -> None:
    script = (
        PACKAGE_ROOT / "packaging" / "windows" / "build_windows_package.ps1"
    ).read_text(encoding="utf-8-sig")
    assert '[string]$Python = "auto"' in script
    assert "Resolve-ReleasePython $Python" in script
    assert "Assert-ReleasePython $pythonInfo" in script
    assert "Build-NativeGraphRuntime" in script
    assert '"--add-binary", "$nativeGraphDll;tech_connector\\game_engine\\native\\bin"' in script
    assert "Write-Sha256Sidecar $zipPath" in script
    assert "Write-Sha256Sidecar $installer" in script


def test_release_dependency_floors_support_python_314() -> None:
    build = (PACKAGE_ROOT / "packaging" / "requirements-build.txt").read_text(encoding="utf-8")
    runtime = (PACKAGE_ROOT / "packaging" / "requirements-runtime.txt").read_text(encoding="utf-8")
    assert "pyinstaller>=6.21,<7" in build.lower()
    assert "PySide6>=6.10.1,<6.12" in runtime


def test_release_tiers_exclude_generated_runtime_state() -> None:
    manifest = json.loads(
        (PACKAGE_ROOT / "packaging" / "package_tiers.json").read_text(encoding="utf-8")
    )
    generated_paths = (
        "tech_connector/.ai_studio/unreal_request_log.jsonl",
        "plugins/AIStudioBridge/.build/output/HostProject/Intermediate/plugin.obj",
        "tech_connector/game_engine/native/.tech_connector/build.ninja",
        "tech_connector/knowledge/index/legacy/knowledge_index.sqlite",
        "tech_connector/data/capability_registry/entries_0001.json",
        "tech_connector/project_analysis/project_analysis.db",
        "tech_connector/project_analysis/project_analysis.db-wal",
        "tech_connector/services/__pycache__/service.cpython-314.pyc",
        "tech_connector/benchmarks/results/repeat/report.json",
        "tech_connector/benchmarks/pytest_demo/host_port.txt",
    )
    for tier in manifest["tiers"].values():
        excludes = tier["exclude"]
        assert all(matches_any(path, excludes) for path in generated_paths)


def test_staging_skips_generated_state_but_keeps_source() -> None:
    excludes = [
        "**/.ai_studio",
        "**/.tech_connector",
        "**/*.pyc",
        "**/pytest_*",
        "tech_connector/project_analysis/*.db",
    ]
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "source"
        output = Path(temp_dir) / "output"
        source = root / "tech_connector"
        (source / ".ai_studio").mkdir(parents=True)
        (source / "game_engine" / "native" / ".tech_connector").mkdir(parents=True)
        (source / "project_analysis").mkdir(parents=True)
        (source / "services" / "__pycache__").mkdir(parents=True)
        (source / "benchmarks" / "pytest_demo").mkdir(parents=True)
        (source / "services" / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
        (source / ".ai_studio" / "request.log").write_text("generated", encoding="utf-8")
        (source / "game_engine" / "native" / ".tech_connector" / "build.ninja").write_text(
            "generated", encoding="utf-8"
        )
        (source / "project_analysis" / "project_analysis.db").write_bytes(b"generated")
        (source / "services" / "__pycache__" / "runtime.pyc").write_bytes(b"generated")
        (source / "benchmarks" / "pytest_demo" / "host_port.txt").write_text("7001", encoding="utf-8")

        copy_tree_entry(root, "tech_connector", output, excludes)

        assert (output / "tech_connector" / "services" / "runtime.py").is_file()
        assert not (output / "tech_connector" / ".ai_studio").exists()
        assert not (
            output / "tech_connector" / "game_engine" / "native" / ".tech_connector"
        ).exists()
        assert not (
            output / "tech_connector" / "project_analysis" / "project_analysis.db"
        ).exists()
        assert not (output / "tech_connector" / "services" / "__pycache__").exists()
        assert not (output / "tech_connector" / "benchmarks" / "pytest_demo").exists()


def test_staging_prunes_nested_benchmark_output(tmp_path) -> None:
    """A package staged below its source must not copy itself recursively."""

    root = tmp_path / "source"
    source = root / "tech_connector"
    (source / "services").mkdir(parents=True)
    (source / "services" / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    generated = source / "benchmarks" / "results"
    generated.mkdir(parents=True)
    (generated / "report.json").write_text("{}", encoding="utf-8")
    output = generated / "stage"

    copy_tree_entry(root, "tech_connector", output, ["tech_connector/benchmarks/results"])

    assert (output / "tech_connector" / "services" / "runtime.py").is_file()
    assert not (output / "tech_connector" / "benchmarks").exists()


def test_full_tools_stage_uses_canonical_cross_dcc_rig_implementations(tmp_path) -> None:
    staged = stage_package("full-tools", tmp_path)
    rig_files = (
        Path("blender_tools/Rigging/__init__.py"),
        Path("blender_tools/Rigging/rigging_host_adapter.py"),
        Path("houdini_tools/Rigging/__init__.py"),
        Path("houdini_tools/Rigging/rigging_host_adapter.py"),
        Path("max_tools/Rigging/rigging_host_adapter.py"),
        Path("maya_tools/Rigging/create_rig.py"),
        Path("maya_tools/Rigging/create_rig_core.py"),
        Path("maya_tools/Rigging/rigging_host_adapter.py"),
        Path("maya_tools/Rigging/mocap/hik_ui.py"),
        Path("maya_tools/Rigging/unreal_skeletal_export.py"),
        Path("unreal_tools/skeletal_mesh_import.py"),
    )

    for relative in rig_files:
        packaged = staged / relative
        canonical = TOOLS_ROOT / relative
        assert packaged.is_file()
        assert packaged.read_bytes() == canonical.read_bytes()


def test_official_tools_stages_without_core_and_declares_entitlement(tmp_path) -> None:
    staged = stage_package("official-tools", tmp_path)
    inventory = json.loads((staged / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))

    assert inventory["tier"] == "official-tools"
    assert inventory["product_id"] == "official_tools_bundle"
    assert inventory["required_capability"] == "official_tools_bundle"
    assert (staged / "official_tools_bundle.json").is_file()
    assert (staged / "maya_tools").is_dir()
    assert not (staged / "tech_connector/app").exists()
    smoke_import(staged)


def test_reasoning_runtime_uses_the_current_portable_rig_facade(tmp_path) -> None:
    staged = stage_package("reasoning-runtime", tmp_path)
    relative = Path("tech_connector/game_engine/integration/tc_hik_ui_host.py")

    assert not (staged / "maya_tools").exists()
    assert not (staged / "blender_tools").exists()
    assert (staged / relative).read_bytes() == (TOOLS_ROOT / relative).read_bytes()


def test_blender_rig_backend_has_native_ik_and_lip_main_controls() -> None:
    source = (TOOLS_ROOT / "blender_tools" / "Rigging" / "rigging_host_adapter.py").read_text(encoding="utf-8")
    compile(source, "blender_tools/Rigging/rigging_host_adapter.py", "exec")
    assert 'pose_bone.constraints.new(type=constraint_type)' in source
    assert 'ik = _constraint(mid_pose, "IK"' in source
    assert 'ik.chain_count = 2' in source
    assert 'ik.target = ik_control' in source
    assert 'f"{module}_{bone.name}_fk_ctrl"' in source
    assert 'constraint.influence = 1.0 - blend' in source
    assert 'end_rotation = _constraint(end_pose, "COPY_ROTATION"' in source
    assert '"c_upper_lip_main_ctrl"' in source
    assert '"c_lower_lip_main_ctrl"' in source
    assert '"lip_main_ctrl"' in source
    assert 'def _op_rig_create_ribbon(' in source
    assert '"SPLINE_IK"' in source
    assert 'hook.vertex_indices_set' in source
    assert 'constraint.forward_axis = "FORWARD_Y"' in source
    assert 'constraint.up_axis = "UP_Z"' in source


def test_blender_and_max_share_current_character_build_behavior() -> None:
    blender = (TOOLS_ROOT / "blender_tools" / "Rigging" / "rigging_host_adapter.py").read_text(
        encoding="utf-8"
    )
    max_source = (TOOLS_ROOT / "max_tools" / "Rigging" / "rigging_host_adapter.py").read_text(
        encoding="utf-8"
    )
    tc_source = (
        TOOLS_ROOT / "tech_connector" / "game_engine" / "integration" / "tc_rigging_host_adapter.py"
    ).read_text(encoding="utf-8")

    for source in (blender, max_source):
        assert "RIG_BEHAVIOR_REVISION = 7" in source
    assert "RIG_BEHAVIOR_REVISION = 7" in tc_source
    for source in (blender, max_source, tc_source):
        assert 'if bool(payload.get("preview", False)):' in source
        assert 'if bool(options.get("set_t_pose", True)):' in source
        assert '"t_pose": t_pose_result' in source
        assert '"foot_alignment": "rotation_only"' in source
        assert '"controls_world_oriented": True' in source
        assert '"bind_pose_preserved": True' in source
        assert '"world_up_object"' in source
        assert "twist_driver_contract" in source
        assert '"constraint_settings": settings' in source
        assert '"surface_face"' in source
        assert '"y_outward_view_up_alignment"' in source
        assert "under_?eye" in source
        assert ".+cheek.*" in source
        assert "removed_auto_joint_guides" in source
        assert "brow_shape_rotation_y" in source
        assert "spine_sub_shape_rotation_x" in source
        assert "pole_side" in source
        assert "dorsal_direction" in source
    assert 'payload.get("blend", 0.0)' in blender
    assert 'payload.get("blend", 0.0)' in max_source
    assert 'payload.get("blend", 1.0)' in tc_source

    assert "def _mapped_mesh_fit_positions(" in blender
    assert "def _mapped_mesh_fit_positions(" in max_source
    assert '"fingers": FINGER_SLOTS' in blender
    assert '"fingers": FINGER_SLOTS' in max_source
    assert "thumb_rig_contract" in blender
    assert "thumb_rig_contract" in max_source
    assert "thumb_rig_contract" in tc_source
    assert 'contract["fk_controls"]' in blender
    assert 'contract["fk_controls"]' in max_source
    assert 'contract["ik_control"]' in blender
    assert 'contract["ik_control"]' in max_source
    assert 'contract["pole_control"]' in blender
    assert 'contract["pole_control"]' in max_source
    assert 'contract["fk_controls"]' in tc_source
    assert 'contract["ik_control"]' in tc_source
    assert 'contract["pole_control"]' in tc_source
    assert "add_ik_chain_solver" in tc_source
    assert "ik.chain_count = 3" in blender
    assert '"IKHISolver"' in max_source
    assert 'options.get("ik_fk_blend", 1.0)' in blender
    assert 'options.get("ik_fk_blend", 1.0)' in max_source
    assert 'options.get("ik_fk_blend", 1.0)' in tc_source
    assert 'attributes.get("bounds") or attributes.get("bbox")' in tc_source

    assert "Matrix.Translation(target_matrix.translation)" in blender
    assert "for joint_id in dict.fromkeys(definition.slots.values()):" in blender
    assert 'world_oriented=True' in blender
    assert 'rt.Matrix3(' in max_source
    assert '_set_if_property(controller, "enabled", blend > 0.0)' in max_source

    portable_loader = (
        TOOLS_ROOT / "tech_connector" / "services" / "dcc" / "rigging_workspace_service.py"
    ).read_text(encoding="utf-8")
    assert "_tech_connector_portable_rigging_workspace_service" in portable_loader
    assert "_spec_from_file_location" in portable_loader


def test_cross_dcc_authoring_calls_force_fresh_host_modules() -> None:
    from tech_connector.game_engine.integration.rigging_host_adapter_service import (
        PythonHostRiggingAdapter,
    )

    scripts = []

    def executor(script: str, _timeout: float):
        scripts.append(script)
        payload = {
            "ok": True,
            "capability": "rig.place_joints",
            "host": "test",
            "message": "ok",
        }
        return True, "__TC_RIGGING_RESULT__" + json.dumps(payload)

    adapter = PythonHostRiggingAdapter(
        "test", executor, "test.host_adapter", {"rig.place_joints": "translated"}
    )
    result = adapter.execute("rig.place_joints", {})

    assert result.ok
    assert "_tc_force_reload = True" in scripts[-1]
    assert "_tc_reload_dependencies()" in scripts[-1]


def test_cross_dcc_twist_adapters_consume_the_portable_constraint_profile() -> None:
    adapter_paths = (
        "maya_tools/Rigging/rigging_host_adapter.py",
        "blender_tools/Rigging/rigging_host_adapter.py",
        "max_tools/Rigging/rigging_host_adapter.py",
        "houdini_tools/Rigging/rigging_host_adapter.py",
        "tech_connector/game_engine/integration/tc_rigging_host_adapter.py",
    )
    for relative in adapter_paths:
        source = (TOOLS_ROOT / relative).read_text(encoding="utf-8")
        compile(source, relative, "exec")
        assert "twist_driver_contract" in source
        assert "constraint_settings" in source

    maya_core = (TOOLS_ROOT / "maya_tools/Rigging/create_rig_core.py").read_text(encoding="utf-8")
    assert "settings = twist_driver_contract(" in maya_core
    assert 'worldUpVector=tuple(settings["world_up_vector"])' in maya_core
    assert 'if settings["aim_offset"] is not None:' in maya_core


def test_portable_thumb_rig_contract_matches_maya_control_semantics() -> None:
    from tech_connector.services.dcc.rigging_workspace_service import (
        CharacterDefinition,
        thumb_rig_contract,
    )

    definition = CharacterDefinition("ThumbParity", {
        **{
            f"LeftHandThumb{index}": f"l_thumb_{index:02d}"
            for index in range(1, 5)
        },
        **{
            f"RightHandThumb{index}": f"r_thumb_{index:02d}"
            for index in range(1, 5)
        },
    })
    contracts = thumb_rig_contract(definition)

    assert [contract["side"] for contract in contracts] == ["left", "right"]
    assert contracts[0]["fk_controls"] == [
        "l_thumb_01_ctrl", "l_thumb_02_ctrl", "l_thumb_03_ctrl",
    ]
    assert contracts[0]["ik_control"] == "l_thumb_ikh_ctrl"
    assert contracts[0]["pole_control"] == "l_thumb_02_ik_ctrl"
    assert contracts[1]["ik_control"] == "r_thumb_ikh_ctrl"
    assert contracts[1]["pole_control"] == "r_thumb_02_ik_ctrl"
    assert all(contract["solver"] == "rotate_plane" for contract in contracts)
    assert all(contract["pole_side"] == "dorsal" for contract in contracts)
    assert all(contract["revision"] == 2 for contract in contracts)
    assert all(contract["controls_world_oriented"] for contract in contracts)
    assert all(not contract["channels_locked"] for contract in contracts)


def test_tc_native_thumb_build_preserves_bind_pose_and_solves_full_chain() -> None:
    from tech_connector.game_engine.authoring.rigging_workspace_service import CharacterDefinition
    from tech_connector.game_engine.integration.tc_rigging_host_adapter import TCRiggingHostAdapter
    from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX

    def translated(x: float, y: float, z: float) -> list[float]:
        matrix = list(IDENTITY_MATRIX)
        matrix[12:15] = [x, y, z]
        return matrix

    graph = EditableRigGraph()
    graph.add_joint("l_hand", local_matrix=translated(0.0, 0.0, 0.0), joint_id="l_hand")
    graph.add_joint("l_thumb_01", parent_id="l_hand", local_matrix=translated(0.0, 0.0, 0.0), joint_id="l_thumb_01")
    graph.add_joint("l_thumb_02", parent_id="l_thumb_01", local_matrix=translated(1.0, 0.2, 0.0), joint_id="l_thumb_02")
    graph.add_joint("l_thumb_03", parent_id="l_thumb_02", local_matrix=translated(1.0, 0.1, 0.0), joint_id="l_thumb_03")
    graph.add_joint("l_thumb_04", parent_id="l_thumb_03", local_matrix=translated(1.0, 0.0, 0.0), joint_id="l_thumb_04")
    definition = CharacterDefinition("Thumb", {
        "LeftHand": "l_hand",
        **{f"LeftHandThumb{index}": f"l_thumb_0{index}" for index in range(1, 5)},
    })
    adapter = TCRiggingHostAdapter(graph)
    before = {
        joint: adapter._joint_world_matrix(joint)
        for joint in definition.slots.values()
        if "thumb" in joint
    }

    built = adapter.execute("rig.build_module", {
        "module": "fingers", "definition": definition.to_dict(), "options": {"blend": 1.0},
    })
    assert built.ok, built.message
    evaluated = graph.evaluate_local()
    assert not evaluated.errors
    assert max(
        abs(expected - actual)
        for joint, matrix in before.items()
        for expected, actual in zip(matrix, evaluated.world_matrices[joint])
    ) == 0.0
    for control in ("l_thumb_01_ctrl", "l_thumb_02_ctrl", "l_thumb_03_ctrl", "l_thumb_ikh_ctrl", "l_thumb_02_ik_ctrl"):
        assert control in graph.nodes
        assert graph.nodes[control]["attributes"]["channels_locked"] is False
    assert graph.nodes["l_thumb_ikh_ctrl"]["attributes"]["world_oriented"] is True
    assert graph.nodes["l_thumb_02_ik_ctrl"]["attributes"]["world_oriented"] is True
    assert graph.constraints["left_thumb_ik_solver"]["settings"]["joint_ids"] == [
        "l_thumb_01", "l_thumb_02", "l_thumb_03", "l_thumb_04",
    ]
    assert graph.constraints["l_thumb_02_ik_ctrl_space_constraint"]["settings"]["space_names"] == [
        "IK", "Hand", "Composite",
    ]

    target = graph.nodes["l_thumb_ikh_ctrl"]["attributes"]["matrix"]
    target[12:15] = [2.7, 0.8, 0.4]
    solved = graph.evaluate_local()
    assert not solved.errors
    assert solved.world_matrices["l_thumb_04"][12:15] == pytest.approx(target[12:15], abs=1.0e-6)


def test_maya_joint_placer_keeps_anatomical_limb_and_digit_contracts() -> None:
    source = (TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placer.py").read_text(
        encoding="utf-8"
    )

    assert "STUDIO_THIGH_INSET_HEIGHT_RATIO = 0.0" in source
    assert "def solve_reference_joint_roll_vectors(" in source
    assert "_rotate_vector_between_directions(" in source
    assert 'reference_name = "l_" + name[2:] if mirrored_right else name' in source
    assert 'source_y = (source_y[0], -source_y[1], -source_y[2])' in source
    assert "medoid, _medoid_weight = max(" in source
    assert "if float(sample * medoid) >= 0.75" in source
    assert '"reference_roll_transferred": bool(reference_roll)' in source
    assert '_set_string_attr(joint, BEND_AXIS_ATTR, "z")' in source
    arm_orient = source.split("def orient_studio_arm_chains(", 1)[1].split(
        "def orient_studio_leg_reference_frames(", 1
    )[0]
    assert 'cmds.setAttr(joint + ".translateY", 0.0)' in arm_orient
    assert 'cmds.setAttr(joint + ".translateZ", 0.0)' in arm_orient
    assert "Hand retains the approved production roll." in source
    assert 'not name.endswith(\n                    ("_clavicle", "_upperarm", "_lowerarm")' in source
    studio_fit = source.split("def fit_studio_template_skeleton(", 1)[1].split(
        "def preview_biped_joint_placement(", 1
    )[0]
    assert "move_all_studio_joint_orientation_to_rotate(" in studio_fit
    assert 'volume_report["orientation_channels"]' in studio_fit
    assert "three-axis flip such as (-150, 78, 153)" in source
    assert "compact_world_matrix" in source
    assert "def fit_studio_arm_hinge_plane_to_mesh(" in source
    assert 'volume_report["arm_mesh_hinge_plane"]' in studio_fit
    assert "def orient_studio_brow_joints(" in source
    brow_orient = source.split("def orient_studio_brow_joints(", 1)[1].split(
        "def zero_studio_eyelid_tip_rotates(", 1
    )[0]
    assert "positions[index + 1] - origin" in brow_orient
    assert '"x_next_brow_alignment"' in brow_orient
    assert '"y_surface_tangent_alignment"' in brow_orient
    assert "_move_joint_orientation_to_rotate(joint)" in brow_orient
    assert 'volume_report["brow_orientation"] = orient_studio_brow_joints(' in studio_fit
    assert "def orient_studio_surface_face_joints(" in source
    assert 'volume_report["surface_face_orientation"]' in studio_fit
    assert '"x_surface_tangent_alignment"' in source
    assert '"y_outward_view_up_alignment"' in source
    assert 'volume_report["eyelid_tip_zero_rotates"]' in studio_fit
    assert "def delete_auto_joint_guides(" in source
    assert 'detail_placement_report["removed_auto_joint_guides"]' in source
    assert '("nose_base", "X")' in source
    assert '("nose_root", "nose_upper", "nose_tip", "nose_base")' in source
    assert "wrist_y_interval" in source
    assert "STUDIO_WRIST_DORSAL_FRACTION = 0.60" in source
    assert '"wrist_section_fraction_from_bottom": STUDIO_WRIST_DORSAL_FRACTION' in source
    assert '"elbow_section_fraction_from_inner": 2.0 / 3.0' in source
    assert "mesh_bend_sign" in source
    assert "mesh_bend_sign = -1.0 if depth_centered[1][2] >= chord_z else 1.0" in source
    assert "validate_studio_final_joint_placement(" in studio_fit
    assert '"method": "preserve_topology_reference_landmarks"' in source


def test_tc_joint_placer_applies_brow_eyelid_and_nose_channel_rules() -> None:
    from tech_connector.game_engine.authoring.rigging_workspace_service import CharacterDefinition
    from tech_connector.game_engine.integration.tc_rigging_host_adapter import TCRiggingHostAdapter
    from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX

    def translated(x: float, y: float, z: float) -> list[float]:
        matrix = list(IDENTITY_MATRIX)
        matrix[12:15] = [x, y, z]
        return matrix

    graph = EditableRigGraph()
    guide_group = graph.add_node(
        "auto_joint_guides_grp", "dag.group", node_id="auto_joint_guides_grp"
    )
    graph.add_node(
        "temporary_face_guide",
        "dag.guide",
        parent_id=guide_group,
        node_id="temporary_face_guide",
    )
    graph.add_joint("head", local_matrix=translated(0.0, 10.0, 0.0), joint_id="head")
    slots = {}
    brow_points = ((-1.5, 1.0, 2.0), (-1.0, 1.3, 2.1), (-0.4, 1.45, 2.15), (0.2, 1.4, 2.15), (0.8, 1.2, 2.05), (1.2, 0.9, 1.9))
    for index, point in enumerate(brow_points, 1):
        name = "l_brow_end" if index == 6 else f"l_brow{index}"
        graph.add_joint(name, parent_id="head", local_matrix=translated(*point), joint_id=name)
        slots[name] = name
    slots["LeftBrow"] = "l_brow1"
    rotated = translated(0.5, 0.2, 1.8)
    rotated[0:3], rotated[4:7] = [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]
    graph.add_joint("l_upper_eyelidTip", parent_id="head", local_matrix=rotated, joint_id="l_upper_eyelidTip")
    graph.add_joint("nose_base", parent_id="head", local_matrix=translated(2.0, 0.0, 2.0), joint_id="nose_base")
    under_points = ((-1.2, 0.1, 1.8), (-0.6, -0.1, 2.0), (0.1, -0.2, 2.1))
    for index, point in enumerate(under_points, 1):
        name = f"l_undereye_{index}"
        graph.add_joint(name, parent_id="head", local_matrix=translated(*point), joint_id=name)
        slots[name] = name
    graph.add_joint(
        "l_upper_cheek",
        parent_id="head",
        local_matrix=translated(-1.5, -1.2, 1.5),
        joint_id="l_upper_cheek",
    )
    slots.update({"lid": "l_upper_eyelidTip", "nose": "nose_base", "cheek": "l_upper_cheek"})
    mesh = graph.add_node(
        "face_mesh", "mesh", node_id="face_mesh",
        attributes={"bounds": {"min": [-3.0, 8.0, -2.0], "max": [3.0, 14.0, 3.0]}},
    )
    adapter = TCRiggingHostAdapter(graph)
    definition = CharacterDefinition("Face", slots)
    result = adapter.execute("rig.place_joints", {
        "definition": definition.to_dict(), "mesh": mesh,
        "positions": {key: adapter._joint_world_matrix(value)[12:15] for key, value in slots.items()},
    })
    assert result.ok, result.message
    evaluated = graph.evaluate_local()
    assert not evaluated.errors
    first = evaluated.world_matrices["l_brow1"]
    first_position = first[12:15]
    next_position = evaluated.world_matrices["l_brow2"][12:15]
    direction = [next_position[index] - first_position[index] for index in range(3)]
    length = sum(value * value for value in direction) ** 0.5
    direction = [value / length for value in direction]
    assert sum(first[index] * direction[index] for index in range(3)) == pytest.approx(1.0, abs=1.0e-6)
    assert graph.nodes["l_upper_eyelidTip"]["attributes"]["rotate"] == [0.0, 0.0, 0.0]
    assert graph.joints["nose_base"]["local_matrix"][12] == 0.0
    mesh_center = [0.0, 11.0, 0.5]
    for joint_id in ("l_undereye_1", "l_undereye_2", "l_undereye_3", "l_upper_cheek"):
        matrix = evaluated.world_matrices[joint_id]
        normal = [matrix[12 + index] - mesh_center[index] for index in range(3)]
        normal_length = sum(value * value for value in normal) ** 0.5
        normal = [value / normal_length for value in normal]
        assert abs(sum(matrix[index] * normal[index] for index in range(3))) < 1.0e-6
        projected_up = [0.0, 1.0, 0.0]
        up_dot_normal = sum(projected_up[index] * normal[index] for index in range(3))
        projected_up = [
            projected_up[index] - normal[index] * up_dot_normal
            for index in range(3)
        ]
        up_length = sum(value * value for value in projected_up) ** 0.5
        projected_up = [value / up_length for value in projected_up]
        assert sum(matrix[4 + index] * projected_up[index] for index in range(3)) == pytest.approx(1.0, abs=1.0e-6)
    assert set(result.data["face_orientation"]["surface_face"]) >= {
        "l_undereye_1", "l_undereye_2", "l_undereye_3", "l_upper_cheek",
    }
    assert result.data["removed_auto_joint_guides"] == [
        "auto_joint_guides_grp", "temporary_face_guide",
    ]
    assert "auto_joint_guides_grp" not in graph.nodes
    assert "temporary_face_guide" not in graph.nodes
    brow_build = adapter.execute("rig.build_module", {
        "module": "brows", "definition": definition.to_dict(),
    })
    assert brow_build.ok, brow_build.message
    assert brow_build.data["brow_shape_rotation_y"] == 90.0
    assert graph.nodes["brows_LeftBrow_ctrl"]["attributes"]["shape_rotation_y"] == 90.0
    assert graph.nodes["brows_LeftBrow_ctrl"]["dag_parent_id"] == "l_brow_main_ctrl"
    assert graph.nodes["l_brow_main_ctrl"]["attributes"]["shape_rotation_y"] == 90.0

def test_maya_surface_rig_reacquires_path_after_grouping() -> None:
    source_path = TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig_core.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "setup_surface_rig"
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))

    class FakeCmds:
        @staticmethod
        def duplicate(*_args, **_kwargs): return ["c_upper_lip_temp"]
        @staticmethod
        def parentConstraint(*_args, **_kwargs): return ["temporaryConstraint"]
        @staticmethod
        def delete(*_args, **_kwargs): return None
        @staticmethod
        def group(*_args, **_kwargs): return "mouth_surface_grp"
        @staticmethod
        def objExists(_node): return True
        @staticmethod
        def setAttr(*_args, **_kwargs): return None

        @staticmethod
        def parent(node, destination):
            if node == "mouth_surface_grp" and destination == "Do_Not_Touch":
                return ["|Do_Not_Touch|mouth_surface_grp"]
            return [str(node)]

        @staticmethod
        def listRelatives(node, **kwargs):
            if kwargs.get("children") and node == "|Do_Not_Touch|mouth_surface_grp":
                return ["|Do_Not_Touch|mouth_surface_grp|mouth"]
            if kwargs.get("shapes") and node.endswith("|mouth"):
                return ["|Do_Not_Touch|mouth_surface_grp|mouth|mouthShape"]
            if kwargs.get("p"):
                return [str(node) + "Transform"]
            return []

    namespace = {
        "cmds": FakeCmds(),
        "create_surface_from_joints_original": lambda *_args, **_kwargs: (
            "|mouth",
            ["mouth_lip1_folJoint", "mouth_lip2_folJoint", "mouth_temp_folJoint"],
        ),
    }
    exec(compile(module, str(source_path), "exec"), namespace)

    surface, follicles, controls = namespace["setup_surface_rig"](
        ["lip1", "lip2"],
        loft_name="mouth",
        region="mouth",
        create_controls=False,
    )

    assert surface == "|Do_Not_Touch|mouth_surface_grp|mouth"
    assert follicles == ["mouth_lip1_folJoint", "mouth_lip2_folJoint"]
    assert controls == {}


def test_maya_surface_binding_uses_explicit_influences_without_reparenting() -> None:
    source_path = TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig_core.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_bind_surface_to_joints"
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))

    class FakeCmds:
        skin_args = ()

        @staticmethod
        def ls(node, **_kwargs):
            if node in {"mouth", "|Do_Not_Touch|mouth_surface_grp|mouth"}:
                return ["|Do_Not_Touch|mouth_surface_grp|mouth"]
            return [str(node)]

        @staticmethod
        def listRelatives(_node, **kwargs):
            return ["|Do_Not_Touch|mouth_surface_grp"] if kwargs.get("parent") else []

        @staticmethod
        def nodeType(_node): return "transform"

        @staticmethod
        def parent(node, destination=None, **kwargs):
            if kwargs.get("world"):
                return ["mouth"]
            assert destination == "|Do_Not_Touch|mouth_surface_grp"
            return ["|Do_Not_Touch|mouth_surface_grp|mouth"]

        @classmethod
        def skinCluster(cls, *args, **_kwargs):
            cls.skin_args = args
            return ["mouth_skinCluster"]

        @staticmethod
        def objExists(_node): return True

    namespace = {"cmds": FakeCmds}
    exec(compile(module, str(source_path), "exec"), namespace)
    skin, surface = namespace["_bind_surface_to_joints"](
        "|Do_Not_Touch|mouth_surface_grp|mouth",
        ["c_upper_lip_main", "c_lower_lip_main"],
        tsb=True,
    )

    assert skin == "mouth_skinCluster"
    assert FakeCmds.skin_args == (
        "c_upper_lip_main", "c_lower_lip_main", "|Do_Not_Touch|mouth_surface_grp|mouth")
    assert surface == "|Do_Not_Touch|mouth_surface_grp|mouth"


def test_maya_mouth_builder_requires_and_returns_the_overall_lip_control() -> None:
    create_rig = (TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig.py").read_text(encoding="utf-8")
    create_rig_core = (TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig_core.py").read_text(encoding="utf-8")
    temp_cleanup = (TOOLS_ROOT / "maya_tools" / "Rigging" / "temp_cleanup.py").read_text(encoding="utf-8")

    assert 'get("main_ctrl", "lip_main_ctrl")' in create_rig
    assert '"main_ctrl": main_ctrl' in create_rig_core
    assert 'legacy_snap_nodes = {"l_brow_main", "r_brow_main", "lip_main"}' in create_rig
    assert 'cmds.delete(brow_main_transform)' in create_rig
    assert 'control_shape="circle_z"' in create_rig.split(
        "def create_brow_main_setup(", 1
    )[1].split("def _safe_rename_hierarchy_tokens(", 1)[0]
    assert 'cmds.delete(temp_grp)' in create_rig_core
    assert "def _bind_surface_to_joints(" in create_rig_core
    assert 'elif control_shape == "circle_z":' in create_rig_core
    assert 'normal=[0, 0, 1]' in create_rig_core
    assert "def rotate_ctrl_cvs_object_x(" in create_rig_core
    assert "def rotate_ctrl_cvs_object_y(" in create_rig_core
    assert 'rotation_attr = "controlCvShapeRotations"' in create_rig_core
    assert '"tcShapeRotationSchema"' in create_rig_core
    assert "rotate_ctrl_cvs_object_x(ctrl, desired_x)" in create_rig_core
    assert "rotate_ctrl_cvs_object_y(ctrl, desired_y)" in create_rig_core
    joint_controls_body = create_rig_core.split(
        "def create_joint_controls(", 1
    )[1].split("def get_side_prefix(", 1)[0]
    assert 'ctrl = ctrl.rsplit("|", 1)[-1]' in joint_controls_body
    assert 'sdk = sdk.rsplit("|", 1)[-1]' in joint_controls_body
    assert 'pad = pad.rsplit("|", 1)[-1]' in joint_controls_body
    assert 'sub_ctrl = sub_ctrl.rsplit("|", 1)[-1]' in joint_controls_body
    rotate_cvs_body = create_rig_core.split(
        "def rotate_ctrl_cvs_object_x(", 1
    )[1].split("\ndef ", 1)[0]
    assert "objectSpace=True" in rotate_cvs_body
    assert "(y_value * cosine) - (z_value * sine)" in rotate_cvs_body
    assert "sub_ctrl_shape_rotation_x=0.0" in joint_controls_body
    assert "rotate_ctrl_cvs_object_x(" in joint_controls_body
    spine_module_body = create_rig.split("def rig_spine_module(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert spine_module_body.count(
        "sub_ctrl_shape_rotation_x=0.0"
    ) == 2
    assert "create_bi_arrow_ctrl already converts" in spine_module_body
    brow_main_body = create_rig.split(
        "def create_brow_main_setup(", 1
    )[1].split("def _safe_rename_hierarchy_tokens(", 1)[0]
    assert "rotate_ctrl_cvs_object_y(main_ctrl, 90.0)" in brow_main_body
    assert "def ensure_world_aligned_bank_sdk(" in create_rig_core
    bank_sdk_body = create_rig_core.split(
        "def ensure_world_aligned_bank_sdk(", 1
    )[1].split("\ndef ", 1)[0]
    assert "alignment_rotation = cmds.xform(" in bank_sdk_body
    assert "align_pad = cmds.parent(align_pad, alignment_parent, absolute=True)[0]" in bank_sdk_body
    assert 'cmds.createNode("transform", name=bank_sdk, parent=align_pad)' in bank_sdk_body
    assert "cmds.parent(downstream_control_pad, bank_sdk, absolute=True)" in bank_sdk_body
    rfl_sdk_body = create_rig_core.split("def setup_rfl_sdks(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert 'ensure_world_aligned_bank_sdk(rfl_joints["innerBank"])' in rfl_sdk_body
    assert 'outer_bank_sdk = sdk_from_joint(rfl_joints["outerBank"])' in rfl_sdk_body
    full_rig_body = create_rig.split("def create_full_rig(", 1)[1].split(
        "\ndef remove_full_rig(", 1
    )[0]
    assert "rig_spine_module(body_joint_map)" in full_rig_body
    assert 'rig_leg_module("l", body_joint_map)' in full_rig_body
    assert 'rig_leg_module("r", body_joint_map)' in full_rig_body
    assert "hide_post_build_face_nodes()" in full_rig_body
    assert full_rig_body.index("hide_post_build_face_nodes()") > full_rig_body.index(
        "delete_unused_scaffold_nodes()"
    )
    expected_hidden_face_nodes = {
        "l_brow5_main", "l_upper_lip3_main", "r_lower_inner_eyelid",
        "l_brow2_main", "c_upper_lip_main", "l_upper_outer_eyelid",
        "r_brow4_main", "c_lower_lip_main", "r_lower_outer_eyelid",
        "r_brow1_main", "r_upper_lip3_main", "l_lip_corner1_main",
        "l_lower_lip3_main", "r_brow3_main", "r_lip_corner1_main",
        "l_lower_eyelid", "r_upper_eyelid", "r_inner_eyelid1",
        "r_upper_outer_eyelid", "r_brow5_main", "r_lower_eyelid",
        "r_upper_inner_eyelid", "l_lower_outer_eyelid",
        "l_lower_inner_eyelid", "l_brow4_main", "l_upper_inner_eyelid",
        "r_brow2_main", "r_lower_lip3_main", "l_outer_eyelid1",
        "l_brow1_main", "l_brow3_main", "r_outer_eyelid1",
        "l_upper_eyelid", "l_inner_eyelid1",
    }
    create_rig_tree = ast.parse(create_rig)
    hidden_assignment = next(
        node for node in create_rig_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "POST_BUILD_HIDDEN_FACE_NODES"
            for target in node.targets
        )
    )
    actual_hidden_face_nodes = ast.literal_eval(hidden_assignment.value)
    assert len(actual_hidden_face_nodes) == len(expected_hidden_face_nodes) == 34
    assert set(actual_hidden_face_nodes) == expected_hidden_face_nodes
    assert 'matches = cmds.ls(base_name, "*:" + base_name, long=True)' in create_rig
    assert 'cmds.setAttr(draw_style_attr, 2)' in create_rig
    surface_rig_body = create_rig_core.split("def setup_surface_rig(", 1)[1].split(
        "def _bind_surface_to_joints(", 1
    )[0]
    assert 'control_shape = "circle_z" if region == "brow" else "circle"' in surface_rig_body
    assert 'control_shape="circle_z" if region == "brow" else "circle"' in surface_rig_body
    assert "if cmds.objExists(temp_joint):" in surface_rig_body
    driver_surface_body = create_rig_core.split(
        "def setup_surface_rig_with_drivers(", 1
    )[1].split("def constrain_controls_to_two_parents(", 1)[0]
    assert 'control_shape = "circle_z" if region == "brow" else "circle"' in driver_surface_body
    assert "*(list(influences) + [bind_surface])" in create_rig_core
    assert "skin, surface = _bind_surface_to_joints(" in create_rig_core
    assert create_rig_core.count("cmds.parent(fol_joint, fol_tr, absolute=True)") == 2
    assert "# turn remain constrained to the original bind joint." in create_rig_core
    assert "def _ensure_distance_nodes_group():" in create_rig_core
    assert 'name="distance_nodes", parent=dnt' in create_rig_core
    assert 'cmds.ls(type="distanceDimShape", long=True)' in create_rig_core
    assert 'name=f"{token}_dim", parent=distance_group' in create_rig_core
    assert 'RIG_BUILD_REVISION = "rig-nondegenerate-limb-ribbons-v34"' in create_rig_core
    surface_builder_body = create_rig_core.split(
        "def create_surface_from_joints_original(", 1
    )[1].split("def create_loft_surface_with_follicle_joints(", 1)[0]
    assert "width_direction -= chain_direction *" in surface_builder_body
    assert "width_direction = om.MVector(0.0, 0.0, 1.0)" in surface_builder_body
    assert "worldSpace=True" in surface_builder_body
    assert "cmds.move(0, offset * i, 0" not in surface_builder_body
    assert 'if region == "brow":' in surface_rig_body
    assert "rotate_ctrl_cvs_object_y(ctrl_name, 90.0)" in surface_rig_body
    assert "def _curve_world_up_vector(curve_shape):" in create_rig_core
    assert 'cmds.setAttr(f"{motion_path}.frontAxis", 1)' in create_rig_core
    assert 'cmds.setAttr(f"{motion_path}.upAxis", 2)' in create_rig_core
    assert 'cmds.setAttr(f"{motion_path}.worldUpType", 3)' in create_rig_core
    assert "def _group_center_surface_controls(" in create_rig_core
    assert 'group_name = f"{_stretch_node_token(loft_name)}_main_ctrls_grp"' in create_rig_core
    assert 'f"{main_group}.scale{axis}",' in create_rig_core
    assert 'f"{pad}.scale{axis}",' in create_rig_core
    assert "cmds.ikSystem(edit=True, solve=True)" in create_rig_core
    assert 'cmds.setAttr(f"{ik_handle}.ikBlend", 1.0)' in create_rig_core
    assert "def duplicate_exact_chain(source_chain, suffix):" in create_rig_core
    assert "cmds.duplicate(source, parentOnly=True, name=target_name)" in create_rig_core
    assert "cmds.duplicate(top_joint, rc=True)" not in create_rig_core
    assert "duplicate joint names" in create_rig_core
    assert "blend_point_constraints = []" in create_rig_core
    assert "point_con = cmds.pointConstraint(" in create_rig_core
    assert "for con in blend_point_constraints:" in create_rig_core
    assert '"blend_point_constraints": blend_point_constraints' in create_rig_core
    assert "current_parent = cmds.listRelatives(" in create_rig_core
    assert "current_parent[0] != target_matches[0]" in create_rig_core
    assert 'source_plug = "{}.preferredAngle{}".format(source, axis)' in create_rig_core
    assert "matched_ik_twist = 0.0" in create_rig_core
    assert 'cmds.setAttr(ik_handle + ".twist", matched_ik_twist)' in create_rig_core
    assert '"matched_ik_twist": matched_ik_twist' in create_rig_core
    assert 'longName="ikFkBlend", attributeType="float", min=0, max=1, dv=1.0' in create_rig_core
    assert 'cmds.setAttr(f"{switch_ctrl_name}.ikFkBlend", 1.0)' in create_rig_core
    assert "def set_all_limb_ik_fk_switches(value=1.0):" in create_rig
    assert "set_all_limb_ik_fk_switches(1.0)" in full_rig_body
    assert full_rig_body.index("set_all_limb_ik_fk_switches(1.0)") > full_rig_body.index(
        "restore_rig_connections(module)"
    )
    assert full_rig_body.index("set_all_limb_ik_fk_switches(1.0)") < full_rig_body.index(
        "hide_post_build_face_nodes()"
    )
    twist_driver_body = create_rig_core.split("def create_twist_driver(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert 'child_tx = cmds.getAttr(child_bone + ".translateX")' in twist_driver_body
    assert "x_val = -1.0 if child_tx >= 0.0 else 1.0" in twist_driver_body
    assert 'driver_token = driver_bone.split("|")[-1].split(":")[-1].lower()' in twist_driver_body
    assert 'if "lowerarm" in driver_token or "knee" in driver_token:' in twist_driver_body
    assert "world_up_object = child_bone" in twist_driver_body
    assert "world_up_object = parent" in twist_driver_body
    assert "worldUpObject=world_up_object" in twist_driver_body
    assert "worldUpObject=driver_bone" not in twist_driver_body
    assert 'name=driver_token.replace("_driver", "_twist_invert_mdl")' not in twist_driver_body
    assert 'cmds.setAttr(invert_node + ".input2", -1.0)' not in twist_driver_body
    assert '"upperarm" in driver_token or "thigh" in driver_token' in twist_driver_body
    assert 'weight_twist = 1.0 - (i / float(num_cvs - 1))' in twist_driver_body
    assert "settings = twist_driver_contract(" in twist_driver_body
    assert 'worldUpVector=tuple(settings["world_up_vector"])' in twist_driver_body
    assert 'mo=settings["maintain_offset"]' in twist_driver_body
    assert 'if settings["aim_offset"] is not None:' in twist_driver_body
    assert "segment_length_squared = segment * segment" in twist_driver_body
    assert "cmds.pointPosition(cv, world=True)" in twist_driver_body
    assert "'lowerarm' not in driver_bone" not in twist_driver_body
    assert "for joint, ctrl in (joint_to_ctrl or {}).items():" not in twist_driver_body
    assert 'sdk = ctrl + "_sdk_pad"' not in twist_driver_body
    assert 'twistOrientConstraint' not in twist_driver_body
    other_face_body = create_rig.split(
        "def rig_other_face_module(", 1
    )[1].split("\ndef ", 1)[0]
    assert 'existing_pad = f"{fj}_ctrl_pad"' in other_face_body
    assert "cmds.parent(pad_long, target_long, absolute=True)" in other_face_body
    extension_restore_body = create_rig.split(
        "def restore_post_build_extensions(", 1
    )[1].split("\ndef ", 1)[0]
    assert "builder_systems = set()" in extension_restore_body
    assert "_is_builder_owned_extension_root(" in extension_restore_body
    assert "is_twist_rig = (" not in surface_rig_body
    assert "cmds.disconnectAttr(rotate_source, rotate_destination)" not in surface_rig_body
    assert "cmds.parentConstraint(follicle_joints[idx], ctrl_pad, mo=True)" in surface_rig_body
    assert "joint_to_ctrl[joint_chain[-1]] = ctrl_name" in surface_rig_body
    assert "def delete_temp_bones():" in temp_cleanup
    assert "def cleanup_temp_bones(function):" in temp_cleanup
    assert "finally:" in temp_cleanup
    assert "@cleanup_temp_bones\ndef create_rig_from_mapping" in create_rig
    leg_module_body = create_rig.split("def rig_leg_module(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert 'built_ik_chain = list(limb_data.get("ik_chain") or [])' in leg_module_body
    assert "ik_leg_joints = built_ik_chain[2:5]" in leg_module_body
    assert "def get_ik_joint_name" not in leg_module_body
    limb_body = create_rig_core.split("def create_ik_fk_limb(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert limb_body.index("pole_direction = mid_vector - projection") < limb_body.index(
        "cmds.ikHandle("
    )
    assert "straight_tolerance = max(limb_line.length() * 1.0e-2" in limb_body
    assert "pole_direction.length() <= straight_tolerance" in limb_body
    assert "preferred = []" in limb_body
    assert "bend_axis = world_axes[dominant_index]" in limb_body
    assert "pole_direction = (limb_axis ^ bend_axis) * bend_sign" in limb_body
    assert "if not is_leg:" in limb_body
    assert "pole_direction.y = 0.0" in limb_body
    assert "pole_position = pole_origin + pole_direction * pv_distance" in limb_body
    assert "preferred_sign" not in limb_body
    assert limb_body.index("cmds.ikHandle(") < limb_body.index(
        "cmds.poleVectorConstraint(pv_ctrl, ik_handle)"
    )
    assert "matched_ik_twist = 0.0" in limb_body
    assert "translation=ik_end_position" in limb_body
    assert "rotation=(0.0, 0.0, 0.0)" in limb_body
    assert 'cmds.orientConstraint(ik_ctrl, ik_joints[ik_end_index], mo=True)' in limb_body
    assert "cmds.orientConstraint(end_joint, ik_joints[ik_end_index], mo=False)" in limb_body
    assert "ik_pose_targets = []" in limb_body
    assert 'pose_target_name = f"{ik_joints[i]}_poseTarget"' in limb_body
    assert "cmds.parentConstraint(ik_joints[i], ik_pose_target, mo=True)" in limb_body
    assert '"ik_pose_targets": ik_pose_targets' in limb_body
    assert "resolved_nodes = cmds.ls(related_node, long=True)" in create_rig
    assert "node_type = cmds.nodeType(resolved)" in create_rig


def test_major_maya_rig_operations_always_cleanup_temporary_bones() -> None:
    joint_placer = (TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placer.py").read_text(
        encoding="utf-8"
    )
    setup_hik = (TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "setup_hik.py").read_text(
        encoding="utf-8"
    )

    assert '@undoable("Fit Studio Skeleton")\n@cleanup_temp_bones' in joint_placer
    assert '@undoable("Place Biped Joints")\n@cleanup_temp_bones' in joint_placer
    assert '@undoable("Set T-Pose")\n@cleanup_temp_bones' in setup_hik


def test_maya_hik_ui_reloads_rig_core_before_the_public_builder() -> None:
    hik_ui = (TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py").read_text(encoding="utf-8")

    reload_core = hik_ui.index("create_rig_core,")
    reload_builder = hik_ui.index("importlib.reload(create_rig)")
    assert reload_core < reload_builder
    assert "Rig source:" in hik_ui
    assert "RIG_BUILD_REVISION" in hik_ui
    assert "owns_undo_chunk = not silent" in hik_ui
    assert "Full Rig build failed and was rolled back" in hik_ui
    build_action = hik_ui.split("    def build_full_rig(self):", 1)[1].split(
        "    def remove_full_rig(self):", 1
    )[0]
    assert "reload_rig_function_stack(force=True)" in build_action
    assert "Full Build reloaded rig stack" in build_action
    assert "setup_hik.set_t_pose(joint_map=self.default_map)" in build_action
    assert 'self.fields.get("Head"), "head1_ctrl"' in build_action
    assert "parent_override=parent_override" in build_action
    assert "jaw_ctrl_override=jaw_parent" in build_action
    assert 'if module == "Tongue":' in build_action
    assert 'module in {"Eyelids (Left)", "Eyelids (Right)"}' in build_action
    assert "create_rig_mapping(refresh_details=False)" in build_action
    assert build_action.index("create_rig.hide_post_build_face_nodes()") > build_action.index(
        "create_rig.restore_all_control_cv_positions()"
    )
    assert build_action.count("self._load_module_metadata_from_scene()") == 1
    assert "self._refresh_all_module_details()" not in build_action
    assert build_action.index("cmds.undoInfo(closeChunk=True)") < build_action.rindex(
        'self._notify_operation("Full Rig Built", success_summary, "success")'
    )
    assert 'self._notify_operation("Full Rig Built", success_summary, "success")' in build_action
    assert "QtWidgets.QMessageBox(self)" not in build_action
    assert "success_dialog.show()" not in build_action
    assert "success_dialog.finished.connect(_release_success_dialog)" not in build_action
    assert 'cmds.confirmDialog(\n            title="Success"' not in build_action
    hik_definition_ui = hik_ui.split("class HIKDefinitionUI(", 1)[1].split(
        "def launch_hik_ui(", 1
    )[0]
    assert "QtWidgets.QMessageBox." not in hik_definition_ui
    assert hik_definition_ui.count("cmds.confirmDialog(") == 1
    assert "def _notify_operation(" in hik_definition_ui
    body_build = hik_ui.split("    def create_body_module_setup(self, module, silent=False):", 1)[1].split(
        "    def remove_body_module_setup(self, module):", 1
    )[0]
    face_build = hik_ui.split("    def create_face_module_setup(", 1)[1].split(
        "    def remove_face_module_setup(self, module):", 1
    )[0]
    assert "parent_override=None" in face_build
    assert "jaw_ctrl_override=None" in face_build
    assert "if not silent:\n            self.create_rig_mapping()" in body_build
    assert "if not silent:\n            self.create_rig_mapping()" in face_build
    assert "if not silent:\n                self.store_all_face_connections(silent=False)" in body_build
    assert "if not silent:\n                self.store_all_face_connections(silent=False)" in face_build
    assert "joint_placer," in hik_ui
    preview_action = hik_ui.split(
        "    def preview_selected_joint_placement(self):", 1
    )[1].split("    def fit_template_to_selected_mesh(self):", 1)[0]
    fit_action = hik_ui.split(
        "    def fit_template_to_selected_mesh(self):", 1
    )[1].split("    def capture_joint_placement_baseline(self):", 1)[0]
    assert "reload_rig_function_stack(force=True)" in preview_action
    assert "joint_placer.preview_selected_mesh_joint_placement(" in preview_action
    assert 'solver="production"' in preview_action
    assert "mapped_studio_template_namespace(" in preview_action
    assert "placement_map = None if studio_namespace is not None else self.default_map" in preview_action
    assert "joint_map=placement_map" in preview_action
    assert "create_rig_mapping(refresh_details=False)" in preview_action
    assert "reload_rig_function_stack(force=True)" in fit_action
    assert "joint_placer.build_basic_biped_skeleton(" in fit_action
    assert 'solver="production"' in fit_action
    assert "require_interior=False" in fit_action
    assert "require_interior=True" not in fit_action
    assert "mapped_studio_template_namespace(" in fit_action
    assert "joint_map=placement_map" in fit_action
    assert fit_action.count("create_rig_mapping(refresh_details=False)") == 2
    assert '"UI refresh={2:.3f}s, dialog ready={3:.3f}s"' in fit_action
    assert "self.setUpdatesEnabled(False)" in fit_action
    assert "self.setUpdatesEnabled(True)" in fit_action
    assert 'QPushButton("Preview Joint Placement")' in hik_ui
    assert 'QPushButton("Fit Mapped Skeleton / Default Template")' in hik_ui
    assert 'QPushButton("Capture Approved Baseline")' in hik_ui
    assert 'QPushButton("Validate Selected Placement")' in hik_ui
    assert 'QPushButton("Run Placement Regression Suite")' in hik_ui
    assert "joint_placement_regression," in hik_ui
    assert "joint_placement_layout_combo" not in hik_ui
    assert "def preview_selected_joint_placement(self):" in hik_ui
    assert "def fit_template_to_selected_mesh(self):" in hik_ui


def test_maya_joint_placer_uses_hybrid_volume_validation() -> None:
    source = (TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placer.py").read_text(encoding="utf-8")

    assert "class MeshPlacementReport:" in source
    assert "class MeshInteriorQuery:" in source
    assert "def analyze_mesh_for_joint_placement(" in source
    assert "def solve_production_biped_points(" in source
    assert "DEFAULT_PLACEMENT_TEMPLATE = rig_template.DEFAULT_BIPED_RIG_TEMPLATE" in source
    assert "def extract_studio_template_core_points(" in source
    assert "def solve_studio_template_points(" in source
    assert "def fit_studio_template_skeleton(" in source
    assert "replace_existing`` must be a true clean rebuild" in source
    assert "def is_studio_template_skeleton(" in source
    assert 'layout: str = "high"' not in source
    assert "use_studio_template_hierarchy" not in source
    assert "LOW_RES_BUILD_ORDER" not in source
    assert "def build_low_resolution_studio_skeleton(" not in source
    assert "template_joint_count=template_joint_count" in source
    assert "reverse_foot_joint_count=reverse_foot_joint_count" in source
    assert "TEMPLATE_SCALE_ATTR" in source
    assert 'setAttr\\s+"\\.bps"' in source
    assert "Studio template proposal failed; using proportional fallback" in source
    assert "class PlacementPreview:" in source
    assert "def preview_biped_joint_placement(" in source
    assert "def preview_selected_mesh_joint_placement(" in source
    assert "def validate_points_inside_mesh(" in source
    assert "self.mesh_fn.allIntersections(" in source
    assert "inside_votes >= 2" in source
    assert 'solver: str = "production"' in source
    assert "landmark_points: Optional[Dict[str, Vector3]]" in source
    assert "requires_review=requires_review" in source
    assert "PLACEMENT_SECTION_AXES =" in source
    assert "def validate_anatomical_layout(" in source
    assert "placementConfidence" in source
    assert "placementVerifiedInside" in source
    assert "anatomical_issues=anatomical_issues" in source
    assert "clearance=clearance" in source
    assert "detached = cmds.parent(child, world=True)[0]" in source
    assert "reparented = cmds.parent(child, joint)[0]" in source
    assert "minimum_bend=query.diagonal * 0.005" in source
    assert "def configure_studio_bend_axes(" in source
    assert "def enforce_studio_finger_planarity(" in source
    assert "def _enforce_no_reverse_finger_bend(" in source
    assert "fitted_slopes" in source
    assert 'name + "_reverse_bend_correction"' in source
    assert "def fit_studio_hand_joints(" in source
    assert "def fit_studio_arm_hand_from_reference(" in source
    assert "def _studio_digit_surface_rows(" in source
    assert 'report["surface_rows"]' in source
    assert "def fit_studio_detail_joints_to_volume(" in source
    assert "def _bounded_move_inside(" in source
    assert "def orient_studio_single_child_chains(" in source
    assert "def orient_studio_leg_chains(" in source
    assert "def _fit_studio_twist_segments(" in source
    assert "def _fit_studio_feet_to_volume(" in source
    assert "STUDIO_VOLUME_REPORT_ATTR" in source
    assert 'detail_placement_report["studio_volume_fit"]' in source
    assert '"depth_projected_surface_joints"' in source
    assert "HAND_FIT_REPORT_ATTR" in source
    assert 'detail_placement_report["studio_hand_fit"]' in source
    assert "def orient_studio_arm_chains(" in source
    assert "def orient_studio_leg_reference_frames(" in source
    assert 'volume_report["leg_reference_orientation"] = orient_studio_leg_reference_frames(' in source
    arm_orient = source.split("def orient_studio_arm_chains(", 1)[1].split(
        "def orient_studio_spine_vertical(", 1
    )[0]
    assert '"{0}_clavicle".format(side)' in arm_orient
    assert 'aim_sign = 1.0 if side == "l" else -1.0' in arm_orient
    assert "solve_reference_joint_roll_vectors(" in arm_orient
    assert "_reference_roll_basis(x_axis, y_axis)" in arm_orient
    assert "_set_joint_world_basis_preserving_children(" in arm_orient
    assert 'cmds.setAttr(joint + ".translateY", 0.0)' in arm_orient
    assert 'cmds.setAttr(joint + ".translateZ", 0.0)' in arm_orient
    assert "previous_dof = cmds.joint(joint, query=True, degreeOfFreedom=True)" in source
    assert "Recenter every proposal" in source
    assert "folds back on itself" in source
    assert "is implausibly above" in source
    assert "class PlacementFrame:" in source
    assert "def placement_frame_from_mapping(" in source
    assert "def mapped_anatomical_joints(" in source
    assert "def mapped_studio_template_namespace(" in source
    assert "Create or update color-coded guides without rebuilding the DAG." in source
    assert "viewport_was_suspended" in source
    assert "stale = [" in source
    assert "def solve_mapped_hierarchy_points(" in source
    assert "def fit_mapped_skeleton(" in source
    assert "def place_mapped_detail_joints(" in source
    assert "def mapped_detail_editability_issues(" in source
    assert '"No skeleton joints were changed."' in source
    assert '"all_correctives_verified"' in source
    assert '"all_detail_joints_verified"' in source
    assert '"corrective_validation_errors"' in source
    assert '"twist_validation_errors"' in source
    assert '"unclassified_corrective_joints"' in source
    assert '"twist_correctives_placed"' in source
    assert '"active_hik_rig_mapping"' in source
    assert 'short_name.startswith("FACIAL_")' in source
    assert "_capture_mapped_twist_fractions" in source
    assert "def _project_joint_chain_to_plane(" in source
    assert '"elbow_z_knee_y_thumb02_terminal_z_digit03_terminal_z"' in source
    assert "preferredAngle{1}" in source
    assert "def orient_studio_spine_vertical(" in source
    assert "orient_studio_spine_vertical(namespace=namespace)" in source
    assert "def align_studio_center_face_positions(" in source
    assert "align_studio_center_face_positions(" in source
    assert "def orient_studio_neck1_grid_standard(" in source
    assert "orient_studio_neck1_grid_standard(" in source
    assert 'forward_axis = _joint_world_axes(spine_tip)["y"]' in source
    assert 'world_up=(forward_axis.x, forward_axis.y, forward_axis.z)' in source
    assert 'orientation_issues[name + "_forward_y"]' in source
    assert 'orientation_issues["neck2_midpoint_frame"]' in source
    assert "reference_points, reference_cases = solve_reference_internal_head_points(mesh)" in source
    assert 'if "neck2" in reference_points:' in source
    assert 'if "head1" in reference_points:' in source
    assert "neck2 at the exact midpoint" in source
    assert '(float(neck1_target[index]) + float(head_target[index])) * 0.5' in source
    assert 'volume_report["approved_positions_locked"]' in source
    assert "def _restore_studio_joint_world_positions(" in source
    assert 'volume_report["approved_positions_final_restore"]' in source
    assert "def _set_joint_local_rotation_preserving_children(" in source
    assert "def orient_studio_center_face_grid_axes(" in source
    assert "orient_studio_center_face_grid_axes(" in source
    assert "def enforce_studio_center_face_local_zeroes(" in source
    assert "enforce_studio_center_face_local_zeroes(namespace=namespace)" in source
    assert '("nose_root", "Z")' in source
    assert '("nose_upper", "X")' in source
    assert '("nose_tip", "X")' in source
    assert '"nose_root", "nose_upper", "nose_tip", "nose_base"' in source
    assert "lateral_fraction = math.sin(angle)" in source
    assert "center_weight = math.cos(angle)" in source
    assert "finger_pattern = re.compile" in source
    assert 'cmds.setAttr(child + ".translate", length * aim_sign, 0.0, 0.0)' in source
    assert '"translate_x_only_from_02": True' in source
    assert '"translate_x_sign": aim_sign' in source
    assert '"topology_longitudinal_reach_preserved": True' in source
    assert '"tip_cross_section_adjusted": tip_moved' in source
    assert "def _align_mild_studio_digit_bend(" in source
    assert "obvious_bend_ratio: float = 0.08" in source
    assert '"minor_bend_alignment": alignment_report' in source
    assert '"shared_thumb_curl_plane"' in source
    assert 'cmds.setAttr(child + ".translateY", 0.0)' in source
    assert 'cmds.setAttr(child + ".translateZ", 0.0)' in source
    assert '"each_joint_aims_at_child": True' in source
    assert '"zero_rotation_from_01": True' in source
    assert '"terminal_rotation_zero": True' in source
    assert '"tip_mesh_centered": centered_ok' in source
    assert "desired_x_by_name = {}" in source
    assert "reference_roll, reference_ids = solve_reference_joint_roll_vectors(" in source
    assert "def solve_reference_thumb_knuckle_z_vectors(" in source
    assert "thumb_shared_z = (" in source
    assert "thumb_knuckle_z.get(_short_name(chain[1]))" in source
    assert "_reference_z_basis(terminal_x, thumb_shared_z)" in source
    assert "standardFrameDots" in source
    assert '"reference_atlases": reference_ids' in source

    regression = (TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placement_regression.py").read_text(
        encoding="utf-8"
    )
    assert "SCHEMA_VERSION = 1" in regression
    assert "def capture_baseline(" in regression
    assert "def capture_anchor_baseline(" in regression
    assert "def capture_mapped_baseline(" in regression
    assert "def evaluate_mesh_against_baseline(" in regression
    assert "def evaluate_studio_foot_contract(" in regression
    assert "def evaluate_studio_pelvis_contract(" in regression
    assert '"toe_rotate_z_only"' in regression
    assert '"stable_ankle_roll"' in regression
    assert '"continuous_front_line"' in regression
    assert '"channels_unlocked"' in regression
    assert '"required_template_joint_count": 280' in regression
    assert '"required_reverse_foot_joint_count": 12' in regression

    runner = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placement_regression_runner.py"
    ).read_text(encoding="utf-8")
    assert "def _import_fbx_in_namespace(" in runner
    assert "returnNewNodes=True" in runner
    assert 'report["foot_contract"] = foot_contract' in runner
    assert 'report["pelvis_contract"] = pelvis_contract' in runner
    assert 'foot_namespace = "__foot_contract__"' in runner

    corpus_root = TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placement_regression_cases"
    manifest = json.loads((corpus_root / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["cases"]) >= 4
    assert {case["id"] for case in manifest["cases"]} >= {
        "studio_juice_approved",
        "studio_john_healthy_approved",
        "cc0_quaternius_superhero_female",
        "cc0_quaternius_superhero_male",
    }
    provenance = json.loads(
        (
            corpus_root
            / "assets"
            / "quaternius_universal_base"
            / "SOURCE.json"
        ).read_text(encoding="utf-8")
    )
    assert provenance["license"] == "CC0 1.0 Universal"
    assert len(provenance["included_files"]) == 3


def test_maya_surface_smooth_brush_uses_viewport_overlay_and_direct_strokes() -> None:
    source = (TOOLS_ROOT / "maya_tools" / "Rigging" / "skinning_utils.py").read_text(encoding="utf-8")

    assert "class _SurfaceSmoothBrushOverlay(QtWidgets.QWidget):" in source
    assert "def _update_overlay(self, hit_data, view, panel, widget):" in source
    assert "def begin_viewport_stroke(self):" in source
    assert "def continue_viewport_stroke(self):" in source
    assert "def finish_viewport_stroke(self):" in source
    assert "QtCore.QEvent.MouseButtonPress" in source
    assert "brush.resize_from_pixels" in source
    assert "Auto Hammer Weight Spikes" in (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"
    ).read_text(encoding="utf-8")
    assert "Auto Smooth Whole Mesh / Selected Verts" in (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"
    ).read_text(encoding="utf-8")
    assert "vertex_indices=None if entire_mesh else vertices" in source
    assert '"detect_weight_outlier_indices", "detect_deformation_ripple_indices"' in source
    assert "importlib.reload(_spatial_smoothing)" in source


def test_reverse_foot_snap_is_deferred_until_t_pose() -> None:
    placer = (TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placer.py").read_text(
        encoding="utf-8"
    )
    studio_fit = placer.split("def fit_studio_template_skeleton(", 1)[1].split(
        "def preview_biped_joint_placement(", 1
    )[0]
    assert "_fit_reverse_foot_chain(side, namespace, points, scale_multiplier)" not in studio_fit
    assert "def snap_reverse_foot_helpers_to_deformation_skeleton(" in placer
    assert "def snap_all_reverse_foot_helpers_after_t_pose(" in placer
    assert "PLACEMENT_MESH_ATTR = \"autoJointPlacerSourceMesh\"" in placer
    assert "PLACEMENT_MESH_MESSAGE_ATTR = \"autoJointPlacerSourceMeshMessage\"" in placer
    assert "def _connect_placement_mesh(" in placer
    assert "def _solve_reverse_foot_ground_pivots(" in placer
    assert "def _orient_reverse_foot_ik_chain(" in placer
    assert 'cmds.setAttr(child + ".translate", length * aim_sign, 0.0, 0.0)' in placer
    assert "world_up=(0.0, aim_sign, 0.0)" in placer
    assert "def _mirror_reverse_foot_ground_pivots_if_symmetric(" in placer
    assert "reference_width = max(" in placer
    assert "max(deviations) > reference_width * 0.05" in placer
    assert '"mirrored_ground_pivots": mirrored_ground_pivots' in placer
    assert "heel_forward -= max(foot_length * 0.025" in placer
    assert "toe_forward = (toe_vector - ankle_vector) * forward" in placer
    assert "search_start = foot_length * 0.35" in placer
    assert "search_end = min(toe_forward, foot_length * 0.78)" in placer
    assert "if item[0] >= widest * 0.99" in placer
    assert "bank_forward = sum(widest_plateau) / len(widest_plateau)" in placer
    assert "edge_inset = max(bank_width * 0.10" in placer
    assert "edge_clearance = max(bank_width * 0.0125" in placer
    assert "inner_side = inner_edge + edge_inset" in placer
    assert "outer_side = outer_edge + edge_clearance" in placer
    assert "return (float(position.x), float(ground_y), float(position.z))" in placer
    assert '"innerBank": _world_position(bank_forward, inner_side)' in placer
    assert '"outerBank": _world_position(bank_forward, outer_side)' in placer
    assert "ground_pivots=ground_pivots.get(side)" in placer
    assert '"post_t_pose"' in placer
    assert "snap_all_reverse_foot_helpers_after_skin_import" not in placer
    assert studio_fit.index("orient_studio_single_child_chains(") < studio_fit.index(
        "orient_studio_arm_chains("
    )
    assert 'volume_report["elbow_z_hinges"] = enforce_studio_elbow_z_hinges(' in studio_fit
    assert studio_fit.index("orient_studio_arm_chains(") < studio_fit.index(
        "orient_studio_digit_chains("
    )
    assert studio_fit.index("orient_studio_leg_reference_frames(") < studio_fit.index(
        "orient_studio_digit_chains("
    )
    assert studio_fit.index("orient_studio_single_child_chains(") < studio_fit.index(
        "orient_studio_leg_chains("
    )

    skinning = (TOOLS_ROOT / "maya_tools" / "Rigging" / "skinning_utils.py").read_text(
        encoding="utf-8"
    )
    import_body = skinning.split("def import_skin_weights(", 1)[1]
    assert "imported_meshes.append(mesh)" in import_body
    assert "cmds.delete(existing_skin)" not in import_body
    assert "original_influence_names" in import_body
    assert "original_bind_poses" in import_body
    assert "addInfluence=influence" in import_body
    assert "removed_influences" in import_body
    assert "changed_bind_poses" in import_body
    assert '"bind_pose_preserved": True' in import_body
    assert '"influence_reports": influence_reports' in import_body
    assert '"stage": "skin_import_deferred_to_t_pose"' in import_body
    assert '"skipped": True' in import_body
    assert "snap_all_reverse_foot_helpers" not in import_body

    setup_hik = (TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "setup_hik.py").read_text(
        encoding="utf-8"
    )
    t_pose_body = setup_hik.split("def set_t_pose(", 1)[1].split(
        "t_pose_character = set_t_pose", 1
    )[0]
    assert "def _prepare_legs_for_t_pose(" in setup_hik
    leg_pose_body = setup_hik.split("def _prepare_legs_for_t_pose(", 1)[1].split(
        "def set_t_pose(", 1
    )[0]
    assert "_set_joint_world_position_preserving_children(" not in leg_pose_body
    assert "worldSpace=True, translation=" not in leg_pose_body
    assert "pelvis_position" not in leg_pose_body
    assert "twist_segments" not in leg_pose_body
    assert '_set_rotation_value(knee, "X", 0.0)' not in leg_pose_body
    assert "thigh_swing_axis = _best_oriented_rotation_axis(" not in leg_pose_body
    assert "_sample_rotation_axis(" in leg_pose_body
    assert 'thigh,\n            "Z",' in leg_pose_body
    assert "lambda: _front_vertical_segment_error(thigh, knee)" in leg_pose_body
    assert "snapped_z = _nearest_right_angle(solved_z)" in leg_pose_body
    assert "_flatten_foot_mesh_with_rotation(" not in leg_pose_body
    assert "_mirror_right_foot_pose_from_left(" not in leg_pose_body
    assert "_ground_flattened_feet_with_pelvis(" not in leg_pose_body
    assert '_front_vertical_segment_error(thigh, knee)' in leg_pose_body
    assert '_front_vertical_segment_error(knee, ankle)' in leg_pose_body
    assert '"flattened": True' in leg_pose_body
    assert '"translation_preserved": True' in leg_pose_body
    assert 'hinge_axis="Z"' in setup_hik
    assert 'axis = str(hinge_axis).upper()' in setup_hik
    assert "sample_count = 18" in setup_hik
    assert "for _iteration in range(22):" in setup_hik
    assert "golden-section refinement" in setup_hik
    assert "ankle_world_rotation_snapshot" not in leg_pose_body
    assert "toe_rotation_snapshot" not in leg_pose_body
    assert "_flatten_segment_with_rotation(" not in leg_pose_body
    assert '"foot_mesh_grounding"' not in leg_pose_body
    assert "rotation=ankle_world_rotation_snapshot[side]" not in leg_pose_body
    assert "def _skin_mesh_for_joints(" in setup_hik
    assert "def _foot_mesh_contact_regions(" in setup_hik
    assert "def _mesh_contact_height(" in setup_hik
    assert '"heel": (-0.35 * foot_length, -0.05 * foot_length)' in setup_hik
    assert '"ball": (0.52 * foot_length, 0.78 * foot_length)' in setup_hik
    assert '"tip": (0.84 * foot_length, 1.18 * foot_length)' in setup_hik
    assert '"hinge_axes": {"ankle": ("X", "Z"), "toe": "Z"}' in setup_hik
    assert "def _align_foot_front_projection_with_rotation(" in setup_hik
    assert '_sample_rotation_axis(\n        ankle,\n        "Y",' in setup_hik
    assert '_sample_rotation_axis(\n        toe,\n        "Y",' not in setup_hik
    assert '_set_rotation_value(toe, "X", 0.0)' in setup_hik
    assert '_set_rotation_value(toe, "Y", 0.0)' in setup_hik
    assert '"toe_rotation_axes": ("Z",)' in setup_hik
    assert '"front_projection": front_projection' in setup_hik
    assert '"contact_spread"' in setup_hik
    assert "def _heel_ball_objective():" in setup_hik
    assert "def _toe_tip_objective():" in setup_hik
    assert '"tip_support_offset": tip_position.y - (' in setup_hik
    assert "def _mirror_right_foot_pose_from_left(" in setup_hik
    assert 'foot_pose_mirroring = _mirror_right_foot_pose_from_left(valid, result)' not in leg_pose_body
    assert '"support_{}_{}".format(long_label, side_label)' in setup_hik
    assert '("heel", (-0.35, 0.02))' in setup_hik
    assert '("tip", (0.78, 1.12))' in setup_hik
    assert "def _support_plane_objective():" in setup_hik
    assert 'if label.startswith("support_")' in setup_hik
    assert "positions[1::3]" in setup_hik
    assert '"support_spread":' in setup_hik
    assert '_sample_rotation_axis(\n                ankle,\n                "X",' in setup_hik
    assert "for _ground_iteration in range(3):" in setup_hik
    assert "def _ground_flattened_feet_with_pelvis(" in setup_hik
    assert "shift = -ground_reference" in setup_hik
    assert "position[1] + shift" in setup_hik
    assert '"rotated_joints": rotated_joints' in leg_pose_body
    assert '"reason": "rigid_chain_rotation"' in leg_pose_body
    assert "_prepare_legs_for_t_pose(leg_chains, pelvis=pelvis)" in t_pose_body
    assert 'pelvis = pelvis or _extract("Hips", "pelvis")' in t_pose_body
    assert 'for axis in ("X", "Y", "Z"):' not in setup_hik.split(
        "def _flatten_segment_with_rotation(", 1
    )[1].split("def _skin_mesh_for_joints(", 1)[0]
    assert 'aim_joint_x_axis_to_world_x(\n            l_upperarm, side="l"' in t_pose_body
    assert 'aim_joint_x_axis_to_world_x(\n            r_upperarm, side="r"' in t_pose_body
    aim_body = setup_hik.split("def aim_joint_x_axis_to_world_x(", 1)[1].split(
        "def _toe_tip_from_chain(", 1
    )[0]
    assert "joint_orient_before" in aim_body
    assert "rotate_axis_before" in aim_body
    assert "cmds.orientConstraint(" in aim_body
    assert "maintainOffset=False" in aim_body
    assert '.replace(":", "_") + "_worldAlignTemp"' in aim_body
    assert '"jointOrient", joint_orient_before' in aim_body
    assert '"translate", translate_before' in aim_body
    assert "axis_errors = {" in aim_body
    assert "if max(axis_errors.values()) > 1.0e-5:" in aim_body
    assert "def _aim_frame_preserving_roll(" in setup_hik
    roll_aim_body = setup_hik.split(
        "def _aim_frame_preserving_roll(", 1
    )[1].split("def aim_joint_x_axis_to_world_x(", 1)[0]
    assert "shortest_arc = current_x.rotateTo(desired_x)" in roll_aim_body
    assert "current_y.rotateBy(shortest_arc)" in roll_aim_body
    assert "current_z.rotateBy(shortest_arc)" in roll_aim_body
    assert "_canonical_t_pose_arm_frame(" in aim_body
    assert '"roll_normalized": side in ("l", "r")' in aim_body
    assert "def _set_oriented_elbow_prebend(" in setup_hik
    elbow_pose_body = setup_hik.split(
        "def _set_oriented_elbow_prebend(", 1
    )[1].split("def _toe_tip_from_chain(", 1)[0]
    assert 'name=elbow.split("|")[-1].replace(":", "_") + "_tPoseForearmTemp"' in elbow_pose_body
    assert "cmds.orientConstraint(" in elbow_pose_body
    assert "maintainOffset=False" in elbow_pose_body
    assert "_canonical_t_pose_arm_frame(" in elbow_pose_body
    assert '(cosine, 0.0, -sine if is_right else sine)' in elbow_pose_body
    assert "_set_oriented_elbow_prebend(" in t_pose_body
    assert '"elbow_prebend_reports": elbow_prebend_reports' in t_pose_body
    assert "align_clavicle_Y_by_rotateY(" not in t_pose_body
    assert "def align_clavicle_to_upperarm_height(" in setup_hik
    clavicle_align_body = setup_hik.split(
        "def align_clavicle_to_upperarm_height(", 1
    )[1].split("def aim_joint_x_axis_to_world_x(", 1)[0]
    assert '"rotation_space": "world_z_only"' in clavicle_align_body
    assert "target_azimuth = 0.0 if x_axis.x >= 0.0 else math.pi" in clavicle_align_body
    assert "om.MQuaternion(delta, om.MVector(0.0, 0.0, 1.0))" in clavicle_align_body
    assert "world_x_after[2] - x_axis.z" in clavicle_align_body
    assert "align_clavicle_to_upperarm_height(l_clav, l_upperarm)" in t_pose_body
    assert "align_clavicle_to_upperarm_height(r_clav, r_upperarm)" in t_pose_body
    assert t_pose_body.index("_prepare_legs_for_t_pose(") < t_pose_body.index(
        "snap_all_reverse_foot_helpers_after_t_pose()"
    )
    assert "configure_mapped_bend_axes(" not in t_pose_body
    assert '"preferred_bends": {}' in t_pose_body
    mapped_fit = placer.split("def fit_mapped_skeleton(", 1)[1].split(
        "def fit_studio_template_skeleton(", 1
    )[0]
    assert mapped_fit.index("place_mapped_detail_joints(") < mapped_fit.index(
        "configure_mapped_bend_axes("
    )
    preferred_capture = placer.split(
        "def capture_current_pose_as_preferred_angles(", 1
    )[1].split("def _finger_plane_normal(", 1)[0]
    assert 'value = float(cmds.getAttr(rotate_plug))' in preferred_capture
    assert "cmds.setAttr(preferred_plug, value)" in preferred_capture
    bend_axis_helper = placer.split(
        "def _configure_preferred_bend_axis(", 1
    )[1].split("def capture_current_pose_as_preferred_angles(", 1)[0]
    assert "preferredAngle" not in bend_axis_helper
    assert "preferred_degrees" not in bend_axis_helper
    assert mapped_fit.index("configure_mapped_bend_axes(") < mapped_fit.index(
        "capture_current_pose_as_preferred_angles(root)"
    )
    studio_fit = placer.split("def fit_studio_template_skeleton(", 1)[1].split(
        "def preview_joint_placement(", 1
    )[0]
    assert studio_fit.index("configure_studio_bend_axes(") < studio_fit.index(
        "capture_current_pose_as_preferred_angles(root)"
    )
    assert 'DEFAULT_SKIN_WEIGHT_DIR = "C:/temp/weights"' in placer
    assert "def import_matching_skin_weights(" in placer
    auto_skin_import = placer.split("def import_matching_skin_weights(", 1)[1].split(
        "def _finger_plane_normal(", 1
    )[0]
    assert '"{0}_weights.xml".format(mesh_name)' in auto_skin_import
    assert '"{0}_weights_influences.json".format(mesh_name)' in auto_skin_import
    assert 'if not report["matched"]:' in auto_skin_import
    assert "from maya_tools.Rigging import skinning_utils" in auto_skin_import
    assert "skinning_utils.import_skin_weights([mesh_name], str(weight_dir))" in auto_skin_import
    assert "import_skin_weights: bool = False" in placer
    assert "if import_skin_weights:" in placer
    assert 'detail_placement_report["skin_weight_import"] = import_matching_skin_weights(' in placer
    assert '"reason": "disabled_for_joint_placement_performance"' in placer
    assert 'for ground_suffix in ("heel_RFL", "outerBank_RFL", "innerBank_RFL"):' in placer

    ui = (TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py").read_text(
        encoding="utf-8"
    )
    ui_import = ui.split("    def import_skin_weights(self):", 1)[1].split(
        "    def smooth_skin_weights_spatially(self):", 1
    )[0]
    assert "reload_rig_function_stack()" in ui_import
    assert "_RIG_STACK_SIGNATURE" in ui
    assert "if not force and _RIG_STACK_SIGNATURE == current_signature:" in ui

    undo_utils = (TOOLS_ROOT / "maya_tools" / "Rigging" / "undo_utils.py").read_text(
        encoding="utf-8"
    )
    create_rig_source = (TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig.py").read_text(
        encoding="utf-8"
    )
    full_rig_body = create_rig_source.split("def create_full_rig(", 1)[1].split(
        "def create_rig_from_mapping(", 1
    )[0]
    assert "setup_hik.set_t_pose(" in full_rig_body
    assert "making repeated calls a" in full_rig_body
    assert '_T_POSE_SNAPSHOT_ATTR = "tcTposeWorldMatrices"' in setup_hik
    assert "_T_POSE_SNAPSHOT_VERSION = 10" in setup_hik
    assert 'decoded.get("version") != _T_POSE_SNAPSHOT_VERSION' in setup_hik
    assert '"reason": "already_in_t_pose"' in setup_hik
    assert "def _capture_t_pose_authored_channels(" in setup_hik
    assert "def _validate_t_pose_authored_channels(" in setup_hik
    assert "authored_channel_snapshot = _capture_t_pose_authored_channels(pose_joints)" in t_pose_body
    assert "authored_channel_report = _validate_t_pose_authored_channels(" in t_pose_body
    assert 'if attribute == "translate" and joint == pelvis_path:' in setup_hik
    assert '"non_pelvis_translate_preserved": True' in setup_hik
    assert '"authored_channels": authored_channel_report' in t_pose_body
    assert "_store_t_pose_snapshot(snapshot_holder, pose_joints)" in setup_hik
    assert 'toe_z_limits = (toe_start_z - 45.0, toe_start_z + 45.0)' in setup_hik
    assert 'toe_start_z = _rotation_value(toe, "Z")' in setup_hik
    assert '_set_rotation_value(toe, "Z", 0.0)' not in setup_hik
    assert "def _foot_pose_is_grounded(" in setup_hik
    assert "absolute_min=toe_z_limits[0]" in setup_hik
    assert "cmds.undoInfo(openChunk=True" in undo_utils
    assert "cmds.undoInfo(closeChunk=True)" in undo_utils
    assert '@undoable("Build Full Rig")' in create_rig_source
    assert '@undoable("Fit Studio Skeleton")' in placer
    assert '@undoable("Preview Joint Placement")' in placer
    assert '@undoable("Place Biped Joints")' in placer
    assert '@undoable("Set T-Pose")' in setup_hik
    assert "Reverse-foot joints were left unchanged; they snap after T-pose." in ui_import
    assert 'QPushButton("Set T-Pose")' in ui
    assert "t_pose_btn.clicked.connect(self.set_t_pose_from_mapping)" in ui
    assert "def set_t_pose_from_mapping(self):" in ui
    t_pose_action = ui.split("    def set_t_pose_from_mapping(self):", 1)[1].split(
        "    def build_full_rig(self):", 1
    )[0]
    assert "reload_rig_function_stack()" in t_pose_action
    assert "self.create_rig_mapping()" in t_pose_action
    assert "setup_hik.set_t_pose(joint_map=self.default_map)" in t_pose_action
    assert 'cmds.undoInfo(openChunk=True, chunkName="Set T-Pose")' in t_pose_action
    assert "cmds.undo()" in t_pose_action

def test_studio_foot_flare_runs_after_volume_containment() -> None:
    placer = (TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placer.py").read_text(
        encoding="utf-8"
    )
    studio_fit = placer.split("def fit_studio_template_skeleton(", 1)[1].split(
        "def preview_biped_joint_placement(", 1
    )[0]
    volume_index = studio_fit.index("fit_studio_detail_joints_to_volume(")
    flare_index = studio_fit.index(
        'volume_report["foot_front_flare"] = fit_studio_foot_front_flare('
    )
    volume_center_index = studio_fit.index(
        'volume_report["toe_volume_centers"] = fit_studio_toe_pivots_to_volume('
    )
    mirror_index = studio_fit.index("mirror_studio_right_leg_from_left(")
    thigh_depth_index = studio_fit.index(
        'volume_report["thigh_pelvis_depth"] = align_studio_thigh_roots_to_pelvis_depth('
    )

    assert "def fit_studio_foot_front_flare(" in placer
    assert "def fit_studio_toe_pivots_to_volume(" in placer
    assert "def _same_side_span(intervals, side):" in placer
    assert '(terminal_depth - toe_depth) * 0.9423' in placer
    assert "toe_depth = ankle[2] + ((terminal_depth - ankle[2]) * 0.6386)" in placer
    assert "(outward_x - medial_x) * 0.4124" in placer
    assert "(toe_y_interval[1] - toe_y_interval[0]) * 0.5093" in placer
    assert "def mirror_studio_right_leg_from_left(" in placer
    assert "world-X reflection of the authored left leg" in placer
    assert "plane_normal = (ankle_vector - knee) ^ (toe_vector - ankle_vector)" in placer
    assert "sole_inset = max(query.diagonal * 0.0006025" in placer
    assert 'tip_y = query.bounds["min"].y + sole_inset' in placer
    assert "plane_error = tip_vector * plane_normal" in placer
    assert "tip_vector.x -= plane_error / plane_normal.x" in placer
    assert "tip_vector.z -= plane_error / plane_normal.z" in placer
    assert "def align_studio_thigh_roots_to_pelvis_depth(" in placer
    assert "pelvis_position[2]" in placer
    assert "def orient_studio_root_pelvis_hipswing_y_up(" in placer
    assert 'for name in ("origin", "pelvis", "hipswing")' in placer
    assert 'if name == "hipswing" and pelvis_position is not None:' in placer
    assert "origin = pelvis_position" in placer
    assert "orient_studio_root_pelvis_hipswing_y_up(namespace=namespace)" in studio_fit
    assert "def fit_studio_pelvis_ridge(" in placer
    assert 'volume_report["pelvis_ridge"] = fit_studio_pelvis_ridge(' in studio_fit
    assert volume_index < flare_index < volume_center_index < mirror_index < thigh_depth_index
    assert "Reference toe tips can initially sit beyond the mesh end." in placer
    assert "* (toe_depth / foot_depth)" in placer
    leg_orient = placer.split("def orient_studio_leg_chains(", 1)[1].split(
        "def unlock_studio_joint_channels(", 1
    )[0]
    assert "lateral_reference = (1.0, 0.0, 0.0)" in leg_orient
    assert 'aim_sign = 1.0 if side == "l" else -1.0' in leg_orient
    assert "segment.x * aim_sign" in leg_orient
    assert "hinge_direction.x * aim_sign" not in leg_orient
    assert "foot_length * aim_sign" in leg_orient
    assert "toe_length * aim_sign" in leg_orient
    assert "_orient_joint_with_world_z_hinge(" in leg_orient
    assert "Leg Y axis flipped between joints" in leg_orient
    assert "Leg Z axis flipped between joints" in leg_orient
    assert "Leg Z axis flipped at the ankle" in leg_orient
    assert "leg_plane_normal = foot_vector ^ toe_vector" in leg_orient
    assert "previous_z" in leg_orient
    assert "side_direction * (toe_vector - ankle_vector).length() * 0.006862" in placer
    assert "TEMPLATE_KNEE_BEND_AXIS_ATTR" in leg_orient
    assert 'STUDIO_TEMPLATE_KNEE_BEND_AXIS = "y"' in placer
    assert "def enforce_studio_elbow_z_hinges(" in placer
    elbow_hinge = placer.split("def enforce_studio_elbow_z_hinges(", 1)[1].split(
        "def enforce_studio_knee_y_hinges(", 1
    )[0]
    assert 'cmds.joint(joint, edit=True, degreeOfFreedom="xyz")' in elbow_hinge
    assert 'BEND_AXIS_ATTR, "z"' in elbow_hinge
    assert '"arm_reference_frame_local_z_hinge"' in elbow_hinge
    assert "upper_segment ^ lower_segment" in elbow_hinge
    assert "reference_z = om.MVector(_joint_world_axes(upperarm)" in elbow_hinge
    assert "upper_y = z_axis ^ upper_x" in elbow_hinge
    assert 'clavicle = _find_template_joint("{0}_clavicle".format(side), namespace)' in elbow_hinge
    assert "clavicle_z = z_axis - clavicle_x * (z_axis * clavicle_x)" in elbow_hinge
    assert "_set_joint_world_basis_preserving_children(" in elbow_hinge
    assert 'cmds.setAttr(hand + ".translateY", 0.0)' in elbow_hinge
    assert 'cmds.setAttr(hand + ".translateZ", 0.0)' in elbow_hinge
    assert 'volume_report["elbow_z_hinges"] = enforce_studio_elbow_z_hinges(' in studio_fit
    assert "def enforce_studio_knee_y_hinges(" in placer
    knee_hinge = placer.split("def enforce_studio_knee_y_hinges(", 1)[1].split(
        "def orient_studio_spine_vertical(", 1
    )[0]
    assert 'cmds.setAttr(knee + ".rotate", 0.0, best_angle, 0.0)' in knee_hinge
    assert 'cmds.joint(knee, edit=True, degreeOfFreedom="xyz")' in knee_hinge
    assert 'cmds.setAttr(joint + ".translateY", 0.0)' in knee_hinge
    assert 'cmds.setAttr(joint + ".translateZ", 0.0)' in knee_hinge
    assert 'volume_report["knee_y_hinges"] = enforce_studio_knee_y_hinges(' in studio_fit
    assert "def enforce_studio_twist_translate_x(" in placer
    twist_orient = placer.split("def orient_studio_twist_joints_like_parents(", 1)[1].split(
        "def enforce_studio_twist_translate_x(", 1
    )[0]
    assert 'cmds.setAttr(joint + ".jointOrient", 0.0, 0.0, 0.0)' in twist_orient
    assert 'cmds.setAttr(joint + ".rotateAxis", 0.0, 0.0, 0.0)' in twist_orient
    assert "cmds.xform(joint, worldSpace=True, matrix=matrix)" in twist_orient
    assert 'cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0)' in twist_orient
    twist_translate = placer.split("def enforce_studio_twist_translate_x(", 1)[1].split(
        "def unlock_studio_joint_channels(", 1
    )[0]
    assert '"twist" not in lowered' in twist_translate
    assert '"corrective" in lowered' in twist_translate
    assert '"twistcor" in lowered' in twist_translate
    assert 'cmds.setAttr(joint + ".translate", translate_x, 0.0, 0.0)' in twist_translate
    assert "cmds.parent(child, world=True, absolute=True)" in twist_translate
    assert "reparented = cmds.parent(child, joint, absolute=True)" in twist_translate
    assert "enforce_studio_twist_translate_x(root)" in studio_fit
    assert studio_fit.index(
        "orient_studio_arm_chains("
    ) < studio_fit.index("orient_studio_twist_joints_like_parents(root, namespace=namespace)")
    assert studio_fit.index(
        "orient_studio_twist_joints_like_parents(root, namespace=namespace)"
    ) < studio_fit.index(
        "enforce_studio_twist_translate_x(root)"
    )
    assert 'placed_y = float(cmds.getAttr(joint + ".rotateY"))' not in placer
    assert "_studio_knee_hinge_direction(side, namespace)" in leg_orient
    assert "def align_studio_leg_front_projection(" in placer
    assert "_set_joint_world_translation_preserving_children(knee, target)" in placer
    assert "def finalize_studio_spine_neck_head(" in placer
    assert "def enforce_studio_neck2_midpoint(" in placer
    assert 'volume_report["neck2_final_midpoint"] = enforce_studio_neck2_midpoint(' in studio_fit
    assert "mouth_y + (face_span * 0.43)" in placer
    assert "jaw_y = mouth_y + (face_span * 0.56)" in placer
    assert '"head1": 0.25' in placer
    assert '"jaw": 0.28' in placer
    assert 'cmds.setAttr(tip + ".rotate", 0.0, 0.0, 0.0)' in placer
    assert 'volume_report["spine_neck_head_final"] = finalize_studio_spine_neck_head(' in studio_fit
    assert 'volume_report["leg_front_projection"] = align_studio_leg_front_projection(' in studio_fit
    assert 'if bend_axis == "z":' in leg_orient
    assert "_orient_joint_with_world_z_hinge(" in leg_orient
    assert 'elif bend_axis == "y":' in leg_orient
    assert "_move_joint_orientation_to_rotate(joint)" in leg_orient
    assert "capture_studio_template_knee_bend_axes(namespace=namespace)" in studio_fit
    assert "def move_all_studio_joint_orientation_to_rotate(" in placer
    assert "move_all_studio_joint_orientation_to_rotate(" in studio_fit
    assert 'orientation_issues["nonzero_joint_orientation_channels"]' in placer
    assert 'volume_report["final_joint_placement"] = validate_studio_final_joint_placement(' in studio_fit
    assert 'cmds.setAttr(tip + ".rotate", 0.0, 0.0, 0.0)' in placer
    assert '"front_projection": "mesh_centered_leg_plane"' in placer
    assert "def _recenter_along_direction(" in placer
    assert "def _place_along_direction_fraction(" in placer
    assert "2.0 / 3.0" in placer
    assert "(interval[0] + interval[1]) * 0.5" in placer
    assert "solve_reference_joint_roll_vectors(" in placer
    assert "shortest arc from its signed local X" in placer
    assert "smoothing: float = 0.0" in placer
    assert "def fit_studio_thumb_root_depth(" in placer
    assert "dorsal_fraction: float = 0.45" in placer
    assert 'volume_report["thumb_root_depth"] = fit_studio_thumb_root_depth(' in studio_fit
    assert "section_found = _place_along_direction_fraction(" in placer
    assert "_set_joint_world_translation_preserving_children(" in placer
    assert "_project_joint_chain_to_plane(chain)" in placer
    assert 'cmds.setAttr(toe_joint + ".rotate", 0.0, 0.0, signed_angle)' in leg_orient


def test_studio_approved_rerun_preserves_scene_positions() -> None:
    placer = (TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placer.py").read_text(
        encoding="utf-8"
    )
    lip_fit = placer.split("def fit_studio_lip_joints_to_surface(", 1)[1].split(
        "def fit_studio_eyelid_joints_to_surface(", 1
    )[0]
    studio_fit = placer.split("def fit_studio_template_skeleton(", 1)[1].split(
        "def preview_biped_joint_placement(", 1
    )[0]

    assert "elliptical half-arc" in lip_fit
    assert "Equal angular steps give stable spacing" in lip_fit
    assert "lateral_fraction = math.sin(angle)" in lip_fit
    assert "center_weight = math.cos(angle)" in lip_fit
    assert "Always use the outermost +Z shell" in lip_fit
    assert "interval[1] for interval in intervals" in lip_fit
    assert "_set_joint_world_translation_preserving_children(joint, target)" in lip_fit
    assert "if len(placed) != 16:" in lip_fit
    assert "if failed_projection:" in lip_fit
    assert "if max_surface_distance > surface_tolerance:" in lip_fit
    assert '"anchors_preserved"' in lip_fit
    restore_index = studio_fit.index("_restore_studio_joint_world_matrices(")
    lock_index = studio_fit.index('volume_report["approved_positions_locked"]')
    final_restore_index = studio_fit.index(
        'volume_report["approved_positions_final_restore"]'
    )
    assert restore_index < lock_index < final_restore_index
    assert 'volume_report["approved_lip_arc_refit"]' not in studio_fit
    assert 'volume_report["approved_neck2_head1_refit"]' not in studio_fit
    assert 'volume_report["distal_thumb_rest_bend"]' in studio_fit
    assert "if mesh and not approved_rerun:" in studio_fit
    assert '"authored_thumb_rest_bend_preserved"' in placer
    assert "minimum_bend_degrees: float = 4.0" in placer
    assert '"bend_degrees": bend_degrees' in placer
    assert "reference_points, reference_cases = solve_reference_detail_points(mesh)" in placer
    assert 'previous_name = "{0}_thumb_02".format(side)' in placer
    assert 'knuckle_name = "{0}_thumb_03".format(side)' in placer
    assert "namespace=namespace,\n                smoothing=1.0," in studio_fit
    assert "if mesh and not approved_rerun:" in studio_fit
    assert "preserve_positions=approved_rerun" in studio_fit

    build = placer.split("def build_basic_biped_skeleton(", 1)[1].split(
        "def place_joints_from_selected_mesh(", 1
    )[0]
    capture_guard = build.split("approved_world_matrices = None", 1)[1].split(
        "preview = preview_biped_joint_placement(", 1
    )[0]
    assert "is_studio_template_skeleton(" in capture_guard
    assert "_is_generated_joint(existing_root)" not in capture_guard
    # Only a validated fit for the same mesh is approved for position reuse.
    # A template-shaped but unvalidated rig must take the fresh-fit path.
    assert "STUDIO_VOLUME_REPORT_ATTR" in capture_guard
    assert "PLACEMENT_MESH_MESSAGE_ATTR" in capture_guard
    assert "same_mesh" in capture_guard
    assert 'prior_validation.get("post_fit_drift_count") == 0' in capture_guard
    assert 'prior_validation.get("outside_bounds_count") == 0' in capture_guard
    assert 'prior_validation.get("limb_orientation_issues") == 0' in capture_guard
    assert "and preserve_approved_fit" in capture_guard


def test_studio_arm_hand_uses_reference_landmarks_and_centered_tips() -> None:
    placer = (TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placer.py").read_text(
        encoding="utf-8"
    )
    reference_fit = placer.split(
        "def fit_studio_arm_hand_from_reference(", 1
    )[1].split("def _fit_studio_twist_segments(", 1)[0]
    studio_fit = placer.split("def fit_studio_template_skeleton(", 1)[1].split(
        "def preview_biped_joint_placement(", 1
    )[0]

    assert "reference_targets=detail_targets" in studio_fit
    assert '"approved_topology_reference_landmarks"' in reference_fit
    assert '"independent_section_centering": False' in reference_fit
    assert '_set_joint_world_translation(joint, target)' in reference_fit
    assert "depth_centered = []" in reference_fit
    assert "target_y = wrist_y if index == 2 else original[index][1]" in reference_fit
    assert "shared_y" not in reference_fit
    assert '"pose_preserving_mesh_depth_local_z_hinge_plane"' in reference_fit
    assert "refined_arm_points = refine_shoulder_landmarks(arm_points, query)" in reference_fit
    assert "if index > 0:" in reference_fit
    assert "def _find_studio_elbow_section(" in reference_fit
    assert "fraction = 0.40 + (step * (0.22 / 44.0))" in reference_fit
    assert "elbow_section = _find_studio_elbow_section(" in reference_fit
    assert "planar_chain = chain[1:-1]" in placer
    conform_fit = placer.split(
        "def _fit_studio_hand_from_reference(", 1
    )[1].split("def fit_studio_hand_joints(", 1)[0]
    assert 'elif short_name.endswith("_01"):' in conform_fit
    assert 'depth_bias = 0.55' in conform_fit
    assert 'depth_bias = 0.0' in conform_fit
    assert '"mesh_centerline_fitted"' in conform_fit
    assert 'depth_bias = 0.40' not in conform_fit
    assert 'volume_report["arm_hand_reference_volume_conform"]' in studio_fit
    assert 'volume_report["finger_knuckle_height_after_arm_refit"]' in studio_fit
    assert "upper_fraction=2.0 / 3.0" in studio_fit
    knuckle_fit = placer.split(
        "def fit_studio_finger_knuckle_height(", 1
    )[1].split("def fit_studio_arm_red_dot_refinement(", 1)[0]
    assert "joint = chain[1]" in knuckle_fit
    assert "chain[1:-1]" not in knuckle_fit
    restore_index = studio_fit.index("_restore_studio_joint_world_matrices(")
    center_index = studio_fit.index('volume_report["arm_hand_reference_landmarks"]')
    conform_index = studio_fit.index('volume_report["arm_hand_reference_volume_conform"]')
    twist_index = studio_fit.index('volume_report["arm_twists_after_reference_restore"]')
    plane_index = studio_fit.index('volume_report["finger_02_terminal_planarity"]')
    assert restore_index < center_index < conform_index < twist_index < plane_index


def test_studio_joint_placer_never_leaves_transform_channels_locked() -> None:
    placer = (TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placer.py").read_text(
        encoding="utf-8"
    )
    unlock = placer.split("def unlock_studio_joint_channels(", 1)[1].split(
        "def _capture_mapped_twist_fractions(", 1
    )[0]
    assert 'cmds.joint(joint, edit=True, degreeOfFreedom="xyz")' in unlock
    assert "lock=False" in unlock
    assert "keyable=True" in unlock
    assert 'degreeOfFreedom="z"' not in unlock
    assert 'degreeOfFreedom="y"' not in unlock
    assert 'orientation_issues["locked_transform_channels"]' in placer


def test_studio_thumb_02_terminal_uses_unlocked_single_axis_bend_policy() -> None:
    placer = (TOOLS_ROOT / "maya_tools" / "Rigging" / "joint_placer.py").read_text(
        encoding="utf-8"
    )
    bend_policy = placer.split("def configure_studio_bend_axes(", 1)[1].split(
        "def capture_studio_template_knee_bend_axes(", 1
    )[0]
    validator = placer.split("def validate_studio_final_joint_placement(", 1)[1].split(
        "def fit_studio_template_skeleton(", 1
    )[0]

    assert 'minimum_hinge_index = 2 if digit == "thumb" else 3' in bend_policy
    assert '"elbow_z_knee_y_thumb02_terminal_z_digit03_terminal_z"' in bend_policy
    assert 'hinge_joints = chain[1:] if digit == "thumb" else chain[2:]' in validator
    assert 'maximum_offset = first_length * 0.15' in placer
    assert '_set_joint_world_translation_preserving_children(' in placer
    assert 'mesh=mesh,' in placer
    assert "def enforce_studio_thumb_z_only_rotates(" in placer
    assert "Approved thumb pivots can require a multi-axis rest frame" in placer
    assert "cmds.makeIdentity(" in placer
    assert 'r"^(?:l|r)_thumb_0[2-4]$"' in placer
    assert 'volume_report["thumb_z_only_rotates"]' in placer
    assert "validate_fingertip_centering=not approved_rerun" in placer


def test_thumb_rig_has_three_fk_controls_and_bind_safe_rp_ik_with_pv() -> None:
    source = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig_core.py"
    ).read_text(encoding="utf-8")
    finger_rig = source.split("def create_finger_rigs(", 1)[1].split(
        "def mirror_face_joints(", 1
    )[0]

    assert 'if finger == "thumb":' in finger_rig
    assert "fk_chain = thumb_deform_chain[:-1]" in finger_rig
    assert 'sol="ikRPsolver"' in finger_rig
    assert 'rotation=(0.0, 0.0, 0.0)' in finger_rig
    assert "pv_constraint = cmds.poleVectorConstraint(" in finger_rig
    assert '"pv_ctrl": pv_ctrl_info["ctrl"]' in finger_rig
    assert "pole_distance = 5.0" in finger_rig
    assert "dorsal_direction = -om.MVector(*hand_matrix[8:11])" in finger_rig
    assert "if dorsal_direction * world_up < 0.0:" in finger_rig
    assert "if pole_direction * dorsal_direction < 0.0:" in finger_rig
    assert "pole_direction_flipped = True" in finger_rig
    assert 'if pole_direction_flipped and side != "r":' in finger_rig
    assert 'ik_handle + ".twist"' in finger_rig
    assert '"pv_dorsal_aligned": bool(' in finger_rig
    assert 'name=pv_ctrl_info["pad"] + "_space"' in finger_rig
    assert 'driven=pv_ctrl_info["ctrl"]' in finger_rig
    assert "# Align and position the pad in one operation." in finger_rig
    assert "translation=pv_joint_position" in finger_rig
    assert "position_finger_pv_above_knuckle(pv_pad, pv_joint, distance=5.0)" in finger_rig
    assert "offset_pv_pad(pv_pad, side, amount=-5.0)" not in finger_rig
    pv_helper = source.split(
        "def position_finger_pv_above_knuckle(", 1
    )[1].split("\ndef ", 1)[0]
    assert "knuckle_matrix[8:11]" in pv_helper
    assert "om.MVector(0.0, 1.0, 0.0)" in pv_helper
    assert '"ik_chain": ik_chain' in finger_rig
    assert '"ik_handle": ik_handle' in finger_rig
    assert '"ik_ctrl": ik_ctrl_info["ctrl"]' in finger_rig
    assert '"ik_constraints": thumb_ik_constraints' in finger_rig
    assert '"bind_pose_preserved": True' in finger_rig
    assert "maximum_bind_error > 1.0e-5" in finger_rig
    thumb_branch = finger_rig.split('if finger == "thumb":', 1)[1].split(
        "duplicate_source = fk_chain[1:]", 1
    )[0]
    assert "cmds.ikHandle(" in thumb_branch
    assert "cmds.poleVectorConstraint(" in thumb_branch
    assert "maintainOffset=True" in thumb_branch
    assert "cmds.connectAttr(" not in thumb_branch
    assert 'cmds.delete(fk_ctrls[index]["pad"])' not in thumb_branch


def test_maya_dynamic_rig_modules_are_registered_and_rebuilt_before_extensions() -> None:
    create_rig = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig.py"
    ).read_text(encoding="utf-8")
    hik_ui = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"
    ).read_text(encoding="utf-8")

    assert 'DYNAMIC_MODULES_ATTR = "dynamicRigModules"' in create_rig
    assert "def register_dynamic_rig_module(" in create_rig
    assert "def remove_dynamic_rig_modules_for_rebuild(" in create_rig
    assert "def rebuild_dynamic_rig_modules(" in create_rig
    assert 'module_type in ("arm", "leg")' in create_rig
    assert 'module_type == "surface_rig"' in create_rig
    assert 'module_type == "controls"' in create_rig

    removal = create_rig.split("def remove_full_rig(", 1)[1].split(
        '@undoable("Build Full Rig")', 1
    )[0]
    assert removal.index("preserve_post_build_extensions()") < removal.index(
        "remove_dynamic_rig_modules_for_rebuild()"
    )

    full_build = create_rig.split("def create_full_rig(", 1)[1].split(
        "def set_all_limb_ik_fk_switches(", 1
    )[0]
    assert full_build.index("rebuild_dynamic_rig_modules()") < full_build.index(
        "record_rig_owned_nodes()"
    ) < full_build.index("restore_post_build_extensions()")

    assert 'QGroupBox("Additional Arm / Leg Module")' in hik_ui
    assert 'QPushButton("Add Arm Module")' in hik_ui
    assert 'QPushButton("Add Leg Module")' in hik_ui
    assert "def create_additional_limb_module(self, module_type):" in hik_ui
    assert 'register_dynamic_rig_module(\n                module_id, "controls"' in hik_ui
    assert 'register_dynamic_rig_module(\n                module_id, "surface_rig"' in hik_ui


def test_maya_limb_and_spine_stretch_have_independent_volume_blend() -> None:
    source = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig_core.py"
    ).read_text(encoding="utf-8")
    helper = source.split("def _create_volume_stretch_network(", 1)[1].split(
        "def _joint_segment_axis(", 1
    )[0]
    spine = source.split("def setup_spine_segment_stretch(", 1)[1].split(
        "def _drive_stretch_segments(", 1
    )[0]
    limb = source.split("def setup_ik_limb_stretch(", 1)[1].split(
        "def create_ik_fk_limb(", 1
    )[0]

    assert 'niceName="Volume Stretch" if attr_name == "volumeStretch"' in source
    assert 'cmds.setAttr(f"{power}.input2X", -0.5)' in helper
    assert 'cmds.setAttr(f"{blend}.color2R", 1.0)' in helper
    assert 'if axis != length_axis.upper()' in helper
    assert '_ensure_stretch_attr(pelvis_ctrl, "volumeStretch")' in spine
    assert '_create_volume_stretch_network(' in spine
    assert '_ensure_stretch_attr(switch_ctrl, "volumeStretch")' in limb
    assert 'for index, driven_joint in enumerate(ik_joints[:2]):' in limb
    assert '"volume_attr": volume_attr' in spine
    assert '"volume_attr": volume_attr' in limb


def test_maya_preserved_extensions_do_not_claim_nose_or_body_slots() -> None:
    create_rig = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig.py"
    ).read_text(encoding="utf-8")
    hik_ui = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"
    ).read_text(encoding="utf-8")

    assert 'BUILDER_OWNED_CONTROL_ROOTS = (' in create_rig
    assert '"nose_root_ctrl_pad"' in create_rig
    assert "def repair_preserved_extension_body_mapping(" in create_rig
    repair = create_rig.split(
        "def repair_preserved_extension_body_mapping(", 1
    )[1].split("def _metadata_rig_ownership(", 1)[0]
    assert '"Neck": ("Neck", 0)' in repair
    assert '"Head": ("Head", 0)' in repair
    assert "extension_stems.add(_extension_base_name(node))" in repair
    assert "repair_preserved_extension_body_mapping(body_joint_map)" in create_rig
    assert "create_rig.repair_preserved_extension_body_mapping(" in hik_ui
    assert "linked_external_nodes" not in create_rig


def test_maya_additional_rig_systems_are_visible_in_module_setup() -> None:
    create_rig = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig.py"
    ).read_text(encoding="utf-8")
    hik_ui = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"
    ).read_text(encoding="utf-8")

    assert "def get_external_rig_systems(" in create_rig
    assert "def _is_builder_owned_extension_root(" in create_rig
    assert "def _normalize_extension_manifest_state(" in create_rig
    assert "def inspect_external_rig_system(" in create_rig
    assert "def inspect_dynamic_rig_module(" in create_rig
    assert "def set_external_rig_system_active(" in create_rig
    assert "def set_dynamic_rig_module_active(" in create_rig
    assert '"nose_root_ctrl_pad"' in create_rig
    assert 'QLabel("<b>Additional Rig Systems</b>")' in hik_ui
    assert "def _refresh_additional_systems(self):" in hik_ui
    assert "create_rig.get_dynamic_rig_modules()" in hik_ui
    assert "create_rig.get_external_rig_systems(discover_live=True)" in hik_ui
    assert "def _set_additional_system_active(" in hik_ui
    assert 'QtWidgets.QPushButton("Add")' in hik_ui
    assert 'QtWidgets.QPushButton("Remove")' in hik_ui
    assert "Constraints ({})" in hik_ui
    assert "Connections ({})" in hik_ui
    refresh = hik_ui.split("def _refresh_all_module_details(self):", 1)[1].split(
        "def _get_registered_module_ids(self):", 1
    )[0]
    assert "self._refresh_additional_systems()" in refresh


def test_maya_eyelid_removal_does_not_claim_shared_eye_aim_controls() -> None:
    create_rig = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig.py"
    ).read_text(encoding="utf-8")

    eyelid_build = create_rig.split("def rig_eyelids_module(", 1)[1].split(
        "def get_ordered_hierarchy(", 1
    )[0]
    eyelid_remove = create_rig.split("def remove_eyelids_module(", 1)[1].split(
        "def rig_mouth_module(", 1
    )[0]
    prefix_branch = create_rig.split(
        'elif module_id in ("Eyelids (Left)", "Eyelids (Right)"):', 1
    )[1].split('elif module_id == "Mouth & Lips":', 1)[0]

    assert "before_uuids = _scene_node_uuids()" in eyelid_build
    assert '"cleanup_nodes": generated_names' in eyelid_build
    assert '"exact_ownership": True' in eyelid_build
    assert 'f"{side}_eye_ctrl_pad"' in eyelid_remove
    assert 'load_module_metadata("Eyes Aim")' in eyelid_remove
    assert "protected_nodes=shared_eye_nodes" in eyelid_remove
    assert "prefer_fallback=not bool(" in eyelid_remove
    assert "fallback_controls=safe_controls" in eyelid_remove
    assert 'f"{side}_eye_ctrl_pad_static"' in eyelid_remove
    assert 'f"{side}_eye",' not in prefix_branch

    eyes_build = create_rig.split("def rig_eyes_module(", 1)[1].split(
        "def remove_eyes_module(", 1
    )[0]
    assert "before_uuids = _scene_node_uuids()" in eyes_build
    assert '"exact_ownership": True' in eyes_build


def test_maya_hik_ui_has_fast_tabs_and_dedicated_skinning_tab() -> None:
    hik_ui = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"
    ).read_text(encoding="utf-8")

    init = hik_ui.split("class HIKDefinitionUI", 1)[1].split(
        "def _notify_operation", 1
    )[0]
    assert init.index("self._build_rigging_tab()") < init.index(
        "self._build_skinning_tab()"
    ) < init.index("self._build_vehicle_tab()")
    assert "def _build_skinning_tab(self):" in hik_ui
    skinning_tab = hik_ui.split("def _build_skinning_tab(self):", 1)[1].split(
        "def _build_vehicle_tab(self):", 1
    )[0]
    assert 'self.tabs.addTab(scroll_area, "Skinning")' in skinning_tab
    assert "self.rig_layout.removeWidget(self.skin_group)" in skinning_tab
    tab_changed = hik_ui.split("def _on_tab_changed(self, index):", 1)[1].split(
        "def _load_module_metadata_from_scene", 1
    )[0]
    assert "_refresh_all_module_details" not in tab_changed


def test_rigging_tool_has_confirmed_unreal_skeletal_mesh_deployment() -> None:
    hik_ui = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"
    ).read_text(encoding="utf-8")
    maya_export = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "unreal_skeletal_export.py"
    ).read_text(encoding="utf-8")
    unreal_import = (
        TOOLS_ROOT / "unreal_tools" / "skeletal_mesh_import.py"
    ).read_text(encoding="utf-8")
    subprocess_adapter = (
        TOOLS_ROOT / "unreal_tools" / "unreal_subprocess.py"
    ).read_text(encoding="utf-8")

    compile(maya_export, "maya_tools/Rigging/unreal_skeletal_export.py", "exec")
    compile(unreal_import, "unreal_tools/skeletal_mesh_import.py", "exec")
    assert 'self.tabs.addTab(scroll_area, "Mesh")' in hik_ui
    assert 'QGroupBox("Maya Mesh Export Set")' in hik_ui
    assert 'QGroupBox("Unreal Skeletal Mesh Definition")' in hik_ui
    assert "def send_skeletal_mesh_to_unreal(self):" in hik_ui
    assert "Remove Rig, Export Defined Meshes && Import to Unreal" in hik_ui
    assert "def remove_rig_restore_bind_pose_and_export(" in maya_export
    assert 'f"{mesh_asset_name}.fbx"' in maya_export
    assert 'mesh_asset_name = f"SKM_{name}"' in maya_export
    assert "cmds.dagPose" in maya_export
    assert "create_rig.remove_full_rig" in maya_export
    assert "def list_skeletal_import_targets(" in unreal_import
    assert "def import_skeletal_mesh_fbx(" in unreal_import
    assert 'mode not in {"create_new", "use_existing"}' in unreal_import
    assert 'mesh_name = f"SKM_{name}"' in unreal_import
    assert "def character_asset_folder(" in unreal_import
    assert "EditorAssetLibrary.make_directory(destination_path)" in unreal_import
    assert 'f"{destination_path}/SK_{name}"' in unreal_import
    assert 'f"{destination_path}/PHYS_{name}"' in unreal_import
    assert "def run_list_skeletal_import_targets(" in subprocess_adapter
    assert "def run_import_skeletal_mesh_fbx(" in subprocess_adapter
    assert '"Overwrite Existing: "' in hik_ui
    assert "def refresh_mesh_export_scene_meshes(" in hik_ui
    assert "meshes = unreal_skeletal_export.list_skinned_meshes()" in hik_ui
    assert "def refresh_mesh_export_unreal_assets(" in hik_ui
    assert "def _mesh_export_settings(" in hik_ui
    assert 'form.addRow("New Asset Parent Folder:"' in hik_ui
    assert "def _mesh_export_character_folder(" in hik_ui
    assert 'meshes=settings["meshes"]' in hik_ui
    assert "def list_skinned_meshes()" in maya_export
    assert 'existing_mesh_path.rstrip("/").rsplit("/", 1)[-1]' in hik_ui
