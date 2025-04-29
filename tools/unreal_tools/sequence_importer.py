import json
import os
import unreal

'''script_dir = os.path.dirname(__file__)
tools_dir = os.path.dirname(script_dir)
art_source_dir = tools_dir.replace("tools", "ArtSource").replace("\\", "/")
content_dir = "/Game"
'''
def add_actor_to_level_sequence(sequence_path, asset_path, actor=None, possessable=None, namespace=None):
    """
    Adds a blueprint actor and its components to a level sequence, creating and binding the actor and components.

    :param sequence_path: The level sequence path to which the actor and components will be added.
    :param asset_path: The path to the blueprint or skeletal mesh asset to load and spawn.
    :param actor: The actor to be added to the sequence (optional). If not provided, the actor will be spawned.
    :param possessable: The possessable to bind to the actor (optional). If not provided, it will be created.
    :param namespace: The namespace to use for the actor (optional). If not provided, it will be use the SK mesh name

    :return: A list containing the possessable, the actor, and the component list (if any).
    """
    level_sequence = load_level_sequence(sequence_path)
    if not level_sequence:
        unreal.log_error(f"Failed to load level sequence at {sequence_path}")
        return [None, None]

    asset = unreal.load_asset(asset_path)
    if not asset:
        unreal.log_error(f"Failed to load asset at {asset_path}")
        return [None, None]

    if not actor:
        if isinstance(asset, unreal.Blueprint):

            actor, possessable, component_list = find_actor_by_blueprint_or_skeletal_mesh(blueprint_path=asset_path, skeletal_mesh_path=None,
                                                     shot_sequence=level_sequence)
            if not actor:

                actor = unreal.EditorLevelLibrary.spawn_actor_from_object(asset, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))

        elif isinstance(asset, unreal.SkeletalMesh):
            skeletal_mesh_actor_class = unreal.SkeletalMeshActor
            all_actors = unreal.EditorLevelLibrary.get_all_level_actors()

            for a in all_actors:
                if namespace:
                    if isinstance(a, unreal.SkeletalMeshActor):
                        if namespace in a.get_actor_label():
                            actor = a
                            break

            if not actor:
                for a in all_actors:
                    if isinstance(a, unreal.SkeletalMeshActor):
                        sm_comp = a.get_editor_property("skeletal_mesh_component")
                        if sm_comp and sm_comp.get_editor_property("skeletal_mesh") == asset:
                            actor = a
                            break

            if not actor:
                actor_rotation = unreal.Rotator(0.0, 0.0, 0.0)
                actor = unreal.EditorLevelLibrary.spawn_actor_from_class(skeletal_mesh_actor_class,
                                                                         unreal.Vector(0, 0, 0), actor_rotation)
                sm_comp = actor.get_editor_property("skeletal_mesh_component")
                sm_comp.set_editor_property("skeletal_mesh", asset)

                if namespace:
                    skeletal_mesh_name = namespace
                else:
                    skeletal_mesh_name = asset.get_name()
                actor.set_actor_label(skeletal_mesh_name)
        else:
            unreal.log_error(f"Unsupported asset type for spawning: {asset}")
            return [None, None]

    if not actor:
        unreal.log_error(f"Failed to spawn actor from asset {asset_path}")
        return [None, None]

    possessable = possessable or level_sequence.add_possessable(actor)
    if not possessable:
        unreal.log_error("Failed to add possessable to level sequence.")
        return [None, None]

    return [actor, possessable]


def add_skeletal_mesh_components_to_level_sequence(actor, possessable):
    """
    Adds skeletal mesh components to the level sequence.

    :param actor: The actor containing the skeletal mesh components.
    :param possessable: The possessable associated with the actor.
    :return: A list of components added to the sequence.
    """
    component_list = []

    mesh_component = actor.get_editor_property("skeletal_mesh_component")
    component_list.append(mesh_component)

    existing_track = None
    for track in possessable.get_tracks():
        if isinstance(track, unreal.MovieSceneSkeletalAnimationTrack):
            existing_track = track
            break

    if not existing_track:
        existing_track = possessable.add_track(unreal.MovieSceneSkeletalAnimationTrack)


    sections = existing_track.get_sections()
    if not sections:
        existing_track.add_section()


    return component_list


def add_camera_actor_to_level_sequence(sequence, camera_actor=None, camera_name=None):
    """
    Adds a CineCameraActor to the level sequence.

    :param sequence: The LevelSequence asset where the camera should be added.
    :param camera_actor: (Optional) The CineCameraActor to add. If None, a new one will be created.
    :param camera_name: (Optional) Updates camera name otherwise uses default name

    :return: The CineCameraActor that was added to the sequence.
    """
    sequence_asset = unreal.LevelSequence.cast(sequence)

    if not camera_actor:
        camera_actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.CineCameraActor, unreal.Vector(0, 0, 100)
        )
        if camera_name:
            camera_actor.set_actor_label(camera_name)
        else:
            camera_actor.set_actor_label("Cinematic_Camera")

    binding = sequence_asset.add_possessable(camera_actor)

    camera_component = camera_actor.get_cine_camera_component()
    camera_component.set_editor_property("current_focal_length", 35.0)

    focus_settings = camera_component.get_editor_property("focus_settings")
    focus_settings.manual_focus_distance = 1000.0
    camera_component.set_editor_property("focus_settings", focus_settings)

    return [camera_actor, binding, camera_component]


def add_shot_track_to_master_sequence(master_sequence):
    """
    Adds shot track if it doesnt exist to master sequence
    :param master_sequence: Master sequence asset
    :return:
    """
    shot_track = None
    for track in master_sequence.get_tracks():
        if isinstance(track, unreal.MovieSceneCinematicShotTrack):
            shot_track = track
            break

    if not shot_track:
        shot_track = master_sequence.add_track(unreal.MovieSceneCinematicShotTrack)

    return shot_track


def add_shot_sequence_section_to_shot_track(shot_track, shot_sequence, start_frame, end_frame):
    """
    Adds section for shot sequence to shot track if it doesn't exist
    :param shot_track:
    :param shot_sequence:
    :param start_frame:
    :param end_frame:
    :return:
    """
    existing_section = None
    for section in shot_track.get_sections():
        if section.get_editor_property('sub_sequence') == shot_sequence:
            existing_section = section
            break

    if not existing_section:
        shot_section = shot_track.add_section()
        shot_section.set_range(start_frame, end_frame)
        shot_section.set_editor_property('sub_sequence', shot_sequence)
    else:
        existing_section.set_range(start_frame, end_frame)

    return existing_section


