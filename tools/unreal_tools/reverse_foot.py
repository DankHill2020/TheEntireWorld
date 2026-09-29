"""Build Maya-style reverse feet as project-owned, native UE 5.8 modules.

Python authors the graph only: animation evaluation has no Python dependency.
The stock foot's FK/backward solve and leg effector integration are retained.
"""
import math
import unreal


def _key(name, kind="Control"):
    return '(Type={},Name="{}")'.format(kind, name)


class _Graph:
    def __init__(self, blueprint, name, start):
        self.graph = next(g for g in blueprint.get_all_models() if g.get_name() == name)
        self.controller = blueprint.get_controller(self.graph)
        for node in list(self.graph.get_nodes()):
            if node.get_name().startswith("MayaRFL_"):
                self.controller.remove_node(node)
        self.tail = start
        self.index = 0

    def link(self, source, target):
        if not self.controller.add_link(source, target):
            raise RuntimeError("Reverse foot link failed: {} -> {}".format(source, target))

    def node(self, unit, label, values=None, links=None, execute=False):
        self.index += 1
        node = self.controller.add_unit_node(
            getattr(unreal, unit).static_struct(), "Execute",
            unreal.Vector2D(400 + self.index * 200, 700), "MayaRFL_" + label)
        if not node:
            raise RuntimeError("Cannot create reverse foot node: " + label)
        name = node.get_name()
        for pin, value in (values or {}).items():
            if not self.controller.set_pin_default_value(name + "." + pin, str(value)):
                raise RuntimeError("Cannot set reverse foot pin: " + name + "." + pin)
        for pin, source in (links or {}).items():
            self.link(source, name + "." + pin)
        if execute:
            pin = "ExecutePin" if node.find_pin("ExecutePin") else "ExecuteContext"
            self.link(self.tail, name + "." + pin)
            self.tail = name + "." + pin
        return name


def _transform(position):
    return unreal.Transform(location=unreal.Vector(*position)).export_text()


