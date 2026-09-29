import unreal
import re
import os
import math
from utilities.p4_utils import prepare_file_for_write


def _prepare_game_asset_for_write(asset_path):
    package = asset_path.split(".", 1)[0]
    if package.startswith("/Game/"):
        content_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())
        prepare_file_for_write(os.path.join(content_dir, package[len("/Game/"):] + ".uasset"))

def create_control_rig_from_asset(asset_path):
    if not isinstance(asset_path, str) or not asset_path:
        raise ValueError("Select a valid SkeletalMesh or Skeleton asset path.")
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
    module_path = "/ControlRigModules/Modules58/Spine.Spine_C"
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
    module_path = "/ControlRigModules/Modules58/Leg.Leg_C"
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
    module_path = "/ControlRigModules/Modules58/Neck.Neck_C"
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
    module_path = "/ControlRigModules/Modules58/Finger.Finger_C"
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
    module_path = "/ControlRigModules/Modules58/Shoulder.Shoulder_C"
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
    module_path = "/ControlRigModules/Modules58/Arm.Arm_C"
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
    module_path = "/ControlRigModules/Modules58/Foot.Foot_C"
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
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("No skeletal asset was selected.")
    identity = file_name.strip()
    if identity.startswith("/"):
        if not unreal.EditorAssetLibrary.does_asset_exist(identity):
            raise ValueError("Selected Unreal asset does not exist: {}".format(identity))
        return identity
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    matches = []
    for data in asset_registry.get_all_assets(True):
        if str(data.asset_class_path.asset_name) not in ("SkeletalMesh", "Skeleton"):
            continue
        if str(data.asset_name).casefold() == identity.casefold():
            matches.append("{}.{}".format(data.package_name, data.asset_name))
    if len(matches) != 1:
        raise ValueError("Expected one skeletal asset named '{}'; found {}. Select its full asset path.".format(identity, len(matches)))
    return matches[0]

def configure_arm_reference_axes(blueprint, joint_map):
    """Choose explicit limb axes that preserve the imported reference pose."""
    controller = blueprint.get_modular_rig_controller()
    module = unreal.load_asset('/ControlRigModules/Modules58/Arm.Arm')
    defaults = next(str(v.default_value) for v in module.get_member_variables() if str(v.name) == 'Module Settings')
    def joint(slot):
        value = joint_map[slot]
        value = value.get('joint') if isinstance(value, dict) else value[0] if isinstance(value, (list, tuple)) else value
        return str(value).rsplit('|', 1)[-1].rsplit(':', 1)[-1]
    def configure(name, variable, value):
        if not controller.set_config_value_in_module(name, variable, value):
            raise RuntimeError('Could not set {} / {}'.format(name, variable))
    report = {}
    for side, suffix in [('Left', 'L'), ('Right', 'R')]:
        name = 'Arm_' + suffix
        child = unreal.RigElementKey(unreal.RigElementType.BONE, joint(side+'ForeArm'))
        offset = blueprint.hierarchy.get_local_transform(child, True).translation
        values = [offset.x, offset.y, offset.z]
        axis = max(range(3), key=lambda i: abs(values[i]))
        primary = [0, 0, 0]
        primary[axis] = 1 if values[axis] >= 0 else -1
        def vector(v):
            return '(X={},Y={},Z={})'.format(*v)
        base = re.sub(r'(PrimaryBoneAxis_[A-Za-z0-9_]+=)\([^)]*\)', lambda m: m[1]+vector(primary), defaults)
        configure(name, 'Use Custom Axis', 'True')
        best = None
        for secondary_axis in range(3):
            if secondary_axis == axis:
                continue
            for sign in (1, -1):
                secondary = [0, 0, 0]
                secondary[secondary_axis] = sign
                settings = re.sub(r'(SecondaryAxis_[A-Za-z0-9_]+=)\([^)]*\)', lambda m: m[1]+vector(secondary), base)
                configure(name, 'Module Settings', settings)
                blueprint.recompile_modular_rig()
                blueprint.recompile_vm()
                instance = blueprint.create_control_rig()
                instance.request_init()
                if not instance.execute_event('Construction'):
                    raise RuntimeError('Cannot construct arm-axis validation rig')
                hierarchy = instance.get_hierarchy()
                switches = [k for k in hierarchy.get_all_keys()
                            if str(k.name).startswith(name + '/') and str(k.name).endswith('fk_ik_switch')]
                if len(switches) != 1:
                    raise RuntimeError('Cannot identify IK switch for ' + name)
                hierarchy.set_control_value(switches[0], hierarchy.make_control_value_from_bool(True))
                # A single forward event can still show the untouched bind pose.
                # Evaluate the complete sequence repeatedly, as the editor does.
                for _ in range(3):
                    for event in ('Pre Forwards Solve', 'Forwards Solve', 'Post Forwards Solve'):
                        instance.execute_event(event)
                errors = []
                for slot in ('Arm', 'ForeArm'):
                    key = unreal.RigElementKey(unreal.RigElementType.BONE, joint(side+slot))
                    a = hierarchy.get_global_transform(key, True).rotation
                    b = hierarchy.get_global_transform(key, False).rotation
                    dot = abs(a.x*b.x+a.y*b.y+a.z*b.z+a.w*b.w)
                    errors.append(math.degrees(2*math.acos(min(1.0, dot))))
                score = max(errors)
                if best is None or score < best[0]:
                    best = (score, settings)
        configure(name, 'Module Settings', best[1])
        if best[0] > 1.0:
            raise RuntimeError('{} reference-pose rotation error is {:.2f} degrees; check limb mapping and axes'.format(name, best[0]))
        report[name] = best[0]
    blueprint.recompile_modular_rig()
    blueprint.recompile_vm()
    return report