def add_anim_to_level_sequence(animation_path, anim_track, anim_section=None, start_frame=0):
    """
    Adds an animation to a track in the level sequence without shifting animation keyframe timing.
    Places the animation so its first keyframe starts exactly at start_frame.

    :param animation_path: Path to the animation asset.
    :param anim_track: The track to add the animation to.
    :param anim_section: Optional pre-existing section to add animation to.
    :param start_frame: Frame number to start the animation from.
    :return: The end frame of the animation.
    """
    animation_asset = unreal.load_asset(animation_path)
    animation_asset.set_editor_property("enable_root_motion", True)
    num_frames = animation_asset.get_editor_property('number_of_sampled_frames')
    params = unreal.MovieSceneSkeletalAnimationParams()
    params.set_editor_property('animation', animation_asset)

    if not anim_section:
        anim_section = anim_track.add_section()
    anim_section.set_editor_property('params', params)

    set_section_range(anim_section, start_frame, start_frame + num_frames)
    return start_frame + num_frames


def add_anim_track_to_possessable(possessable, animation_asset_path=None):
    """
    Adds an animation track and section to the possessable, ensuring no duplicates.

    :param possessable: The possessable to which the animation track will be added.
    :param animation_asset_path: The path to the animation asset (e.g. FBX).
    :return: None
    """
    existing_anim_track = None
    for track in possessable.get_tracks():
        if isinstance(track, unreal.MovieSceneSkeletalAnimationTrack):
            existing_anim_track = track
            break

    if not existing_anim_track:
        existing_anim_track = possessable.add_track(unreal.MovieSceneSkeletalAnimationTrack)


    sections = existing_anim_track.get_sections()
    existing_anim_section = sections[0] if sections else None

    if not existing_anim_section:
        existing_anim_section = existing_anim_track.add_section()

    if animation_asset_path:
        add_anim_to_level_sequence(animation_asset_path, existing_anim_track, anim_section=existing_anim_section)


def add_blueprint_mesh_components_to_level_sequence(blueprint_path, sequence_path, actor, control_rig=True):
    """
    Adds specific mesh components from a blueprint actor to a level sequence.
    Adds 'Mesh' (typically CharacterMesh0), 'Body', and 'Face' components if they exist.

    :param blueprint_path: The blueprint asset path bound in the Level Sequence.
    :param sequence_path: The Level Sequence asset path.
    :param actor: (Optional) Actor to use. If None, the actor will be spawned from the blueprint.
    :param control_rig: (Optional) Whether to add control rig for track if it is found

    :return: A list of added SkeletalMeshComponent references.
    """
    component_list = []
    level_sequence = load_level_sequence(sequence_path)
    binding = get_blueprint_binding_in_sequence(blueprint_path, sequence_path)

    if not binding:
        unreal.log_warning(f"No binding found for blueprint: {blueprint_path}")
        return component_list

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

    if actor is None:
        blueprint_class = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        if not blueprint_class:
            unreal.log_warning(f"Failed to load blueprint at path: {blueprint_path}")
            return component_list

        actor = unreal.EditorLevelLibrary.spawn_actor_from_class(blueprint_class, unreal.Vector(0, 0, 100))
        if not actor:
            unreal.log_warning(f"Failed to spawn actor from blueprint: {blueprint_path}")
            return component_list

        playback_range = get_full_range(level_sequence)
        script_range = unreal.SequencerScriptingRange(has_start_value=True, has_end_value=True,
                                                      inclusive_start=playback_range[0],
                                                      exclusive_end=playback_range[1])

        bound_objects = unreal.SequencerTools.get_bound_objects(world, level_sequence, binding, script_range)

        if not bound_objects:
            unreal.log_warning(f"No bound objects found for blueprint: {blueprint_path}")
            return component_list

        actor = bound_objects[0]

    bound_components = get_existing_blueprint_mesh_components_in_level_sequence(blueprint_path,
                                                                               sequence_path, actor)
    bound_names = [component.get_name() for component in bound_components]
    mesh_components = actor.get_components_by_class(unreal.SkeletalMeshComponent)
    top_mesh = get_top_level_mesh_component(actor)
    top_mesh_name = top_mesh.get_name()
    mesh_names = [top_mesh.get_name(), "Body", "Face"]

    mesh_list = [[mesh.get_name(), mesh] for mesh in mesh_components]
    if len(mesh_components) == 1:
        top_mesh_name = "temp"

    for name, mesh in mesh_list:

        if name in mesh_names:
            if name in bound_names:
                existing_binding = find_binding_for_component(sequence_path, name)
                component_possessable = existing_binding
            else:
                component_possessable = level_sequence.add_possessable(mesh)
            if name == top_mesh_name:
                tracks = component_possessable.get_tracks()
                transform_track = None
                if tracks:
                    for track in tracks:
                        if type(track) is unreal.MovieScene3DTransformTrack:
                            transform_track = track
                if not transform_track:
                    transform_track = component_possessable.add_track(unreal.MovieScene3DTransformTrack)
                    transform_track.add_section()

            elif name != top_mesh.get_name() and name != "Face":
                add_anim_track_to_possessable(component_possessable)
                component_list.append(component_possessable)
            else:
                properties_to_change = {}
                if not control_rig:
                    tracks = component_possessable.get_tracks()
                    if tracks:
                        for track in tracks:
                            if type(track) is unreal.MovieSceneControlRigParameterTrack:
                                control_rig_track = track
                                component_possessable.remove_track(control_rig_track)
                    add_anim_track_to_possessable(component_possessable)
                    component_list.append(component_possessable)
                    properties_to_change["disable_post_process_blueprint"] = True
                    mesh.set_editor_properties(properties_to_change)
                    mesh.modify()
                else:
                    tracks = component_possessable.get_tracks()
                    if tracks:
                        for track in tracks:
                            if type(track) is unreal.MovieSceneSkeletalAnimationTrack:
                                anim_track = track
                                component_possessable.remove_track(anim_track)
                    control_rig_class = get_control_rig_class()
                    if not control_rig_class:
                        continue
                    control_rig_track = unreal.ControlRigSequencerLibrary.find_or_create_control_rig_track(
                        world,
                        level_sequence,
                        control_rig_class,
                        component_possessable)
                    component_list.append([component_possessable, control_rig_track])
                    properties_to_change["disable_post_process_blueprint"] = False
                    mesh.set_editor_properties(properties_to_change)
                    mesh.modify()

                actor.modify()

    return component_list


