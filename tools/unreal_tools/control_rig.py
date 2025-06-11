import unreal
import re
import os

def create_control_rig_from_asset(asset_path):
    asset = unreal.load_asset(asset_path)

    if not asset or not isinstance(asset, (unreal.SkeletalMesh, unreal.Skeleton)):
        raise RuntimeError("Asset must be a SkeletalMesh or Skeleton.")

    control_rig_bp = unreal.ControlRigBlueprintFactory.create_control_rig_from_skeletal_mesh_or_skeleton(asset, modular_rig=True)

    if not control_rig_bp:
        raise RuntimeError("Failed to create Control Rig Blueprint.")

    print(f"Created Control Rig at: {control_rig_bp.get_path_name()}")
    return control_rig_bp.get_path_name()


def add_parent_constraint_node(
    control_rig_bp,
    graph: unreal.RigVMGraph,
    child_name: str,
    parent_name: str,
    child_type=unreal.RigElementType.BONE,
    parent_type=unreal.RigElementType.CONTROL,
    maintain_offset=True,
    weight=1.0,
    translation=True,
    rotation=True,
    scale=False,
    node_position=unreal.Vector2D(0.0, 0.0),
    node_name="ParentConstraintNode",
    input_node=None
):
    controller = control_rig_bp.get_controller(graph)
    parent_constraint_struct = unreal.RigUnit_ParentConstraint.static_struct()

    unit_node = controller.add_unit_node(
        script_struct=parent_constraint_struct,
        method_name="Execute",
        position=node_position,
        node_name=node_name
    )
    unit_name = unit_node.get_name()

    # Set up child
    child_key = f"(Type={child_type.name},Name={child_name})"
    controller.set_pin_default_value(f"{unit_name}.Child", child_key)

    controller.set_array_pin_size(f"{unit_name}.Parents", 1)
    controller.set_pin_default_value(f"{unit_name}.Parents.0.Weight", str(weight))

    controller.set_pin_default_value(f"{unit_name}.Parents.0.Item.Name", parent_name)
    controller.set_pin_default_value(f"{unit_name}.Parents.0.Item.Type", parent_type.name)

    controller.set_pin_default_value(f"{unit_name}.bMaintainOffset", str(maintain_offset).lower())
    controller.set_pin_default_value(f"{unit_name}.Weight", str(weight))

    controller.set_pin_default_value(f"{unit_name}.Filter.TranslationFilter", str(translation).lower())
    controller.set_pin_default_value(f"{unit_name}.Filter.RotationFilter", str(rotation).lower())
    controller.set_pin_default_value(f"{unit_name}.Filter.ScaleFilter", str(scale).lower())

    connect_to_forward_solve(controller, graph, unit_node, forward_entry_node=input_node)

    return unit_node



def connect_to_forward_solve(controller, graph, unit_node, forward_entry_node=None):
    """

    :param controller:
    :param graph:
    :param unit_node:
    :param forward_entry_node:
    :return:
    """
    if not forward_entry_node:
        for node in graph.get_nodes():
            if isinstance(node, unreal.RigVMUnitNode) and node.get_node_title().lower() == "forwardsolve":
                forward_entry_node = node
                break

    if not forward_entry_node:
        begin_exec_struct = unreal.RigUnit_BeginExecution.static_struct()
        forward_entry_node = controller.add_unit_node(
            script_struct=begin_exec_struct,
            method_name="Execute",
            position=unreal.Vector2D(-400, 0),
            node_name="ForwardSolve"
        )

    forward_exec_pin = forward_entry_node.find_pin("ExecuteContext")
    if not forward_exec_pin:
        raise RuntimeError("Could not find 'ExecuteContext' output pin on ForwardSolve node.")

    target_exec_pin = unit_node.find_pin("ExecuteContext")

    if not target_exec_pin:
        print(f"[Info] Node '{unit_node.get_node_title()}' has no 'ExecuteContext' pin. Skipping connection.")
        return

    controller.add_link(
        output_pin_path=forward_exec_pin.get_pin_path(),
        input_pin_path=target_exec_pin.get_pin_path()
    )

    print(f"Connected ForwardSolve to {unit_node.get_node_title()}")
    return unit_node