def verify_arm_reference_pose(blueprint, joint_map):
    """Reject fresh builds with arm or roll-bone rest-pose flips in FK or IK."""
    names = {}
    for side in ('Left', 'Right'):
        for slot in ('Arm', 'ForeArm'):
            value = joint_map[side + slot]
            value = value.get('joint') if isinstance(value, dict) else value[0] if isinstance(value, (list, tuple)) else value
            names[side + slot] = str(value).rsplit('|', 1)[-1].rsplit(':', 1)[-1]
    rig = blueprint.create_control_rig()
    rig.request_init()
    if not rig.execute_event('Construction'):
        raise RuntimeError('Arm validation could not construct rig')
    hierarchy = rig.get_hierarchy()
    keys = hierarchy.get_all_keys()
    checked = []
    for key in keys:
        if key.type != unreal.RigElementType.BONE:
            continue
        if str(key.name) in names.values():
            checked.append(key)
        elif re.search(r'twist|roll', str(key.name), re.IGNORECASE):
            parent = hierarchy.get_first_parent(key)
            visited = set()
            while str(parent.name) not in visited and parent.type == unreal.RigElementType.BONE:
                visited.add(str(parent.name))
                if str(parent.name) in names.values():
                    checked.append(key)
                    break
                parent = hierarchy.get_first_parent(parent)
    switches = [key for key in keys if str(key.name).startswith(('Arm_L/', 'Arm_R/'))
                and str(key.name).endswith('fk_ik_switch')]
    if len(switches) != 2:
        raise RuntimeError('Arm validation requires both constructed IK switches')
    worst = 0.0
    for ik_mode in (False, True):
        for switch in switches:
            hierarchy.set_control_value(switch, hierarchy.make_control_value_from_bool(ik_mode))
        for _ in range(3):
            for event in ('Pre Forwards Solve', 'Forwards Solve', 'Post Forwards Solve'):
                rig.execute_event(event)
        for key in checked:
            a = hierarchy.get_global_transform(key, True).rotation
            b = hierarchy.get_global_transform(key).rotation
            error = math.degrees(2 * math.acos(min(1.0, abs(a.x*b.x + a.y*b.y + a.z*b.z + a.w*b.w))))
            worst = max(worst, error)
            if error > 1.0:
                raise RuntimeError('{} has {:.2f} degree rest twist in {} mode'.format(
                    key.name, error, 'IK' if ik_mode else 'FK'))
    return {'bones_checked': len(checked), 'max_rotation_error_degrees': worst}