def add_camera_anim_to_level_sequence(shot_sequence, camera_actor, world, export_path, anim_range):
    """
    Imports and applies a camera animation to a CineCameraActor inside a Level Sequence,
    and offsets the animation so that the first keyframe is at frame 0 of the sequence.
    Also adds a Camera Cut Track to switch the camera at frame 0.

    :param shot_sequence: The LevelSequence asset where the animation should be added.
    :param camera_actor: The CineCameraActor that will receive the animation.
    :param world: The Unreal world context.
    :param export_path: The path to the FBX file containing the camera animation.
    :param anim_range: Range to use for offsetting the animation sections
    :return: None
    """
    existing_binding = None
    for binding in shot_sequence.get_bindings():
        if binding.get_name() == camera_actor.get_actor_label():
            existing_binding = binding
            break

    if not existing_binding:
        existing_binding = shot_sequence.add_possessable(camera_actor)
    shot_scene_sequence = unreal.MovieSceneSequence.cast(shot_sequence)
    binding_id = shot_scene_sequence.get_binding_id(existing_binding)

    import_options = unreal.MovieSceneUserImportFBXSettings()
    import_options.set_editor_property('match_by_name_only', False)
    import_options.set_editor_property('reduce_keys', False)
    import_options.set_editor_property('reduce_keys_tolerance', 0.001)
    import_options.set_editor_property('create_cameras', False)
    import_options.set_editor_property('force_front_x_axis', False)
    import_options.set_editor_property('replace_transform_track', True)

    # Import camera animation FBX into the level sequence
    success = unreal.SequencerTools.import_level_sequence_fbx(world,
                                                              shot_sequence,
                                                              [existing_binding],
                                                              import_options,
                                                              export_path
                                                              )


    camera_cut_track = None
    for track in shot_sequence.get_tracks():
        if isinstance(track, unreal.MovieSceneCameraCutTrack):
            camera_cut_track = track

    if not camera_cut_track:
        camera_cut_track = shot_sequence.add_track(unreal.MovieSceneCameraCutTrack)

    camera_cut_section = None
    sections = camera_cut_track.get_sections()
    for section in sections:
        if isinstance(section, unreal.MovieSceneCameraCutSection):
            camera_cut_section = section
    start_time, end_time = anim_range
    if not camera_cut_section:
        camera_cut_section = camera_cut_track.add_section()

    set_section_range(camera_cut_section, start_time - start_time, end_time - start_time)
    camera_cut_section.set_camera_binding_id(binding_id)

    tracks = existing_binding.get_tracks()
    offset_frames = -start_time

    # Offset 3D transform keys on the camera actor
    for track in tracks:
        if isinstance(track, unreal.MovieScene3DTransformTrack):
            offset_transform_track_keys(track, offset_frames)

    # Offset focal length, focus distance, etc., on the camera component
    camera_component = camera_actor.get_cine_camera_component()
    all_bindings = list_all_tracks_in_sequence(shot_sequence)

    for binding in all_bindings:
        if binding.get_name() == camera_component.get_name():
            for track in binding.get_tracks():
                if isinstance(track, unreal.MovieSceneFloatTrack):
                    offset_float_track_keys(track, offset_frames)


def get_control_rig_class(control_rig_path = "Face_ControlBoard_CtrlRig"):
    """

    :param control_rig_path:
    :return:
    """
    control_rig_path = find_uasset_path(control_rig_path)
    control_rig_asset = unreal.load_asset(control_rig_path)
    if not control_rig_asset:
        unreal.log_error(f"Failed to load Control Rig from {control_rig_path}")
    control_rig_class = control_rig_asset.generated_class()
    return control_rig_class


def offset_key_times_in_section(section, offset_frames):
    """

    :param section: section to offset
    :param offset_frames: frame value to offset
    :return:
    """
    channels = section.get_all_channels()

    if not channels:
        return

    for channel in channels:

        keys = channel.get_keys()

        for key in keys:
            original_time = key.get_time()
            original_frame = original_time.frame_number.value

            new_frame = unreal.FrameNumber(original_frame + offset_frames)
            key.set_time(new_frame)


def offset_float_track_keys(track, offset_frames):
    """
    Offsets all float keys in a MovieSceneFloatTrack by a given number of frames.
    :param track: The MovieSceneFloatTrack to modify.
    :param offset_frames: The number of frames to offset the keys by.
    """
    for section in track.get_sections():
        if isinstance(section, unreal.MovieSceneFloatSection):
            offset_key_times_in_section(section, offset_frames)


def offset_transform_track_keys(track, offset_frames):
    """

    :param track: Should be a MovieScene3DTransformTrack
    :param offset_frames: The number of frames to offset the keys by.
    :return:
    """
    for section in track.get_sections():
        if isinstance(section, unreal.MovieScene3DTransformSection):
            offset_key_times_in_section(section, offset_frames)


def set_section_range(section, start_frame, end_frame):
    """
    Sets the start and end time for the given section directly.
    :param section: actual section object in sequencer
    :param start_frame: start frame to set the section to
    :param end_frame: end frame to set the section to
    :return:
    """
    section.set_start_frame(start_frame)
    section.set_end_frame(end_frame)


def list_all_tracks_in_sequence(sequence):
    """

    :param sequence: The Sequence asset to parse
    :return:
    """
    bindings = sequence.get_bindings()

    return bindings


def get_skeleton_from_skeletal_mesh_using_metadata(skeletal_mesh_path):
    """
    Get the skeleton from a given skeletal mesh by retrieving metadata tags.
    :param skeletal_mesh_path: The asset path of the skeletal mesh (e.g., "/Game/Characters/Hero/Hero_SkeletalMesh")
    :return: The skeleton associated with the given skeletal mesh, or None if not found.
    """
    # Print all metadata tags to debug
    asset = unreal.EditorAssetLibrary.load_asset(skeletal_mesh_path)
    if asset:
        skeleton = asset.skeleton
        if skeleton:
            return skeleton.get_name()


def find_skeletal_meshes_using_skeleton(skeleton_asset_path):
    """
    Finds all Skeletal Mesh assets that use the given Skeleton asset.
    :param skeleton_asset_path: The full asset path to the Skeleton (e.g. "/Game/Characters/Hero/Hero_Skeleton")
    :return: A list of SkeletalMesh asset objects that use the given Skeleton.
    """
    skeletal_meshes_using_skeleton = []

    skeleton = unreal.EditorAssetLibrary.load_asset(skeleton_asset_path)
    if not skeleton:
        unreal.log_error(f"Could not load skeleton at {skeleton_asset_path}")
        return skeletal_meshes_using_skeleton

    registry = unreal.AssetRegistryHelpers.get_asset_registry()

    skeletal_mesh_class_path = unreal.TopLevelAssetPath("/Script/Engine", "SkeletalMesh")
    skeletal_mesh_assets = registry.get_assets_by_class(skeletal_mesh_class_path, True)

    for asset_data in skeletal_mesh_assets:
        asset = unreal.EditorAssetLibrary.load_asset(asset_data.package_name)
        skel = asset.get_editor_property('skeleton')
        if skel:
            package_name = skel.get_path_name().split('.')[0]
            if package_name == skeleton_asset_path:
                skeletal_mesh = unreal.EditorAssetLibrary.load_asset(asset_data.get_asset().get_path_name())
                skeletal_meshes_using_skeleton.append(skeletal_mesh)

    return skeletal_meshes_using_skeleton


