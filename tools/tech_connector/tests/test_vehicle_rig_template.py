from __future__ import annotations

import json
from pathlib import Path
import re


TOOLS_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = TOOLS_ROOT / "maya_tools" / "Rigging" / "templates" / "vehicle_rig_template.ma"
RIG = TOOLS_ROOT / "maya_tools" / "Rigging" / "templates" / "vehicle_rig.ma"
DEMO = TOOLS_ROOT / "maya_tools" / "Rigging" / "templates" / "vehicle_rig_demo.ma"


def test_bundled_vehicle_template_has_portable_contract_and_four_wheels() -> None:
    assert TEMPLATE.is_file()
    source = TEMPLATE.read_text(encoding="utf-8", errors="replace")

    assert source.startswith("//Maya ASCII 2023 scene")
    assert '"tech_connector.vehicle_rig.v1"' in source
    assert '"vehicle_root_JNT"' in source
    assert '"vehicle_chassis_JNT"' in source
    for wheel_id in ("front_left", "front_right", "rear_left", "rear_right"):
        assert '"{}_mount_JNT"'.format(wheel_id) in source
        assert '"{}_wheel_JNT"'.format(wheel_id) in source
        assert '"{}_contact_JNT"'.format(wheel_id) in source
    assert source.count("createNode joint ") == 14
    assert "vehicle_global_CTRL" not in source
    assert "preview_GEO" not in source
    assert "groundRay_GUIDE" not in source
    assert "createNode network" not in source


def test_embedded_vehicle_definition_is_json_and_uses_si_units() -> None:
    source = TEMPLATE.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r'setAttr "\.tcVehicleDefinition" -type "string"\s*\(\s*"((?:\\.|[^"\\])*)"\);',
        source,
        re.DOTALL,
    )
    assert match, "vehicle template is missing its embedded portable definition"
    maya_string = match.group(1).replace(r'\"', '"').replace(r'\\', '\\')
    definition = json.loads(maya_string)

    assert definition["schema"] == "tech_connector.vehicle_rig.v1"
    assert definition["coordinate_system"] == {
        "forward": "Z", "right": "X", "unit": "meter", "up": "Y",
    }
    assert len(definition["wheels"]) == 4
    assert {wheel["id"] for wheel in definition["wheels"]} == {
        "front_left", "front_right", "rear_left", "rear_right",
    }
    assert all(wheel["radius_m"] > 0.0 for wheel in definition["wheels"])
    by_id = {wheel["id"]: wheel for wheel in definition["wheels"]}
    assert by_id["front_left"]["mount_m"][0] < 0.0
    assert by_id["front_right"]["mount_m"][0] > 0.0


def test_vehicle_template_loader_is_exposed_alongside_biped_loader() -> None:
    source = (TOOLS_ROOT / "maya_tools" / "Rigging" / "rig_template.py").read_text(encoding="utf-8")
    assert "DEFAULT_VEHICLE_RIG_TEMPLATE" in source
    assert "def load_vehicle_rig_template(" in source
    assert "def load_default_vehicle_rig_template(" in source


def test_bundled_vehicle_rig_contains_controls_solver_and_ground_contract() -> None:
    assert RIG.is_file()
    source = RIG.read_text(encoding="utf-8", errors="replace")
    assert source.startswith("//Maya ASCII 2023 scene")
    assert '"tech_connector.vehicle_rig.maya.v1"' in source
    assert '"vehicle_global_CTRL"' in source
    assert '"vehicle_chassis_CTRL"' in source
    assert '"front_left_suspension_DRV"' in source
    assert '"front_left_wheel_CTRL"' in source
    assert '"vehicle_ground_GEO"' in source
    assert '"tcGroundMeshes"' in source
    assert '"tcWheelRigMap"' in source
    assert '"autoWheelSpin"' in source
    assert '"wheelRollMultiplier"' in source
    assert '"ackermann"' in source
    assert '"autoSteering"' in source
    assert '"autoSteerBlend"' in source
    assert '"autoSteerAngle"' in source
    assert '"steeringDrivesMotion"' in source
    assert '"minimumGroundNormal"' in source
    assert '"front_left_groundRay_DBG"' in source


def test_bundled_vehicle_demo_has_baked_roll_and_suspension() -> None:
    assert DEMO.is_file()
    source = DEMO.read_text(encoding="utf-8", errors="replace")
    assert '"vehicle_demo_ground_GEO"' in source
    assert '"front_left_spin_DRV_rotateX"' in source
    assert '"front_left_suspension_DRV_translateY"' in source
    assert '"vehicle_global_CTRL_translateX"' in source
    assert '"vehicle_global_CTRL_rotateY"' in source
    assert "createNode animCurveTA" in source
    assert "createNode animCurveTL" in source


def test_vehicle_rigging_ui_exposes_complete_vehicle_workflow() -> None:
    source = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"
    ).read_text(encoding="utf-8")
    for function_name in (
        "_build_vehicle_tab", "load_vehicle_joint_template",
        "build_vehicle_rig_from_template", "assign_vehicle_ground",
        "update_vehicle_ground", "enable_vehicle_live_ground",
        "reset_vehicle_wheel_roll", "set_vehicle_auto_steering",
        "set_vehicle_steering_drive",
        "bake_vehicle_ground", "save_vehicle_rig_file",
    ):
        assert "def {}(".format(function_name) in source
    assert 'self.tabs.addTab(vehicle_tab, "Vehicle")' in source
    assert "Automatic steering from chassis yaw and path curvature" in source
    assert "Steering drives forward/reverse vehicle path" in source


def test_vehicle_live_evaluation_uses_native_callbacks_and_ui_heartbeat() -> None:
    rig_source = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "vehicle_rig.py"
    ).read_text(encoding="utf-8")
    ui_source = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"
    ).read_text(encoding="utf-8")
    menu_source = (
        TOOLS_ROOT / "maya_tools" / "maya_menu.py"
    ).read_text(encoding="utf-8")

    assert "MNodeMessage.addAttributeChangedCallback" in rig_source
    assert 'MEventMessage.addEventCallback("timeChanged"' in rig_source
    assert "MSceneMessage.kAfterOpen" in rig_source
    assert "def update_registered_live_rigs(" in rig_source
    assert "QtCore.QTimer(self)" in ui_source
    assert "setInterval(16)" in ui_source
    assert "vehicle_rig.install_scene_callbacks()" in menu_source


def test_vehicle_forward_roll_uses_maya_positive_x_rotation_convention() -> None:
    source = (
        TOOLS_ROOT / "maya_tools" / "Rigging" / "vehicle_rig.py"
    ).read_text(encoding="utf-8")
    assert "auto_spin += (signed_distance / radius)" in source
    assert "auto_spin += -(signed_distance / radius)" not in source
    assert "suspension_length = maximum_suspension_length" in source
    assert "def _automatic_steer_angle(" in source
    assert "math.atan(wheelbase * yaw_radians / signed_distance)" in source
    assert "def _apply_bicycle_motion(" in source
    assert "math.tan(math.radians(steering_degrees)) / wheelbase" in source
    assert "compressed_center = mount_position + down * minimum_suspension_length" in source
    assert "distance - radius / normal_alignment" in source