def apply_body_control_connections(control_rig_bp, joint_map):
    """Resolve generated control spaces and twist arrays after construction."""
    # A fresh instance avoids depending on an open editor or its next UI tick.
    rig = control_rig_bp.create_control_rig()
    rig.request_init()
    rig.request_construction()
    if not rig.execute_event("Construction"):
        raise RuntimeError("Modular rig Construction event failed before control mapping")
    hierarchy = rig.get_hierarchy()
    controller = control_rig_bp.get_modular_rig_controller()
    keys = {str(k.name): k for k in hierarchy.get_all_keys()}
    def bone(slot):
        value = joint_map.get(slot)
        name = value.get("joint") if isinstance(value, dict) else value[0] if value else ""
        return str(name or "").rsplit("|", 1)[-1].rsplit(":", 1)[-1]
    def controls(module):
        return [str(k.name) for k in hierarchy.get_controls()
                if str(k.name).startswith(module + "/") and str(k.name).endswith("_ctrl")]
    upper_spine_control = next(
        (name for name in ("Spine/spine4_ctrl", "Spine/spine_04_ctrl") if name in keys),
        None,
    )
    if upper_spine_control is None:
        raise RuntimeError("Required upper-spine parent control is missing: spine4_ctrl (spine_04_ctrl)")
    links = {
        "Spine/Parent Control": "Base/body_offset_ctrl",
        "Spine/Settings Control": "Base/root_ctrl",
        "Neck/Parent Control": upper_spine_control,
        "Neck/Settings Control": "Base/root_ctrl",
    }
    for side, suffix in (("Left", "L"), ("Right", "R")):
        arm, leg, shoulder, foot = [p+suffix for p in ("Arm_", "Leg_", "Shoulder_", "Foot_")]
        shoulder_controls = controls(shoulder)
        mapped_shoulder = shoulder + "/" + bone(side+"Shoulder") + "_ctrl"
        if mapped_shoulder in shoulder_controls:
            shoulder_controls = [mapped_shoulder]
        if len(shoulder_controls) != 1:
            raise RuntimeError("Expected one shoulder control in {}: {}".format(shoulder, shoulder_controls))
        ankle_candidates = [k for k in controls(leg) if re.search(r"/foot_[lr]_ctrl$", k)]
        wrist_candidates = [k for k in controls(arm) if k.endswith("_wrist_ctrl")]
        if len(ankle_candidates) != 1 or len(wrist_candidates) != 1:
            raise RuntimeError("Could not identify generated foot/wrist controls for " + side)
        ankle = ankle_candidates[0]
        links.update({
            shoulder+"/Parent Control": upper_spine_control,
            arm+"/Parent Control": "Base/root_ctrl",
            arm+"/FK Arm Space": shoulder_controls[0],
            arm+"/Pole Vector Parent": "Base/root_ctrl",
            arm+"/Settings Control": "Base/root_ctrl",
            leg+"/Parent Control": "Base/root_ctrl",
            leg+"/Pole Vector Parent": "Base/root_ctrl",
            leg+"/Settings Control": "Base/root_ctrl",
            foot+"/Parent Control": ankle,
            foot+"/Settings Control": ankle,
        })
        for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            module = finger+"_"+suffix
            if module in [str(m) for m in controller.get_all_modules()]:
                links[module+"/Parent Control"] = wrist_candidates[0]
    connected = []
    for connector, name in links.items():
        if name not in keys:
            raise RuntimeError("Generated control is missing: " + name)
        key = unreal.RigElementKey(unreal.RigElementType.CONNECTOR, connector)
        if not controller.connect_connector_to_element(key, keys[name], auto_resolve_other_connectors=False):
            raise RuntimeError("Could not connect {} to {}".format(connector, name))
        connected.append((connector, name))
    twists = {}
    for side, suffix in (("Left", "L"), ("Right", "R")):
        for module, slots in (("Arm_"+suffix, ("Arm", "ForeArm")), ("Leg_"+suffix, ("UpLeg", "Leg"))):
            owners = {bone(side+s) for s in slots}
            targets = []
            for key in hierarchy.get_all_keys():
                if key.type != unreal.RigElementType.BONE or not re.search(r"twist|roll", str(key.name), re.I):
                    continue
                parent = hierarchy.get_first_parent(key)
                visited = set()
                while str(parent.name) and str(parent.name) not in visited:
                    visited.add(str(parent.name))
                    if str(parent.name) in owners:
                        targets.append(key)
                        break
                    parent = hierarchy.get_first_parent(parent)
            connector = unreal.RigElementKey(unreal.RigElementType.CONNECTOR, module+"/Twist Bones")
            controller.disconnect_connector(connector)
            for target in targets:
                if not controller.add_target_to_array_connector(connector, target, auto_resolve_other_connectors=False):
                    raise RuntimeError("Could not connect twist bone {} to {}".format(target.name, module))
            twists[module] = [str(k.name) for k in targets]
    control_rig_bp.recompile_modular_rig()
    control_rig_bp.recompile_vm()
    model_text = control_rig_bp.modular_rig_model.export_text()
    for connector, target in connected:
        if 'Name="{}"'.format(connector) not in model_text or 'Name="{}"'.format(target) not in model_text:
            raise RuntimeError("Control connection did not persist: " + connector)
    preview = control_rig_bp.get_debugged_control_rig()
    if preview:
        preview.request_construction()
        preview.execute_event("Construction")
    return {"control_connections": connected, "twist_bones": twists}