def get_blueprints_using_skeleton_cmd(skeleton_path, asset_registry=None):
    """
    Finds all Blueprints using a given skeleton, prioritizing CinematicCharacter Blueprints,
    and only checks for CinematicCharacter, Actor, and Character Blueprints.
    :param skeleton_path: The asset path of the skeleton (e.g., "/Game/Characters/Hero/Hero_Skeleton")
    :return: A list of Blueprint asset paths, prioritizing CinematicCharacter BPs.
    """
    if not asset_registry:
        asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()

    if not asset_registry:
        unreal.log_error("Asset registry could not be initialized.")
        return []

    blueprint_class_path = unreal.TopLevelAssetPath("/Script/Engine.Blueprint")
    blueprint_assets = asset_registry.get_assets_by_class(blueprint_class_path)

    if not blueprint_assets:
        unreal.log_error("No Blueprints found.")
        return []

    unreal.log(f"Found {len(blueprint_assets)} Blueprints.")

    cinematic_bps = []

    dependency_options = unreal.AssetRegistryDependencyOptions(
        include_soft_package_references=True,
        include_hard_package_references=True,
        include_searchable_names=True,
        include_soft_management_references=False,
        include_hard_management_references=False
    )

    for blueprint in blueprint_assets:
        if "Engine" or "Maps" not in blueprint.package_name :
            unreal.log(f"Processing Blueprint: {blueprint.package_name}")
            dependencies = asset_registry.get_dependencies(blueprint.package_name, dependency_options)
            if dependencies:
                for dep in dependencies:
                    if 'Script' not in str(dep):
                        dep_asset_data = unreal.EditorAssetLibrary.find_asset_data(dep)
                        if dep_asset_data:
                            test = dep_asset_data.get_asset()

                            if isinstance(test, unreal.SkeletalMesh):
                                asset = unreal.EditorAssetLibrary.load_asset(dep_asset_data.package_name)
                                if not asset:
                                    unreal.log_error(f"Failed to load asset: {dep_asset_data.package_name}")
                                    continue

                                skel = asset.get_editor_property('skeleton')
                                if skel:
                                    package_name = skel.get_path_name().split('.')[0]
                                    if package_name == skeleton_path:
                                        cinematic_bps.append(blueprint.get_asset())

    unreal.log(f"Found {len(cinematic_bps)} Cinematic Blueprints.")
    return cinematic_bps


def get_possessables_for_sequence(level_sequence):
    """
    Retrieves all possessables (actors) bound to the given level sequence.

    :param level_sequence: The Level Sequence asset to get the possessables from.
    :return: A list of possessable objects (MovieSceneBindingProxy).
    """
    possessables = level_sequence.get_possessables()

    return possessables


def get_blueprints_using_skeleton(skeleton_path, asset_registry=None, mesh_string=None):
    """
    Finds all Blueprints using a given skeleton, prioritizing CinematicCharacter Blueprints,
    and only checks for CinematicCharacter, Actor, and Character Blueprints.
    :param skeleton_path: The asset path of the skeleton (e.g., "/Game/Characters/Hero/Hero_Skeleton")
    :return: A list of Blueprint asset paths, prioritizing CinematicCharacter BPs.
    """
    if not asset_registry:
        asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()

    blueprint_class_path = unreal.TopLevelAssetPath("/Script/Engine.Blueprint")
    blueprint_assets = asset_registry.get_assets_by_class(blueprint_class_path)
    cinematic_bps = []

    dependency_options = unreal.AssetRegistryDependencyOptions(
        include_soft_package_references=True,
        include_hard_package_references=True,
        include_searchable_names=True,
        include_soft_management_references=False,
        include_hard_management_references=False
    )
    for blueprint in blueprint_assets:
        dependencies = asset_registry.get_dependencies(blueprint.package_name, dependency_options)
        for dep in dependencies:
            if 'Script' not in str(dep):
                dep_asset_data = unreal.EditorAssetLibrary.find_asset_data(dep)

                if dep_asset_data:
                    test = dep_asset_data.get_asset()
                    if isinstance(test, unreal.SkeletalMesh):

                        asset = unreal.EditorAssetLibrary.load_asset(dep_asset_data.package_name)
                        skel = asset.get_editor_property('skeleton')
                        if skel:

                            package_name = skel.get_path_name().split('.')[0]
                            if package_name == skeleton_path:
                                if mesh_string:
                                    if mesh_string in str(dep_asset_data.package_name):
                                        cinematic_bps.append(blueprint.get_asset())
                                        break
                                else:
                                    cinematic_bps.append(blueprint.get_asset())
    return cinematic_bps


def get_blueprint_binding_in_sequence(blueprint_path, sequence_path):
    """
    Returns the binding for a Blueprint actor in the Level Sequence, if it exists.
    Compares the binding name to the actor name.

    :param blueprint_path: Path to the Blueprint asset (e.g., "/Game/Blueprints/MyActorBP")
    :param sequence_path: Path to the Level Sequence asset (e.g., "/Game/Cinematics/MySequence")
    :return: The binding (MovieSceneBindingProxy) if found, else None
    """
    blueprint_asset = unreal.load_asset(blueprint_path)
    level_sequence = load_level_sequence(sequence_path=sequence_path)

    if not blueprint_asset:
        unreal.log_warning(f"Blueprint not found at path: {blueprint_path}")
        return None

    if not level_sequence:
        unreal.log_warning(f"Level Sequence not found at path: {sequence_path.split('.')[0]}")
        return None

    bindings = get_possessables_for_sequence(level_sequence)
    for binding in bindings:
        if blueprint_asset.get_name() in binding.get_name():
            unreal.log(f"Found binding: {binding.get_display_name()}")
            return binding

    unreal.log("No binding found for the specified Blueprint.")
    return None


def get_top_level_mesh_component(actor):
    root_component = actor.get_attach_parent_actor()

    if isinstance(root_component, unreal.SkeletalMeshComponent):
        return root_component

    mesh_components = actor.get_components_by_class(unreal.SkeletalMeshComponent)
    for comp in mesh_components:
        if comp.get_attach_parent() == root_component:
            return comp

    return mesh_components[0] if mesh_components else None