def _author_module(module, ankle, pivots, foot_chain):
    construction = _Graph(module, "ConstructionGraph", "CONSTR Foot.ExecuteContext")
    parent = construction.node("RigUnit_ResolveConnector", "Parent", {
        "Connector": _key("Parent Control", "Connector"), "SkipSocket": "true"})
    parent_pin = parent + ".Result"
    for channel in ("footRoll", "footBank", "toeSwivel", "showRFLCtrls"):
        boolean = channel == "showRFLCtrls"
        values = {"Name": channel, "InitialValue": "False" if boolean else "0"}
        if not boolean:
            values.update(MinimumValue="-1", MaximumValue="1")
        construction.node("RigUnit_HierarchyAddAnimationChannel" + ("Bool" if boolean else "Float"),
                          channel, values, {"Parent": parent_pin}, True)
    for pivot, position in pivots.items():
        sdk = construction.node("RigUnit_HierarchyAddNull", pivot + "SDK", {
            "Name": "rfl_" + pivot + "_sdk", "Space": "GlobalSpace",
            "Transform": _transform(position)}, {"Parent": parent_pin}, True)
        ctrl = construction.node("RigUnit_HierarchyAddControlTransform", pivot + "Control", {
            "Name": "rfl_" + pivot + "_ctrl", "Settings.Shape.Name": "Sphere_Thick",
            "Settings.Shape.Transform.Scale3D": "(X=0.25,Y=0.25,Z=0.25)",
            "Settings.Shape.bVisible": "False"}, {"Parent": sdk + ".Item"}, True)
        parent_pin = ctrl + ".Item"
    # The native module has already attached the leg's effector to foot_ik.
    # Keep that integration, but parent it to the Maya reverse chain instead.
    for child, parent_name, kind in (
            (ankle + "_foot_ik", "rfl_ankle_ctrl", "Null"),
            (ankle + "_ball_ik_ctrl", "rfl_toe_ctrl", "Control")):
        construction.node("RigUnit_SetDefaultParent", "Parent_" + child, {
            "Child": _key(child, kind), "Parent": _key(parent_name)}, execute=True)
    construction.node("RigUnit_HierarchyAddNull", "ToeTipTarget", {
        "Name": "rfl_toeTip_target", "Parent": _key("rfl_toeTip_ctrl"),
        "Space": "GlobalSpace", "Transform": _transform(foot_chain["tip_position"])}, execute=True)

    forward = _Graph(module, "RigVMModel", "RigUnit_BeginExecution.ExecutePin")
    forward.controller.break_all_links("Forward Reverse Foot_2.ExecuteContext", True)
    event = forward.node("RigUnit_PreBeginExecution", "PreSolve")
    forward.tail = event + ".ExecutePin"
    # Leave the native forward-foot post solve (including FK mode) intact.
    parent = forward.node("RigUnit_ResolveConnector", "Parent", {
        "Connector": _key("Parent Control", "Connector"), "SkipSocket": "true"})
    channels = {}
    for channel in ("footRoll", "footBank", "toeSwivel", "showRFLCtrls"):
        unit = "RigUnit_GetBoolAnimationChannel" if channel == "showRFLCtrls" else "RigUnit_GetFloatAnimationChannel"
        n = forward.node(unit, channel, {"Channel": channel}, {"Control": parent + ".Result.Name"})
        channels[channel] = n + ".Value"

    def remap(label, source, lo, hi, out_lo, out_hi, middle=False):
        # Maya's auto SDK tangents are flat at the end keys/extrema. For the
        # three collinear swivel keys, the middle tangent remains linear.
        curve_keys = [(0, 0, 0), (1, 1, 0)]
        if middle:
            curve_keys.insert(1, (.5, .5, 1))
        curve = "(EditorCurveData=(Keys=({}),PreInfinityExtrap=RCCE_Constant,PostInfinityExtrap=RCCE_Constant))".format(
            ",".join("(InterpMode=RCIM_Cubic,TangentMode=RCTM_User,Time={},Value={},ArriveTangent={},LeaveTangent={})".format(
                x, y, tangent, tangent) for x, y, tangent in curve_keys))
        n = forward.node("RigUnit_AnimEvalRichCurve", label, {
            "SourceMinimum": lo, "SourceMaximum": hi,
            "TargetMinimum": out_lo, "TargetMaximum": out_hi, "Curve": curve}, {"Value": source})
        return n + ".Result"

    heel = remap("HeelRoll", channels["footRoll"], -1, 0, 45, 0)
    tip = remap("TipRoll", channels["footRoll"], 0, 1, 0, -45)
    ball_up = remap("BallRise", channels["footRoll"], 0, .3, 0, -20)
    ball_down = remap("BallFall", channels["footRoll"], .3, 1, 0, 20)
    ball = forward.node("RigUnit_MathFloatAdd", "BallRoll", links={"A": ball_up, "B": ball_down}) + ".Result"
    outer = remap("OuterBank", channels["footBank"], -1, 0, -45, 0)
    inner = remap("InnerBank", channels["footBank"], 0, 1, 0, 45)
    swivel = remap("Swivel", channels["toeSwivel"], -1, 1, -45, 45, middle=True)
    # Global, zero-oriented SDK pads: Unreal Z up, character forward +Y.
    for pivot, axes in (("heel", {"X": heel}), ("outerBank", {"Y": outer}),
                        ("innerBank", {"Y": inner}), ("toeTip", {"X": tip, "Z": swivel}),
                        ("toe", {"X": ball})):
        quat = forward.node("RigUnit_MathQuaternionFromEuler", pivot + "Rotation",
                            links={"Euler." + axis: pin for axis, pin in axes.items()})
        initial = forward.node("RigUnit_GetTransform", pivot + "Initial", {
            "Item": _key("rfl_" + pivot + "_sdk", "Null"),
            "Space": "LocalSpace", "bInitial": "true"})
        rotation = forward.node("RigUnit_MathQuaternionMul", pivot + "OffsetRotation", links={
            "A": initial + ".Transform.Rotation", "B": quat + ".Result"})
        forward.node("RigUnit_SetRotation", pivot + "Driven", {
            "Item": _key("rfl_" + pivot + "_sdk", "Null"), "Space": "LocalSpace"},
            {"Value": rotation + ".Result"}, True)
    # Native FK/IK matching can preserve these buffers' globals by changing
    # their locals. Restore bind offsets after the pivot evaluation, before
    # the leg consumes its effector, so switching cannot cancel foot motion.
    for child, kind in ((ankle + "_foot_ik", "Null"), (ankle + "_ball_ik_ctrl", "Control")):
        initial = forward.node("RigUnit_GetTransform", "Bind_" + child, {
            "Item": _key(child, kind), "Space": "LocalSpace", "bInitial": "true"})
        forward.node("RigUnit_SetTransform", "Follow_" + child, {
            "Item": _key(child, kind), "Space": "LocalSpace"},
            {"Value": initial + ".Transform"}, True)
    effector = forward.controller.add_variable_node(
        "Effector Null", "FRigElementKey", unreal.RigElementKey.static_struct(),
        True, _key("None", "Null"), node_name="MayaRFL_LegEffector")
    if not effector:
        raise RuntimeError("Cannot read the leg's reverse-foot effector")
    effector_pin = effector.get_name() + ".Value"
    initial = forward.node("RigUnit_GetTransform", "LegEffectorBind", {
        "Space": "LocalSpace", "bInitial": "true"}, {"Item": effector_pin})
    forward.node("RigUnit_SetTransform", "LegEffectorFollow", {"Space": "LocalSpace"},
                 {"Item": effector_pin, "Value": initial + ".Transform"}, True)
    for pivot in pivots:
        forward.node("RigUnit_SetControlVisibility", pivot + "Visibility", {
            "Item": _key("rfl_" + pivot + "_ctrl")}, {"bVisible": channels["showRFLCtrls"]}, True)
    for suffix in ("heel_ctrl", "tip_ctrl", "bk_ctrl", "roll_ctrl", "ball_ik_ctrl"):
        forward.node("RigUnit_SetControlVisibility", "Hide_" + suffix, {
            "Item": _key(ankle + "_" + suffix), "bVisible": "False"}, execute=True)

    # Maya has two independent single-chain IK handles AFTER the leg solve:
    # ankle -> ball and ball -> toe tip. A foot orientation constraint cannot
    # reproduce these when the leg cannot reach its planted effector.
    post = _Graph(module, "RigVMModel Post Forwards Solve Graph", "Forward Foot.ExecuteContext")
    branch = post.node("RigVMFunction_ControlFlowBranch", "IKOnly",
                       links={"Condition": "If.Result"}, execute=True)
    post.tail = branch + ".True"
    toe = foot_chain["toe"]
    # Native Forward Foot sets a world-space ball transform. SC IK must retain
    # the actual segment length instead of stretching that segment to target.
    rest = post.node("RigUnit_GetTransform", "BallRest", {
        "Item": _key(toe, "Bone"), "Space": "LocalSpace", "bInitial": "true"})
    post.node("RigUnit_SetTranslation", "PreserveFootLength", {
        "Item": _key(toe, "Bone"), "Space": "LocalSpace"},
        {"Value": rest + ".Transform.Translation"}, True)
    for label, bone, target, kind, axis in (
            ("AnkleToBall", ankle, ankle + "_ball_ik_ctrl", "Control", foot_chain["ankle_axis"]),
            ("BallToTip", toe, "rfl_toeTip_target", "Null", foot_chain["toe_axis"])):
        goal = post.node("RigUnit_GetTransform", label + "Goal", {"Item": _key(target, kind)})
        post.node("RigUnit_AimBone", label + "IK", {
            "Bone": bone, "Primary.Axis": axis, "Secondary.Weight": "0",
            "bPropagateToChildren": "true"}, {"Primary.Target": goal + ".Transform.Translation"}, True)
    # The stock backward solver bakes to FK. Clear procedural inputs afterward
    # so they are not applied a second time when the baked pose is evaluated.
    backward = _Graph(module, "RigVMModel Backwards Solve Graph", "ParentConstraint_1.ExecutePin")
    parent = backward.node("RigUnit_ResolveConnector", "Parent", {
        "Connector": _key("Parent Control", "Connector"), "SkipSocket": "true"})
    for channel in ("footRoll", "footBank", "toeSwivel"):
        backward.node("RigUnit_SetFloatAnimationChannel", "Reset_" + channel,
                      {"Channel": channel, "Value": "0"}, {"Control": parent + ".Result.Name"}, True)
    for pivot in pivots:
        for kind, suffix in (("Null", "_sdk"), ("Control", "_ctrl")):
            name = "rfl_" + pivot + suffix
            initial = backward.node("RigUnit_GetTransform", name + "Bind", {
                "Item": _key(name, kind), "Space": "LocalSpace", "bInitial": "true"})
            backward.node("RigUnit_SetTransform", name + "Reset", {
                "Item": _key(name, kind), "Space": "LocalSpace"},
                {"Value": initial + ".Transform"}, True)
    module.recompile_vm()


