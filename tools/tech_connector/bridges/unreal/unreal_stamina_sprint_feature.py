"""Blueprint authoring helpers for the approved stamina/sprint feature."""

from __future__ import annotations


COMPONENT_PATH = "/Game/TimeFighters/Blueprints/Components/BPC_StaminaSprint"
CHARACTER_PATH = "/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter"

VARIABLES = (
    ("MaxStamina", "real", "100.0"),
    ("Stamina", "real", "100.0"),
    ("DrainPerSecond", "real", "20.0"),
    ("RecoveryPerSecond", "real", "15.0"),
    ("RecoveryDelay", "real", "1.0"),
    ("WalkSpeed", "real", "600.0"),
    ("SprintSpeed", "real", "900.0"),
    ("TimeSinceSprint", "real", "0.0"),
    ("bIsSprinting", "bool", "false"),
)


def _pin(unreal, node, *names):
    wanted = {str(name).lower().replace(" ", "") for name in names}
    for pin in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
        name = str(unreal.BlueprintGraphPinLibrary.get_pin_name(pin))
        if name.lower().replace(" ", "") in wanted:
            return pin
    return None


def _connect(unreal, source, target, label):
    if source is None or target is None:
        raise RuntimeError("Missing pin for connection: " + label)
    if not unreal.BlueprintGraphPinLibrary.try_create_connection(source, target):
        raise RuntimeError("Could not connect pins: " + label)


def _set_value(unreal, pin, value, label):
    if pin is None:
        raise RuntimeError("Missing value pin: " + label)
    if not unreal.BlueprintGraphPinLibrary.set_pin_value(pin, str(value)):
        raise RuntimeError("Could not set pin value: " + label)


def _set_pos(unreal, node, x, y):
    unreal.BlueprintEditorLibrary.set_node_pos(node, unreal.IntPoint(int(x), int(y)))


def _function_editor(unreal, blueprint, name):
    graph_names = {str(value) for value in unreal.BlueprintEditorLibrary.list_graph_names(blueprint) or []}
    if name in graph_names:
        return unreal.BlueprintGraphEditor.get_graph_editor_by_name(blueprint, name), False
    return unreal.BlueprintGraphEditor.create_and_edit_function_graph(blueprint, name), True


def _operator(unreal, editor, name, context_pin, x, y):
    node = editor.create_node_from_name(
        "Utilities|Operators|" + name,
        unreal.Vector2D(float(x), float(y)),
        [context_pin] if context_pin is not None else [],
        None,
    )
    if node is None:
        raise RuntimeError("Could not create operator: " + name)
    _set_pos(unreal, node, x, y)
    return node


def _author_start_stop(unreal, blueprint, name, sprinting):
    editor, created = _function_editor(unreal, blueprint, name)
    nodes = list(editor.list_all_nodes() or [])
    if not created and len(nodes) > 1:
        return {"name": name, "created": False, "node_count": len(nodes)}
    entry = editor.find_graph_entry_pin()
    set_sprinting = editor.add_set_member_variable_node("bIsSprinting")
    set_elapsed = editor.add_set_member_variable_node("TimeSinceSprint")
    _set_pos(unreal, entry.get_owning_node(), 0, 0)
    _set_pos(unreal, set_sprinting, 320, 0)
    _set_pos(unreal, set_elapsed, 640, 0)
    _set_value(unreal, _pin(unreal, set_sprinting, "bIsSprinting"), "true" if sprinting else "false", name)
    _set_value(unreal, _pin(unreal, set_elapsed, "TimeSinceSprint"), "0.0", name)
    _connect(unreal, entry, _pin(unreal, set_sprinting, "execute"), name + " entry")
    _connect(
        unreal,
        _pin(unreal, set_sprinting, "then"),
        _pin(unreal, set_elapsed, "execute"),
        name + " sequence",
    )
    editor.add_comment_to_nodes(name + " state transition", [set_sprinting, set_elapsed], 48)
    return {"name": name, "created": created, "node_count": len(editor.list_all_nodes() or [])}