def get_skeleton_path_by_name(skeleton_name):
    """
    Retrieves the asset path of a skeleton based on its name using Unreal's Asset Registry.

    :param skeleton_name: Name of the skeleton asset (e.g., "SK_Mannequin").
    :return: The asset path of the skeleton (e.g., "/Game/Characters/Hero/Hero_Skeleton") or None if not found.
    """
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()

    skeleton_class = unreal.TopLevelAssetPath("/Script/Engine", "Skeleton")

    skeleton_assets = asset_registry.get_assets_by_class(skeleton_class)

    for skeleton in skeleton_assets:
        if skeleton.asset_name == skeleton_name and "Identity" not in str(skeleton.package_name):
            return str(skeleton.package_name)

    return None


def extract_shot_number_from_path(export_path):
    """
    Extracts the shot number from the export path, which contains 'shot' as part of its name.

    :param export_path: The export path containing the shot number (e.g., "MyAnimation_Shot1_Anim.fbx").
    :return: The shot number as an integer (e.g., 1 for "Shot1"), or None if not found.
    """
    parts = export_path.split('_')

    for part in parts:
        if 'shot' in part.lower():
            shot_number = part.lower().replace('shot', '')
            return int(shot_number)

    return None


def import_gameplay_animations_from_json(anim_dict_path):
    """
    Import gameplay animations, replaces Art Source Dir with Content Dir
    :param anim_dict_path: Exported Dict with the data to import
    :return:
    """
    anim_dict = read_dict_from_file(anim_dict_path)
    for anim_path in anim_dict:
        anim_name = os.path.basename(anim_path).split('.')[0]
        existing_path = find_uasset_path(anim_name)
        if not existing_path:
            if art_source_dir in anim_path:
                import_dir = os.path.dirname(anim_path).replace(art_source_dir, content_dir).replace('Exports/', '')
            else:
                import_dir = "/Game/Animations"
        else:
            import_dir = os.path.dirname(existing_path)
        anim_data = anim_dict[anim_path]
        skeleton_name = anim_data[3]
        skeleton_path = get_skeleton_path_by_name(skeleton_name)
        import_animation(anim_path, skeleton_path, import_dir, anim_name)

    return anim_dict.keys()


def import_animation(anim_path, skeleton_path, destination_path, destination_name):
    """
    Imports an animation asset into Unreal Engine, optionally reimporting if it already exists.

    :param anim_path: Path to the animation FBX file.
    :param skeleton_path: Path to the skeleton asset for the animation.
    :param destination_path: Destination path in Unreal where the asset will be imported.
    :param destination_name: Name for the imported animation asset.
    :return: The path to the imported animation asset.
    """
    unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX 0")

    task = unreal.AssetImportTask()
    task.set_editor_property('automated', True)
    task.set_editor_property('filename', anim_path)
    task.set_editor_property('destination_path', destination_path)
    task.set_editor_property('destination_name', destination_name)
    task.set_editor_property('replace_existing', True)
    task.set_editor_property('save', True)

    fbx_options = build_import_options(skeleton_path)
    task.set_editor_property('options', fbx_options)

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    return f"{destination_path}/{destination_name}"


def build_import_options(skeleton_path):
    """
    Creates the import options for importing an animation in Unreal Engine.

    :param skeleton_path: Path to the skeleton asset for the animation.
    :return: Unreal FBX import UI object with specified settings.
    """
    options = unreal.FbxImportUI()
    options.original_import_type = unreal.FBXImportType.FBXIT_ANIMATION
    options.import_animations = True
    options.create_physics_asset = False
    options.import_mesh = False
    options.import_rigid_mesh = False
    options.import_materials = False
    options.import_textures = False
    options.import_as_skeletal = False
    options.skeleton = unreal.load_asset(skeleton_path)
    options.anim_sequence_import_data.set_editor_property('import_uniform_scale', 1.0)
    options.anim_sequence_import_data.set_editor_property("import_bone_tracks", True)
    options.anim_sequence_import_data.set_editor_property('animation_length',
                                                          unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME)
    options.anim_sequence_import_data.set_editor_property('remove_redundant_keys', False)

    return options


def load_level_sequence(sequence_path="/Game/Cinematics/Test_Anim/Test_Anim_shot1/Test_Anim_shot1"):
    """
    :param sequence_path: full path to sequence to load, checks current sequence for match first
    :return:
    """
    loaded_sequence = unreal.LevelSequenceEditorBlueprintLibrary.get_current_level_sequence()
    if loaded_sequence:
        asset_path = unreal.EditorAssetLibrary.get_path_name_for_loaded_asset(loaded_sequence)

        if asset_path.split('.')[0] == sequence_path:
            level_sequence = unreal.load_asset(sequence_path)
            return level_sequence

    if unreal.EditorAssetLibrary.does_asset_exist(sequence_path):
        level_sequence = unreal.load_asset(sequence_path)
    else:
        level_sequence = None

    return level_sequence


def get_level_sequence_actor(level_sequence_asset):
    """
    Returns the Level Sequence Actor that references the given LevelSequence asset in the level.

    :param level_sequence_asset: The LevelSequence asset to search for in the level.
    :return: The Level Sequence Actor if found, else None.
    """
    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()

    for actor in all_actors:
        if isinstance(actor, unreal.LevelSequenceActor):
            if actor.get_sequence() == level_sequence_asset:
                return actor

    unreal.log_warning(f"No Level Sequence Actor found referencing {level_sequence_asset.get_name()}")
    return None


def get_full_range(level_sequence):
    """
    gets range for use in get_bound_objects
    :param level_sequence: level sequence asset
    :return:
    """
    playback_range = level_sequence.get_playback_range()

    start_frame = playback_range.inclusive_start
    end_frame = playback_range.exclusive_end

    return [start_frame, end_frame]


def get_actor_from_possessable(sequence_path, actor_binding):
    """
    Retrieves the actor bound to the given possessable within a Level Sequence.

    :param actor_binding: The possessable (actor binding) in the sequence.
    :param sequence_path: The level sequence to search within.
    :return: The actor bound to the possessable, or None if not found.
    """
    level_sequence = load_level_sequence(sequence_path)
    bindings = get_possessables_for_sequence(level_sequence)

    for binding in bindings:

        if binding.get_id() == actor_binding.get_id():

            actor = unreal.EditorLevelLibrary.get_actor_reference(binding.get_name())
            return actor

    return None


def get_actor_from_binding(sequence_path, blueprint_binding):
    """
    Retrieve the actor bound to a sequence via the blueprint binding.

    :param sequence_path: Path to the Level Sequence.
    :param blueprint_binding: The binding that we are checking.
    :return: Actor or None if not found.
    """
    level_sequence = load_level_sequence(sequence_path=sequence_path)

    if not level_sequence:
        unreal.log_warning(f"Failed to load Level Sequence at {sequence_path}")
        return None
    bindings = level_sequence.get_bindings()

    for binding in bindings:
        if binding.get_name() == blueprint_binding.get_name():
            unreal.log(f"Found matching binding: {binding.get_name()}")

            possessables = get_possessables_for_sequence(level_sequence)

            for possessable in possessables:

                if possessable.get_name() == binding.get_name():
                    actor = get_actor_from_possessable(sequence_path, blueprint_binding)
                    return actor

    unreal.log_warning(f"No actor found for binding: {blueprint_binding.get_name()}")
    return None