def install_reverse_feet(blueprint, joint_map, pivot_overrides=None):
    """Install on existing rigs and fresh builds using mapped reference bones.

    Assets are local to each rig, so different characters cannot overwrite one
    another's pivot placement. Engine-provided modules are never modified.
    Optional pivot_overrides maps Left/Right to named reference-pose positions
    in Unreal rig space, allowing authored Maya pivots to be transferred.
    """
    from unreal_tools.control_rig import _prepare_game_asset_for_write
    bones = {slot: str(value[0] if isinstance(value, (list, tuple)) else value).split("|")[-1].split(":")[-1]
             for slot, value in joint_map.items() if value}
    hierarchy = blueprint.hierarchy
    bone_keys = {str(k.name): k for k in hierarchy.get_all_keys() if k.type == unreal.RigElementType.BONE}
    controller = blueprint.get_modular_rig_controller()
    result = []
    for side, suffix in (("Left", "L"), ("Right", "R")):
        ankle, toe = bones[side + "Foot"], bones[side + "ToeBase"]
        children = [k for k in hierarchy.get_children(bone_keys[toe], False) if k.type == unreal.RigElementType.BONE]
        if len(children) != 1:
            raise ValueError("Reverse foot requires one unambiguous toe-tip child of " + toe)
        def position(key):
            v = hierarchy.get_global_transform(key, initial=True).translation
            return [v.x, v.y, v.z]
        a, b, t = position(bone_keys[ankle]), position(bone_keys[toe]), position(children[0])
        if math.dist(b, t) < 0.001:
            # Some FBX skeletons collapse the end joint onto the ball. Keep the
            # tip separately editable instead of producing coincident pivots.
            t = [b[0] + (b[0] - a[0]) * .5, b[1] + (b[1] - a[1]) * .5, 0]
            unreal.log_warning("{}: toe-tip joint is coincident with ball; estimated RFL tip. Adjust rfl_toeTip_ctrl pivot if needed.".format(side))
        def aim_axis(bone, start, end):
            delta = unreal.Vector(*(end[i] - start[i] for i in range(3)))
            local = hierarchy.get_global_transform(bone_keys[bone], initial=True).rotation.unrotate_vector(delta)
            length = math.sqrt(local.x * local.x + local.y * local.y + local.z * local.z)
            if length < .001:
                raise ValueError("Cannot solve zero-length foot segment: " + bone)
            return "(X={},Y={},Z={})".format(local.x / length, local.y / length, local.z / length)
        foot_chain = {"toe": toe, "tip_position": t,
                      "ankle_axis": aim_axis(ankle, a, b), "toe_axis": aim_axis(toe, b, t)}
        sign = 1 if side == "Left" else -1
        pivots = {"heel": [a[0], a[1] - 1.5, 0],
                  "outerBank": [b[0] - 2.5 * sign, b[1], 0],
                  "innerBank": [b[0] + 2.5 * sign, b[1], 0],
                  "toeTip": t, "toe": b, "ankle": a}
        for name, point in (pivot_overrides or {}).get(side, {}).items():
            if name not in pivots or len(point) != 3 or not all(math.isfinite(float(v)) for v in point):
                raise ValueError("Invalid reverse-foot pivot override: {} {}".format(side, name))
            pivots[name] = [float(v) for v in point]
        path = blueprint.get_path_name().split(".")[0] + "_MayaFoot_" + suffix
        _prepare_game_asset_for_write(path)
        module = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else unreal.EditorAssetLibrary.duplicate_asset(
            "/ControlRigModules/Modules58/Foot", path)
        if not module:
            raise RuntimeError("Cannot create project-owned reverse foot module: " + path)
        auto_compile = module.get_auto_vm_recompile()
        module.set_auto_vm_recompile(False)
        try:
            _author_module(module, ankle, pivots, foot_chain)
        finally:
            module.set_auto_vm_recompile(auto_compile)
        if not unreal.EditorAssetLibrary.save_loaded_asset(module):
            raise RuntimeError("Cannot save reverse foot module: " + path)
        current = controller.get_module_reference("Foot_" + suffix).export_text()
        if path not in current and not controller.swap_module_class("Foot_" + suffix, unreal.load_class(None, path + "." + path.rsplit("/", 1)[-1] + "_C")):
            raise RuntimeError("Cannot install reverse foot module: " + suffix)
        result.append(path)
    blueprint.recompile_modular_rig()
    blueprint.recompile_vm()
    return result