def apply_body_joint_map(control_rig_bp, joint_map):
    """Build and resolve modular connectors from explicit HIK body slots."""
    bones = {}
    for slot, value in joint_map.items():
        name = value.get("joint") if isinstance(value, dict) else value[0]
        if name:
            bones[slot] = str(name).rsplit("|", 1)[-1].rsplit(":", 1)[-1]
    def required(slot):
        if slot not in bones:
            raise ValueError("Body joint map is missing {}".format(slot))
        return bones[slot]
    spines = [bones[s] for s in sorted(
        (s for s in bones if re.fullmatch(r"Spine\d*", s)),
        key=lambda s: int(s[5:] or 0))]
    if not spines:
        raise ValueError("Body joint map is missing Spine")
    plan = [("Base", "Root", "", {"Root": required("Reference")}),
            ("Spine", "Spine", "Base", {
                "Spine Primary": required("Hips"), "Pelvis Bone": required("Hips"),
                "Spine Start Bone": spines[0], "Spine End Bone": spines[-1]}),
            ("Neck", "Neck", "Spine", {
                "Neck Primary": required("Neck"), "Neck Start Bone": required("Neck"),
                "Head Bone": required("Head")})]
    for side, suffix in (("Left", "L"), ("Right", "R")):
        shoulder, arm, leg = "Shoulder_"+suffix, "Arm_"+suffix, "Leg_"+suffix
        plan.extend([
            (shoulder, "Shoulder", "Spine", {"Shoulder Primary": required(side+"Shoulder"), "Chest Bone": spines[-1]}),
            (arm, "Arm", shoulder, {"Arm Primary": required(side+"Arm"), "Shoulder Bone": required(side+"Arm"), "Elbow Bone": required(side+"ForeArm"), "Hand Bone": required(side+"Hand")}),
            (leg, "Leg", "Spine", {"Leg Primary": required(side+"UpLeg"), "Pelvis Bone": required("Hips"), "Thigh Bone": required(side+"UpLeg"), "Knee Bone": required(side+"Leg"), "Foot Bone": required(side+"Foot")}),
            ("Foot_"+suffix, "Foot", leg, {"Foot Primary": required(side+"Foot"), "Foot Bone": required(side+"Foot"), "Ball Bone": required(side+"ToeBase")}),
        ])
        for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            slots = [side+"InHand"+finger] + [side+"Hand"+finger+str(i) for i in range(1, 6)]
            chain = list(dict.fromkeys(bones[s] for s in slots if s in bones))
            if len(chain) >= 2:
                plan.append((finger+"_"+suffix, "Finger", arm, {
                    "Finger Primary": chain[0], "Start Bone": chain[0], "End Bone": chain[-1]}))
    hierarchy = control_rig_bp.hierarchy
    available = {str(k.name) for k in hierarchy.get_all_keys() if k.type == unreal.RigElementType.BONE}
    missing = sorted({b for _, _, _, targets in plan for b in targets.values()} - available)
    if missing:
        raise ValueError("Body map bones absent from selected Unreal skeleton: " + ", ".join(missing))
    controller = control_rig_bp.get_modular_rig_controller()
    modules = set(str(m) for m in controller.get_all_modules())
    if "Base" not in modules and "Root" in modules:
        controller.rename_module("Root", "Base")
        modules.add("Base")
    connected = []
    for name, kind, parent, targets in plan:
        module_root = "/ControlRig/Modules/Modules58/" if kind == "Root" else "/ControlRigModules/Modules58/"
        module_path = module_root + "{0}.{0}_C".format(kind)
        if name not in modules:
            asset = unreal.load_class(None, module_path)
            if not asset:
                raise RuntimeError("Missing modular Control Rig asset: " + kind)
            if not controller.add_module(name, asset, parent):
                raise RuntimeError("Could not add modular rig module: " + name)
            modules.add(name)
        elif ("Modules58/" not in controller.get_module_reference(name).export_text()
              and not (kind == "Foot" and "_MayaFoot_" in controller.get_module_reference(name).export_text())):
            asset = unreal.load_class(None, module_path)
            if not asset or not controller.swap_module_class(name, asset):
                raise RuntimeError("Could not upgrade module to UE 5.8: " + name)
        connectors = {str(k.name).rsplit("/", 1)[-1]: k for k in controller.get_connectors_for_module(name)}
        for label, bone in targets.items():
            key = connectors.get(label)
            if key is None and label == "Neck Start Bone":
                key = connectors.get("Neck Base Bone")
            if key is None:
                raise RuntimeError("Module {} has no connector {}".format(name, label))
            target = unreal.RigElementKey(unreal.RigElementType.BONE, unreal.Name(bone))
            if label.endswith(" Primary"):
                socket_name = "HIK_" + bone
                socket = unreal.RigElementKey(unreal.RigElementType.SOCKET, unreal.Name(socket_name))
                if socket not in hierarchy.get_all_keys():
                    socket = hierarchy.get_controller().add_socket(
                        socket_name, target, unreal.Transform(), transform_in_global=False, setup_undo=True)
                target = socket
                controller.disconnect_connector(key)
            connect = controller.add_target_to_array_connector if label.endswith(" Primary") else controller.connect_connector_to_element
            if not connect(key, target, setup_undo=True, auto_resolve_other_connectors=False):
                raise RuntimeError("Could not connect {} to Body map bone {}".format(key.name, bone))
            connected.append((str(key.name), bone))
        control_rig_bp.recompile_vm()
    control_rig_bp.recompile_modular_rig()
    control_rig_bp.recompile_vm()
    preview = control_rig_bp.get_debugged_control_rig()
    if preview:
        preview.request_construction()
    apply_body_control_connections(control_rig_bp, joint_map)
    # Settings/parent connectors must exist before testing IK. Otherwise the
    # switch is never constructed and an untouched FK pose falsely scores zero.
    configure_arm_reference_axes(control_rig_bp, joint_map)
    from unreal_tools.reverse_foot import install_reverse_feet, verify_reverse_feet
    install_reverse_feet(control_rig_bp, joint_map)
    verify_reverse_feet(control_rig_bp, joint_map)
    verify_arm_reference_pose(control_rig_bp, joint_map)
    return connected