def get_blueprint_class_from_binding(blueprint_binding):
    """
    Retrieves the Blueprint class from the binding.

    :param blueprint_binding: The MovieSceneBindingProxy for the blueprint.
    :return: The BlueprintGeneratedClass for the actor in the binding.
    """
    possessable = blueprint_binding.get_possessable()

    if possessable is None:
        unreal.log_warning("No possessable found for binding.")
        return None

    actor_class = possessable.get_class()

    if actor_class and actor_class.is_a(unreal.BlueprintGeneratedClass):
        blueprint_class = actor_class
        unreal.log(f"Found Blueprint Class: {blueprint_class.get_name()}")
        return blueprint_class
    else:
        unreal.log_warning("Possessable does not represent a Blueprint class.")
        return None


def get_existing_blueprint_mesh_components_in_level_sequence(blueprint, sequence_path, actor =None):
    """
    Detects existing mesh components (such as 'Mesh', 'Body', and 'Face') that have already been added
    to the Level Sequence from the given blueprint.

    :param blueprint: The Blueprint path to check for mesh components.
    :param sequence_path: The Level Sequence path to check for bindings.
    :return: A list of detected mesh components that are already bound in the sequence.
    """
    existing_components = []

    level_sequence = load_level_sequence(sequence_path)
    if not level_sequence:
        unreal.log_warning(f"Could not load Level Sequence at {sequence_path}")
        return existing_components

    blueprint_binding = get_blueprint_binding_in_sequence(blueprint, sequence_path)
    if not blueprint_binding:
        unreal.log_warning(f"No binding found for blueprint {blueprint}")
        return existing_components
    if actor:
        blueprint_actor = actor
    else:
        blueprint_actor = get_actor_from_binding(sequence_path, blueprint_binding)
    if not blueprint_actor:
        unreal.log_warning("Failed to resolve actor from binding.")
        return existing_components

    possessables = get_possessables_for_sequence(level_sequence)

    mesh_components = blueprint_actor.get_components_by_class(unreal.SkeletalMeshComponent)
    for mesh_component in mesh_components:
        mesh_name = mesh_component.get_name()
        if mesh_name not in ["CharacterMesh0", "Body", "Mesh", "Face"]:
            continue

        for possessable in possessables:
            if possessable.get_display_name() == mesh_name:
                existing_components.append(mesh_component)
                break

    return existing_components


def render_level_sequence(level_sequence_path, output_directory, resolution=(1920, 1080)):
    """
    Renders a level sequence to the specified directory.

    :param level_sequence_path: Path to the level sequence to render.
    :param output_directory: Directory where the rendered output will be saved.
    :param resolution: Resolution of the render.
    :return: Path to the output directory.
    """
    capture = unreal.AutomatedLevelSequenceCapture()
    capture.level_sequence_asset = unreal.SoftObjectPath(level_sequence_path)

    capture_settings = unreal.MovieSceneCaptureSettings()
    capture_settings.output_directory = unreal.DirectoryPath(path=output_directory)
    capture_settings.output_format = "PNG"
    capture_settings.use_relative_frame_numbers = True
    capture_settings.resolution = unreal.CaptureResolution(res_x=resolution[0], res_y=resolution[1])
    capture.settings = capture_settings

    unreal.SequencerTools.render_movie(capture, unreal.OnRenderMovieStopped())

    return output_directory


def write_dict_to_file(anim_dict, file_path):
    """
    Writes a dictionary to a JSON file.

    :param anim_dict: The dictionary to write to a file.
    :param file_path: Path where the file will be saved.
    :return: Path to the saved file.
    """
    with open(file_path, 'w') as f:
        f.write(json.dumps(anim_dict, indent=4))

    return file_path


def read_dict_from_file(file_path):
    """
    Reads a dictionary from a JSON file.

    :param file_path: Path to the JSON file.
    :return: The dictionary read from the file.
    """
    with open(file_path, 'r') as fp:
        anim_dict = json.loads(fp.read())

    return anim_dict


def list_all_maps():
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    all_assets = asset_registry.get_assets_by_class("World", True)
    map_paths = []
    for asset_data in all_assets:
        map_paths.append(asset_data.package_name)

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


def find_actor_by_blueprint_or_skeletal_mesh(blueprint_path=None, skeletal_mesh_path=None, shot_sequence=None):
    """
    Helper function to find an actor in the current level by its blueprint or directly by SkeletalMeshActor.
    It also returns the possessable for the found actor and the actor's components.

    :param blueprint_path: (Optional) The path to the blueprint asset. Can be None if searching for SkeletalMeshActor.
    :param skeletal_mesh_path: (Optional) The path to the Skeletal Mesh asset if no blueprint exists.
    :param shot_sequence: The LevelSequence to search for the possessable.
    :return: Tuple (actor, possessable, components) if found, else (None, None, None).
    """
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    actor = None
    possessable = None
    component_list = None
    if blueprint_path:
        blueprint_asset = unreal.load_asset(blueprint_path)
        generated_class = blueprint_asset.generated_class() if blueprint_asset else None
        if generated_class:
            actors = unreal.GameplayStatics.get_all_actors_of_class(world, generated_class)

            if actors:
                actor = actors[0]
                possessable = find_possessable_for_actor(actor, shot_sequence)
                if possessable:
                    component_list = actor.get_components_by_class(unreal.ActorComponent)
                    return [actor, possessable, component_list]

    if skeletal_mesh_path:
        actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SkeletalMeshActor)
        for actor in actors:
            skeletal_mesh_component = actor.get_component_by_class(unreal.SkeletalMeshComponent)
            if skeletal_mesh_component:
                mesh_asset = skeletal_mesh_component.get_skeletal_mesh_asset()
                if mesh_asset:
                    mesh_asset_path = mesh_asset.get_path_name().split('.')[0]

                    if mesh_asset_path == skeletal_mesh_path:
                        possessable = find_possessable_for_actor(actor, shot_sequence)
                        if possessable:
                            component_list = actor.get_components_by_class(unreal.ActorComponent)

    return [actor, possessable, component_list]


def find_possessable_for_actor(actor, shot_sequence):
    """
    Find the possessable for the given actor in the provided shot sequence.

    :param actor: The actor to search for.
    :param shot_sequence: The LevelSequence to search within.
    :return: The possessable object if found, otherwise None.
    """
    if shot_sequence:
        for binding in shot_sequence.get_bindings():
            if binding.get_name() == actor.get_actor_label():
                return binding
    return None