def _author_can_sprint(unreal, blueprint):
    editor, created = _function_editor(unreal, blueprint, "CanSprint")
    nodes = list(editor.list_all_nodes() or [])
    if not created and len(nodes) > 1:
        return {"name": "CanSprint", "created": False, "node_count": len(nodes)}
    bool_type = unreal.BlueprintEditorLibrary.get_basic_type_by_name("bool")
    result_node = editor.add_graph_output_parameter("CanSprint", bool_type)
    entry = editor.find_graph_entry_pin()
    stamina = editor.add_get_member_variable_node("Stamina")
    stamina_value = _pin(unreal, stamina, "Stamina")
    greater = editor.create_node_from_name(
        "Utilities|Operators|Greater(>)", unreal.Vector2D(400.0, 160.0), [stamina_value], None
    )
    _set_pos(unreal, entry.get_owning_node(), 0, 0)
    _set_pos(unreal, stamina, 80, 160)
    _set_pos(unreal, greater, 400, 160)
    _set_pos(unreal, result_node, 760, 0)
    inputs = list(unreal.BlueprintEditorLibrary.list_input_pins(greater) or [])
    outputs = list(unreal.BlueprintEditorLibrary.list_output_pins(greater) or [])
    if len(inputs) < 2 or not outputs:
        raise RuntimeError("Greater operator did not expose expected pins")
    _connect(unreal, stamina_value, inputs[0], "CanSprint stamina")
    _set_value(unreal, inputs[1], "0.0", "CanSprint threshold")
    _connect(unreal, outputs[0], _pin(unreal, result_node, "CanSprint"), "CanSprint result")
    _connect(unreal, entry, _pin(unreal, result_node, "execute"), "CanSprint exec")
    editor.add_comment_to_nodes("Stamina availability", [stamina, greater], 48)
    return {"name": "CanSprint", "created": created, "node_count": len(editor.list_all_nodes() or [])}


def _author_drain_stamina(unreal, blueprint):
    editor, created = _function_editor(unreal, blueprint, "DrainStamina")
    nodes = list(editor.list_all_nodes() or [])
    if not created and len(nodes) > 1:
        return {"name": "DrainStamina", "created": False, "node_count": len(nodes)}
    real_type = unreal.BlueprintEditorLibrary.get_basic_type_by_name("real")
    delta = editor.add_graph_input_parameter("DeltaSeconds", real_type, "0.0")
    entry = editor.find_graph_entry_pin()
    is_sprinting = editor.add_get_member_variable_node("bIsSprinting")
    branch = editor.add_branch_node()
    stamina = editor.add_get_member_variable_node("Stamina")
    drain_rate = editor.add_get_member_variable_node("DrainPerSecond")
    max_stamina = editor.add_get_member_variable_node("MaxStamina")
    multiply = _operator(unreal, editor, "Multiply", _pin(unreal, drain_rate, "DrainPerSecond"), 560, 240)
    subtract = _operator(unreal, editor, "Subtract", _pin(unreal, stamina, "Stamina"), 840, 160)
    clamp = editor.create_node_from_name(
        "Math|Float|Clamp(Float)", unreal.Vector2D(1120.0, 160.0), [_pin(unreal, subtract, "ReturnValue")], None
    )
    set_stamina = editor.add_set_member_variable_node("Stamina")
    _set_pos(unreal, entry.get_owning_node(), 0, 0)
    _set_pos(unreal, is_sprinting, 0, 180)
    _set_pos(unreal, branch, 280, 0)
    _set_pos(unreal, stamina, 560, 80)
    _set_pos(unreal, drain_rate, 280, 280)
    _set_pos(unreal, max_stamina, 840, 360)
    _set_pos(unreal, clamp, 1120, 160)
    _set_pos(unreal, set_stamina, 1440, 0)
    _connect(unreal, entry, _pin(unreal, branch, "execute"), "Drain entry")
    _connect(unreal, _pin(unreal, is_sprinting, "bIsSprinting"), _pin(unreal, branch, "condition"), "Drain condition")
    _connect(unreal, _pin(unreal, branch, "then"), _pin(unreal, set_stamina, "execute"), "Drain exec")
    multiply_inputs = list(unreal.BlueprintEditorLibrary.list_input_pins(multiply) or [])
    subtract_inputs = list(unreal.BlueprintEditorLibrary.list_input_pins(subtract) or [])
    if len(multiply_inputs) < 2 or len(subtract_inputs) < 2:
        raise RuntimeError("Drain math nodes did not expose expected pins")
    _connect(unreal, _pin(unreal, drain_rate, "DrainPerSecond"), multiply_inputs[0], "Drain rate")
    _connect(unreal, delta, multiply_inputs[1], "Drain delta")
    _connect(unreal, _pin(unreal, stamina, "Stamina"), subtract_inputs[0], "Drain stamina")
    _connect(unreal, list(unreal.BlueprintEditorLibrary.list_output_pins(multiply) or [None])[0], subtract_inputs[1], "Drain amount")
    clamp_value = _pin(unreal, clamp, "Value")
    _connect(unreal, list(unreal.BlueprintEditorLibrary.list_output_pins(subtract) or [None])[0], clamp_value, "Drain clamp value")
    _set_value(unreal, _pin(unreal, clamp, "Min"), "0.0", "Drain clamp min")
    _connect(unreal, _pin(unreal, max_stamina, "MaxStamina"), _pin(unreal, clamp, "Max"), "Drain clamp max")
    _connect(unreal, _pin(unreal, clamp, "ReturnValue"), _pin(unreal, set_stamina, "Stamina"), "Drain result")
    editor.add_comment_to_nodes("Drain stamina while sprinting", [branch, stamina, drain_rate, multiply, subtract, clamp, set_stamina], 64)
    return {"name": "DrainStamina", "created": created, "node_count": len(editor.list_all_nodes() or [])}


