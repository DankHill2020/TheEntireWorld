"""Build the bundled joint-only Maya vehicle placement template.

Run this file with Maya's ``mayapy``. Controls, geometry, ground detection,
constraints, and solver nodes belong to the vehicle rig builder, not here.
"""

from __future__ import annotations

import json
from pathlib import Path

import maya.cmds as cmds
import maya.standalone


SCHEMA = "tech_connector.vehicle_rig.v1"
TEMPLATE_VERSION = 1
OUTPUT_PATH = Path(__file__).resolve().parent / "templates" / "vehicle_rig_template.ma"


WHEELS = (
    ("front_left", -80.0, 120.0, "front", True, False),
    ("front_right", 80.0, 120.0, "front", True, False),
    ("rear_left", -80.0, -120.0, "rear", False, True),
    ("rear_right", 80.0, -120.0, "rear", False, True),
)


def _string_attr(node: str, name: str, value: str) -> None:
    cmds.addAttr(node, longName=name, dataType="string")
    cmds.setAttr("{}.{}".format(node, name), value, type="string")


def _double_attr(node: str, name: str, value: float, *, minimum: float = 0.0) -> None:
    cmds.addAttr(node, longName=name, attributeType="double", minValue=minimum, keyable=True)
    cmds.setAttr("{}.{}".format(node, name), float(value))


def _bool_attr(node: str, name: str, value: bool) -> None:
    cmds.addAttr(node, longName=name, attributeType="bool", keyable=True)
    cmds.setAttr("{}.{}".format(node, name), bool(value))


def _role(node: str, value: str) -> None:
    _string_attr(node, "tcVehicleRole", value)


def build(output_path: Path = OUTPUT_PATH) -> Path:
    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm", angle="deg", time="film")
    cmds.upAxis(axis="y", rotateView=True)

    cmds.select(clear=True)
    vehicle_root = cmds.joint(name="vehicle_root_JNT", position=(0.0, 0.0, 0.0), radius=8.0)
    _role(vehicle_root, "root")
    _string_attr(vehicle_root, "tcVehicleSchema", SCHEMA)
    cmds.addAttr(vehicle_root, longName="tcTemplateVersion", attributeType="long")
    cmds.setAttr(vehicle_root + ".tcTemplateVersion", TEMPLATE_VERSION)
    _string_attr(vehicle_root, "tcUpAxis", "Y")
    _string_attr(vehicle_root, "tcForwardAxis", "Z")
    _string_attr(vehicle_root, "tcRightAxis", "X")
    _string_attr(vehicle_root, "tcSceneLinearUnit", "centimeter")
    _string_attr(vehicle_root, "tcPortableLinearUnit", "meter")
    _string_attr(vehicle_root, "tcGroundQuery", "raycast")
    _string_attr(vehicle_root, "tcTransferPolicy", "reconstruct_live_solver_or_bake_animation")

    cmds.select(vehicle_root)
    chassis = cmds.joint(name="vehicle_chassis_JNT", position=(0.0, 65.0, 0.0), radius=7.0)
    _role(chassis, "chassis")
    _double_attr(chassis, "tcMassKg", 1350.0)
    _double_attr(chassis, "tcMaximumSteerAngleDeg", 32.0)
    _double_attr(chassis, "tcEngineForceN", 8500.0)
    _double_attr(chassis, "tcAerodynamicDrag", 0.34)
    _double_attr(chassis, "tcRollingResistance", 0.015)
    _double_attr(chassis, "tcAntiRollStiffness", 7500.0)
    for axis, value in zip("XYZ", (0.0, -0.35, 0.0)):
        cmds.addAttr(chassis, longName="tcCenterOfMassOffset{}M".format(axis), attributeType="double", keyable=True)
        cmds.setAttr("{}.tcCenterOfMassOffset{}M".format(chassis, axis), value)

    wheel_contract = []
    for wheel_id, x, z, axle, steerable, driven in WHEELS:
        cmds.select(chassis)
        mount = cmds.joint(name="{}_mount_JNT".format(wheel_id), position=(x, 70.0, z), radius=4.0)
        _role(mount, "wheel_mount")
        _string_attr(mount, "tcWheelId", wheel_id)
        _string_attr(mount, "tcAxle", axle)
        _string_attr(mount, "tcCollisionMask", "world_static")
        _double_attr(mount, "tcRadiusM", 0.34)
        _double_attr(mount, "tcSuspensionRestLengthM", 0.36)
        _double_attr(mount, "tcSuspensionTravelM", 0.18)
        _double_attr(mount, "tcSpringStiffness", 32000.0)
        _double_attr(mount, "tcSpringDamping", 4200.0)
        _double_attr(mount, "tcBrakeTorqueNm", 1800.0)
        _bool_attr(mount, "tcSteerable", steerable)
        _bool_attr(mount, "tcDriven", driven)
        _bool_attr(mount, "tcBraked", True)

        cmds.select(mount)
        wheel = cmds.joint(name="{}_wheel_JNT".format(wheel_id), position=(x, 34.0, z), radius=5.0)
        _role(wheel, "wheel")
        _string_attr(wheel, "tcWheelId", wheel_id)

        cmds.select(wheel)
        contact = cmds.joint(name="{}_contact_JNT".format(wheel_id), position=(x, 0.0, z), radius=2.0)
        _role(contact, "ground_contact")
        _string_attr(contact, "tcWheelId", wheel_id)

        wheel_contract.append({
            "id": wheel_id,
            "mount_joint": mount,
            "wheel_joint": wheel,
            "contact_joint": contact,
            "mount_m": [x / 100.0, 0.05, z / 100.0],
            "radius_m": 0.34,
            "suspension_rest_length_m": 0.36,
            "suspension_travel_m": 0.18,
            "axle": axle,
            "steerable": steerable,
            "driven": driven,
            "braked": True,
        })

    _string_attr(vehicle_root, "tcVehicleDefinition", json.dumps({
        "schema": SCHEMA,
        "version": TEMPLATE_VERSION,
        "coordinate_system": {"up": "Y", "forward": "Z", "right": "X", "unit": "meter"},
        "root_joint": vehicle_root,
        "chassis_joint": chassis,
        "wheels": wheel_contract,
    }, sort_keys=True, separators=(",", ":")))

    cmds.select(vehicle_root, replace=True)
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmds.file(rename=str(output_path))
    cmds.file(save=True, type="mayaAscii", force=True)
    return output_path


if __name__ == "__main__":
    maya.standalone.initialize(name="python")
    try:
        print(build())
    finally:
        maya.standalone.uninitialize()