def find_binding_for_component(sequence_path, component_name):
    """
    Finds the MovieSceneBinding in the Level Sequence located at the given path that corresponds
    to the specified component in the current level.

    :param sequence_path: The path to the Level Sequence asset in the content browser.
    :param component_name: The component name to match against the Level Sequence bindings.
    :return: The MovieSceneBinding if found, else None.
    """
    level_sequence = load_level_sequence(sequence_path)
    if not level_sequence or not component_name:
        unreal.log_warning("Missing level sequence or component.")
        return None

    bindings = level_sequence.get_bindings()
    for binding in bindings:
        if component_name in binding.get_name():
            return binding

    return None


def find_camera_component_in_scene():
    """
    Finds the CineCameraActor in the scene that should be used for the camera animation.

    :return: The CineCameraActor component if found, else None.
    """
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

    camera_actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CineCameraActor)

    if not camera_actors:
        return [None, None]

    for cam_actor in camera_actors:
        camera_component = cam_actor.get_cine_camera_component()
        return [cam_actor, camera_component]


def set_section_range(section, start_frame, end_frame):
    """
    Sets the start and end time for the given section directly.
    :param section: actual section object in sequencer
    :param start_frame: start frame to set the section to
    :param end_frame: end frame to set the section to
    :return:
    """
    section.set_start_frame(start_frame)
    section.set_end_frame(end_frame)


def get_section_range(section):
    """
    Gets the range for the defined section
    :param section: actual section object in sequencer
    :return: list of the start and end frames
    """
    start_frame = section.get_start_frame()
    end_frame = section.get_end_frame()

    return [start_frame, end_frame]


def set_sequence_range(sequence, start_frame, end_frame):
    """
    Sets the start and end time for the given Level Sequence directly.

    :param sequence: The LevelSequence asset to modify.
    :param start_frame: The start time (in frames).
    :param end_frame: The end time (in frames).
    """
    # Set the range for the LevelSequence
    sequence.set_playback_start(start_frame)
    sequence.set_playback_end(end_frame)


def update_asset_registry_and_save(asset_directory, asset_path):
    """
    Saves the asset after refreshing, seems necessary from cmd.exe
    :param asset_directory: directory to refresh assets for
    :param asset_path: asset path to save
    :return:
    """
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    asset_registry.scan_paths_synchronous([asset_directory])
    unreal.EditorAssetLibrary.save_asset(asset_path)


def set_frame_rate(sequence, fps):
    """
    Sets the start and end time for the given Level Sequence directly.

    :param sequence: The LevelSequence asset to modify.
    :param fps: Frame Rate from Export data
    """
    display_rate = unreal.FrameRate(numerator=fps, denominator=1)
    sequence.set_display_rate(display_rate)

    sequence.set_tick_resolution(display_rate)


def create_level_sequence(sequence_name, destination_path="/Game/Cinematics/"):
    """
    Creates a new Level Sequence asset in the specified path.

    :param sequence_name: Name for the new Level Sequence.
    :param destination_path: Path where the Level Sequence will be created.
    :return: List containing the created Level Sequence asset and a boolean indicating if it was pre-existing.
    """
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    sequence_path = f"{destination_path}/{sequence_name}"
    level_sequence = load_level_sequence(sequence_path=sequence_path)

    pre_existing = False
    if level_sequence:
        pre_existing = True

    if not pre_existing:
        unreal.EditorAssetLibrary.make_directory(destination_path)
        level_sequence = unreal.AssetTools.create_asset(asset_tools, asset_name=sequence_name,
                                                        package_path=destination_path,
                                                        asset_class=unreal.LevelSequence,
                                                        factory=unreal.LevelSequenceFactoryNew())

    return [level_sequence, pre_existing]


def create_cinematic_sequence_from_json(anim_dict_path, destination_path="/Game/Cinematics/", from_cmd=True):
    """
    Creates a cinematic sequence in Unreal Engine from a JSON file.

    :param anim_dict_path: Path to the JSON file containing animation data, generated from maya export
    :param destination_path: Path to the directory where the cinematic sequence will be saved in Unreal Engine.
    :return: Path to the created sequence.
    """
    #StartUp Map was not loading correctly when running via cmd.exe, so I load via code here to get around the crash
    if from_cmd:
        if '/Game/ThirdPerson/Maps/ThirdPersonMap' in list_all_maps():
            unreal.EditorLevelLibrary.load_level('/Game/ThirdPerson/Maps/ThirdPersonMap')

    if not os.path.exists(anim_dict_path):
        print('FILE DOES NOT EXIST')
        return

    anim_dict = read_dict_from_file(anim_dict_path)
    sequence_name = os.path.basename(anim_dict_path).split('.')[0]
    sequence_path = create_cinematic_sequence(anim_dict, sequence_name, destination_path=destination_path)

    return sequence_path