def _author_recover_stamina(unreal, blueprint):
    editor, created = _function_editor(unreal, blueprint, "RecoverStamina")
    nodes = list(editor.list_all_nodes() or [])
    if not created and len(nodes) > 1:
        repaired = _repair_recover_delay_dataflow(unreal, editor)
        return {
            "name": "RecoverStamina",
            "created": False,
            "repaired_delay_dataflow": repaired,
            "node_count": len(nodes),
        }
    real_type = unreal.BlueprintEditorLibrary.get_basic_type_by_name("real")
    delta = editor.add_graph_input_parameter("DeltaSeconds", real_type, "0.0")
    entry = editor.find_graph_entry_pin()
    is_sprinting = editor.add_get_member_variable_node("bIsSprinting")
    idle_branch = editor.add_branch_node()
    elapsed = editor.add_get_member_variable_node("TimeSinceSprint")
    add_elapsed = _operator(unreal, editor, "Add", _pin(unreal, elapsed, "TimeSinceSprint"), 560, 240)
    set_elapsed = editor.add_set_member_variable_node("TimeSinceSprint")
    delay = editor.add_get_member_variable_node("RecoveryDelay")
    ready = _operator(unreal, editor, "GreaterEqual(>=)", _pin(unreal, add_elapsed, "ReturnValue"), 1120, 240)
    ready_branch = editor.add_branch_node()
    stamina = editor.add_get_member_variable_node("Stamina")
    recovery_rate = editor.add_get_member_variable_node("RecoveryPerSecond")
    max_stamina = editor.add_get_member_variable_node("MaxStamina")
    multiply = _operator(unreal, editor, "Multiply", _pin(unreal, recovery_rate, "RecoveryPerSecond"), 1680, 400)
    add_stamina = _operator(unreal, editor, "Add", _pin(unreal, stamina, "Stamina"), 1960, 240)
    clamp = editor.create_node_from_name(
        "Math|Float|Clamp(Float)", unreal.Vector2D(2240.0, 240.0), [_pin(unreal, add_stamina, "ReturnValue")], None
    )
    set_stamina = editor.add_set_member_variable_node("Stamina")
    positions = [
        (entry.get_owning_node(), 0, 0), (is_sprinting, 0, 180), (idle_branch, 280, 0),
        (elapsed, 280, 240), (add_elapsed, 560, 240), (set_elapsed, 840, 0),
        (delay, 840, 360), (ready, 1120, 240), (ready_branch, 1400, 0),
        (stamina, 1680, 160), (recovery_rate, 1400, 440), (max_stamina, 1960, 480),
        (multiply, 1680, 400), (add_stamina, 1960, 240), (clamp, 2240, 240), (set_stamina, 2560, 0),
    ]
    for node, x, y in positions:
        _set_pos(unreal, node, x, y)
    _connect(unreal, entry, _pin(unreal, idle_branch, "execute"), "Recover entry")
    _connect(unreal, _pin(unreal, is_sprinting, "bIsSprinting"), _pin(unreal, idle_branch, "condition"), "Recover sprint state")
    _connect(unreal, _pin(unreal, idle_branch, "else"), _pin(unreal, set_elapsed, "execute"), "Recover idle path")
    elapsed_inputs = list(unreal.BlueprintEditorLibrary.list_input_pins(add_elapsed) or [])
    _connect(unreal, _pin(unreal, elapsed, "TimeSinceSprint"), elapsed_inputs[0], "Recover elapsed")
    _connect(unreal, delta, elapsed_inputs[1], "Recover elapsed delta")
    elapsed_value = list(unreal.BlueprintEditorLibrary.list_output_pins(add_elapsed) or [None])[0]
    _connect(unreal, elapsed_value, _pin(unreal, set_elapsed, "TimeSinceSprint"), "Recover elapsed result")
    _connect(unreal, _pin(unreal, set_elapsed, "then"), _pin(unreal, ready_branch, "execute"), "Recover ready exec")
    ready_inputs = list(unreal.BlueprintEditorLibrary.list_input_pins(ready) or [])
    _connect(
        unreal,
        _pin(unreal, set_elapsed, "Output_Get"),
        ready_inputs[0],
        "Recover stored delay elapsed",
    )
    _connect(unreal, _pin(unreal, delay, "RecoveryDelay"), ready_inputs[1], "Recover delay")
    _connect(unreal, list(unreal.BlueprintEditorLibrary.list_output_pins(ready) or [None])[0], _pin(unreal, ready_branch, "condition"), "Recover ready")
    _connect(unreal, _pin(unreal, ready_branch, "then"), _pin(unreal, set_stamina, "execute"), "Recover exec")
    multiply_inputs = list(unreal.BlueprintEditorLibrary.list_input_pins(multiply) or [])
    _connect(unreal, _pin(unreal, recovery_rate, "RecoveryPerSecond"), multiply_inputs[0], "Recover rate")
    _connect(unreal, delta, multiply_inputs[1], "Recover delta")
    add_inputs = list(unreal.BlueprintEditorLibrary.list_input_pins(add_stamina) or [])
    _connect(unreal, _pin(unreal, stamina, "Stamina"), add_inputs[0], "Recover stamina")
    _connect(unreal, list(unreal.BlueprintEditorLibrary.list_output_pins(multiply) or [None])[0], add_inputs[1], "Recover amount")
    _connect(unreal, list(unreal.BlueprintEditorLibrary.list_output_pins(add_stamina) or [None])[0], _pin(unreal, clamp, "Value"), "Recover clamp")
    _set_value(unreal, _pin(unreal, clamp, "Min"), "0.0", "Recover clamp min")
    _connect(unreal, _pin(unreal, max_stamina, "MaxStamina"), _pin(unreal, clamp, "Max"), "Recover clamp max")
    _connect(unreal, _pin(unreal, clamp, "ReturnValue"), _pin(unreal, set_stamina, "Stamina"), "Recover result")
    editor.add_comment_to_nodes("Delayed stamina recovery", [idle_branch, elapsed, add_elapsed, set_elapsed, ready, ready_branch, stamina, recovery_rate, multiply, add_stamina, clamp, set_stamina], 64)
    return {"name": "RecoverStamina", "created": created, "node_count": len(editor.list_all_nodes() or [])}