def verify_reverse_feet(blueprint, joint_map=None):
    """Exercise fresh transient instances; never change animator control values."""
    rig = blueprint.create_control_rig()
    rig.request_init()
    if not rig.execute_event("Construction"):
        raise RuntimeError("Reverse foot verification could not construct rig")
    hierarchy = rig.get_hierarchy()

    def control(name):
        return unreal.RigElementKey(unreal.RigElementType.CONTROL, name)

    def solve():
        for event in ("Pre Forwards Solve", "Forwards Solve", "Post Forwards Solve"):
            if not rig.execute_event(event):
                raise RuntimeError("Reverse foot verification event failed: " + event)

    solve()
    rows = []
    for suffix in ("L", "R"):
        prefix = "Foot_" + suffix + "/"
        switches = [k for k in hierarchy.get_all_keys()
                    if str(k.name).startswith("Leg_" + suffix + "/") and str(k.name).endswith("fk_ik_switch")]
        if len(switches) != 1:
            raise RuntimeError("Cannot identify leg IK switch: " + suffix)
        hierarchy.set_control_value(switches[0], hierarchy.make_control_value_from_bool(True))
        solve()
        # The original foot_ik name is derived from the mapped ankle, not side aliases.
        native_ankles = [k for k in hierarchy.get_all_keys()
                        if str(k.name).startswith(prefix) and str(k.name).endswith("_foot_ik")]
        if len(native_ankles) != 1:
            raise RuntimeError("Missing native ankle effector: " + suffix)
        bone_name = str(native_ankles[0].name).rsplit("/", 1)[-1][:-len("_foot_ik")]
        bone = unreal.RigElementKey(unreal.RigElementType.BONE, bone_name)
        ankle = control(prefix + "rfl_ankle_ctrl")
        baseline = hierarchy.get_global_transform(ankle).translation
        bone_baseline = hierarchy.get_global_transform(bone).translation
        for channel in ("footRoll", "footBank", "toeSwivel"):
            key = control(prefix + channel)
            for value in (-1.0, .3, 1.0):
                hierarchy.set_control_value(key, hierarchy.make_control_value_from_float(value))
                solve()
                point = hierarchy.get_global_transform(ankle).translation
                distance = math.dist((point.x, point.y, point.z), (baseline.x, baseline.y, baseline.z))
                if distance < .001:
                    raise RuntimeError("Reverse foot does not respond: {} {} {}".format(suffix, channel, value))
                bone_point = hierarchy.get_global_transform(bone).translation
                if math.dist((bone_point.x, bone_point.y, bone_point.z),
                             (bone_baseline.x, bone_baseline.y, bone_baseline.z)) < .001:
                    raise RuntimeError("Reverse foot control moves but ankle bone does not: " + suffix + channel)
                rows.append((suffix, channel, value, round(distance, 5)))
            hierarchy.set_control_value(key, hierarchy.make_control_value_from_float(0.0))
            solve()
            point = hierarchy.get_global_transform(ankle).translation
            if math.dist((point.x, point.y, point.z), (baseline.x, baseline.y, baseline.z)) > .001:
                raise RuntimeError("Reverse foot does not return to neutral: " + suffix + channel)
        # Foot drivers must not change the FK leg pose.
        hierarchy.set_control_value(switches[0], hierarchy.make_control_value_from_bool(False))
        solve()
        fk_pose = hierarchy.get_global_transform(bone)
        hierarchy.set_control_value(control(prefix + "footRoll"), hierarchy.make_control_value_from_float(1))
        solve()
        fk_after = hierarchy.get_global_transform(bone)
        if math.dist((fk_pose.translation.x, fk_pose.translation.y, fk_pose.translation.z),
                     (fk_after.translation.x, fk_after.translation.y, fk_after.translation.z)) > .001:
            raise RuntimeError("Reverse foot changed FK ankle: " + suffix)
        hierarchy.set_control_value(control(prefix + "footRoll"), hierarchy.make_control_value_from_float(0))
        visibility = control(prefix + "showRFLCtrls")
        for value in (True, False):
            hierarchy.set_control_value(visibility, hierarchy.make_control_value_from_bool(value))
            solve()
            for pivot in ("heel", "outerBank", "innerBank", "toeTip", "toe", "ankle"):
                if hierarchy.get_control_settings(control(prefix + "rfl_" + pivot + "_ctrl")).shape_visible != value:
                    raise RuntimeError("Reverse foot visibility failed: " + suffix + pivot)
    if joint_map:
        rows.extend(verify_toe_ik(blueprint, joint_map))
    return rows