def create_cinematic_sequence(anim_dict, sequence_name, destination_path="/Game/Cinematics"):
    """
    Creates a master cinematic sequence and sub-sequences for each shot. Imports animations and adds actors accordingly.

    :param anim_dict: anim dictionary containing animation data, generated from maya export
    :param sequence_name: name of master sequence
    :param destination_path: Path to the directory where the cinematic sequence will be saved in Unreal Engine.
    :return: Path to the created master sequence.
    """
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

    current_asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    sequence_dir = f"{destination_path}/{sequence_name}"
    sequence_path = f"{destination_path}/{sequence_name}/{sequence_name}"
    master_sequence = create_level_sequence(sequence_name, sequence_dir)[0]

    shot_track = add_shot_track_to_master_sequence(master_sequence)
    unreal.EditorAssetLibrary.save_asset(sequence_path)
    update_asset_registry_and_save(sequence_dir, sequence_path)
    facial_control_rig_dict = dict()
    try:
        for shot_name, animations in anim_dict.items():
            shot_sequence_name = f"_{shot_name}"
            shot_sequence_dir = f"{sequence_dir}/{shot_sequence_name}"
            shot_sequence = create_level_sequence(shot_sequence_name, destination_path=shot_sequence_dir)[0]
            shot_sequence_path = f"{sequence_dir}/{shot_sequence_name}/{shot_sequence_name}"
            update_asset_registry_and_save(shot_sequence_dir, shot_sequence_path)

            for i, animation in enumerate(animations):
                start_frame = animation["start_frame"]
                end_frame = animation["end_frame"]
                offset = start_frame
                export_path = animation["export_path"]
                namespace = animation["name_space"]
                skeleton = animation["skeleton"]
                blueprint = animation["blueprint"]
                fps = animation['fps']
                if i == 0:
                    set_frame_rate(master_sequence, fps)
                    update_asset_registry_and_save(sequence_dir, sequence_path)
                    set_sequence_range(shot_sequence, start_frame - offset, end_frame - offset)
                    add_shot_sequence_section_to_shot_track(shot_track, shot_sequence, start_frame, end_frame)
                    set_frame_rate(shot_sequence, fps)

                if namespace == "CAM":
                    camera_name = animation["nodes"][0]
                    camera_actor, camera_component = find_camera_component_in_scene()
                    if not camera_actor:
                        camera_actor, camera_possessable, camera_component = add_camera_actor_to_level_sequence(shot_sequence, camera_actor,
                                                                                            camera_name=camera_name)
                    add_camera_anim_to_level_sequence(shot_sequence, camera_actor, world, export_path, [start_frame, end_frame])
                else:
                    skeleton_path = get_skeleton_path_by_name(skeleton)
                    if not blueprint:

                        blueprints = get_blueprints_using_skeleton(skeleton_path, current_asset_registry, mesh_string=namespace.split("_")[0])
                        if not len(blueprints):
                            blueprints = get_blueprints_using_skeleton(skeleton_path, current_asset_registry)

                        blueprint = blueprints[0] if blueprints else None


                    actor, possessable, component_list = None, None, []
                    if not facial_control_rig_dict.get(namespace.split("_")[0]):
                        facial_control_rig = False
                        facial_control_rig_dict[namespace.split("_")[0]] = facial_control_rig
                    else:
                        facial_control_rig = facial_control_rig_dict[namespace.split("_")[0]]

                    if "FacialSliders" in export_path:
                        facial_control_rig = True
                        facial_control_rig_dict[namespace.split("_")[0]] = facial_control_rig

                    if blueprint:

                        blueprint_path = blueprint.get_package().get_name()
                        binding = get_blueprint_binding_in_sequence(blueprint_path, shot_sequence_path)

                        if binding:
                            possessable = binding

                            actor = get_actor_from_binding(shot_sequence_path, possessable)
                            actor, possessable = add_actor_to_level_sequence(shot_sequence_path, blueprint_path, actor=actor,
                                                                                             possessable=binding)
                        else:
                            actor, possessable = add_actor_to_level_sequence(shot_sequence_path, blueprint_path)
                        component_list = add_blueprint_mesh_components_to_level_sequence(blueprint_path,
                                                                                     shot_sequence_path,
                                                                                     actor=actor,
                                                                                     control_rig=facial_control_rig)
                    else:
                        skeletal_meshes = find_skeletal_meshes_using_skeleton(skeleton_path)

                        skeletal_mesh = skeletal_meshes[0]
                        skeletal_mesh_path = find_uasset_path(skeletal_mesh.get_name())
                        actor, possessable = add_actor_to_level_sequence(shot_sequence_path, skeletal_mesh_path, actor=actor, namespace=namespace)
                        component_list = add_skeletal_mesh_components_to_level_sequence(actor, possessable)

                    if "FacialSliders" not in export_path:
                        root, ext = os.path.splitext(export_path)
                        animation_asset_path = import_animation(export_path, skeleton_path, shot_sequence_dir,
                                                            os.path.basename(export_path.replace(ext, "")))

                        update_asset_registry_and_save(shot_sequence_dir, animation_asset_path)

                    if actor and possessable:
                        if isinstance(actor, unreal.SkeletalMeshActor):
                            add_anim_track_to_possessable(possessable, animation_asset_path)
                        else:
                            top_mesh = get_top_level_mesh_component(actor)
                            top_mesh_name = top_mesh.get_name()
                            top_binding = find_binding_for_component(shot_sequence_path, top_mesh_name)
                            if top_binding:
                                top_tracks = top_binding.get_tracks()
                                for t_track in top_tracks:
                                    if isinstance(t_track, unreal.MovieScene3DTransformTrack):
                                        t_sections = t_track.get_sections()
                                        t_section = t_sections[0] if t_sections else t_track.add_section()
                                        set_section_range(t_section, start_frame, end_frame)

                            anim_imported = False
                            if component_list:
                                for item in component_list:

                                    if item and not "FacialSliders" in export_path:
                                        component_binding = item
                                        component_name = component_binding.get_display_name() if hasattr(
                                            component_binding, 'get_display_name') else component_binding.get_name()

                                        if "FacialJoints" in export_path and "Face" != component_name:
                                            continue

                                        if component_binding and not anim_imported:
                                            tracks = component_binding.get_tracks()
                                            if tracks:
                                                for track in tracks:

                                                    if isinstance(track, unreal.MovieSceneSkeletalAnimationTrack):
                                                        sections = track.get_sections()
                                                        section = sections[0] if sections else track.add_section()
                                                        add_anim_to_level_sequence(animation_asset_path, track,
                                                                                   anim_section=section)
                                                        anim_imported = True
                                                        break
                                    else:
                                        if type(item) is list:
                                            component_binding, control_rig_track = item
                                            bindings = shot_sequence.get_bindings()
                                            for binding in bindings:
                                                for track in binding.get_tracks():
                                                    if track == control_rig_track:
                                                        control_rig_binding = binding
                                                        settings = unreal.MovieSceneUserImportFBXControlRigSettings()
                                                        success = unreal.SequencerTools.import_fbx_to_control_rig(
                                                            world=world,
                                                            sequence=shot_sequence,
                                                            actor_with_control_rig_track=control_rig_binding.get_name(),
                                                            selected_control_rig_names=[],
                                                            import_fbx_control_rig_settings=settings,
                                                            import_filename=export_path)

                                                        if not success:
                                                            unreal.log_error("FBX Import to Control Rig failed.")
                                                        break
                actor.modify()
            unreal.EditorLevelLibrary.save_current_level()
            update_asset_registry_and_save(shot_sequence_dir, shot_sequence_path)
    except:
        unreal.SystemLibrary.collect_garbage()
    finally:
        update_asset_registry_and_save(sequence_dir, sequence_path)
        unreal.LevelSequenceEditorBlueprintLibrary.close_level_sequence()
        current_world = unreal.EditorLevelLibrary.get_editor_world()
        current_level_path = current_world.get_path_name()
        unreal.EditorLevelLibrary.save_current_level()
        unreal.EditorLevelLibrary.load_level(current_level_path)
        shot_sequence = load_level_sequence(shot_sequence_path)
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(shot_sequence)

    return sequence_path

test_dict_path = "C:/depot/ArtSource/Exports/Animation/Cinematics/Test/JSON/DS_ANIMTEST_SEQ000_SHOT160_v27_JD.json"
create_cinematic_sequence_from_json(test_dict_path, destination_path="/Game/Cinematics", from_cmd=False)


