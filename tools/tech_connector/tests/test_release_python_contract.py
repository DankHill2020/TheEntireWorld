import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory

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
    )
    for tier in manifest["tiers"].values():
        excludes = tier["exclude"]
        assert all(matches_any(path, excludes) for path in generated_paths)


def test_staging_skips_generated_state_but_keeps_source() -> None:
    excludes = [
        "**/.ai_studio",
        "**/.tech_connector",
        "**/*.pyc",
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
        (source / "services" / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
        (source / ".ai_studio" / "request.log").write_text("generated", encoding="utf-8")
        (source / "game_engine" / "native" / ".tech_connector" / "build.ninja").write_text(
            "generated", encoding="utf-8"
        )
        (source / "project_analysis" / "project_analysis.db").write_bytes(b"generated")
        (source / "services" / "__pycache__" / "runtime.pyc").write_bytes(b"generated")

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


def test_full_tools_stage_uses_canonical_maya_and_blender_rig_implementations(tmp_path) -> None:
    staged = stage_package("full-tools", tmp_path)
    rig_files = (
        Path("blender_tools/Rigging/__init__.py"),
        Path("blender_tools/Rigging/rigging_host_adapter.py"),
        Path("maya_tools/Rigging/create_rig.py"),
        Path("maya_tools/Rigging/create_rig_core.py"),
        Path("maya_tools/Rigging/rigging_host_adapter.py"),
        Path("maya_tools/Rigging/mocap/hik_ui.py"),
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
    assert '"c_upper_lip_main_ctrl"' in source
    assert '"c_lower_lip_main_ctrl"' in source
    assert '"lip_main_ctrl"' in source
    assert 'def _op_rig_create_ribbon(' in source
    assert '"SPLINE_IK"' in source
    assert 'hook.vertex_indices_set' in source
    assert 'constraint.forward_axis = "FORWARD_Y"' in source
    assert 'constraint.up_axis = "UP_Z"' in source


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

    assert 'get("main_ctrl", "lip_main_ctrl")' in create_rig
    assert '"main_ctrl": main_ctrl' in create_rig_core
    assert 'legacy_snap_nodes = {"l_brow_main", "r_brow_main", "lip_main"}' in create_rig
    assert 'cmds.delete(brow_main_transform)' in create_rig
    assert 'cmds.delete(temp_grp)' in create_rig_core
    assert "def _bind_surface_to_joints(" in create_rig_core
    assert "*(list(influences) + [bind_surface])" in create_rig_core
    assert "skin, surface = _bind_surface_to_joints(" in create_rig_core
    assert create_rig_core.count("cmds.parent(fol_joint, fol_tr, absolute=True)") == 2
    assert "# turn remain constrained to the original bind joint." in create_rig_core
    assert "def _ensure_distance_nodes_group():" in create_rig_core
    assert 'name="distance_nodes", parent=dnt' in create_rig_core
    assert 'cmds.ls(type="distanceDimShape", long=True)' in create_rig_core
    assert 'name=f"{token}_dim", parent=distance_group' in create_rig_core
    assert 'RIG_BUILD_REVISION = "rig-centered-curve-frame-v15"' in create_rig_core
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
    assert "resolved_nodes = cmds.ls(related_node, long=True)" in create_rig
    assert "node_type = cmds.nodeType(resolved)" in create_rig


def test_maya_hik_ui_reloads_rig_core_before_the_public_builder() -> None:
    hik_ui = (TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py").read_text(encoding="utf-8")

    reload_core = hik_ui.index("create_rig_core,")
    reload_builder = hik_ui.index("importlib.reload(create_rig)")
    assert reload_core < reload_builder
    assert "Rig source:" in hik_ui
    assert "RIG_BUILD_REVISION" in hik_ui
    assert "owns_undo_chunk = not silent" in hik_ui
    assert "Full Rig build failed and was rolled back" in hik_ui


def test_maya_surface_smooth_brush_uses_viewport_overlay_and_direct_strokes() -> None:
    source = (TOOLS_ROOT / "maya_tools" / "Rigging" / "skinning_utils.py").read_text(encoding="utf-8")

    assert "class _SurfaceSmoothBrushOverlay(QtWidgets.QWidget):" in source
    assert "def _update_overlay(self, hit_data, view, panel, widget):" in source
    assert "def begin_viewport_stroke(self):" in source
    assert "def continue_viewport_stroke(self):" in source
    assert "def finish_viewport_stroke(self):" in source
    assert "QtCore.QEvent.MouseButtonPress" in source
    assert "brush.resize_from_pixels" in source