def _repair_recover_delay_dataflow(unreal, editor):
    """Use the stored elapsed value so pure-node reevaluation cannot double DeltaSeconds."""

    nodes = list(editor.list_all_nodes() or [])
    set_elapsed = next(
        (
            node
            for node in nodes
            if str(unreal.BlueprintEditorLibrary.get_node_title(node)) == "Set TimeSinceSprint"
        ),
        None,
    )
    ready = next(
        (
            node
            for node in nodes
            if str(unreal.BlueprintEditorLibrary.get_node_title(node)) == "float >= float"
        ),
        None,
    )
    stored_elapsed = _pin(unreal, set_elapsed, "Output_Get") if set_elapsed else None
    ready_inputs = list(unreal.BlueprintEditorLibrary.list_input_pins(ready) or []) if ready else []
    if stored_elapsed is None or len(ready_inputs) < 2:
        raise RuntimeError("RecoverStamina delay nodes could not be resolved")
    ready_elapsed = ready_inputs[0]
    connected = list(unreal.BlueprintGraphPinLibrary.list_connected_pins(ready_elapsed) or [])
    if any(unreal.BlueprintGraphPinLibrary.is_same_native_pin(pin, stored_elapsed) for pin in connected):
        return False
    unreal.BlueprintGraphPinLibrary.break_pin_links(ready_elapsed)
    _connect(unreal, stored_elapsed, ready_elapsed, "Recover stored delay elapsed repair")
    return True


def _author_tick(unreal, blueprint):
    editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(blueprint, "EventGraph")
    nodes = list(editor.list_all_nodes() or [])
    by_title = {str(unreal.BlueprintEditorLibrary.get_node_title(node)): node for node in nodes}
    if "DrainStamina" in by_title and "RecoverStamina" in by_title:
        return {"name": "Event Tick", "created": False, "node_count": len(nodes)}
    tick = by_title.get("Event Tick")
    if tick is None:
        tick = editor.create_node_from_name("AddEvent|EventTick", unreal.Vector2D(0.0, 0.0), [], None)
    delta = _pin(unreal, tick, "DeltaSeconds")
    drain = editor.create_node_from_name("CallFunction|DrainStamina", unreal.Vector2D(360.0, 0.0), [delta], None)
    recover = editor.create_node_from_name("CallFunction|RecoverStamina", unreal.Vector2D(720.0, 0.0), [delta], None)
    for node, x in ((tick, 0), (drain, 360), (recover, 720)):
        if node is None:
            raise RuntimeError("Could not create stamina tick node")
        _set_pos(unreal, node, x, 0)
    _connect(unreal, _pin(unreal, tick, "then"), _pin(unreal, drain, "execute"), "Tick drain")
    _connect(unreal, _pin(unreal, drain, "then"), _pin(unreal, recover, "execute"), "Tick recover")
    _connect(unreal, delta, _pin(unreal, drain, "DeltaSeconds"), "Tick drain delta")
    _connect(unreal, delta, _pin(unreal, recover, "DeltaSeconds"), "Tick recover delta")
    editor.add_comment_to_nodes("Stamina update", [tick, drain, recover], 64)
    return {"name": "Event Tick", "created": True, "node_count": len(editor.list_all_nodes() or [])}