def get_bone_hierarchy(skeletal_mesh_path):
    """

    :param skeletal_mesh_path: Path to skeletal mesh being used
    :return:
    """
    skeletal_mesh = unreal.load_asset(skeletal_mesh_path)
    skeleton = skeletal_mesh.get_editor_property("skeleton")
    ref_pose = skeleton.get_reference_pose()

    modifier = unreal.SkeletonModifier()
    modifier.set_skeletal_mesh(skeletal_mesh)

    bone_names = ref_pose.get_bone_names()
    hierarchy = {}  # Parent -> list of children

    for bone in bone_names:
        hierarchy[bone] = []

    for bone in bone_names:
        parent = modifier.get_parent_name(bone)
        if parent in hierarchy:
            hierarchy[parent].append(bone)

    return hierarchy


def get_finger_joints(joint_map, finger_name, side="Left"):
    """

    :param joint_map: mapping from HIK UI (maya_tools/Rigging/mocap)
    :param finger_name:
    :param side:
    :return:
    """
    joints = []

    for key, value in joint_map.items():
        if f'{side}InHand{finger_name}' in key or f'{side}Hand{finger_name}' in key:
            joints.append((key, value[0]))

    def sort_key(item):
        key = item[0]
        if 'InHand' in key:
            return -1
        match = re.search(r'(\d+)$', key)
        return int(match.group(1)) if match else 999

    joints.sort(key=sort_key)
    return [j[1] for j in joints]


def build_spine_module(controller, spine_joints):
    """

    :param controller: control_rig_bp.get_modular_rig_controller()
    :param spine_joints:
    :return:
    """
    module_path = "/ControlRigModules/Modules56/Spine.Spine_C"
    module_asset = unreal.load_asset(module_path)

    # Add the spine module to the rig
    module_name = "Spine"
    controller.add_module(module_name, module_asset, "Base")

    connectors = controller.get_connectors_for_module(module_name)
    primary = next(c for c in connectors if str(c.name).endswith("Spine Primary"))
    target_elem = unreal.RigElementKey(
        unreal.RigElementType.SOCKET,
        unreal.Name(f"Base/{spine_joints[1]}_socket")
    )
    # Add the socket as target to the spine primary array connector
    controller.add_target_to_array_connector(
        connector_key=primary,
        target_key=target_elem,
        setup_undo=True,
    )
    connections = {
        "Spine/Spine End Bone": spine_joints[-1],
    }

    for connector_key in connectors:
        key_str = str(connector_key.name)

        if key_str in connections:
            target_bone_name = connections[key_str]
            target_key = unreal.RigElementKey(unreal.RigElementType.BONE, unreal.Name(target_bone_name))

            success = controller.connect_connector_to_element(
                connector_key, target_key, setup_undo=True
            )
            print(f"Connected {key_str} → {target_bone_name}: {success}")


def build_leg_modules(controller, leg_joints, spine_joints):
    """

    :param controller: control_rig_bp.get_modular_rig_controller()
    :param leg_joints:
    :param spine_joints:
    :return:
    """
    module_path = "/ControlRigModules/Modules56/Leg.Leg_C"
    l_asset = unreal.load_asset(module_path)
    controller.add_module("Leg_L", l_asset, "Spine")
    r_asset = unreal.load_asset(module_path)
    controller.add_module("Leg_R", r_asset, "Spine")
    index = 0
    for side in ["L", "R"]:
        if side == "R":
            index+=3
        else:
            index=0
        module_name = "Leg_" + side
        connectors = controller.get_connectors_for_module(module_name)
        primary = next(c for c in connectors if str(c.name).endswith("Leg Primary"))
        target_elem = unreal.RigElementKey(
            unreal.RigElementType.SOCKET,
            unreal.Name(f"Spine/thigh_{side.lower()}_socket")
        )

        # Add the socket as target to the spine primary array connector
        controller.add_target_to_array_connector(
            connector_key=primary,
            target_key=target_elem,
            setup_undo=True,
            auto_resolve_other_connectors=True,
        )

        connections = {
            module_name + "/Pelvis Bone": spine_joints[0],
            module_name + "/Thigh Bone": leg_joints[index],
            module_name + "/Foot Bone": leg_joints[index+1],
            module_name + "/Knee Bone": leg_joints[index+2]
        }
        for connector_key in connectors:
            key_str = str(connector_key.name)

            if key_str in connections:
                target_bone_name = connections[key_str]
                target_key = unreal.RigElementKey(unreal.RigElementType.BONE, unreal.Name(target_bone_name))

                success = controller.connect_connector_to_element(
                    connector_key, target_key, setup_undo=True
                )
                print(f"Connected {key_str} → {target_bone_name}: {success}")