def build_modular_fk_control_rig(skeletal_mesh_name, rig_name, joint_map):
    """

    :param skeletal_mesh_name:
    :param rig_name:
    :param joint_map:
    :return:
    """
    skeletal_mesh_path = find_uasset_path(skeletal_mesh_name)
    rig_name = str(rig_name or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rig_name):
        raise ValueError("Enter a Control Rig name using letters, numbers and underscores.")
    rig_output_path = skeletal_mesh_path.rsplit("/", 1)[0] + "/" + rig_name
    if unreal.EditorAssetLibrary.does_asset_exist(rig_output_path):
        raise ValueError("Control Rig destination already exists: {}. Choose another name.".format(rig_output_path))
    _prepare_game_asset_for_write(rig_output_path)
    control_rig_bp_path = create_control_rig_from_asset(skeletal_mesh_path)
    control_rig_bp = unreal.load_asset(control_rig_bp_path)
    if control_rig_bp is None:
        raise RuntimeError("Could not load the newly created Control Rig: {}".format(control_rig_bp_path))
    # Step 2: Rename/move if needed
    if control_rig_bp_path.split(".", 1)[0] != rig_output_path:
        _prepare_game_asset_for_write(control_rig_bp_path)
        if not unreal.EditorAssetLibrary.rename_asset(control_rig_bp_path, rig_output_path):
            raise RuntimeError(
                "Unreal could not rename '{}' to '{}'. The generated asset remains at '{}'. "
                "Check Unreal's revision-control connection; if working offline, select "
                "Revision Control > Change Revision Control Settings > None, then retry.".format(
                    control_rig_bp_path, rig_output_path, control_rig_bp_path))
        # Keep the factory asset reference: successful rename updates this object.

    controller = control_rig_bp.get_modular_rig_controller()
    if controller is None:
        raise RuntimeError("Created blueprint has no modular rig controller: {}".format(control_rig_bp.get_path_name()))

    apply_body_joint_map(control_rig_bp, joint_map)

    # Step 6: Finalize rig
    control_rig_bp.recompile_vm()
    unreal.EditorAssetLibrary.save_loaded_asset(control_rig_bp)
    return control_rig_bp