def create_stamina_component(asset_path=COMPONENT_PATH, save=True):
    """Create the component schema and its state-transition functions."""

    import unreal

    path = str(asset_path).split(".", 1)[0]
    blueprint = unreal.EditorAssetLibrary.load_asset(path)
    created = False
    if blueprint is None:
        package, name = path.rsplit("/", 1)
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", unreal.ActorComponent)
        blueprint = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, package, unreal.Blueprint, factory
        )
        created = True
    if blueprint is None:
        raise RuntimeError("Could not create stamina component Blueprint")
    graph = unreal.BlueprintGraphEditor.get_graph_editor_by_name(blueprint, "EventGraph")
    if graph is None:
        raise RuntimeError("Stamina component has no EventGraph")
    existing = {str(value) for value in unreal.BlueprintEditorLibrary.list_member_variable_names(blueprint) or []}
    added_variables = []
    for name, type_name, default in VARIABLES:
        if name in existing:
            continue
        pin_type = unreal.BlueprintEditorLibrary.get_basic_type_by_name(type_name)
        if not graph.add_member_variable(name, pin_type, default):
            raise RuntimeError("Could not add member variable: " + name)
        added_variables.append(name)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(blueprint):
        raise RuntimeError("Component schema failed its first compile")
    functions = [
        _author_start_stop(unreal, blueprint, "StartSprint", True),
        _author_start_stop(unreal, blueprint, "StopSprint", False),
        _author_can_sprint(unreal, blueprint),
        _author_drain_stamina(unreal, blueprint),
        _author_recover_stamina(unreal, blueprint),
    ]
    if not unreal.BlueprintEditorLibrary.compile_blueprint(blueprint):
        raise RuntimeError("Stamina component behavior functions failed to compile")
    tick = _author_tick(unreal, blueprint)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(blueprint):
        raise RuntimeError("Stamina component functions failed to compile")
    if save and not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
        raise RuntimeError("Could not save stamina component Blueprint")
    return {
        "ok": True,
        "operation": "gameplay.create_stamina_component",
        "asset_path": path,
        "created": created,
        "added_variables": added_variables,
        "functions": functions,
        "tick": tick,
        "compile_ok": True,
        "saved": bool(save),
        "verified": True,
    }


def _add_component_to_blueprint(unreal, blueprint, component_class, variable_name):
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    existing = _blueprint_component_rows(unreal, blueprint)
    for row in existing:
        if row["variable_name"] == variable_name or component_class.get_path_name() in row["class_path"]:
            return row["variable_name"] or variable_name, False
    handles = list(subsystem.k2_gather_subobject_data_for_blueprint(blueprint) or [])
    if not handles:
        raise RuntimeError("Could not gather Blueprint subobjects")
    params = unreal.AddNewSubobjectParams()
    params.set_editor_property("parent_handle", handles[0])
    params.set_editor_property("new_class", component_class)
    params.set_editor_property("blueprint_context", blueprint)
    handle, fail_reason = subsystem.add_new_subobject(params)
    if not unreal.SubobjectDataBlueprintFunctionLibrary.is_handle_valid(handle):
        raise RuntimeError("Could not add stamina component: " + str(fail_reason))
    if not subsystem.rename_subobject(handle, variable_name):
        raise RuntimeError("Could not rename stamina component to " + variable_name)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(blueprint):
        raise RuntimeError("Character failed to compile after adding stamina component")
    verified = _blueprint_component_rows(unreal, blueprint)
    if not any(row["variable_name"] == variable_name for row in verified):
        raise RuntimeError("Stamina component SubobjectData postcondition failed")
    return variable_name, True


def _blueprint_component_rows(unreal, blueprint):
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    library = unreal.SubobjectDataBlueprintFunctionLibrary
    rows = []
    for handle in subsystem.k2_gather_subobject_data_for_blueprint(blueprint) or []:
        try:
            data = library.get_data(handle)
            if not library.is_component(data):
                continue
            obj = library.get_object_for_blueprint(data, blueprint)
            class_path = str(obj.get_class().get_path_name()) if obj else ""
            rows.append(
                {
                    "variable_name": str(library.get_variable_name(data)),
                    "display_name": str(library.get_display_name(data)),
                    "class_path": class_path,
                    "object_path": str(obj.get_path_name()) if obj else "",
                }
            )
        except Exception:
            continue
    return rows


def _call_node(unreal, editor, function_name, context_pin, x, y):
    node = editor.create_node_from_name(
        "CallFunction|" + function_name,
        unreal.Vector2D(float(x), float(y)),
        [context_pin] if context_pin is not None else [],
        None,
    )
    if node is None:
        raise RuntimeError("Could not create call node: " + function_name)
    _set_pos(unreal, node, x, y)
    if context_pin is not None:
        self_pin = _pin(unreal, node, "self", "target")
        if self_pin is not None:
            _connect(unreal, context_pin, self_pin, function_name + " target")
    return node