def build_neck_module(controller, neck_joints):
    """

    :param controller: control_rig_bp.get_modular_rig_controller()
    :param neck_joints:
    :return:
    """
    module_path = "/ControlRigModules/Modules56/Neck.Neck_C"
    asset = unreal.load_asset(module_path)
    module_name = "Neck"
    controller.add_module(module_name, asset, "Spine")

    connectors = controller.get_connectors_for_module(module_name)
    primary = next(c for c in connectors if str(c.name).endswith("Neck Primary"))

    target_elem = unreal.RigElementKey(
        unreal.RigElementType.SOCKET,
        unreal.Name(f"Spine/neck_socket")
    )

    controller.add_target_to_array_connector(
        connector_key=primary,
        target_key=target_elem,
        setup_undo=True,
        auto_resolve_other_connectors=True,
    )

    connections = {
        f"{module_name}/Neck Base Bone": neck_joints[1],
        f"{module_name}/Head Bone": neck_joints[2]
    }

    for connector_key in connectors:
        key_str = str(connector_key.name)
        if key_str in connections:
            target_bone_name = connections[key_str]
            target_key = unreal.RigElementKey(unreal.RigElementType.BONE, unreal.Name(target_bone_name))

            success = controller.connect_connector_to_element(
                connector_key, target_key, setup_undo=True
            )
            print(f"Connected {key_str} → {target_bone_name}: {success}")


def build_finger_modules(controller, joint_map):
    """

    :param controller: control_rig_bp.get_modular_rig_controller()
    :param joint_map:
    :return:
    """
    module_path = "/ControlRigModules/Modules56/Finger.Finger_C"
    l_asset = unreal.load_asset(module_path)
    r_asset = unreal.load_asset(module_path)

    finger_definitions = {
        "Thumb_L": get_finger_joints(joint_map, "Thumb", side="Left"),
        "Index_L": get_finger_joints(joint_map, "Index", side="Left"),
        "Middle_L": get_finger_joints(joint_map, "Middle", side="Left"),
        "Ring_L": get_finger_joints(joint_map, "Ring", side="Left"),
        "Pinky_L": get_finger_joints(joint_map, "Pinky", side="Left"),

        "Thumb_R": get_finger_joints(joint_map, "Thumb", side="Right"),
        "Index_R": get_finger_joints(joint_map, "Index", side="Right"),
        "Middle_R": get_finger_joints(joint_map, "Middle", side="Right"),
        "Ring_R": get_finger_joints(joint_map, "Ring", side="Right"),
        "Pinky_R": get_finger_joints(joint_map, "Pinky", side="Right")
    }
    for module_name, bone_list in finger_definitions.items():
        parent = "Arm_L" if module_name.endswith("_L") else "Arm_R"
        asset = l_asset if module_name.endswith("_L") else r_asset

        controller.add_module(module_name, asset, parent)

        connectors = controller.get_connectors_for_module(module_name)

        # Set up primary connector to finger socket
        primary = next((c for c in connectors if str(c.name).endswith("Finger Primary")), None)
        if primary:
            socket_name = bone_list[-1] + "_socket"
            socket_path = f"{parent}/{socket_name}"
            target_elem = unreal.RigElementKey(
                unreal.RigElementType.SOCKET,
                unreal.Name(socket_path)
            )
            success = controller.add_target_to_array_connector(
                connector_key=primary,
                target_key=target_elem,
                setup_undo=True,
                auto_resolve_other_connectors=True
            )
            print(f"{module_name} → {socket_path}: {success}")


