import unreal


def get_blueprint_graphs(blueprint):
    if not blueprint or not isinstance(blueprint, unreal.Blueprint):
        unreal.log_warning(f"Not a valid Blueprint asset: {blueprint}")
        return []

    editor_utility_library = unreal.EditorUtilityLibrary()
    graphs = editor_utility_library.get_blueprint_graphs(blueprint)
    return graphs


def add_custom_events_to_blueprint(bp_path, event_names):
    """
    Ensures each name in `event_names` exists as a custom event inside the Blueprint at `bp_path`.
    If it doesn't exist, it creates the event.
    :param event_names: List of new attribute events to add to the bp
    :param bp_path: Path to the Blueprint to update (e.g., "/Game/Blueprints/MyBP")
    """
    # Load the Blueprint asset
    blueprint = unreal.load_asset(bp_path)
    if not blueprint:
        unreal.log_error(f"Blueprint not found: {bp_path}")
        return

    editor_subsystem = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
    editor_subsystem.open_editor_for_assets([blueprint])

    # Get the Event Graph
    all_graphs = get_blueprint_graphs(blueprint)

    event_graph = None
    for graph in all_graphs:
        if graph.get_name() == "EventGraph":
            event_graph = graph
            break

    if not event_graph:
        unreal.log_error("Event Graph not found in Blueprint.")
        return

    # Find existing event names
    existing_nodes = unreal.KismetEditorUtilities.get_all_nodes_for_blueprint(blueprint)
    existing_event_names = [
        node.get_name()
        for node in existing_nodes
        if isinstance(node, unreal.K2Node_CustomEvent)
    ]

    # Add missing custom events
    for event_name in event_names:
        if event_name in existing_event_names:
            unreal.log(f"Event '{event_name}' already exists.")
            continue

        # Create the custom event node
        custom_event_node = unreal.K2Node_CustomEvent()
        event_graph_node = unreal.KismetEditorUtilities.create_node(event_graph, custom_event_node, 0, 0)
        event_graph_node.set_name(event_name)
        unreal.log(f"Added custom event: {event_name}")

    # Compile and save the Blueprint
    unreal.EditorAssetLibrary.save_asset(bp_path)
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)


def get_valid_events_from_import(imported_events, bp_class):
    """

    :param imported_events:
    :param bp_class:
    :return:
    """
    valid = []
    for func in unreal.get_functions(bp_class):
        if func.has_function_flag(unreal.FunctionFlags.FUNCTION_BlueprintCallable):
            name = func.get_name()
            if name in imported_events:
                valid.append(name)
    return valid