def _set_walk_speed_node(unreal, editor, movement_pin, speed, x, y):
    node = editor.add_set_member_variable_node(
        "MaxWalkSpeed", "/Script/Engine.CharacterMovementComponent"
    )
    _set_pos(unreal, node, x, y)
    target = _pin(unreal, node, "self", "target")
    if target is not None:
        _connect(unreal, movement_pin, target, "MaxWalkSpeed target")
    _set_value(unreal, _pin(unreal, node, "MaxWalkSpeed"), str(speed), "MaxWalkSpeed")
    return node


def _graph_clear_band(unreal, editor):
    positions = []
    for node in editor.list_all_nodes() or []:
        try:
            positions.append(unreal.BlueprintEditorLibrary.get_node_pos(node))
        except Exception:
            pass
    max_y = max((int(point.y) for point in positions), default=0)
    return ((max_y + 799) // 400) * 400


def integrate_stamina_character(
    character_path=CHARACTER_PATH,
    component_path=COMPONENT_PATH,
    save=True,
):
    """Add the stamina component and clean IA_Sprint glue to the character."""

    import unreal

    character = unreal.EditorAssetLibrary.load_asset(str(character_path).split(".", 1)[0])
    component_bp = unreal.EditorAssetLibrary.load_asset(str(component_path).split(".", 1)[0])
    if character is None or component_bp is None:
        raise ValueError("Character or stamina component Blueprint could not be loaded")
    component_class = unreal.BlueprintEditorLibrary.generated_class(component_bp)
    component_name, component_added = _add_component_to_blueprint(
        unreal, character, component_class, "StaminaSprint"
    )
    editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(character, "EventGraph")
    existing_titles = {
        str(unreal.BlueprintEditorLibrary.get_node_title(node))
        for node in editor.list_all_nodes() or []
    }
    if "EnhancedInputAction IA_Sprint" in existing_titles:
        return {
            "ok": True,
            "operation": "gameplay.integrate_stamina_character",
            "character_path": character_path,
            "component_added": component_added,
            "graph_added": False,
            "compile_ok": True,
            "saved": False,
            "verified": True,
        }

    base_y = _graph_clear_band(unreal, editor)
    event = editor.create_node_from_name(
        "Input|EnhancedActionEvents|IA_Sprint",
        unreal.Vector2D(0.0, float(base_y)),
        [],
        None,
    )
    if event is None:
        raise RuntimeError("Could not create IA_Sprint event node")
    _set_pos(unreal, event, 0, base_y)
    component_get = editor.add_get_member_variable_node(component_name)
    movement_get = editor.add_get_member_variable_node("CharacterMovement")
    _set_pos(unreal, component_get, 320, base_y + 1280)
    _set_pos(unreal, movement_get, 1280, base_y + 1280)
    component_pin = _pin(unreal, component_get, component_name)
    movement_pin = _pin(unreal, movement_get, "CharacterMovement")

    created_nodes = [event, component_get, movement_get]
    rows = {
        "started": (base_y, True, 900.0),
        "triggered": (base_y + 360, False, 600.0),
        "completed": (base_y + 720, None, 600.0),
        "canceled": (base_y + 1080, None, 600.0),
    }
    for event_pin_name, (row_y, requires_available, speed) in rows.items():
        source_exec = _pin(unreal, event, event_pin_name)
        if requires_available is not None:
            can_sprint = _call_node(unreal, editor, "CanSprint", component_pin, 400, row_y)
            branch = editor.add_branch_node()
            _set_pos(unreal, branch, 720, row_y)
            _connect(unreal, source_exec, _pin(unreal, can_sprint, "execute"), event_pin_name + " CanSprint")
            _connect(unreal, _pin(unreal, can_sprint, "then"), _pin(unreal, branch, "execute"), event_pin_name + " branch")
            _connect(unreal, _pin(unreal, can_sprint, "CanSprint", "ReturnValue"), _pin(unreal, branch, "condition"), event_pin_name + " condition")
            source_exec = _pin(unreal, branch, "then" if requires_available else "else")
            created_nodes.extend([can_sprint, branch])
        function_name = "StartSprint" if event_pin_name == "started" else "StopSprint"
        state_call = _call_node(unreal, editor, function_name, component_pin, 1040, row_y)
        speed_set = _set_walk_speed_node(unreal, editor, movement_pin, speed, 1440, row_y)
        _connect(unreal, source_exec, _pin(unreal, state_call, "execute"), event_pin_name + " state")
        _connect(unreal, _pin(unreal, state_call, "then"), _pin(unreal, speed_set, "execute"), event_pin_name + " speed")
        created_nodes.extend([state_call, speed_set])

    editor.add_comment_to_nodes("Stamina Sprint Input", created_nodes, 96)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(character):
        raise RuntimeError("Character stamina integration failed to compile")
    if save and not unreal.EditorAssetLibrary.save_loaded_asset(character, False):
        raise RuntimeError("Could not save character stamina integration")
    return {
        "ok": True,
        "operation": "gameplay.integrate_stamina_character",
        "character_path": character_path,
        "component_name": component_name,
        "component_added": component_added,
        "graph_added": True,
        "graph_band_y": base_y,
        "created_node_count": len(created_nodes),
        "compile_ok": True,
        "saved": bool(save),
        "verified": True,
    }


def _function_names(unreal, blueprint):
    names = set()
    for value in unreal.BlueprintEditorLibrary.list_functions(blueprint) or []:
        text = str(value)
        marker = 'name: "'
        start = text.find(marker)
        if start >= 0:
            start += len(marker)
            end = text.find('"', start)
            names.add(text[start:end] if end >= 0 else text[start:])
    return names


def _feature_layout_report(unreal, blueprint):
    graph = unreal.BlueprintEditorLibrary.find_event_graph(blueprint)
    feature_nodes = []
    for node in unreal.BlueprintGraphEditor.get_graph_editor_by_name(blueprint, "EventGraph").list_comment_nodes() or []:
        try:
            if str(unreal.BlueprintEditorLibrary.get_comment_text(node)) == "Stamina Sprint Input":
                feature_nodes = list(unreal.BlueprintEditorLibrary.get_nodes_in_comment(node) or [])
                break
        except Exception:
            continue
    if not feature_nodes:
        return {"ok": False, "errors": ["Stamina Sprint Input comment group was not found."], "node_count": 0}
    bounds = []
    for node in feature_nodes:
        position = unreal.BlueprintEditorLibrary.get_node_pos(node)
        size = unreal.BlueprintEditorLibrary.get_node_size(node)
        width = max(220, int(getattr(size, "x", 0) or 0))
        height = max(120, int(getattr(size, "y", 0) or 0))
        bounds.append((str(node.get_name()), int(position.x), int(position.y), width, height))
    overlaps = []
    for index, left in enumerate(bounds):
        for right in bounds[index + 1 :]:
            separated = (
                left[1] + left[3] + 24 <= right[1]
                or right[1] + right[3] + 24 <= left[1]
                or left[2] + left[4] + 24 <= right[2]
                or right[2] + right[4] + 24 <= left[2]
            )
            if not separated:
                overlaps.append([left[0], right[0]])
    return {
        "ok": not overlaps,
        "node_count": len(feature_nodes),
        "overlaps": overlaps,
        "flow_direction": "left_to_right",
        "comment_group": "Stamina Sprint Input",
    }


def _transient_component_behavior_report(unreal, component):
    """Exercise the compiled Blueprint class without requiring a PIE world."""

    import uuid

    errors = []
    observations = {}
    try:
        component_class = unreal.BlueprintEditorLibrary.generated_class(component)

        recovery = unreal.new_object(
            component_class,
            name="StaminaRecoveryProbe_" + uuid.uuid4().hex,
        )
        recovery.call_method("StartSprint", ())
        recovery.call_method("DrainStamina", (1.0,))
        drained = float(recovery.get_editor_property("Stamina"))
        started = bool(recovery.get_editor_property("bIsSprinting"))
        recovery.call_method("StopSprint", ())
        stopped = not bool(recovery.get_editor_property("bIsSprinting"))
        recovery.call_method("RecoverStamina", (0.5,))
        before_delay = float(recovery.get_editor_property("Stamina"))
        elapsed_before_delay = float(recovery.get_editor_property("TimeSinceSprint"))
        recovery.call_method("RecoverStamina", (0.5,))
        at_delay = float(recovery.get_editor_property("Stamina"))
        recovery.call_method("RecoverStamina", (10.0,))
        clamped = float(recovery.get_editor_property("Stamina"))

        exhausted = unreal.new_object(
            component_class,
            name="StaminaExhaustionProbe_" + uuid.uuid4().hex,
        )
        exhausted.call_method("StartSprint", ())
        exhausted.call_method("DrainStamina", (10.0,))
        exhausted_stamina = float(exhausted.get_editor_property("Stamina"))
        can_sprint = bool(exhausted.call_method("CanSprint", ()))

        observations = {
            "started": started,
            "drained_stamina": drained,
            "stopped": stopped,
            "stamina_before_recovery_delay": before_delay,
            "elapsed_before_recovery_delay": elapsed_before_delay,
            "stamina_at_recovery_delay": at_delay,
            "clamped_stamina": clamped,
            "exhausted_stamina": exhausted_stamina,
            "can_sprint_when_exhausted": can_sprint,
        }
        checks = (
            (started, "StartSprint did not enable sprinting."),
            (abs(drained - 80.0) < 0.001, "DrainStamina did not apply its configured rate."),
            (stopped, "StopSprint did not disable sprinting."),
            (abs(before_delay - 80.0) < 0.001, "Stamina recovered before RecoveryDelay elapsed."),
            (abs(elapsed_before_delay - 0.5) < 0.001, "Recovery elapsed time was not accumulated correctly."),
            (at_delay > before_delay, "Stamina did not recover when RecoveryDelay elapsed."),
            (abs(clamped - 100.0) < 0.001, "Recovered stamina did not clamp to MaxStamina."),
            (abs(exhausted_stamina) < 0.001, "Drained stamina did not clamp to zero."),
            (not can_sprint, "CanSprint remained true with zero stamina."),
        )
        errors.extend(message for passed, message in checks if not passed)
    except Exception as exc:
        errors.append("Transient component behavior test failed: " + str(exc))
    return {"ok": not errors, "observations": observations, "errors": errors}


def validate_stamina_feature():
    """Compile and read back every required stamina/sprint postcondition."""

    import unreal
    from tech_connector.bridges.unreal.unreal_enhanced_input import (
        _mapping_identity,
        _mapping_rows,
        _object_path,
    )

    component = unreal.EditorAssetLibrary.load_asset(COMPONENT_PATH)
    character = unreal.EditorAssetLibrary.load_asset(CHARACTER_PATH)
    action = unreal.EditorAssetLibrary.load_asset("/Game/TimeFighters/Input/IA_Sprint")
    context = unreal.EditorAssetLibrary.load_asset("/Game/Input/IMC_Default")
    errors = []
    compile_ok = bool(
        component
        and character
        and unreal.BlueprintEditorLibrary.compile_blueprint(component)
        and unreal.BlueprintEditorLibrary.compile_blueprint(character)
    )
    if not compile_ok:
        errors.append("One or more touched Blueprints failed to compile.")
    variables = set(unreal.BlueprintEditorLibrary.list_member_variable_names(component) or []) if component else set()
    expected_variables = {name for name, _type_name, _default in VARIABLES}
    if not expected_variables.issubset({str(value) for value in variables}):
        errors.append("Stamina component variables are incomplete.")
    functions = _function_names(unreal, component) if component else set()
    expected_functions = {"StartSprint", "StopSprint", "CanSprint", "DrainStamina", "RecoverStamina"}
    if not expected_functions.issubset(functions):
        errors.append("Stamina component functions are incomplete.")
    component_attached = False
    character_components = []
    if character and component:
        character_components = _blueprint_component_rows(unreal, character)
        component_attached = any(
            row["variable_name"] == "StaminaSprint"
            or "BPC_StaminaSprint" in row["class_path"]
            for row in character_components
        )
    if not component_attached:
        errors.append("BP_ThirdPersonCharacter does not contain BPC_StaminaSprint.")
    event_titles = set()
    if character:
        editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(character, "EventGraph")
        event_titles = {str(unreal.BlueprintEditorLibrary.get_node_title(node)) for node in editor.list_all_nodes() or []}
    input_event_ok = "EnhancedInputAction IA_Sprint" in event_titles
    if not input_event_ok:
        errors.append("IA_Sprint event graph integration is missing.")
    mapping_identities = {_mapping_identity(row) for row in _mapping_rows(context)} if context else set()
    action_identity = _object_path(action) if action else ""
    input_mappings_ok = all(
        (action_identity, key) in mapping_identities
        for key in ("LeftShift", "Gamepad_LeftShoulder")
    )
    if not input_mappings_ok:
        errors.append("IA_Sprint mappings are incomplete.")
    layout = _feature_layout_report(unreal, character) if character else {"ok": False, "errors": ["Character missing"]}
    if not layout.get("ok"):
        errors.append("Stamina Sprint Input graph layout contains overlaps or is ungrouped.")
    behavior = (
        _transient_component_behavior_report(unreal, component)
        if component and compile_ok
        else {"ok": False, "observations": {}, "errors": ["Component did not compile."]}
    )
    errors.extend(behavior.get("errors") or [])
    return {
        "ok": not errors,
        "operation": "gameplay.validate_stamina_feature",
        "compile_ok": compile_ok,
        "variables_ok": expected_variables.issubset({str(value) for value in variables}),
        "functions_ok": expected_functions.issubset(functions),
        "component_attached": component_attached,
        "character_components": character_components,
        "input_event_ok": input_event_ok,
        "input_mappings_ok": input_mappings_ok,
        "layout_ok": bool(layout.get("ok")),
        "layout": layout,
        "behavior_ok": bool(behavior.get("ok")),
        "behavior": behavior,
        "errors": errors,
        "verified": not errors,
    }