def build_shoulder_modules(controller):
    """

    :param controller: control_rig_bp.get_modular_rig_controller()
    :return:
    """
    module_path = "/ControlRigModules/Modules56/Shoulder.Shoulder_C"
    l_asset = unreal.load_asset(module_path)
    r_asset = unreal.load_asset(module_path)

    controller.add_module("Shoulder_L", l_asset, "Spine")
    controller.add_module("Shoulder_R", r_asset, "Spine")

    for module_name, socket_name in [("Shoulder_L", "shoulder_l"), ("Shoulder_R", "shoulder_r")]:
        connectors = controller.get_connectors_for_module(module_name)
        primary = next((c for c in connectors if str(c.name).endswith("Shoulder Primary")), None)
        if primary:
            target_elem = unreal.RigElementKey(
                unreal.RigElementType.SOCKET,
                unreal.Name(f"Spine/{socket_name}")
            )
            success = controller.add_target_to_array_connector(
                connector_key=primary,
                target_key=target_elem,
                setup_undo=True,
                auto_resolve_other_connectors=True
            )
            print(f"{module_name} → {socket_name}: {success}")


def build_arm_modules(controller, arm_joints):
    """

    :param controller: control_rig_bp.get_modular_rig_controller()
    :param arm_joints:
    :return:
    """
    module_path = "/ControlRigModules/Modules56/Arm.Arm_C"
    l_asset = unreal.load_asset(module_path)
    r_asset = unreal.load_asset(module_path)

    controller.add_module("Arm_L", l_asset, "Shoulder_L")
    controller.add_module("Arm_R", r_asset, "Shoulder_R")

    for side in ["L", "R"]:
        if side == "R":
            index=3
        else:
            index=0
        module_name = "Arm_" + side
        connectors = controller.get_connectors_for_module(module_name)

        # Set up primary connector to shoulder socket
        primary = next((c for c in connectors if str(c.name).endswith("Arm Primary")), None)
        if primary:

            socket_name = f"_socket"
            socket_path = f"Shoulder_{side}/{socket_name}"
            target_elem = unreal.RigElementKey(
                unreal.RigElementType.SOCKET,
                unreal.Name(socket_path)
            )
            success = controller.add_target_to_array_connector(
                connector_key=primary,
                target_key=target_elem,
                setup_undo=True,
                auto_resolve_other_connectors=True,
            )
            if not success:
                socket_name = f"shoulder_{side.lower()}"
                socket_path = f"Spine/{socket_name}"
                target_elem = unreal.RigElementKey(
                    unreal.RigElementType.SOCKET,
                    unreal.Name(socket_path)
                )
                success = controller.add_target_to_array_connector(
                    connector_key=primary,
                    target_key=target_elem,
                    setup_undo=True,
                    auto_resolve_other_connectors=True,
                )

        connections = {
            module_name + "/Shoulder Bone": arm_joints[index],
            module_name + "/Elbow Bone": arm_joints[index+1],
            module_name + "/Hand Bone": arm_joints[index+2]
        }

        for connector_key in connectors:
            key_str = str(connector_key.name)

            if key_str in connections:
                target_bone_name = connections[key_str]
                target_key = unreal.RigElementKey(
                    unreal.RigElementType.BONE,
                    unreal.Name(target_bone_name)
                )

                success = controller.connect_connector_to_element(
                    connector_key, target_key, setup_undo=True
                )


def build_feet_modules(controller, foot_joints):
    """

    :param controller: control_rig_bp.get_modular_rig_controller()
    :param foot_joints:
    :return:
    """
    module_path = "/ControlRigModules/Modules56/Foot.Foot_C"
    l_asset = unreal.load_asset(module_path)
    controller.add_module("Foot_L", l_asset, "Leg_L")
    r_asset = unreal.load_asset(module_path)
    controller.add_module("Foot_R", r_asset, "Leg_R")
    index = 0
    for side in ["L", "R"]:
        if side == "R":
            index +=2
        else:
            index=0
        module_name = "Foot_" + side
        connectors = controller.get_connectors_for_module(module_name)
        # Set up primary connector to shoulder socket
        primary = next((c for c in connectors if str(c.name).endswith("Foot Primary")), None)
        if primary:
            socket_name = f"foot_{side.lower()}_socket"
            socket_path = f"Leg_{side}/{socket_name}"
            target_elem = unreal.RigElementKey(
                unreal.RigElementType.SOCKET,
                unreal.Name(socket_path)
            )
            success = controller.add_target_to_array_connector(
                connector_key=primary,
                target_key=target_elem,
                setup_undo=True,
                auto_resolve_other_connectors=True,
            )
            print(f"{module_name} → {socket_path}: {success}")

        connections = {
            module_name + "/Foot Bone": foot_joints[index],
            module_name + "/Ball Bone": foot_joints[index+1]
        }

        for connector_key in connectors:
            key_str = str(connector_key.name)

            if key_str in connections:
                target_bone_name = connections[key_str]
                target_key = unreal.RigElementKey(unreal.RigElementType.BONE, unreal.Name(target_bone_name))

                success = controller.connect_connector_to_element(
                    connector_key, target_key, setup_undo=True
                )
                print(f"Connected {key_str} → {target_bone_name}: {success}")