#control_rig_bp = build_modular_fk_control_rig("/Game/Characters/SK_juice", "/Game/Characters/CR_SK_juicy5")


def _json_result(**payload):
    import json

    return json.dumps(payload, indent=2, default=str)


def list_controls(rig_path):
    rig = unreal.load_asset(rig_path)
    if not rig:
        return _json_result(ok=False, error="control_rig_not_found", rig_path=rig_path)
    hierarchy = None
    try:
        hierarchy = rig.hierarchy
    except Exception:
        try:
            hierarchy = rig.get_hierarchy()
        except Exception:
            pass
    if not hierarchy:
        return _json_result(ok=False, status="api_unavailable", rig_path=rig_path)
    rows = []
    try:
        for key in hierarchy.get_all_keys():
            if "control" in str(key.type).lower():
                rows.append({"name": str(key.name), "type": str(key.type)})
    except Exception as exc:
        return _json_result(ok=False, error=str(exc), rig_path=rig_path)
    return _json_result(ok=True, rig_path=rig_path, controls=rows, count=len(rows))


def set_control_property(rig_path, control_name, property_name, value, save=True):
    rig = unreal.load_asset(rig_path)
    if not rig:
        return _json_result(ok=False, error="control_rig_not_found", rig_path=rig_path)
    try:
        rig.set_editor_property(str(property_name), value)
    except Exception as exc:
        return _json_result(ok=False, error=str(exc), rig_path=rig_path, control_name=control_name, property_name=property_name)
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(rig, False)
    return _json_result(ok=True, rig_path=rig_path, control_name=control_name, property_name=property_name, value=value, saved=bool(save))


def set_control_default(rig_path, control_name, value, save=True):
    return set_control_property(rig_path, control_name, "initial_value", value, save=save)


def rename_control(rig_path, old_name, new_name, save=True):
    rig = unreal.load_asset(rig_path)
    if not rig:
        return _json_result(ok=False, error="control_rig_not_found", rig_path=rig_path)
    try:
        controller = rig.get_controller()
        renamed = bool(controller.rename_element(old_name, new_name))
    except Exception as exc:
        return _json_result(ok=False, status="api_unavailable", error=str(exc), rig_path=rig_path)
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(rig, False)
    return _json_result(ok=renamed, rig_path=rig_path, old_name=old_name, new_name=new_name, saved=bool(save))


def add_rig_element(rig_path, element_name, element_type, parent_name="", save=True):
    rig = unreal.load_asset(rig_path)
    if not rig:
        return _json_result(ok=False, error="control_rig_not_found", rig_path=rig_path)
    try:
        controller = rig.get_controller()
        added = bool(controller.add_element(str(element_type), str(element_name), str(parent_name or "")))
    except Exception as exc:
        return _json_result(ok=False, status="api_unavailable", error=str(exc), rig_path=rig_path)
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(rig, False)
    return _json_result(ok=added, rig_path=rig_path, element_name=element_name, element_type=element_type, parent_name=parent_name, saved=bool(save))


def connect_rig_nodes(rig_path, source_node, source_pin, target_node, target_pin, save=True):
    rig = unreal.load_asset(rig_path)
    if not rig:
        return _json_result(ok=False, error="control_rig_not_found", rig_path=rig_path)
    try:
        controller = rig.get_controller()
        linked = bool(controller.add_link(f"{source_node}.{source_pin}", f"{target_node}.{target_pin}"))
    except Exception as exc:
        return _json_result(ok=False, status="api_unavailable", error=str(exc), rig_path=rig_path)
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(rig, False)
    return _json_result(ok=linked, rig_path=rig_path, source=f"{source_node}.{source_pin}", target=f"{target_node}.{target_pin}", saved=bool(save))