def verify_toe_ik(blueprint, joint_map):
    """Regression for pelvis lift: SC aims at planted goals without stretching."""
    rig = blueprint.create_control_rig()
    rig.request_init()
    rig.execute_event("Construction")
    hierarchy = rig.get_hierarchy()
    def bone(slot):
        value = joint_map[slot]
        name = str(value[0] if isinstance(value, (list, tuple)) else value).split("|")[-1].split(":")[-1]
        return unreal.RigElementKey(unreal.RigElementType.BONE, name)
    def solve():
        for event in ("Pre Forwards Solve", "Forwards Solve", "Post Forwards Solve"):
            rig.execute_event(event)
    for suffix in ("L", "R"):
        key = next(k for k in hierarchy.get_all_keys() if str(k.name).startswith("Leg_" + suffix + "/")
                   and str(k.name).endswith("fk_ik_switch"))
        hierarchy.set_control_value(key, hierarchy.make_control_value_from_bool(True))
    solve()
    for side in ("Left", "Right"):
        for slot in (side + "Foot", side + "ToeBase"):
            current = hierarchy.get_global_transform(bone(slot))
            initial = hierarchy.get_global_transform(bone(slot), initial=True)
            a, b = current.translation, initial.translation
            qa, qb = current.rotation, initial.rotation
            dot = abs(qa.x*qb.x + qa.y*qb.y + qa.z*qb.z + qa.w*qb.w)
            if math.dist((a.x, a.y, a.z), (b.x, b.y, b.z)) > .001 or dot < .999999:
                raise RuntimeError("Toe IK changes neutral pose: " + slot)
    body = unreal.RigElementKey(unreal.RigElementType.CONTROL, "Spine/body_ctrl")
    transform = hierarchy.get_global_transform(body)
    p = transform.translation
    rest_foot = hierarchy.get_local_transform(bone("LeftToeBase"), initial=True).translation
    lift = 2 * math.sqrt(rest_foot.x**2 + rest_foot.y**2 + rest_foot.z**2)
    transform.translation = unreal.Vector(p.x, p.y, p.z + lift)
    hierarchy.set_global_transform(body, transform)
    solve()
    rows = []
    for side, suffix in (("Left", "L"), ("Right", "R")):
        ankle, toe = bone(side + "Foot"), bone(side + "ToeBase")
        target = unreal.RigElementKey(unreal.RigElementType.CONTROL,
                                     "Foot_" + suffix + "/" + str(ankle.name) + "_ball_ik_ctrl")
        a, b, t = (hierarchy.get_global_transform(k).translation for k in (ankle, toe, target))
        segment = [getattr(b, c) - getattr(a, c) for c in "xyz"]
        desired = [getattr(t, c) - getattr(a, c) for c in "xyz"]
        length = math.sqrt(sum(v*v for v in segment))
        goal_length = math.sqrt(sum(v*v for v in desired))
        cosine = sum(v*w for v, w in zip(segment, desired)) / (length * goal_length)
        rest = hierarchy.get_local_transform(toe, initial=True).translation
        rest_length = math.sqrt(rest.x**2 + rest.y**2 + rest.z**2)
        if cosine < .99999 or abs(length-rest_length) > .001:
            raise RuntimeError("Toe IK does not preserve aimed bone length: " + side)
        rows.append((side, "pelvis_lift_toe_ik", round(cosine, 8), round(length-rest_length, 8)))
    return rows
