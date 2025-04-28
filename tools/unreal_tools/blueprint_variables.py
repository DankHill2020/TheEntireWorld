import unreal

def detect_new_custom_attrs_from_animation(anim_path, bp_path):
    """

    :param anim_path: Path to Anim Sequence
    :param bp_path: Path to the Blueprint to query and edit
    :return:
    """
    anim_sequence = unreal.load_asset(anim_path)
    if not anim_sequence:
        unreal.log_warning(f"Could not load animation: {anim_path}")
        return
    custom_attr_names = unreal.AnimationLibrary.get_animation_curve_names(anim_sequence, unreal.RawCurveTrackTypes.RCT_FLOAT)
    add_variables_to_blueprint(bp_path, custom_attr_names)


def add_variables_to_blueprint(bp_path, variable_names):
    """
    Adds a list of variables to a Blueprint and exposes them to cinematics.

    :param bp_path: Blueprint path to add the variables to
    :param variable_names: List of variable names from curves
    """
    blueprint = unreal.load_asset(bp_path)

    for variable_name in variable_names:
        try:
            unreal.BlueprintEditorLibrary.set_blueprint_variable_expose_to_cinematics(blueprint, variable_name, True)
        except:
            float_pin = unreal.BlueprintEditorLibrary.get_basic_type_by_name("real")
            unreal.BlueprintEditorLibrary.add_member_variable(
                blueprint, variable_name, float_pin)
            unreal.BlueprintEditorLibrary.set_blueprint_variable_expose_to_cinematics(blueprint, variable_name, True)

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        unreal.EditorAssetLibrary.save_asset(bp_path)

    unreal.BlueprintEditorLibrary.refresh_open_editors_for_blueprint(blueprint)

# Usage example
anim_path = '/Game/Animation/Gameplay/FakeGameplay'
bp_path = '/Game/BP_Test'
detect_new_custom_attrs_from_animation(anim_path, bp_path)