def assign_origin_to_root(controller, root_joint):
    """

    :param controller: control_rig_bp.get_modular_rig_controller()
    :param root_joint: actual top joint name
    :return:
    """
    controller.rename_module("Root", "Base")
    connectors = controller.get_connectors_for_module("Base")
    for connector_key in connectors:
        print(connector_key.name)
        if str(connector_key.name) == "Base/Root":
            target_key = unreal.RigElementKey(
                unreal.RigElementType.BONE,
                unreal.Name(root_joint)
            )
            success = controller.connect_connector_to_element(
                connector_key, target_key, setup_undo=True
            )
            print(f"Connected 'origin' to Base/Root: {success}")
            return


def find_uasset_path(file_name):
    """
    Finds the path of a .uasset file by name.

    :param file_name: The name of the asset to find.
    :return: Path to the asset if found, None otherwise.
    """
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    asset_data_list = asset_registry.get_all_assets(True)

    for asset_data in asset_data_list:
        asset_path = unreal.Paths.convert_relative_path_to_full(asset_data.package_name)
        asset_name = os.path.basename(asset_path)
        if "IdentityTemplate" not in asset_path:
            if file_name.lower() == asset_name.lower():
                return asset_path

    return None

def build_modular_fk_control_rig(skeletal_mesh_name, rig_name, joint_map):
    """

    :param skeletal_mesh_name:
    :param rig_name:
    :param joint_map:
    :return:
    """
    skeletal_mesh_path = find_uasset_path(skeletal_mesh_name)
    control_rig_bp_path = create_control_rig_from_asset(skeletal_mesh_path)
    rig_output_path = os.path.join(os.path.dirname(skeletal_mesh_path), rig_name).replace('\\', '/')
    # Step 2: Rename/move if needed
    if control_rig_bp_path != rig_output_path:
        if unreal.EditorAssetLibrary.does_asset_exist(rig_output_path):
            unreal.EditorAssetLibrary.delete_asset(rig_output_path)
        unreal.EditorAssetLibrary.rename_asset(control_rig_bp_path, rig_output_path)
        control_rig_bp = unreal.load_asset(rig_output_path)
    else:
        control_rig_bp = unreal.load_asset(rig_output_path)

    controller = control_rig_bp.get_modular_rig_controller()

    root_joint = [value[0] for key, value in joint_map.items() if "Reference" in key][0]
    assign_origin_to_root(controller, root_joint)
    control_rig_bp.recompile_vm()
    unreal.EditorAssetLibrary.save_loaded_asset(control_rig_bp)

    spine_joints = [value[0] for key, value in joint_map.items() if "Hips" in key or "Spine" in key]
    build_spine_module(controller, spine_joints)

    #shoulder_joints = [value[0] for key, value in joint_map.items() if "Shoulder" in key]
    build_shoulder_modules(controller)

    neck_joints = [value[0] for key, value in joint_map.items() if "Neck" in key or "Head" in key]
    build_neck_module(controller, neck_joints)

    arm_joints = [value[0] for key, value in joint_map.items() if "ik" not in key and "Arm" in key or key.endswith("Hand")]
    build_arm_modules(controller, arm_joints)

    build_finger_modules(controller, joint_map)

    leg_joints = [value[0] for key, value in joint_map.items() if "Leg" in key or key.endswith("Foot")]
    build_leg_modules(controller, leg_joints, spine_joints)

    feet_joints = [value[0] for key, value in joint_map.items() if "Toe" in key or key.endswith("Foot")]
    build_feet_modules(controller, feet_joints)

    # Step 6: Finalize rig
    control_rig_bp.recompile_vm()
    unreal.EditorAssetLibrary.save_loaded_asset(control_rig_bp)
    return control_rig_bp

#control_rig_bp = build_modular_fk_control_rig("/Game/Characters/SK_juice", "/Game/Characters/CR_SK_juicy5")

