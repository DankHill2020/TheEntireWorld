# Tech Connector API Function Catalog

This file is generated from the current DCC tool source. Friendly calls use
`api.dcc.<host>.<function>(...)` when the function name is unique or has an
official alias. Ambiguous functions are still callable with
`api.dcc.<host>.call("full.package.path", ...)`.

## DCC Index

- [blender](#blender) (0 functions)
- [houdini](#houdini) (0 functions)
- [maya](#maya) (231 functions)
- [motionbuilder](#motionbuilder) (32 functions)
- [substance_painter](#substance_painter) (0 functions)
- [unity](#unity) (0 functions)
- [unreal](#unreal) (103 functions)

## blender

No public functions discovered.

## houdini

No public functions discovered.

## maya

### `api.dcc.maya.add_file_open_callback(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.add_file_open_callback`
- Signature: `add_file_open_callback(widget)`
- API names: `add_file_open_callback`
- Args:
  - `widget`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_file_open_callback(...)`](#apidccmayaremove_file_open_callback) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.remove_file_open_callback` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:21](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:21)
- Source: [sequence_utils.py:10](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:10)

### `api.dcc.maya.add_missing_parents_with_long_names(...)`

- Target: `maya_tools.Animation.anim_export.anim_export.add_missing_parents_with_long_names`
- Signature: `add_missing_parents_with_long_names(joint_list)`
- API names: `add_missing_parents_with_long_names`
- Args:
  - `joint_list`, required
- Description: Given a list of joints, return the full DAG paths including all parent joints. Ensures all names are long paths to avoid ambiguity. :param joint_list: List of joint names (can be short or long) :return: List of joints including all parents, with long names
- Source: [anim_export.py:317](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:317)

### `api.dcc.maya.add_tools_to_user_setup(...)`

- Target: `maya_tools.maya_setup.add_tools_to_user_setup`
- Signature: `add_tools_to_user_setup(tools_dir)`
- API names: `add_tools_to_user_setup`
- Args:
  - `tools_dir`, required
- Related functions:
  - same_module: [`api.dcc.maya.find_or_create_user_setup(...)`](#apidccmayafind_or_create_user_setup) -> `maya_tools.maya_setup.find_or_create_user_setup` - Shares module and name terms; may be useful in the same workflow.; source [maya_setup.py:35](C:/depot/tools/maya_tools/maya_setup.py:35)
- Description: Adds sys.path.append for the tools_dir into userSetup.py if not already present.
- Source: [maya_setup.py:62](C:/depot/tools/maya_tools/maya_setup.py:62)

### `api.dcc.maya.aim_joint_x_axis_to_world_x(...)`

- Target: `maya_tools.Rigging.mocap.setup_hik.aim_joint_x_axis_to_world_x`
- Signature: `aim_joint_x_axis_to_world_x(joint_name)`
- API names: `aim_joint_x_axis_to_world_x`
- Args:
  - `joint_name`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_world_position(...)`](#apidccmayaget_world_position) -> `maya_tools.Rigging.mocap.setup_hik.get_world_position` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:225](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:225)
  - same_module: [`api.dcc.maya.guess_joint_map_from_root(...)`](#apidccmayaguess_joint_map_from_root) -> `maya_tools.Rigging.mocap.setup_hik.guess_joint_map_from_root` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:554](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:554)
- Description: Aligns the joint to +X or -X :param joint_name: joint to align :return:
- Source: [setup_hik.py:271](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:271)

### `api.dcc.maya.align_clavicle_Y_by_rotateY(...)`

- Target: `maya_tools.Rigging.mocap.setup_hik.align_clavicle_Y_by_rotateY`
- Signature: `align_clavicle_Y_by_rotateY(clavicle_joint, sample_range=30.0, step=0.1)`
- API names: `align_clavicle_Y_by_rotateY`
- Args:
  - `clavicle_joint`, required
  - `sample_range`, default `30.0`
  - `step`, default `0.1`
- Description: Rotates Y up until the upper arm and clavicle are as close to the same in Translate Y world position :param clavicle_joint: joint name :param sample_range: how far of rotation range to test against base pose :param step: how small of increments to test :return:
- Source: [setup_hik.py:235](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:235)

### `api.dcc.maya.apply_auto_weights(...)`

- Target: `maya_tools.Rigging.auto_skinner.apply_auto_weights`
- Signature: `apply_auto_weights(`
- API names: `apply_auto_weights`
- Args:
  - `mesh` (str), required
  - `root_joint` (str), required
  - `max_influences` (int), default `DEFAULT_MAX_INFLUENCES`
  - `replace_existing_skin` (bool), default `False`
  - `falloff_power` (float), default `2.0`
  - `bind_method` (int), default `DEFAULT_BIND_METHOD`
  - `custom_distance_weights` (bool), default `True`
  - `geodesic_voxel_falloff` (float), default `0.0`
  - `geodesic_voxel_resolution` (int), default `256`
  - `shoulder_profile` (Optional[object]), default `None`
  - `shoulder_blend_strength` (float), default `0.0`
- Related functions:
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.auto_skin_mesh(...)`](#apidccmayaauto_skin_mesh) -> `maya_tools.Rigging.auto_skinner.auto_skin_mesh` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:588](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:588)
  - same_module: [`api.dcc.maya.auto_skin_selected(...)`](#apidccmayaauto_skin_selected) -> `maya_tools.Rigging.auto_skinner.auto_skin_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:622](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:622)
  - same_module: [`api.dcc.maya.normalize_and_limit_weights(...)`](#apidccmayanormalize_and_limit_weights) -> `maya_tools.Rigging.auto_skinner.normalize_and_limit_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:152](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:152)
- Source: [auto_skinner.py:475](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:475)

### `api.dcc.maya.apply_command_port_python3_patches(...)`

- Target: `maya_tools.maya_menu.apply_command_port_python3_patches`
- Signature: `apply_command_port_python3_patches()`
- API names: `apply_command_port_python3_patches`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.cleanup_command_port_files(...)`](#apidccmayacleanup_command_port_files) -> `maya_tools.maya_menu.cleanup_command_port_files` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:196](C:/depot/tools/maya_tools/maya_menu.py:196)
  - same_module: [`api.dcc.maya.create_command_port(...)`](#apidccmayacreate_command_port) -> `maya_tools.maya_menu.create_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:287](C:/depot/tools/maya_tools/maya_menu.py:287)
  - same_module: [`api.dcc.maya.get_command_port(...)`](#apidccmayaget_command_port) -> `maya_tools.maya_menu.get_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:232](C:/depot/tools/maya_tools/maya_menu.py:232)
  - same_module: [`api.dcc.maya.initialize_command_port(...)`](#apidccmayainitialize_command_port) -> `maya_tools.maya_menu.initialize_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:322](C:/depot/tools/maya_tools/maya_menu.py:322)
  - same_module: [`api.dcc.maya.save_port_to_file(...)`](#apidccmayasave_port_to_file) -> `maya_tools.maya_menu.save_port_to_file` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:216](C:/depot/tools/maya_tools/maya_menu.py:216)
- Source: [maya_menu.py:67](C:/depot/tools/maya_tools/maya_menu.py:67)

### `api.dcc.maya.apply_enum_data(...)`

- Target: `maya_tools.Rigging.enum_attrs.apply_enum_data`
- Signature: `apply_enum_data(data, prefer_first_match=True, strip_namespaces=True, verbose=True)`
- API names: `apply_enum_data`
- Args:
  - `data`, required
  - `prefer_first_match`, default `True`
  - `strip_namespaces`, default `True`
  - `verbose`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.collect_enum_data(...)`](#apidccmayacollect_enum_data) -> `maya_tools.Rigging.enum_attrs.collect_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:86](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:86)
  - same_module: [`api.dcc.maya.load_enum_data_from_json(...)`](#apidccmayaload_enum_data_from_json) -> `maya_tools.Rigging.enum_attrs.load_enum_data_from_json` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:168](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:168)
  - same_module: [`api.dcc.maya.save_enum_data_to_json(...)`](#apidccmayasave_enum_data_to_json) -> `maya_tools.Rigging.enum_attrs.save_enum_data_to_json` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:150](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:150)
  - same_module: [`api.dcc.maya.export_selected_enum_orders(...)`](#apidccmayaexport_selected_enum_orders) -> `maya_tools.Rigging.enum_attrs.export_selected_enum_orders` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:427](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:427)
  - same_module: [`api.dcc.maya.get_enum_attrs(...)`](#apidccmayaget_enum_attrs) -> `maya_tools.Rigging.enum_attrs.get_enum_attrs` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:73](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:73)
- Description: Apply stored enum data to matching nodes in the current scene.
- Source: [enum_attrs.py:348](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:348)

### `api.dcc.maya.apply_shoulder_profile_to_skin(...)`

- Target: `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin`
- Signature: `apply_shoulder_profile_to_skin(`
- API names: `apply_shoulder_profile_to_skin`
- Args:
  - `mesh` (str), required
  - `skin` (str), required
  - `shoulder_profile` (Optional[dict]), required
  - `blend_strength` (float), default `0.35`
  - `max_influences` (int), default `DEFAULT_MAX_INFLUENCES`
- Related functions:
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_skin(...)`](#apidccmayalearn_shoulder_profile_from_skin) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:228](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:228)
  - same_module: [`api.dcc.maya.build_default_shoulder_profile(...)`](#apidccmayabuild_default_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.build_default_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:164](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:164)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_selected(...)`](#apidccmayalearn_shoulder_profile_from_selected) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:277](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:277)
  - same_module: [`api.dcc.maya.load_shoulder_profile(...)`](#apidccmayaload_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.load_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:213](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:213)
- Source: [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)

### `api.dcc.maya.apply_shoulder_profile_to_weights(...)`

- Target: `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights`
- Signature: `apply_shoulder_profile_to_weights(`
- API names: `apply_shoulder_profile_to_weights`
- Args:
  - `pos` (om.MVector), required
  - `weights` (WeightList), required
  - `shoulder_profile` (Optional[dict]), required
  - `blend_strength` (float), required
  - `max_influences` (int), required
- Related functions:
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.apply_auto_weights(...)`](#apidccmayaapply_auto_weights) -> `maya_tools.Rigging.auto_skinner.apply_auto_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:475](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:475)
  - same_module: [`api.dcc.maya.build_default_shoulder_profile(...)`](#apidccmayabuild_default_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.build_default_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:164](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:164)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_selected(...)`](#apidccmayalearn_shoulder_profile_from_selected) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:277](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:277)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_skin(...)`](#apidccmayalearn_shoulder_profile_from_skin) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:228](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:228)
- Source: [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)

### `api.dcc.maya.apply_side_color_override(...)`

- Target: `maya_tools.Rigging.create_rig.apply_side_color_override`
- Signature: `apply_side_color_override(node)`
- API names: `apply_side_color_override`
- Args:
  - `node`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_side_prefix(...)`](#apidccmayaget_side_prefix) -> `maya_tools.Rigging.create_rig.get_side_prefix` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1076](C:/depot/tools/maya_tools/Rigging/create_rig.py:1076)
- Description: Auto-detect side from name and apply viewport override color to the SHAPE. l_ -> blue (6) r_ -> red (13) center -> yellow (17) :param node: ctrl to edit :return:
- Source: [create_rig.py:948](C:/depot/tools/maya_tools/Rigging/create_rig.py:948)

### `api.dcc.maya.auto_skin_mesh(...)`

- Target: `maya_tools.Rigging.auto_skinner.auto_skin_mesh`
- Signature: `auto_skin_mesh(`
- API names: `auto_skin_mesh`
- Args:
  - `mesh` (str), required
  - `root_joint` (str), default `'origin'`
  - `max_influences` (int), default `DEFAULT_MAX_INFLUENCES`
  - `smooth_iterations` (int), default `2`
  - `replace_existing_skin` (bool), default `False`
  - `falloff_power` (float), default `2.0`
  - `bind_method` (int), default `DEFAULT_BIND_METHOD`
  - `custom_distance_weights` (bool), default `True`
  - `geodesic_voxel_falloff` (float), default `0.0`
  - `geodesic_voxel_resolution` (int), default `256`
  - `shoulder_profile` (Optional[object]), default `None`
  - `shoulder_blend_strength` (float), default `0.0`
- Related functions:
  - same_module: [`api.dcc.maya.auto_skin_selected(...)`](#apidccmayaauto_skin_selected) -> `maya_tools.Rigging.auto_skinner.auto_skin_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:622](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:622)
  - same_module: [`api.dcc.maya.apply_auto_weights(...)`](#apidccmayaapply_auto_weights) -> `maya_tools.Rigging.auto_skinner.apply_auto_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:475](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:475)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.bind_mesh(...)`](#apidccmayabind_mesh) -> `maya_tools.Rigging.auto_skinner.bind_mesh` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:375](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:375)
  - same_module: [`api.dcc.maya.find_skin_cluster(...)`](#apidccmayafind_skin_cluster) -> `maya_tools.Rigging.auto_skinner.find_skin_cluster` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:62](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:62)
- Source: [auto_skinner.py:588](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:588)

### `api.dcc.maya.auto_skin_selected(...)`

- Target: `maya_tools.Rigging.auto_skinner.auto_skin_selected`
- Signature: `auto_skin_selected(`
- API names: `auto_skin_selected`
- Args:
  - `root_joint` (str), default `'origin'`
  - `max_influences` (int), default `DEFAULT_MAX_INFLUENCES`
  - `smooth_iterations` (int), default `2`
  - `replace_existing_skin` (bool), default `False`
  - `falloff_power` (float), default `2.0`
  - `bind_method` (int), default `DEFAULT_BIND_METHOD`
  - `custom_distance_weights` (bool), default `True`
  - `geodesic_voxel_falloff` (float), default `0.0`
  - `geodesic_voxel_resolution` (int), default `256`
  - `shoulder_profile` (Optional[object]), default `None`
  - `shoulder_blend_strength` (float), default `0.0`
- Related functions:
  - same_module: [`api.dcc.maya.auto_skin_mesh(...)`](#apidccmayaauto_skin_mesh) -> `maya_tools.Rigging.auto_skinner.auto_skin_mesh` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:588](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:588)
  - same_module: [`api.dcc.maya.apply_auto_weights(...)`](#apidccmayaapply_auto_weights) -> `maya_tools.Rigging.auto_skinner.apply_auto_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:475](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:475)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.find_skin_cluster(...)`](#apidccmayafind_skin_cluster) -> `maya_tools.Rigging.auto_skinner.find_skin_cluster` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:62](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:62)
  - same_module: [`api.dcc.maya.get_skin_joints(...)`](#apidccmayaget_skin_joints) -> `maya_tools.Rigging.auto_skinner.get_skin_joints` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:93](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:93)
- Source: [auto_skinner.py:622](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:622)

### `api.dcc.maya.bake_all_keyable_attributes(...)`

- Target: `maya_tools.Animation.anim_export.anim_export.bake_all_keyable_attributes`
- Signature: `bake_all_keyable_attributes(nodes, start_frame, end_frame)`
- API names: `bake_all_keyable_attributes`
- Args:
  - `nodes`, required
  - `start_frame`, required
  - `end_frame`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_all_joint_children(...)`](#apidccmayaget_all_joint_children) -> `maya_tools.Animation.anim_export.anim_export.get_all_joint_children` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:121](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:121)
- Description: :param nodes: nodes to bake :param start_frame: start of range to bake :param end_frame: end of range to bake :return:
- Source: [anim_export.py:135](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:135)

### `api.dcc.maya.bake_joint_orient_to_rotate(...)`

- Target: `maya_tools.Rigging.create_rig.bake_joint_orient_to_rotate`
- Signature: `bake_joint_orient_to_rotate(joints=None)`
- API names: `bake_joint_orient_to_rotate`
- Args:
  - `joints`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.create_joint_controls(...)`](#apidccmayacreate_joint_controls) -> `maya_tools.Rigging.create_rig.create_joint_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:975](C:/depot/tools/maya_tools/Rigging/create_rig.py:975)
  - same_module: [`api.dcc.maya.mirror_joint_yz_behavior_with_label_flip(...)`](#apidccmayamirror_joint_yz_behavior_with_label_flip) -> `maya_tools.Rigging.create_rig.mirror_joint_yz_behavior_with_label_flip` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2655](C:/depot/tools/maya_tools/Rigging/create_rig.py:2655)
  - same_module: [`api.dcc.maya.orient_control_pad_to_world_safely(...)`](#apidccmayaorient_control_pad_to_world_safely) -> `maya_tools.Rigging.create_rig.orient_control_pad_to_world_safely` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:885](C:/depot/tools/maya_tools/Rigging/create_rig.py:885)
  - same_module: [`api.dcc.maya.snap_to_joint_matrix(...)`](#apidccmayasnap_to_joint_matrix) -> `maya_tools.Rigging.create_rig.snap_to_joint_matrix` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:874](C:/depot/tools/maya_tools/Rigging/create_rig.py:874)
- Description: Moves jointOrient values into rotate channels while preserving world-space pose. :param joints: list of joints to bake; all joints if None :return: None
- Source: [create_rig.py:1935](C:/depot/tools/maya_tools/Rigging/create_rig.py:1935)

### `api.dcc.maya.bind_mesh(...)`

- Target: `maya_tools.Rigging.auto_skinner.bind_mesh`
- Signature: `bind_mesh(`
- API names: `bind_mesh`
- Args:
  - `mesh` (str), required
  - `joints` (Sequence[str]), required
  - `max_influences` (int), default `DEFAULT_MAX_INFLUENCES`
  - `replace_existing` (bool), default `False`
  - `bind_method` (int), default `DEFAULT_BIND_METHOD`
- Related functions:
  - same_module: [`api.dcc.maya.auto_skin_mesh(...)`](#apidccmayaauto_skin_mesh) -> `maya_tools.Rigging.auto_skinner.auto_skin_mesh` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:588](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:588)
  - same_module: [`api.dcc.maya.get_mesh_vertices(...)`](#apidccmayaget_mesh_vertices) -> `maya_tools.Rigging.auto_skinner.get_mesh_vertices` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:147](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:147)
  - same_module: [`api.dcc.maya.run_geodesic_voxel_bind(...)`](#apidccmayarun_geodesic_voxel_bind) -> `maya_tools.Rigging.auto_skinner.run_geodesic_voxel_bind` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:409](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:409)
- Source: [auto_skinner.py:375](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:375)

### `api.dcc.maya.build_basic_biped_skeleton(...)`

- Target: `maya_tools.Rigging.joint_placer.build_basic_biped_skeleton`
- Signature: `build_basic_biped_skeleton(`
- API names: `build_basic_biped_skeleton`
- Args:
  - `mesh` (str), required
  - `orient` (bool), default `True`
  - `replace_existing` (bool), default `True`
  - `create_guides` (bool), default `False`
- Related functions:
  - same_module: [`api.dcc.maya.build_skeleton_from_points(...)`](#apidccmayabuild_skeleton_from_points) -> `maya_tools.Rigging.joint_placer.build_skeleton_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:424](C:/depot/tools/maya_tools/Rigging/joint_placer.py:424)
  - same_module: [`api.dcc.maya.solve_basic_biped_points(...)`](#apidccmayasolve_basic_biped_points) -> `maya_tools.Rigging.joint_placer.solve_basic_biped_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:278](C:/depot/tools/maya_tools/Rigging/joint_placer.py:278)
  - same_module: [`api.dcc.maya.delete_existing_generated_skeleton(...)`](#apidccmayadelete_existing_generated_skeleton) -> `maya_tools.Rigging.joint_placer.delete_existing_generated_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:341](C:/depot/tools/maya_tools/Rigging/joint_placer.py:341)
  - same_module: [`api.dcc.maya.orient_skeleton(...)`](#apidccmayaorient_skeleton) -> `maya_tools.Rigging.joint_placer.orient_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:370](C:/depot/tools/maya_tools/Rigging/joint_placer.py:370)
- Source: [joint_placer.py:516](C:/depot/tools/maya_tools/Rigging/joint_placer.py:516)

### `api.dcc.maya.build_bone_segments(...)`

- Target: `maya_tools.Rigging.auto_skinner.build_bone_segments`
- Signature: `build_bone_segments(joints: Sequence[str]) -> List[Tuple[str, str]]`
- API names: `build_bone_segments`
- Args:
  - `joints` (Sequence[str]), required
- Related functions:
  - same_module: [`api.dcc.maya.build_cached_bone_segments(...)`](#apidccmayabuild_cached_bone_segments) -> `maya_tools.Rigging.auto_skinner.build_cached_bone_segments` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:127](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:127)
  - same_module: [`api.dcc.maya.build_default_shoulder_profile(...)`](#apidccmayabuild_default_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.build_default_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:164](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:164)
- Source: [auto_skinner.py:114](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:114)

### `api.dcc.maya.build_cached_bone_segments(...)`

- Target: `maya_tools.Rigging.auto_skinner.build_cached_bone_segments`
- Signature: `build_cached_bone_segments(joints: Sequence[str]) -> List[BindSegment]`
- API names: `build_cached_bone_segments`
- Args:
  - `joints` (Sequence[str]), required
- Related functions:
  - same_module: [`api.dcc.maya.build_bone_segments(...)`](#apidccmayabuild_bone_segments) -> `maya_tools.Rigging.auto_skinner.build_bone_segments` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:114](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:114)
  - same_module: [`api.dcc.maya.build_default_shoulder_profile(...)`](#apidccmayabuild_default_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.build_default_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:164](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:164)
- Source: [auto_skinner.py:127](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:127)

### `api.dcc.maya.build_default_shoulder_profile(...)`

- Target: `maya_tools.Rigging.auto_skinner.build_default_shoulder_profile`
- Signature: `build_default_shoulder_profile(joints: Sequence[str]) -> dict`
- API names: `build_default_shoulder_profile`
- Args:
  - `joints` (Sequence[str]), required
- Related functions:
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_selected(...)`](#apidccmayalearn_shoulder_profile_from_selected) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:277](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:277)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_skin(...)`](#apidccmayalearn_shoulder_profile_from_skin) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:228](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:228)
  - same_module: [`api.dcc.maya.load_shoulder_profile(...)`](#apidccmayaload_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.load_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:213](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:213)
- Source: [auto_skinner.py:164](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:164)

### `api.dcc.maya.build_enum_names_for_space_targets(...)`

- Target: `maya_tools.Rigging.create_rig.build_enum_names_for_space_targets`
- Signature: `build_enum_names_for_space_targets(targets, side=None)`
- API names: `build_enum_names_for_space_targets`
- Args:
  - `targets`, required
  - `side`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.build_rfl_ik_and_constraints(...)`](#apidccmayabuild_rfl_ik_and_constraints) -> `maya_tools.Rigging.create_rig.build_rfl_ik_and_constraints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:779](C:/depot/tools/maya_tools/Rigging/create_rig.py:779)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_composite_space(...)`](#apidccmayacreate_composite_space) -> `maya_tools.Rigging.create_rig.create_composite_space` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)
  - same_module: [`api.dcc.maya.create_leg_space_switches(...)`](#apidccmayacreate_leg_space_switches) -> `maya_tools.Rigging.create_rig.create_leg_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2711](C:/depot/tools/maya_tools/Rigging/create_rig.py:2711)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
- Description: Build enum display names in the SAME ORDER as the incoming targets. Do not reorder here. Target order must drive enum order. :param targets: list of targets :param side: side :return: result
- Source: [create_rig.py:2403](C:/depot/tools/maya_tools/Rigging/create_rig.py:2403)

### `api.dcc.maya.build_node_lookup(...)`

- Target: `maya_tools.Rigging.enum_attrs.build_node_lookup`
- Signature: `build_node_lookup(strip_namespaces=True)`
- API names: `build_node_lookup`
- Args:
  - `strip_namespaces`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.get_side_from_node(...)`](#apidccmayaget_side_from_node) -> `maya_tools.Rigging.enum_attrs.get_side_from_node` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:23](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:23)
- Description: Build a lookup of scene nodes by short name.
- Source: [enum_attrs.py:328](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:328)

### `api.dcc.maya.build_rfl_ik_and_constraints(...)`

- Target: `maya_tools.Rigging.create_rig.build_rfl_ik_and_constraints`
- Signature: `build_rfl_ik_and_constraints(`
- API names: `build_rfl_ik_and_constraints`
- Args:
  - `side`, required
  - `ik_leg_ctrl`, required
  - `ik_leg_joints`, required
  - `rfl_joints`, required
- Related functions:
  - same_module: [`api.dcc.maya.build_enum_names_for_space_targets(...)`](#apidccmayabuild_enum_names_for_space_targets) -> `maya_tools.Rigging.create_rig.build_enum_names_for_space_targets` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2403](C:/depot/tools/maya_tools/Rigging/create_rig.py:2403)
  - same_module: [`api.dcc.maya.create_rfl_joints_template(...)`](#apidccmayacreate_rfl_joints_template) -> `maya_tools.Rigging.create_rig.create_rfl_joints_template` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)
  - same_module: [`api.dcc.maya.ensure_rfl_attrs(...)`](#apidccmayaensure_rfl_attrs) -> `maya_tools.Rigging.create_rig.ensure_rfl_attrs` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:672](C:/depot/tools/maya_tools/Rigging/create_rig.py:672)
  - same_module: [`api.dcc.maya.preserve_rfl_pivot_joints(...)`](#apidccmayapreserve_rfl_pivot_joints) -> `maya_tools.Rigging.create_rig.preserve_rfl_pivot_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5511](C:/depot/tools/maya_tools/Rigging/create_rig.py:5511)
  - same_module: [`api.dcc.maya.resolve_rfl_joints(...)`](#apidccmayaresolve_rfl_joints) -> `maya_tools.Rigging.create_rig.resolve_rfl_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5891](C:/depot/tools/maya_tools/Rigging/create_rig.py:5891)
- Description: creates full reverse foot setup from existing joints :param side: l or r :param ik_leg_ctrl: actual leg ik ctrl :param ik_leg_joints: list of ['ankle', 'toe', 'toeTip'] joints :param rfl_joints: list of ['heel', 'outerBank', 'innerBank', 'toe', 'toeTip', 'ankle'] joints :return:
- Source: [create_rig.py:779](C:/depot/tools/maya_tools/Rigging/create_rig.py:779)

### `api.dcc.maya.build_skeleton_from_points(...)`

- Target: `maya_tools.Rigging.joint_placer.build_skeleton_from_points`
- Signature: `build_skeleton_from_points(`
- API names: `build_skeleton_from_points`
- Args:
  - `points` (Dict[str, Vector3]), required
  - `root_name` (str), default `'origin'`
  - `orient` (bool), default `True`
  - `replace_existing` (bool), default `True`
  - `pose_type` (str), default `'unknown'`
  - `pose_angle_degrees` (float), default `0.0`
- Related functions:
  - same_module: [`api.dcc.maya.build_basic_biped_skeleton(...)`](#apidccmayabuild_basic_biped_skeleton) -> `maya_tools.Rigging.joint_placer.build_basic_biped_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:516](C:/depot/tools/maya_tools/Rigging/joint_placer.py:516)
  - same_module: [`api.dcc.maya.create_guides_from_points(...)`](#apidccmayacreate_guides_from_points) -> `maya_tools.Rigging.joint_placer.create_guides_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:498](C:/depot/tools/maya_tools/Rigging/joint_placer.py:498)
  - same_module: [`api.dcc.maya.delete_existing_generated_skeleton(...)`](#apidccmayadelete_existing_generated_skeleton) -> `maya_tools.Rigging.joint_placer.delete_existing_generated_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:341](C:/depot/tools/maya_tools/Rigging/joint_placer.py:341)
  - same_module: [`api.dcc.maya.make_hik_maps_from_root(...)`](#apidccmayamake_hik_maps_from_root) -> `maya_tools.Rigging.joint_placer.make_hik_maps_from_root` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:455](C:/depot/tools/maya_tools/Rigging/joint_placer.py:455)
  - same_module: [`api.dcc.maya.orient_skeleton(...)`](#apidccmayaorient_skeleton) -> `maya_tools.Rigging.joint_placer.orient_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:370](C:/depot/tools/maya_tools/Rigging/joint_placer.py:370)
- Source: [joint_placer.py:424](C:/depot/tools/maya_tools/Rigging/joint_placer.py:424)

### `api.dcc.maya.classify_arm_pose(...)`

- Target: `maya_tools.Rigging.joint_placer.classify_arm_pose`
- Signature: `classify_arm_pose(points: Dict[str, Vector3]) -> Tuple[str, float]`
- API names: `classify_arm_pose`
- Args:
  - `points` (Dict[str, Vector3]), required
- Related functions:
  - same_module: [`api.dcc.maya.tag_pose_metadata(...)`](#apidccmayatag_pose_metadata) -> `maya_tools.Rigging.joint_placer.tag_pose_metadata` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:336](C:/depot/tools/maya_tools/Rigging/joint_placer.py:336)
- Description: Classify generated arm placement as T-pose or A-pose from shoulder-to-hand slope. Returns: tuple[str, float]: pose label and absolute arm-down angle from horizontal.
- Source: [joint_placer.py:149](C:/depot/tools/maya_tools/Rigging/joint_placer.py:149)

### `api.dcc.maya.cleanup_command_port_files(...)`

- Target: `maya_tools.maya_menu.cleanup_command_port_files`
- Signature: `cleanup_command_port_files(*args)`
- API names: `cleanup_command_port_files`
- Args:
  - `*args`, required
- Related functions:
  - same_module: [`api.dcc.maya.apply_command_port_python3_patches(...)`](#apidccmayaapply_command_port_python3_patches) -> `maya_tools.maya_menu.apply_command_port_python3_patches` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:67](C:/depot/tools/maya_tools/maya_menu.py:67)
  - same_module: [`api.dcc.maya.create_command_port(...)`](#apidccmayacreate_command_port) -> `maya_tools.maya_menu.create_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:287](C:/depot/tools/maya_tools/maya_menu.py:287)
  - same_module: [`api.dcc.maya.get_command_port(...)`](#apidccmayaget_command_port) -> `maya_tools.maya_menu.get_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:232](C:/depot/tools/maya_tools/maya_menu.py:232)
  - same_module: [`api.dcc.maya.initialize_command_port(...)`](#apidccmayainitialize_command_port) -> `maya_tools.maya_menu.initialize_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:322](C:/depot/tools/maya_tools/maya_menu.py:322)
  - same_module: [`api.dcc.maya.save_port_to_file(...)`](#apidccmayasave_port_to_file) -> `maya_tools.maya_menu.save_port_to_file` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:216](C:/depot/tools/maya_tools/maya_menu.py:216)
- Source: [maya_menu.py:196](C:/depot/tools/maya_tools/maya_menu.py:196)

### `api.dcc.maya.clear_module_metadata(...)`

- Target: `maya_tools.Rigging.create_rig.clear_module_metadata`
- Signature: `clear_module_metadata(module_id)`
- API names: `clear_module_metadata`
- Args:
  - `module_id`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_all_module_metadata(...)`](#apidccmayaget_all_module_metadata) -> `maya_tools.Rigging.create_rig.get_all_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6594](C:/depot/tools/maya_tools/Rigging/create_rig.py:6594)
  - same_module: [`api.dcc.maya.load_module_metadata(...)`](#apidccmayaload_module_metadata) -> `maya_tools.Rigging.create_rig.load_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6575](C:/depot/tools/maya_tools/Rigging/create_rig.py:6575)
  - same_module: [`api.dcc.maya.save_module_metadata(...)`](#apidccmayasave_module_metadata) -> `maya_tools.Rigging.create_rig.save_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6549](C:/depot/tools/maya_tools/Rigging/create_rig.py:6549)
  - same_module: [`api.dcc.maya.get_module_controls(...)`](#apidccmayaget_module_controls) -> `maya_tools.Rigging.create_rig.get_module_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5820](C:/depot/tools/maya_tools/Rigging/create_rig.py:5820)
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
- Description: Mark a module as not built while keeping its joint/parent info. :param module_id: unique module identifier :return: None
- Source: [create_rig.py:6613](C:/depot/tools/maya_tools/Rigging/create_rig.py:6613)

### `api.dcc.maya.closest_point_on_segment(...)`

- Target: `maya_tools.Rigging.auto_skinner.closest_point_on_segment`
- Signature: `closest_point_on_segment(point: om.MVector, a: om.MVector, b: om.MVector) -> Tuple[om.MVector, float]`
- API names: `closest_point_on_segment`
- Args:
  - `point` (om.MVector), required
  - `a` (om.MVector), required
  - `b` (om.MVector), required
- Source: [auto_skinner.py:135](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:135)

### `api.dcc.maya.collect_enum_data(...)`

- Target: `maya_tools.Rigging.enum_attrs.collect_enum_data`
- Signature: `collect_enum_data(nodes=None, attr_filter=None, strip_namespaces=True)`
- API names: `collect_enum_data`
- Args:
  - `nodes`, default `None`
  - `attr_filter`, default `None`
  - `strip_namespaces`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.apply_enum_data(...)`](#apidccmayaapply_enum_data) -> `maya_tools.Rigging.enum_attrs.apply_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:348](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:348)
  - same_module: [`api.dcc.maya.load_enum_data_from_json(...)`](#apidccmayaload_enum_data_from_json) -> `maya_tools.Rigging.enum_attrs.load_enum_data_from_json` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:168](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:168)
  - same_module: [`api.dcc.maya.save_enum_data_to_json(...)`](#apidccmayasave_enum_data_to_json) -> `maya_tools.Rigging.enum_attrs.save_enum_data_to_json` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:150](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:150)
  - same_module: [`api.dcc.maya.export_selected_enum_orders(...)`](#apidccmayaexport_selected_enum_orders) -> `maya_tools.Rigging.enum_attrs.export_selected_enum_orders` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:427](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:427)
  - same_module: [`api.dcc.maya.get_enum_attrs(...)`](#apidccmayaget_enum_attrs) -> `maya_tools.Rigging.enum_attrs.get_enum_attrs` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:73](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:73)
- Description: Collect enum definitions from nodes. Parameters ---------- nodes : list[str] or None Nodes to inspect. If None, uses selection. attr_filter : list[str] or None If provided, only these enum attrs are exported. strip_namespaces : bool If True, stores short node names without namespaces. Returns ------- dict
- Source: [enum_attrs.py:86](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:86)

### `api.dcc.maya.constrain_controls_to_two_parents(...)`

- Target: `maya_tools.Rigging.create_rig.constrain_controls_to_two_parents`
- Signature: `constrain_controls_to_two_parents(`
- API names: `constrain_controls_to_two_parents`
- Args:
  - `controls`, required
  - `parent1`, required
  - `parent2`, required
  - `parent1_value`, default `1.0`
  - `parent2_value`, default `0.0`
  - `maintain_offset`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.safe_constrain_two_parents(...)`](#apidccmayasafe_constrain_two_parents) -> `maya_tools.Rigging.create_rig.safe_constrain_two_parents` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3853](C:/depot/tools/maya_tools/Rigging/create_rig.py:3853)
  - same_module: [`api.dcc.maya.create_joint_controls(...)`](#apidccmayacreate_joint_controls) -> `maya_tools.Rigging.create_rig.create_joint_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:975](C:/depot/tools/maya_tools/Rigging/create_rig.py:975)
  - same_module: [`api.dcc.maya.get_module_controls(...)`](#apidccmayaget_module_controls) -> `maya_tools.Rigging.create_rig.get_module_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5820](C:/depot/tools/maya_tools/Rigging/create_rig.py:5820)
- Description: Apply a parentConstraint to each control in the list using parent1 and parent2 as drivers. :param controls: Controls to constrain :param parent1: First parent/driver :param parent2: Second parent/driver :param parent1_value: Weight value for parent1 :param parent2_value: Weight value for parent2 :param maintain_offset: Whether to maintain offset :return: list[str]
- Source: [create_rig.py:1868](C:/depot/tools/maya_tools/Rigging/create_rig.py:1868)

### `api.dcc.maya.create_and_populate_export_node(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.create_and_populate_export_node`
- Signature: `create_and_populate_export_node(anim_dict, skeletons, uproject, log_path, cmd_path, export_directory, namespace_skeleton_map)`
- API names: `create_and_populate_export_node`
- Args:
  - `anim_dict`, required
  - `skeletons`, required
  - `uproject`, required
  - `log_path`, required
  - `cmd_path`, required
  - `export_directory`, required
  - `namespace_skeleton_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.export_node_exists(...)`](#apidccmayaexport_node_exists) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.export_node_exists` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:59](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:59)
  - same_module: [`api.dcc.maya.get_export_node_data(...)`](#apidccmayaget_export_node_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:271](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:271)
- Description: Data is passed from the UI, likely wont need to call from Maya directly (just separating out cmds calls into this file) :param anim_dict: :param skeletons: :param uproject: :param log_path: :param cmd_path: :param export_directory: :param namespace_skeleton_map: :return:
- Source: [sequence_utils.py:241](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:241)

### `api.dcc.maya.create_arm_space_switches(...)`

- Target: `maya_tools.Rigging.create_rig.create_arm_space_switches`
- Signature: `create_arm_space_switches(side, body_joint_map=None)`
- API names: `create_arm_space_switches`
- Args:
  - `side`, required
  - `body_joint_map`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.create_leg_space_switches(...)`](#apidccmayacreate_leg_space_switches) -> `maya_tools.Rigging.create_rig.create_leg_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2711](C:/depot/tools/maya_tools/Rigging/create_rig.py:2711)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.create_composite_space(...)`](#apidccmayacreate_composite_space) -> `maya_tools.Rigging.create_rig.create_composite_space` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)
  - same_module: [`api.dcc.maya.create_space_switch(...)`](#apidccmayacreate_space_switch) -> `maya_tools.Rigging.create_rig.create_space_switch` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2269](C:/depot/tools/maya_tools/Rigging/create_rig.py:2269)
  - same_module: [`api.dcc.maya.query_space_switches(...)`](#apidccmayaquery_space_switches) -> `maya_tools.Rigging.create_rig.query_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4197](C:/depot/tools/maya_tools/Rigging/create_rig.py:4197)
- Description: Builds space switches (including composite spaces) for the Arm module. :param side: left or right side (l/r) :param body_joint_map: optional body joint mapping dictionary :return: None
- Source: [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)

### `api.dcc.maya.create_auto_joints_for_mesh(...)`

- Target: `maya_tools.Rigging.joint_placer.create_auto_joints_for_mesh`
- Signature: `create_auto_joints_for_mesh(`
- API names: `create_auto_joints_for_mesh`
- Args:
  - `mesh` (str), required
  - `orient` (bool), default `True`
  - `replace_existing` (bool), default `True`
  - `create_guides` (bool), default `False`
- Related functions:
  - same_module: [`api.dcc.maya.create_auto_joints_for_selected_mesh(...)`](#apidccmayacreate_auto_joints_for_selected_mesh) -> `maya_tools.Rigging.joint_placer.create_auto_joints_for_selected_mesh` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:575](C:/depot/tools/maya_tools/Rigging/joint_placer.py:575)
  - same_module: [`api.dcc.maya.create_guides_from_points(...)`](#apidccmayacreate_guides_from_points) -> `maya_tools.Rigging.joint_placer.create_guides_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:498](C:/depot/tools/maya_tools/Rigging/joint_placer.py:498)
  - same_module: [`api.dcc.maya.create_joint(...)`](#apidccmayacreate_joint) -> `maya_tools.Rigging.joint_placer.create_joint` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:351](C:/depot/tools/maya_tools/Rigging/joint_placer.py:351)
  - same_module: [`api.dcc.maya.get_mesh_bounds(...)`](#apidccmayaget_mesh_bounds) -> `maya_tools.Rigging.joint_placer.get_mesh_bounds` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:250](C:/depot/tools/maya_tools/Rigging/joint_placer.py:250)
- Source: [joint_placer.py:560](C:/depot/tools/maya_tools/Rigging/joint_placer.py:560)

### `api.dcc.maya.create_auto_joints_for_selected_mesh(...)`

- Target: `maya_tools.Rigging.joint_placer.create_auto_joints_for_selected_mesh`
- Signature: `create_auto_joints_for_selected_mesh(`
- API names: `create_auto_joints_for_selected_mesh`
- Args:
  - `orient` (bool), default `True`
  - `replace_existing` (bool), default `True`
  - `create_guides` (bool), default `False`
- Related functions:
  - same_module: [`api.dcc.maya.create_auto_joints_for_mesh(...)`](#apidccmayacreate_auto_joints_for_mesh) -> `maya_tools.Rigging.joint_placer.create_auto_joints_for_mesh` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:560](C:/depot/tools/maya_tools/Rigging/joint_placer.py:560)
  - same_module: [`api.dcc.maya.create_guides_from_points(...)`](#apidccmayacreate_guides_from_points) -> `maya_tools.Rigging.joint_placer.create_guides_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:498](C:/depot/tools/maya_tools/Rigging/joint_placer.py:498)
  - same_module: [`api.dcc.maya.create_joint(...)`](#apidccmayacreate_joint) -> `maya_tools.Rigging.joint_placer.create_joint` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:351](C:/depot/tools/maya_tools/Rigging/joint_placer.py:351)
  - same_module: [`api.dcc.maya.get_mesh_bounds(...)`](#apidccmayaget_mesh_bounds) -> `maya_tools.Rigging.joint_placer.get_mesh_bounds` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:250](C:/depot/tools/maya_tools/Rigging/joint_placer.py:250)
- Source: [joint_placer.py:575](C:/depot/tools/maya_tools/Rigging/joint_placer.py:575)

### `api.dcc.maya.create_bi_arrow_ctrl(...)`

- Target: `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl`
- Signature: `create_bi_arrow_ctrl(name, size=1.2)`
- API names: `create_bi_arrow_ctrl`
- Args:
  - `name`, required
  - `size`, default `1.2`
- Related functions:
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
  - same_module: [`api.dcc.maya.create_diamond_ctrl(...)`](#apidccmayacreate_diamond_ctrl) -> `maya_tools.Rigging.create_rig.create_diamond_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:35](C:/depot/tools/maya_tools/Rigging/create_rig.py:35)
  - same_module: [`api.dcc.maya.create_prism_ctrl(...)`](#apidccmayacreate_prism_ctrl) -> `maya_tools.Rigging.create_rig.create_prism_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:66](C:/depot/tools/maya_tools/Rigging/create_rig.py:66)
  - same_module: [`api.dcc.maya.create_sphere_ctrl(...)`](#apidccmayacreate_sphere_ctrl) -> `maya_tools.Rigging.create_rig.create_sphere_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:189](C:/depot/tools/maya_tools/Rigging/create_rig.py:189)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
- Description: Two arrows pointing in opposite directions, rotated 90° around X-axis :param name: ctrl name :param size: relative size mult :return:
- Source: [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)

### `api.dcc.maya.create_brow_main_setup(...)`

- Target: `maya_tools.Rigging.create_rig.create_brow_main_setup`
- Signature: `create_brow_main_setup(side, root_parent='head1_ctrl')`
- API names: `create_brow_main_setup`
- Args:
  - `side`, required
  - `root_parent`, default `'head1_ctrl'`
- Related functions:
  - same_module: [`api.dcc.maya.create_eye_aim_setup(...)`](#apidccmayacreate_eye_aim_setup) -> `maya_tools.Rigging.create_rig.create_eye_aim_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3001](C:/depot/tools/maya_tools/Rigging/create_rig.py:3001)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_composite_space(...)`](#apidccmayacreate_composite_space) -> `maya_tools.Rigging.create_rig.create_composite_space` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
- Description: Creates the main eyebrows setup, snapping it to the middle brow control. :param side: Left or right side (l/r) :param root_parent: Parent control node name :return: dict
- Source: [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)

### `api.dcc.maya.create_command_port(...)`

- Target: `maya_tools.maya_menu.create_command_port`
- Signature: `create_command_port(port=COMMAND_PORT_START, stp="python")`
- API names: `create_command_port`
- Args:
  - `port`, default `COMMAND_PORT_START`
  - `stp`, default `'python'`
- Related functions:
  - same_module: [`api.dcc.maya.apply_command_port_python3_patches(...)`](#apidccmayaapply_command_port_python3_patches) -> `maya_tools.maya_menu.apply_command_port_python3_patches` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:67](C:/depot/tools/maya_tools/maya_menu.py:67)
  - same_module: [`api.dcc.maya.cleanup_command_port_files(...)`](#apidccmayacleanup_command_port_files) -> `maya_tools.maya_menu.cleanup_command_port_files` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:196](C:/depot/tools/maya_tools/maya_menu.py:196)
  - same_module: [`api.dcc.maya.get_command_port(...)`](#apidccmayaget_command_port) -> `maya_tools.maya_menu.get_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:232](C:/depot/tools/maya_tools/maya_menu.py:232)
  - same_module: [`api.dcc.maya.initialize_command_port(...)`](#apidccmayainitialize_command_port) -> `maya_tools.maya_menu.initialize_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:322](C:/depot/tools/maya_tools/maya_menu.py:322)
  - same_module: [`api.dcc.maya.create_maya_menu(...)`](#apidccmayacreate_maya_menu) -> `maya_tools.maya_menu.create_maya_menu` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:422](C:/depot/tools/maya_tools/maya_menu.py:422)
- Source: [maya_menu.py:287](C:/depot/tools/maya_tools/maya_menu.py:287)

### `api.dcc.maya.create_composite_space(...)`

- Target: `maya_tools.Rigging.create_rig.create_composite_space`
- Signature: `create_composite_space(name, parents, match_to, parent_node=None)`
- API names: `create_composite_space`
- Args:
  - `name`, required
  - `parents`, required
  - `match_to`, required
  - `parent_node`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_leg_space_switches(...)`](#apidccmayacreate_leg_space_switches) -> `maya_tools.Rigging.create_rig.create_leg_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2711](C:/depot/tools/maya_tools/Rigging/create_rig.py:2711)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.create_space_switch(...)`](#apidccmayacreate_space_switch) -> `maya_tools.Rigging.create_rig.create_space_switch` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2269](C:/depot/tools/maya_tools/Rigging/create_rig.py:2269)
  - same_module: [`api.dcc.maya.build_enum_names_for_space_targets(...)`](#apidccmayabuild_enum_names_for_space_targets) -> `maya_tools.Rigging.create_rig.build_enum_names_for_space_targets` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2403](C:/depot/tools/maya_tools/Rigging/create_rig.py:2403)
- Description: Creates a transform constrained to multiple parents, matched to the driven group. :param name: name of the composite space node to create :param parents: list of parent control nodes :param match_to: node to match position/orientation to :param parent_node: optional node to parent the created space transform under before constraining :return: str or None
- Source: [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)

### `api.dcc.maya.create_cube_ctrl(...)`

- Target: `maya_tools.Rigging.create_rig.create_cube_ctrl`
- Signature: `create_cube_ctrl(name, size=1.5)`
- API names: `create_cube_ctrl`
- Args:
  - `name`, required
  - `size`, default `1.5`
- Related functions:
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_diamond_ctrl(...)`](#apidccmayacreate_diamond_ctrl) -> `maya_tools.Rigging.create_rig.create_diamond_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:35](C:/depot/tools/maya_tools/Rigging/create_rig.py:35)
  - same_module: [`api.dcc.maya.create_prism_ctrl(...)`](#apidccmayacreate_prism_ctrl) -> `maya_tools.Rigging.create_rig.create_prism_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:66](C:/depot/tools/maya_tools/Rigging/create_rig.py:66)
  - same_module: [`api.dcc.maya.create_sphere_ctrl(...)`](#apidccmayacreate_sphere_ctrl) -> `maya_tools.Rigging.create_rig.create_sphere_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:189](C:/depot/tools/maya_tools/Rigging/create_rig.py:189)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
- Description: Wireframe cube control :param name: control name :param size: local size mult :return:
- Source: [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)

### `api.dcc.maya.create_diamond_ctrl(...)`

- Target: `maya_tools.Rigging.create_rig.create_diamond_ctrl`
- Signature: `create_diamond_ctrl(name, size=1.0, normal=(0, 1, 0))`
- API names: `create_diamond_ctrl`
- Args:
  - `name`, required
  - `size`, default `1.0`
  - `normal`, default `(0, 1, 0)`
- Related functions:
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
  - same_module: [`api.dcc.maya.create_prism_ctrl(...)`](#apidccmayacreate_prism_ctrl) -> `maya_tools.Rigging.create_rig.create_prism_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:66](C:/depot/tools/maya_tools/Rigging/create_rig.py:66)
  - same_module: [`api.dcc.maya.create_sphere_ctrl(...)`](#apidccmayacreate_sphere_ctrl) -> `maya_tools.Rigging.create_rig.create_sphere_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:189](C:/depot/tools/maya_tools/Rigging/create_rig.py:189)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
- Description: Creates a diamond-shaped nurbsCurve control. :param name: ctrl_name :param size: local size mult :param normal: relative direction :return:
- Source: [create_rig.py:35](C:/depot/tools/maya_tools/Rigging/create_rig.py:35)

### `api.dcc.maya.create_eye_aim_setup(...)`

- Target: `maya_tools.Rigging.create_rig.create_eye_aim_setup`
- Signature: `create_eye_aim_setup(`
- API names: `create_eye_aim_setup`
- Args:
  - `left_eye_joint`, default `'l_eye'`
  - `right_eye_joint`, default `'r_eye'`
  - `aim_distance`, default `25`
  - `head_ctrl`, default `'head1_ctrl'`
- Related functions:
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_composite_space(...)`](#apidccmayacreate_composite_space) -> `maya_tools.Rigging.create_rig.create_composite_space` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
- Description: Creates a standard left/right eye aim setup with a shared center aim control. :param left_eye_joint: left eye joint name :param right_eye_joint: right eye joint name :param aim_distance: local aim control distance offset :param head_ctrl: head parent control name :return: dict
- Source: [create_rig.py:3001](C:/depot/tools/maya_tools/Rigging/create_rig.py:3001)

### `api.dcc.maya.create_finger_rigs(...)`

- Target: `maya_tools.Rigging.create_rig.create_finger_rigs`
- Signature: `create_finger_rigs(finger_joints, hand_driver=None)`
- API names: `create_finger_rigs`
- Args:
  - `finger_joints`, required
  - `hand_driver`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.create_composite_space(...)`](#apidccmayacreate_composite_space) -> `maya_tools.Rigging.create_rig.create_composite_space` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
- Description: Creates IK driven FK system for finger joints :param finger_joints: finger joints :param hand_driver: parent transform/joint name to parent finger rigs under :return:
- Source: [create_rig.py:1969](C:/depot/tools/maya_tools/Rigging/create_rig.py:1969)

### `api.dcc.maya.create_full_rig(...)`

- Target: `maya_tools.Rigging.create_rig.create_full_rig`
- Signature: `create_full_rig(arm_joints=None, leg_joints=None, spine_joints=None, neck_joints=None, root_joints=None,`
- API names: `create_full_rig`
- Args:
  - `arm_joints`, default `None`
  - `leg_joints`, default `None`
  - `spine_joints`, default `None`
  - `neck_joints`, default `None`
  - `root_joints`, default `None`
  - `hip_swing`, default `'hipswing'`
  - `face_joint_map`, default `None`
  - `face_joints`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.create_rig(...)`](#apidccmayacreate_rig) -> `maya_tools.Rigging.create_rig.create_rig_from_mapping` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4127](C:/depot/tools/maya_tools/Rigging/create_rig.py:4127)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.remove_full_rig(...)`](#apidccmayaremove_full_rig) -> `maya_tools.Rigging.create_rig.remove_full_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4064](C:/depot/tools/maya_tools/Rigging/create_rig.py:4064)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
- Description: Builds the entire character rig by coordinating modular setup builders. :param arm_joints: list of mapped arm joints :param leg_joints: list or dict of mapped leg joints :param spine_joints: list of mapped spine joints :param neck_joints: list of mapped neck/head joints :param root_joints: list of mapped root/pelvis joints :param hip_swing: hipswing name or prefix :param face_joint_map: mapping dictionary for face joints :param face_joints: list of face joints :return: dict
- Source: [create_rig.py:3870](C:/depot/tools/maya_tools/Rigging/create_rig.py:3870)

### `api.dcc.maya.create_guides_from_points(...)`

- Target: `maya_tools.Rigging.joint_placer.create_guides_from_points`
- Signature: `create_guides_from_points(points: Dict[str, Vector3], group_name: str = "auto_joint_guides_grp") -> List[str]`
- API names: `create_guides_from_points`
- Args:
  - `points` (Dict[str, Vector3]), required
  - `group_name` (str), default `'auto_joint_guides_grp'`
- Related functions:
  - same_module: [`api.dcc.maya.build_skeleton_from_points(...)`](#apidccmayabuild_skeleton_from_points) -> `maya_tools.Rigging.joint_placer.build_skeleton_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:424](C:/depot/tools/maya_tools/Rigging/joint_placer.py:424)
  - same_module: [`api.dcc.maya.create_auto_joints_for_mesh(...)`](#apidccmayacreate_auto_joints_for_mesh) -> `maya_tools.Rigging.joint_placer.create_auto_joints_for_mesh` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:560](C:/depot/tools/maya_tools/Rigging/joint_placer.py:560)
  - same_module: [`api.dcc.maya.create_auto_joints_for_selected_mesh(...)`](#apidccmayacreate_auto_joints_for_selected_mesh) -> `maya_tools.Rigging.joint_placer.create_auto_joints_for_selected_mesh` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:575](C:/depot/tools/maya_tools/Rigging/joint_placer.py:575)
  - same_module: [`api.dcc.maya.create_joint(...)`](#apidccmayacreate_joint) -> `maya_tools.Rigging.joint_placer.create_joint` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:351](C:/depot/tools/maya_tools/Rigging/joint_placer.py:351)
  - same_module: [`api.dcc.maya.make_hik_maps_from_root(...)`](#apidccmayamake_hik_maps_from_root) -> `maya_tools.Rigging.joint_placer.make_hik_maps_from_root` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:455](C:/depot/tools/maya_tools/Rigging/joint_placer.py:455)
- Description: Optional visual guide locators for debugging/approval before skeleton creation.
- Source: [joint_placer.py:498](C:/depot/tools/maya_tools/Rigging/joint_placer.py:498)

### `api.dcc.maya.create_ik_fk_limb(...)`

- Target: `maya_tools.Rigging.create_rig.create_ik_fk_limb`
- Signature: `create_ik_fk_limb(sel, root_parent)`
- API names: `create_ik_fk_limb`
- Args:
  - `sel`, required
  - `root_parent`, required
- Related functions:
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.create_composite_space(...)`](#apidccmayacreate_composite_space) -> `maya_tools.Rigging.create_rig.create_composite_space` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
- Description: Creates an IK/FK limb from either: - 3 joints (arm) - 4+ joints (leg with extra joints) Behavior is determined purely by joint count. :param sel: list of joints in the limb chain (top -> mid -> end -> optional extras) :param root_parent: transform to parent FK controls / IK controls under :return: { "fk_chain": fk_joints, "ik_chain": ik_joints, "driver_chain": driver_joints, "fk_controls": fk_ctrls, "ik_ctrl": ik_ctrl, "pv_ctrl": pv_ctrl, "ik_handle": ik_handle, "blend_constraints": blend_constr
- Source: [create_rig.py:324](C:/depot/tools/maya_tools/Rigging/create_rig.py:324)

### `api.dcc.maya.create_joint(...)`

- Target: `maya_tools.Rigging.joint_placer.create_joint`
- Signature: `create_joint(name: str, position: Vector3, parent: Optional[str] = None, radius: float = 1.0) -> str`
- API names: `create_joint`
- Args:
  - `name` (str), required
  - `position` (Vector3), required
  - `parent` (Optional[str]), default `None`
  - `radius` (float), default `1.0`
- Related functions:
  - same_module: [`api.dcc.maya.create_auto_joints_for_mesh(...)`](#apidccmayacreate_auto_joints_for_mesh) -> `maya_tools.Rigging.joint_placer.create_auto_joints_for_mesh` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:560](C:/depot/tools/maya_tools/Rigging/joint_placer.py:560)
  - same_module: [`api.dcc.maya.create_auto_joints_for_selected_mesh(...)`](#apidccmayacreate_auto_joints_for_selected_mesh) -> `maya_tools.Rigging.joint_placer.create_auto_joints_for_selected_mesh` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:575](C:/depot/tools/maya_tools/Rigging/joint_placer.py:575)
  - same_module: [`api.dcc.maya.create_guides_from_points(...)`](#apidccmayacreate_guides_from_points) -> `maya_tools.Rigging.joint_placer.create_guides_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:498](C:/depot/tools/maya_tools/Rigging/joint_placer.py:498)
  - same_module: [`api.dcc.maya.validate_body_joint_map(...)`](#apidccmayavalidate_body_joint_map) -> `maya_tools.Rigging.joint_placer.validate_body_joint_map` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:489](C:/depot/tools/maya_tools/Rigging/joint_placer.py:489)
- Source: [joint_placer.py:351](C:/depot/tools/maya_tools/Rigging/joint_placer.py:351)

### `api.dcc.maya.create_joint_controls(...)`

- Target: `maya_tools.Rigging.create_rig.create_joint_controls`
- Signature: `create_joint_controls(`
- API names: `create_joint_controls`
- Args:
  - `joint_list`, default `None`
  - `control_shape`, default `'sphere'`
  - `root_parent`, default `None`
  - `sub_ctrls`, default `False`
  - `keep_constraint`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.bake_joint_orient_to_rotate(...)`](#apidccmayabake_joint_orient_to_rotate) -> `maya_tools.Rigging.create_rig.bake_joint_orient_to_rotate` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1935](C:/depot/tools/maya_tools/Rigging/create_rig.py:1935)
  - same_module: [`api.dcc.maya.constrain_controls_to_two_parents(...)`](#apidccmayaconstrain_controls_to_two_parents) -> `maya_tools.Rigging.create_rig.constrain_controls_to_two_parents` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1868](C:/depot/tools/maya_tools/Rigging/create_rig.py:1868)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
- Description: Creates a control hierarchy for the joints :param joint_list: list of joints to create , accepts hierarchy or single item list :param control_shape: shape type, can be circle, diamond, prism, arrow, cube or sphere :param root_parent: what to parent hierarchy to :param sub_ctrls: do you want local sub controls :param keep_constraint: do you want to keep connected to the joint or just snapped to :return: each ctrl gets added to a list of results, which then has a dict for each joint in the list re
- Source: [create_rig.py:975](C:/depot/tools/maya_tools/Rigging/create_rig.py:975)

### `api.dcc.maya.create_leg_space_switches(...)`

- Target: `maya_tools.Rigging.create_rig.create_leg_space_switches`
- Signature: `create_leg_space_switches(side, body_joint_map=None)`
- API names: `create_leg_space_switches`
- Args:
  - `side`, required
  - `body_joint_map`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.create_composite_space(...)`](#apidccmayacreate_composite_space) -> `maya_tools.Rigging.create_rig.create_composite_space` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)
  - same_module: [`api.dcc.maya.create_space_switch(...)`](#apidccmayacreate_space_switch) -> `maya_tools.Rigging.create_rig.create_space_switch` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2269](C:/depot/tools/maya_tools/Rigging/create_rig.py:2269)
  - same_module: [`api.dcc.maya.query_space_switches(...)`](#apidccmayaquery_space_switches) -> `maya_tools.Rigging.create_rig.query_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4197](C:/depot/tools/maya_tools/Rigging/create_rig.py:4197)
- Description: Builds space switches (including composite spaces) for the Leg module. :param side: left or right side (l/r) :param body_joint_map: optional body joint mapping dictionary :return: None
- Source: [create_rig.py:2711](C:/depot/tools/maya_tools/Rigging/create_rig.py:2711)

### `api.dcc.maya.create_loft_surface_with_follicle_joints(...)`

- Target: `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints`
- Signature: `create_loft_surface_with_follicle_joints(joint_chain, name="surface", offset=0.5)`
- API names: `create_loft_surface_with_follicle_joints`
- Args:
  - `joint_chain`, required
  - `name`, default `'surface'`
  - `offset`, default `0.5`
- Related functions:
  - same_module: [`api.dcc.maya.create_surface_from_joints_original(...)`](#apidccmayacreate_surface_from_joints_original) -> `maya_tools.Rigging.create_rig.create_surface_from_joints_original` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1217](C:/depot/tools/maya_tools/Rigging/create_rig.py:1217)
  - same_module: [`api.dcc.maya.create_rfl_joints_template(...)`](#apidccmayacreate_rfl_joints_template) -> `maya_tools.Rigging.create_rig.create_rfl_joints_template` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)
  - same_module: [`api.dcc.maya.setup_surface_rig_with_drivers(...)`](#apidccmayasetup_surface_rig_with_drivers) -> `maya_tools.Rigging.create_rig.setup_surface_rig_with_drivers` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1506](C:/depot/tools/maya_tools/Rigging/create_rig.py:1506)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
- Description: Create a lofted surface along a joint chain. Creates: - Lofted NURBS surface - Follicles attached to the surface - Follicle joints parented to the follicles (to drive controls) :param joint_chain: list of joints :param name: surface name :param offset: offset of curves :return: loft_surf: name of the lofted NURBS surface follicle_joints: list of joints aligned to the follicles
- Source: [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)

### `api.dcc.maya.create_maya_menu(...)`

- Target: `maya_tools.maya_menu.create_maya_menu`
- Signature: `create_maya_menu()`
- API names: `create_maya_menu`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.create_menu_once(...)`](#apidccmayacreate_menu_once) -> `maya_tools.maya_menu.create_menu_once` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:460](C:/depot/tools/maya_tools/maya_menu.py:460)
  - same_module: [`api.dcc.maya.create_command_port(...)`](#apidccmayacreate_command_port) -> `maya_tools.maya_menu.create_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:287](C:/depot/tools/maya_tools/maya_menu.py:287)
  - same_module: [`api.dcc.maya.maya_execute_and_capture(...)`](#apidccmayamaya_execute_and_capture) -> `maya_tools.maya_menu.maya_execute_and_capture` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:39](C:/depot/tools/maya_tools/maya_menu.py:39)
- Source: [maya_menu.py:422](C:/depot/tools/maya_tools/maya_menu.py:422)

### `api.dcc.maya.create_menu_once(...)`

- Target: `maya_tools.maya_menu.create_menu_once`
- Signature: `create_menu_once()`
- API names: `create_menu_once`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.create_maya_menu(...)`](#apidccmayacreate_maya_menu) -> `maya_tools.maya_menu.create_maya_menu` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:422](C:/depot/tools/maya_tools/maya_menu.py:422)
  - same_module: [`api.dcc.maya.create_command_port(...)`](#apidccmayacreate_command_port) -> `maya_tools.maya_menu.create_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:287](C:/depot/tools/maya_tools/maya_menu.py:287)
- Source: [maya_menu.py:460](C:/depot/tools/maya_tools/maya_menu.py:460)

### `api.dcc.maya.create_prism_ctrl(...)`

- Target: `maya_tools.Rigging.create_rig.create_prism_ctrl`
- Signature: `create_prism_ctrl(name, size=1.0, depth=0.5, normal=(0, 1, 0))`
- API names: `create_prism_ctrl`
- Args:
  - `name`, required
  - `size`, default `1.0`
  - `depth`, default `0.5`
  - `normal`, default `(0, 1, 0)`
- Related functions:
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
  - same_module: [`api.dcc.maya.create_diamond_ctrl(...)`](#apidccmayacreate_diamond_ctrl) -> `maya_tools.Rigging.create_rig.create_diamond_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:35](C:/depot/tools/maya_tools/Rigging/create_rig.py:35)
  - same_module: [`api.dcc.maya.create_sphere_ctrl(...)`](#apidccmayacreate_sphere_ctrl) -> `maya_tools.Rigging.create_rig.create_sphere_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:189](C:/depot/tools/maya_tools/Rigging/create_rig.py:189)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
- Description: Creates a prism-shaped nurbsCurve control. :param name: control name :param size: horizontal/vertical scale of diamond :param depth: prism depth along Y-axis :param normal: vector to orient the prism along (default Y-up) :return:
- Source: [create_rig.py:66](C:/depot/tools/maya_tools/Rigging/create_rig.py:66)

### `api.dcc.maya.create_rfl_joints_template(...)`

- Target: `maya_tools.Rigging.create_rig.create_rfl_joints_template`
- Signature: `create_rfl_joints_template(side, ankle_jnt, toe_jnt, toe_tip_jnt)`
- API names: `create_rfl_joints_template`
- Args:
  - `side`, required
  - `ankle_jnt`, required
  - `toe_jnt`, required
  - `toe_tip_jnt`, required
- Related functions:
  - same_module: [`api.dcc.maya.create_loft_surface_with_follicle_joints(...)`](#apidccmayacreate_loft_surface_with_follicle_joints) -> `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)
  - same_module: [`api.dcc.maya.create_surface_from_joints_original(...)`](#apidccmayacreate_surface_from_joints_original) -> `maya_tools.Rigging.create_rig.create_surface_from_joints_original` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1217](C:/depot/tools/maya_tools/Rigging/create_rig.py:1217)
  - same_module: [`api.dcc.maya.preserve_rfl_pivot_joints(...)`](#apidccmayapreserve_rfl_pivot_joints) -> `maya_tools.Rigging.create_rig.preserve_rfl_pivot_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5511](C:/depot/tools/maya_tools/Rigging/create_rig.py:5511)
  - same_module: [`api.dcc.maya.resolve_rfl_joints(...)`](#apidccmayaresolve_rfl_joints) -> `maya_tools.Rigging.create_rig.resolve_rfl_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5891](C:/depot/tools/maya_tools/Rigging/create_rig.py:5891)
  - same_module: [`api.dcc.maya.build_rfl_ik_and_constraints(...)`](#apidccmayabuild_rfl_ik_and_constraints) -> `maya_tools.Rigging.create_rig.build_rfl_ik_and_constraints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:779](C:/depot/tools/maya_tools/Rigging/create_rig.py:779)
- Description: Creates RFL template joints heel > outerBank > innerBank > toeTip > toe > ankle. :param side: side :param ankle_jnt: ankle jnt :param toe_jnt: toe jnt :param toe_tip_jnt: toe tip jnt :return: result
- Source: [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)

### `api.dcc.maya.create_rig(...)`

- Target: `maya_tools.Rigging.create_rig.create_rig_from_mapping`
- Signature: `create_rig_from_mapping(body_joint_map, face_joint_map)`
- API names: `create_rig`, `create_rig_from_mapping`
- Args:
  - `body_joint_map`, required
  - `face_joint_map`, required
- Related functions:
  - prerequisite: [`api.dcc.maya.create_rig_mapping(...)`](#apidccmayacreate_rig_mapping) -> `maya_tools.Rigging.mocap.setup_hik.create_rig_mapping` - Produces body_joint_map and face_joint_map for create_rig_from_mapping.; source [setup_hik.py:766](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:766)
  - same_module: [`api.dcc.maya.create_full_rig(...)`](#apidccmayacreate_full_rig) -> `maya_tools.Rigging.create_rig.create_full_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3870](C:/depot/tools/maya_tools/Rigging/create_rig.py:3870)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.create_surface_from_joints_original(...)`](#apidccmayacreate_surface_from_joints_original) -> `maya_tools.Rigging.create_rig.create_surface_from_joints_original` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1217](C:/depot/tools/maya_tools/Rigging/create_rig.py:1217)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
- Description: Runs create_full_rig using the mapped joints from HIK/Face mappings. :param body_joint_map: body joint mapping dictionary :param face_joint_map: face joint mapping dictionary :return: None
- Source: [create_rig.py:4127](C:/depot/tools/maya_tools/Rigging/create_rig.py:4127)

### `api.dcc.maya.create_rig_mapping(...)`

- Target: `maya_tools.Rigging.mocap.setup_hik.create_rig_mapping`
- Signature: `create_rig_mapping(root_joint=None)`
- API names: `create_rig_mapping`
- Args:
  - `root_joint`, default `None`
- Related functions:
  - consumer: [`api.dcc.maya.create_rig(...)`](#apidccmayacreate_rig) -> `maya_tools.Rigging.create_rig.create_rig_from_mapping` - Consumes this function's output in a known workflow.; source [create_rig.py:4127](C:/depot/tools/maya_tools/Rigging/create_rig.py:4127)
- Description: Standalone HIK mapping function. Auto-detects the skeleton root if none is provided, then runs guess_joint_map_from_root and populate_default_face_map_from_scene. Returns a tuple of (body_joint_map, face_joint_map) suitable for passing to create_rig.hik_map_to_rig_args. :param root_joint: Optional root joint name. If None, auto-detected from scene. :return: (body_joint_map dict, face_joint_map dict)
- Source: [setup_hik.py:766](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:766)

### `api.dcc.maya.create_rig_space_switches(...)`

- Target: `maya_tools.Rigging.create_rig.create_rig_space_switches`
- Signature: `create_rig_space_switches(side)`
- API names: `create_rig_space_switches`
- Args:
  - `side`, required
- Related functions:
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_leg_space_switches(...)`](#apidccmayacreate_leg_space_switches) -> `maya_tools.Rigging.create_rig.create_leg_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2711](C:/depot/tools/maya_tools/Rigging/create_rig.py:2711)
  - same_module: [`api.dcc.maya.create_composite_space(...)`](#apidccmayacreate_composite_space) -> `maya_tools.Rigging.create_rig.create_composite_space` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)
  - same_module: [`api.dcc.maya.create_full_rig(...)`](#apidccmayacreate_full_rig) -> `maya_tools.Rigging.create_rig.create_full_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3870](C:/depot/tools/maya_tools/Rigging/create_rig.py:3870)
  - same_module: [`api.dcc.maya.create_rig(...)`](#apidccmayacreate_rig) -> `maya_tools.Rigging.create_rig.create_rig_from_mapping` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4127](C:/depot/tools/maya_tools/Rigging/create_rig.py:4127)
- Description: Builds the base space switches for both Leg and Arm modules on this side. :param side: left or right side (l/r) :return: None
- Source: [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)

### `api.dcc.maya.create_space_switch(...)`

- Target: `maya_tools.Rigging.create_rig.create_space_switch`
- Signature: `create_space_switch(`
- API names: `create_space_switch`
- Args:
  - `driven`, required
  - `targets`, required
  - `attr_name`, default `'space'`
  - `dup_suffix`, default `'_spaceTarget'`
  - `constraint_type`, default `'parent'`
  - `enum_names`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_composite_space(...)`](#apidccmayacreate_composite_space) -> `maya_tools.Rigging.create_rig.create_composite_space` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)
  - same_module: [`api.dcc.maya.create_leg_space_switches(...)`](#apidccmayacreate_leg_space_switches) -> `maya_tools.Rigging.create_rig.create_leg_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2711](C:/depot/tools/maya_tools/Rigging/create_rig.py:2711)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.build_enum_names_for_space_targets(...)`](#apidccmayabuild_enum_names_for_space_targets) -> `maya_tools.Rigging.create_rig.build_enum_names_for_space_targets` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2403](C:/depot/tools/maya_tools/Rigging/create_rig.py:2403)
- Description: Builds a space switch where each target gets a matched child transform, and those children are the actual constraint drivers. Constraint is applied to the driven control's parent group. :param driven: control name that drives space switching (e.g. "r_lowerarm_low_pv_ctrl") :param targets: list of target control names (e.g. ["r_clavicle1_ctrl", "pelvis_ctrl", "origin_ctrl"]) :param attr_name: name of the enum attribute created on the driven control :param dup_suffix: suffix appended to duplicated
- Source: [create_rig.py:2269](C:/depot/tools/maya_tools/Rigging/create_rig.py:2269)

### `api.dcc.maya.create_sphere_ctrl(...)`

- Target: `maya_tools.Rigging.create_rig.create_sphere_ctrl`
- Signature: `create_sphere_ctrl(name, radius=1.5)`
- API names: `create_sphere_ctrl`
- Args:
  - `name`, required
  - `radius`, default `1.5`
- Related functions:
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
  - same_module: [`api.dcc.maya.create_diamond_ctrl(...)`](#apidccmayacreate_diamond_ctrl) -> `maya_tools.Rigging.create_rig.create_diamond_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:35](C:/depot/tools/maya_tools/Rigging/create_rig.py:35)
  - same_module: [`api.dcc.maya.create_prism_ctrl(...)`](#apidccmayacreate_prism_ctrl) -> `maya_tools.Rigging.create_rig.create_prism_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:66](C:/depot/tools/maya_tools/Rigging/create_rig.py:66)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
- Description: Creates a sphere-like control made of 3 rotated circles with proper shape parenting :param name: ctrl name :param radius: relative radius of sphere :return:
- Source: [create_rig.py:189](C:/depot/tools/maya_tools/Rigging/create_rig.py:189)

### `api.dcc.maya.create_surface_from_joints_original(...)`

- Target: `maya_tools.Rigging.create_rig.create_surface_from_joints_original`
- Signature: `create_surface_from_joints_original(`
- API names: `create_surface_from_joints_original`
- Args:
  - `joint_chain`, required
  - `name`, default `'surface'`
- Related functions:
  - same_module: [`api.dcc.maya.create_loft_surface_with_follicle_joints(...)`](#apidccmayacreate_loft_surface_with_follicle_joints) -> `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)
  - same_module: [`api.dcc.maya.create_rfl_joints_template(...)`](#apidccmayacreate_rfl_joints_template) -> `maya_tools.Rigging.create_rig.create_rfl_joints_template` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)
  - same_module: [`api.dcc.maya.create_rig(...)`](#apidccmayacreate_rig) -> `maya_tools.Rigging.create_rig.create_rig_from_mapping` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4127](C:/depot/tools/maya_tools/Rigging/create_rig.py:4127)
  - same_module: [`api.dcc.maya.get_region_size_from_joints(...)`](#apidccmayaget_region_size_from_joints) -> `maya_tools.Rigging.create_rig.get_region_size_from_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1119](C:/depot/tools/maya_tools/Rigging/create_rig.py:1119)
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
- Description: Stable surface builder using nurbsPlane + CV positioning. - Offsets using joint local Z axis - Supports closed loops - Creates follicles + follicle joints :param joint_chain: list of joints :param name: surface name :return: surface, follicle_joints
- Source: [create_rig.py:1217](C:/depot/tools/maya_tools/Rigging/create_rig.py:1217)

### `api.dcc.maya.create_twist_driver(...)`

- Target: `maya_tools.Rigging.create_rig.create_twist_driver`
- Signature: `create_twist_driver(driver_bone="l_thigh_driver",`
- API names: `create_twist_driver`
- Args:
  - `driver_bone`, default `'l_thigh_driver'`
  - `child_bone`, default `'l_knee_driver'`
  - `parent`, default `'hipswing_ctrl'`
  - `surface`, default `'l_thigh_surface'`
- Related functions:
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.create_composite_space(...)`](#apidccmayacreate_composite_space) -> `maya_tools.Rigging.create_rig.create_composite_space` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2227](C:/depot/tools/maya_tools/Rigging/create_rig.py:2227)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
- Description: Creates a twist driver setup for a limb segment. Args: driver_bone (str): Name of the driver bone. child_bone (str): Name of the child bone. parent (str): Parent control or group name. surface (str): Name of the lofted surface. Returns: str: Name of the created twist driver joint. :param driver_bone: driver bone :param child_bone: child bone :param parent: parent :param surface: surface :return: result
- Source: [create_rig.py:3322](C:/depot/tools/maya_tools/Rigging/create_rig.py:3322)

### `api.dcc.maya.cross(...)`

- Target: `maya_tools.Rigging.create_rig.cross`
- Signature: `cross(a, b)`
- API names: `cross`
- Args:
  - `a`, required
  - `b`, required
- Description: Computes the cross product of two 3D vectors. :param a: first 3D vector :param b: second 3D vector :return: list[float]
- Source: [create_rig.py:1203](C:/depot/tools/maya_tools/Rigging/create_rig.py:1203)

### `api.dcc.maya.delete_existing_generated_skeleton(...)`

- Target: `maya_tools.Rigging.joint_placer.delete_existing_generated_skeleton`
- Signature: `delete_existing_generated_skeleton(root_name: str = "origin") -> None`
- API names: `delete_existing_generated_skeleton`
- Args:
  - `root_name` (str), default `'origin'`
- Related functions:
  - same_module: [`api.dcc.maya.build_basic_biped_skeleton(...)`](#apidccmayabuild_basic_biped_skeleton) -> `maya_tools.Rigging.joint_placer.build_basic_biped_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:516](C:/depot/tools/maya_tools/Rigging/joint_placer.py:516)
  - same_module: [`api.dcc.maya.build_skeleton_from_points(...)`](#apidccmayabuild_skeleton_from_points) -> `maya_tools.Rigging.joint_placer.build_skeleton_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:424](C:/depot/tools/maya_tools/Rigging/joint_placer.py:424)
  - same_module: [`api.dcc.maya.orient_skeleton(...)`](#apidccmayaorient_skeleton) -> `maya_tools.Rigging.joint_placer.orient_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:370](C:/depot/tools/maya_tools/Rigging/joint_placer.py:370)
- Source: [joint_placer.py:341](C:/depot/tools/maya_tools/Rigging/joint_placer.py:341)

### `api.dcc.maya.delete_unused_scaffold_nodes(...)`

- Target: `maya_tools.Rigging.create_rig.delete_unused_scaffold_nodes`
- Signature: `delete_unused_scaffold_nodes()`
- API names: `delete_unused_scaffold_nodes`
- Args: none
- Description: Finds and deletes any nodes in the scene whose names end in '_main' or contain '_temp'.
- Source: [create_rig.py:4295](C:/depot/tools/maya_tools/Rigging/create_rig.py:4295)

### `api.dcc.maya.disable_evaluation(...)`

- Target: `maya_tools.Utilities.dag.disable_evaluation`
- Signature: `disable_evaluation()`
- API names: `disable_evaluation`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.enable_evaluation(...)`](#apidccmayaenable_evaluation) -> `maya_tools.Utilities.dag.enable_evaluation` - Shares module and name terms; may be useful in the same workflow.; source [dag.py:11](C:/depot/tools/maya_tools/Utilities/dag.py:11)
- Description: Equivalent to Evaluation > Evaluation Mode > Off
- Source: [dag.py:3](C:/depot/tools/maya_tools/Utilities/dag.py:3)

### `api.dcc.maya.disconnect_attr_connections(...)`

- Target: `maya_tools.Rigging.enum_attrs.disconnect_attr_connections`
- Signature: `disconnect_attr_connections(plug)`
- API names: `disconnect_attr_connections`
- Args:
  - `plug`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_attr_connections(...)`](#apidccmayaget_attr_connections) -> `maya_tools.Rigging.enum_attrs.get_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:176](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:176)
  - same_module: [`api.dcc.maya.reconnect_attr_connections(...)`](#apidccmayareconnect_attr_connections) -> `maya_tools.Rigging.enum_attrs.reconnect_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:198](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:198)
  - same_module: [`api.dcc.maya.rebuild_enum_attr_with_order(...)`](#apidccmayarebuild_enum_attr_with_order) -> `maya_tools.Rigging.enum_attrs.rebuild_enum_attr_with_order` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:212](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:212)
- Source: [enum_attrs.py:185](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:185)

### `api.dcc.maya.display_warning(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.display_warning`
- Signature: `display_warning(warning)`
- API names: `display_warning`
- Args:
  - `warning`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_display_range(...)`](#apidccmayaget_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)
  - same_module: [`api.dcc.maya.set_display_range(...)`](#apidccmayaset_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.set_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:73](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:73)
- Description: :param warning: Warning to display :return:
- Source: [sequence_utils.py:85](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:85)

### `api.dcc.maya.duplicate_static_hierarchy(...)`

- Target: `maya_tools.Rigging.create_rig.duplicate_static_hierarchy`
- Signature: `duplicate_static_hierarchy(root, suffix="static")`
- API names: `duplicate_static_hierarchy`
- Args:
  - `root`, required
  - `suffix`, default `'static'`
- Related functions:
  - same_module: [`api.dcc.maya.get_ordered_hierarchy(...)`](#apidccmayaget_ordered_hierarchy) -> `maya_tools.Rigging.create_rig.get_ordered_hierarchy` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4466](C:/depot/tools/maya_tools/Rigging/create_rig.py:4466)
- Description: Duplicate static hierarchy. :param root: root :param suffix: suffix :return: result
- Source: [create_rig.py:4489](C:/depot/tools/maya_tools/Rigging/create_rig.py:4489)

### `api.dcc.maya.enable_evaluation(...)`

- Target: `maya_tools.Utilities.dag.enable_evaluation`
- Signature: `enable_evaluation()`
- API names: `enable_evaluation`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.disable_evaluation(...)`](#apidccmayadisable_evaluation) -> `maya_tools.Utilities.dag.disable_evaluation` - Shares module and name terms; may be useful in the same workflow.; source [dag.py:3](C:/depot/tools/maya_tools/Utilities/dag.py:3)
- Description: Restore normal evaluation (Parallel).
- Source: [dag.py:11](C:/depot/tools/maya_tools/Utilities/dag.py:11)

### `api.dcc.maya.enforce_limb_planarity(...)`

- Target: `maya_tools.Rigging.joint_placer.enforce_limb_planarity`
- Signature: `enforce_limb_planarity(points: Dict[str, Vector3]) -> Dict[str, Vector3]`
- API names: `enforce_limb_planarity`
- Args:
  - `points` (Dict[str, Vector3]), required
- Description: Keep generated arms and legs mostly planar per side. Arms are flattened from upperarm/shoulder through hand tip. Clavicles keep their own raised placement because the T-pose setup can intentionally adjust them. Legs are flattened from thigh through toe tip. This avoids accidental out-of-plane joint chains while still allowing left/right X and height differences.
- Source: [joint_placer.py:184](C:/depot/tools/maya_tools/Rigging/joint_placer.py:184)

### `api.dcc.maya.ensure_rfl_attrs(...)`

- Target: `maya_tools.Rigging.create_rig.ensure_rfl_attrs`
- Signature: `ensure_rfl_attrs(ik_leg_ctrl)`
- API names: `ensure_rfl_attrs`
- Args:
  - `ik_leg_ctrl`, required
- Related functions:
  - same_module: [`api.dcc.maya.build_rfl_ik_and_constraints(...)`](#apidccmayabuild_rfl_ik_and_constraints) -> `maya_tools.Rigging.create_rig.build_rfl_ik_and_constraints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:779](C:/depot/tools/maya_tools/Rigging/create_rig.py:779)
  - same_module: [`api.dcc.maya.create_rfl_joints_template(...)`](#apidccmayacreate_rfl_joints_template) -> `maya_tools.Rigging.create_rig.create_rfl_joints_template` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)
  - same_module: [`api.dcc.maya.preserve_rfl_pivot_joints(...)`](#apidccmayapreserve_rfl_pivot_joints) -> `maya_tools.Rigging.create_rig.preserve_rfl_pivot_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5511](C:/depot/tools/maya_tools/Rigging/create_rig.py:5511)
  - same_module: [`api.dcc.maya.resolve_rfl_joints(...)`](#apidccmayaresolve_rfl_joints) -> `maya_tools.Rigging.create_rig.resolve_rfl_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5891](C:/depot/tools/maya_tools/Rigging/create_rig.py:5891)
  - same_module: [`api.dcc.maya.setup_rfl_sdks(...)`](#apidccmayasetup_rfl_sdks) -> `maya_tools.Rigging.create_rig.setup_rfl_sdks` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:708](C:/depot/tools/maya_tools/Rigging/create_rig.py:708)
- Description: Ensures the reverse foot setup attributes exist on the IK leg control. :param ik_leg_ctrl: name of the IK leg control node :return: None
- Source: [create_rig.py:672](C:/depot/tools/maya_tools/Rigging/create_rig.py:672)

### `api.dcc.maya.export_animation(...)`

- Target: `maya_tools.Animation.anim_export.anim_export.export_animation`
- Signature: `export_animation(maya_file, export_path, namespace, start_frame, end_frame, nodes=None, reference_paths=None)`
- API names: `export_animation`
- Args:
  - `maya_file`, required
  - `export_path`, required
  - `namespace`, required
  - `start_frame`, required
  - `end_frame`, required
  - `nodes`, default `None`
  - `reference_paths`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.export_metahuman_sliders_as_fbx(...)`](#apidccmayaexport_metahuman_sliders_as_fbx) -> `maya_tools.Animation.anim_export.anim_export.export_metahuman_sliders_as_fbx` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:162](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:162)
- Description: Opens Maya file and exports animation to FBX using `mayapy`. :param maya_file: (str): Path to the Maya scene file. :param export_path: (str): Path where the FBX should be saved. :param namespace: (str): Namespace of the skeleton. :param start_frame: (int): Start frame of the animation. :param end_frame: (int): End frame of the animation. :param nodes: (list, optional): Specific nodes to export instead. :param reference_paths: (str, optional): Specific reference path to load :return:
- Source: [anim_export.py:13](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:13)

### `api.dcc.maya.export_animation_async(...)`

- Target: `maya_tools.Animation.anim_export.anim_export_command.export_animation_async`
- Signature: `export_animation_async(cmd, maya_env, export_path)`
- API names: `export_animation_async`
- Args:
  - `cmd`, required
  - `maya_env`, required
  - `export_path`, required
- Related functions:
  - same_module: [`api.dcc.maya.export_animation_to_fbx(...)`](#apidccmayaexport_animation_to_fbx) -> `maya_tools.Animation.anim_export.anim_export_command.export_animation_to_fbx` - Shares module and name terms; may be useful in the same workflow.; source [anim_export_command.py:8](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_command.py:8)
  - same_module: [`api.dcc.maya.run_export(...)`](#apidccmayarun_export) -> `maya_tools.Animation.anim_export.anim_export_command.run_export` - Shares module and name terms; may be useful in the same workflow.; source [anim_export_command.py:62](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_command.py:62)
- Description: exports on separate thread so maya session isn't locked up during export :param cmd: subprocess command string for export :param maya_env: maya env settings from os.environ.copy() :param export_path: actual fbx export location :return:
- Source: [anim_export_command.py:88](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_command.py:88)

### `api.dcc.maya.export_animation_to_fbx(...)`

- Target: `maya_tools.Animation.anim_export.anim_export_command.export_animation_to_fbx`
- Signature: `export_animation_to_fbx(export_path, namespace, start_frame, end_frame, nodes=None, reference_paths=None)`
- API names: `export_animation_to_fbx`
- Args:
  - `export_path`, required
  - `namespace`, required
  - `start_frame`, required
  - `end_frame`, required
  - `nodes`, default `None`
  - `reference_paths`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.export_animation_async(...)`](#apidccmayaexport_animation_async) -> `maya_tools.Animation.anim_export.anim_export_command.export_animation_async` - Shares module and name terms; may be useful in the same workflow.; source [anim_export_command.py:88](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_command.py:88)
  - same_module: [`api.dcc.maya.run_export(...)`](#apidccmayarun_export) -> `maya_tools.Animation.anim_export.anim_export_command.run_export` - Shares module and name terms; may be useful in the same workflow.; source [anim_export_command.py:62](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_command.py:62)
- Description: Subprocess command function which calls the actual export function, to make scene state unchanged :param export_path: full path for fbx animation to be exported :param namespace: namespace to be exported in the data :param start_frame: start frame of exported data :param end_frame: end frame of exported data :param nodes: Joints or nodes to be exported :param reference_paths: Paths to import in the maya py instance from reference :return:
- Source: [anim_export_command.py:8](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_command.py:8)

### `api.dcc.maya.export_metahuman_sliders_as_fbx(...)`

- Target: `maya_tools.Animation.anim_export.anim_export.export_metahuman_sliders_as_fbx`
- Signature: `export_metahuman_sliders_as_fbx(slider_set='FacialControls', fbx_path='', start_frame=None, end_frame=None)`
- API names: `export_metahuman_sliders_as_fbx`
- Args:
  - `slider_set`, default `'FacialControls'`
  - `fbx_path`, default `''`
  - `start_frame`, default `None`
  - `end_frame`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.export_animation(...)`](#apidccmayaexport_animation) -> `maya_tools.Animation.anim_export.anim_export.export_animation` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:13](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:13)
- Description: Bakes facial slider animation and exports it as an FBX. :param slider_set: Name of the set containing facial sliders. :param fbx_path: Full file path for the FBX export. :param start_frame: Start frame of baking range. Defaults to timeline start. :param end_frame: End frame of baking range. Defaults to timeline end.
- Source: [anim_export.py:162](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:162)

### `api.dcc.maya.export_node_exists(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.export_node_exists`
- Signature: `export_node_exists()`
- API names: `export_node_exists`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.create_and_populate_export_node(...)`](#apidccmayacreate_and_populate_export_node) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.create_and_populate_export_node` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:241](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:241)
  - same_module: [`api.dcc.maya.get_export_node_data(...)`](#apidccmayaget_export_node_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:271](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:271)
- Source: [sequence_utils.py:59](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:59)

### `api.dcc.maya.export_selected_enum_orders(...)`

- Target: `maya_tools.Rigging.enum_attrs.export_selected_enum_orders`
- Signature: `export_selected_enum_orders(filepath, attr_filter=None)`
- API names: `export_selected_enum_orders`
- Args:
  - `filepath`, required
  - `attr_filter`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.import_enum_orders(...)`](#apidccmayaimport_enum_orders) -> `maya_tools.Rigging.enum_attrs.import_enum_orders` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:439](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:439)
  - same_module: [`api.dcc.maya.apply_enum_data(...)`](#apidccmayaapply_enum_data) -> `maya_tools.Rigging.enum_attrs.apply_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:348](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:348)
  - same_module: [`api.dcc.maya.collect_enum_data(...)`](#apidccmayacollect_enum_data) -> `maya_tools.Rigging.enum_attrs.collect_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:86](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:86)
  - same_module: [`api.dcc.maya.get_enum_attrs(...)`](#apidccmayaget_enum_attrs) -> `maya_tools.Rigging.enum_attrs.get_enum_attrs` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:73](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:73)
  - same_module: [`api.dcc.maya.get_enum_labels(...)`](#apidccmayaget_enum_labels) -> `maya_tools.Rigging.enum_attrs.get_enum_labels` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:66](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:66)
- Description: Export enum label orders from selected nodes to JSON.
- Source: [enum_attrs.py:427](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:427)

### `api.dcc.maya.export_skin_weights(...)`

- Target: `maya_tools.Rigging.skinning_utils.export_skin_weights`
- Signature: `export_skin_weights(meshes, export_dir="C:/temp/weights")`
- API names: `export_skin_weights`
- Args:
  - `meshes`, required
  - `export_dir`, default `'C:/temp/weights'`
- Related functions:
  - same_module: [`api.dcc.maya.import_skin_weights(...)`](#apidccmayaimport_skin_weights) -> `maya_tools.Rigging.skinning_utils.import_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:229](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:229)
  - same_module: [`api.dcc.maya.transfer_skin_weights(...)`](#apidccmayatransfer_skin_weights) -> `maya_tools.Rigging.skinning_utils.transfer_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:24](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:24)
  - same_module: [`api.dcc.maya.transfer_skin_weights_from_selection(...)`](#apidccmayatransfer_skin_weights_from_selection) -> `maya_tools.Rigging.skinning_utils.transfer_skin_weights_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:8](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:8)
- Description: Exports skin weights for a list of meshes to XML using deformerWeights. Saves influence order in individual JSON sidecar files. :param meshes: list of mesh names to export :param export_dir: target directory to save all files
- Source: [skinning_utils.py:173](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:173)

### `api.dcc.maya.find_face_joints(...)`

- Target: `maya_tools.Rigging.mocap.setup_hik.find_face_joints`
- Signature: `find_face_joints(pattern, face_joints)`
- API names: `find_face_joints`
- Args:
  - `pattern`, required
  - `face_joints`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_descendant_joints(...)`](#apidccmayaget_descendant_joints) -> `maya_tools.Rigging.mocap.setup_hik.get_descendant_joints` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:194](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:194)
  - same_module: [`api.dcc.maya.populate_default_face_map_from_scene(...)`](#apidccmayapopulate_default_face_map_from_scene) -> `maya_tools.Rigging.mocap.setup_hik.populate_default_face_map_from_scene` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:466](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:466)
- Description: Return joints in the scene matching the pattern that are descendants of the face root. :param pattern: pattern :param face_joints: list of face joints :return: result
- Source: [setup_hik.py:205](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:205)

### `api.dcc.maya.find_ik_handle_constrained_by_ctrl(...)`

- Target: `maya_tools.Rigging.create_rig.find_ik_handle_constrained_by_ctrl`
- Signature: `find_ik_handle_constrained_by_ctrl(ctrl)`
- API names: `find_ik_handle_constrained_by_ctrl`
- Args:
  - `ctrl`, required
- Related functions:
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
  - same_module: [`api.dcc.maya.create_diamond_ctrl(...)`](#apidccmayacreate_diamond_ctrl) -> `maya_tools.Rigging.create_rig.create_diamond_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:35](C:/depot/tools/maya_tools/Rigging/create_rig.py:35)
  - same_module: [`api.dcc.maya.create_prism_ctrl(...)`](#apidccmayacreate_prism_ctrl) -> `maya_tools.Rigging.create_rig.create_prism_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:66](C:/depot/tools/maya_tools/Rigging/create_rig.py:66)
  - same_module: [`api.dcc.maya.create_sphere_ctrl(...)`](#apidccmayacreate_sphere_ctrl) -> `maya_tools.Rigging.create_rig.create_sphere_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:189](C:/depot/tools/maya_tools/Rigging/create_rig.py:189)
- Description: Finds the IK handle currently constrained by the given control. :param ctrl: actual ik ctrl :return: Returns the ikHandle or None.
- Source: [create_rig.py:857](C:/depot/tools/maya_tools/Rigging/create_rig.py:857)

### `api.dcc.maya.find_or_create_user_setup(...)`

- Target: `maya_tools.maya_setup.find_or_create_user_setup`
- Signature: `find_or_create_user_setup()`
- API names: `find_or_create_user_setup`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.add_tools_to_user_setup(...)`](#apidccmayaadd_tools_to_user_setup) -> `maya_tools.maya_setup.add_tools_to_user_setup` - Shares module and name terms; may be useful in the same workflow.; source [maya_setup.py:62](C:/depot/tools/maya_tools/maya_setup.py:62)
- Description: Finds an existing userSetup.py or creates one without overwriting any existing ones. Returns the full path to userSetup.py.
- Source: [maya_setup.py:35](C:/depot/tools/maya_tools/maya_setup.py:35)

### `api.dcc.maya.find_references_from_namespace(...)`

- Target: `maya_tools.Animation.anim_export.anim_export_utils.find_references_from_namespace`
- Signature: `find_references_from_namespace(namespace)`
- API names: `find_references_from_namespace`
- Args:
  - `namespace`, required
- Related functions:
  - same_module: [`api.dcc.maya.open_scene_with_specific_references(...)`](#apidccmayaopen_scene_with_specific_references) -> `maya_tools.Animation.anim_export.anim_export_utils.open_scene_with_specific_references` - Shares module and name terms; may be useful in the same workflow.; source [anim_export_utils.py:55](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_utils.py:55)
- Description: Find all reference nodes (including sub-references and constraint dependencies) associated with a given namespace. :param namespace: The namespace you want to check, e.g., 'Test:sub_rig'. :return: List of [ref_path, ref_node] pairs.
- Source: [anim_export_utils.py:81](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_utils.py:81)

### `api.dcc.maya.find_skin_cluster(...)`

- Target: `maya_tools.Rigging.auto_skinner.find_skin_cluster`
- Signature: `find_skin_cluster(mesh: str) -> Optional[str]`
- API names: `find_skin_cluster`
- Args:
  - `mesh` (str), required
- Related functions:
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.auto_skin_mesh(...)`](#apidccmayaauto_skin_mesh) -> `maya_tools.Rigging.auto_skinner.auto_skin_mesh` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:588](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:588)
  - same_module: [`api.dcc.maya.auto_skin_selected(...)`](#apidccmayaauto_skin_selected) -> `maya_tools.Rigging.auto_skinner.auto_skin_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:622](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:622)
  - same_module: [`api.dcc.maya.get_skin_joints(...)`](#apidccmayaget_skin_joints) -> `maya_tools.Rigging.auto_skinner.get_skin_joints` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:93](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:93)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_skin(...)`](#apidccmayalearn_shoulder_profile_from_skin) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:228](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:228)
- Source: [auto_skinner.py:62](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:62)

### `api.dcc.maya.find_skinned_or_top_joints(...)`

- Target: `maya_tools.Utilities.joints.find_skinned_or_top_joints`
- Signature: `find_skinned_or_top_joints(namespace='')`
- API names: `find_skinned_or_top_joints`
- Args:
  - `namespace`, default `''`
- Description: Finds the topmost joint in the skinned joint hierarchy. If no skinClusters exist, walks up from any joint in the namespace and returns the highest ancestor. :param namespace: Namespace string with colon suffix (e.g., 'MyChar:') :return: Name of the topmost joint (str)
- Source: [joints.py:4](C:/depot/tools/maya_tools/Utilities/joints.py:4)

### `api.dcc.maya.generate_sequence_dict_from_anim_dict(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.generate_sequence_dict_from_anim_dict`
- Signature: `generate_sequence_dict_from_anim_dict(anim_dict)`
- API names: `generate_sequence_dict_from_anim_dict`
- Args:
  - `anim_dict`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_cameras_from_selection(...)`](#apidccmayaget_cameras_from_selection) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:94](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:94)
  - same_module: [`api.dcc.maya.get_shot_name_from_path(...)`](#apidccmayaget_shot_name_from_path) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_shot_name_from_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:143](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:143)
- Description: Generates a new dictionary with shot_number as the key, and a list of animations as the value. Each animation has export path, skeleton, blueprint (default to None), nodes, start frame, and end frame. :param anim_dict: The original animation dictionary, where the key is the export path and the value contains start frame, end frame, namespace, skeleton, color, and nodes. :return: new dictionary with shot_number as keys.
- Source: [sequence_utils.py:165](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:165)

### `api.dcc.maya.get_all_joint_children(...)`

- Target: `maya_tools.Animation.anim_export.anim_export.get_all_joint_children`
- Signature: `get_all_joint_children(root_joint)`
- API names: `get_all_joint_children`
- Args:
  - `root_joint`, required
- Related functions:
  - same_module: [`api.dcc.maya.bake_all_keyable_attributes(...)`](#apidccmayabake_all_keyable_attributes) -> `maya_tools.Animation.anim_export.anim_export.bake_all_keyable_attributes` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:135](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:135)
  - same_module: [`api.dcc.maya.update_joint_setup_for_import(...)`](#apidccmayaupdate_joint_setup_for_import) -> `maya_tools.Animation.anim_export.anim_export.update_joint_setup_for_import` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:206](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:206)
- Description: Returns a list of all child joints (recursively) under the given root joint.
- Source: [anim_export.py:121](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:121)

### `api.dcc.maya.get_all_module_metadata(...)`

- Target: `maya_tools.Rigging.create_rig.get_all_module_metadata`
- Signature: `get_all_module_metadata()`
- API names: `get_all_module_metadata`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.clear_module_metadata(...)`](#apidccmayaclear_module_metadata) -> `maya_tools.Rigging.create_rig.clear_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6613](C:/depot/tools/maya_tools/Rigging/create_rig.py:6613)
  - same_module: [`api.dcc.maya.get_module_controls(...)`](#apidccmayaget_module_controls) -> `maya_tools.Rigging.create_rig.get_module_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5820](C:/depot/tools/maya_tools/Rigging/create_rig.py:5820)
  - same_module: [`api.dcc.maya.load_module_metadata(...)`](#apidccmayaload_module_metadata) -> `maya_tools.Rigging.create_rig.load_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6575](C:/depot/tools/maya_tools/Rigging/create_rig.py:6575)
  - same_module: [`api.dcc.maya.save_module_metadata(...)`](#apidccmayasave_module_metadata) -> `maya_tools.Rigging.create_rig.save_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6549](C:/depot/tools/maya_tools/Rigging/create_rig.py:6549)
  - same_module: [`api.dcc.maya.get_ctrl_shape_cvs(...)`](#apidccmayaget_ctrl_shape_cvs) -> `maya_tools.Rigging.create_rig.get_ctrl_shape_cvs` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2501](C:/depot/tools/maya_tools/Rigging/create_rig.py:2501)
- Description: Return {module_id: data_dict} for every stored module. :return: dict
- Source: [create_rig.py:6594](C:/depot/tools/maya_tools/Rigging/create_rig.py:6594)

### `api.dcc.maya.get_attr_connections(...)`

- Target: `maya_tools.Rigging.enum_attrs.get_attr_connections`
- Signature: `get_attr_connections(plug)`
- API names: `get_attr_connections`
- Args:
  - `plug`, required
- Related functions:
  - same_module: [`api.dcc.maya.disconnect_attr_connections(...)`](#apidccmayadisconnect_attr_connections) -> `maya_tools.Rigging.enum_attrs.disconnect_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:185](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:185)
  - same_module: [`api.dcc.maya.reconnect_attr_connections(...)`](#apidccmayareconnect_attr_connections) -> `maya_tools.Rigging.enum_attrs.reconnect_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:198](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:198)
  - same_module: [`api.dcc.maya.get_enum_attrs(...)`](#apidccmayaget_enum_attrs) -> `maya_tools.Rigging.enum_attrs.get_enum_attrs` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:73](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:73)
  - same_module: [`api.dcc.maya.get_enum_labels(...)`](#apidccmayaget_enum_labels) -> `maya_tools.Rigging.enum_attrs.get_enum_labels` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:66](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:66)
  - same_module: [`api.dcc.maya.get_side_from_node(...)`](#apidccmayaget_side_from_node) -> `maya_tools.Rigging.enum_attrs.get_side_from_node` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:23](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:23)
- Description: Returns incoming and outgoing connections for an attribute plug.
- Source: [enum_attrs.py:176](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:176)

### `api.dcc.maya.get_camera_sequencer_data(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data`
- Signature: `get_camera_sequencer_data()`
- API names: `get_camera_sequencer_data`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.get_export_node_data(...)`](#apidccmayaget_export_node_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:271](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:271)
  - same_module: [`api.dcc.maya.get_cameras_from_selection(...)`](#apidccmayaget_cameras_from_selection) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:94](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:94)
  - same_module: [`api.dcc.maya.get_display_range(...)`](#apidccmayaget_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)
  - same_module: [`api.dcc.maya.call('maya_tools.Cinematics.SequenceUI.sequence_utils.get_main_window_pointer', ...)`](#apidccmayacallmaya_toolscinematicssequenceuisequence_utilsget_main_window_pointer) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_main_window_pointer` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:33](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:33)
  - same_module: [`api.dcc.maya.get_maya_fps(...)`](#apidccmayaget_maya_fps) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_maya_fps` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:202](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:202)
- Description: Retrieves all shots, shot ranges, and corresponding shot cameras from Maya's Camera Sequencer. :return: List of tuples (shot_number, start_frame, end_frame, camera)
- Source: [sequence_utils.py:42](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:42)

### `api.dcc.maya.get_cameras_from_selection(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection`
- Signature: `get_cameras_from_selection()`
- API names: `get_cameras_from_selection`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.get_shot_name_from_path(...)`](#apidccmayaget_shot_name_from_path) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_shot_name_from_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:143](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:143)
  - same_module: [`api.dcc.maya.generate_sequence_dict_from_anim_dict(...)`](#apidccmayagenerate_sequence_dict_from_anim_dict) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.generate_sequence_dict_from_anim_dict` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:165](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:165)
  - same_module: [`api.dcc.maya.get_camera_sequencer_data(...)`](#apidccmayaget_camera_sequencer_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:42](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:42)
  - same_module: [`api.dcc.maya.get_display_range(...)`](#apidccmayaget_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)
  - same_module: [`api.dcc.maya.get_export_node_data(...)`](#apidccmayaget_export_node_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:271](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:271)
- Source: [sequence_utils.py:94](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:94)

### `api.dcc.maya.get_command_port(...)`

- Target: `maya_tools.maya_menu.get_command_port`
- Signature: `get_command_port()`
- API names: `get_command_port`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.apply_command_port_python3_patches(...)`](#apidccmayaapply_command_port_python3_patches) -> `maya_tools.maya_menu.apply_command_port_python3_patches` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:67](C:/depot/tools/maya_tools/maya_menu.py:67)
  - same_module: [`api.dcc.maya.cleanup_command_port_files(...)`](#apidccmayacleanup_command_port_files) -> `maya_tools.maya_menu.cleanup_command_port_files` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:196](C:/depot/tools/maya_tools/maya_menu.py:196)
  - same_module: [`api.dcc.maya.create_command_port(...)`](#apidccmayacreate_command_port) -> `maya_tools.maya_menu.create_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:287](C:/depot/tools/maya_tools/maya_menu.py:287)
  - same_module: [`api.dcc.maya.initialize_command_port(...)`](#apidccmayainitialize_command_port) -> `maya_tools.maya_menu.initialize_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:322](C:/depot/tools/maya_tools/maya_menu.py:322)
  - same_module: [`api.dcc.maya.save_port_to_file(...)`](#apidccmayasave_port_to_file) -> `maya_tools.maya_menu.save_port_to_file` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:216](C:/depot/tools/maya_tools/maya_menu.py:216)
- Source: [maya_menu.py:232](C:/depot/tools/maya_tools/maya_menu.py:232)

### `api.dcc.maya.get_ctrl_shape_cvs(...)`

- Target: `maya_tools.Rigging.create_rig.get_ctrl_shape_cvs`
- Signature: `get_ctrl_shape_cvs(ctrl)`
- API names: `get_ctrl_shape_cvs`
- Args:
  - `ctrl`, required
- Related functions:
  - same_module: [`api.dcc.maya.scale_ctrl_cvs_local(...)`](#apidccmayascale_ctrl_cvs_local) -> `maya_tools.Rigging.create_rig.scale_ctrl_cvs_local` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1091](C:/depot/tools/maya_tools/Rigging/create_rig.py:1091)
  - same_module: [`api.dcc.maya.snap_ctrl_cvs_to_child(...)`](#apidccmayasnap_ctrl_cvs_to_child) -> `maya_tools.Rigging.create_rig.snap_ctrl_cvs_to_child` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:134](C:/depot/tools/maya_tools/Rigging/create_rig.py:134)
  - same_module: [`api.dcc.maya.strip_ctrl_shape_and_rename(...)`](#apidccmayastrip_ctrl_shape_and_rename) -> `maya_tools.Rigging.create_rig.strip_ctrl_shape_and_rename` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3101](C:/depot/tools/maya_tools/Rigging/create_rig.py:3101)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
- Description: Gets ctrl shape cvs. :param ctrl: ctrl :return: result
- Source: [create_rig.py:2501](C:/depot/tools/maya_tools/Rigging/create_rig.py:2501)

### `api.dcc.maya.get_default_export_path(...)`

- Target: `maya_tools.Rigging.mocap.hik_ui.get_default_export_path`
- Signature: `get_default_export_path()`
- API names: `get_default_export_path`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.call('maya_tools.Rigging.mocap.hik_ui.get_main_window_pointer', ...)`](#apidccmayacallmaya_toolsriggingmocaphik_uiget_main_window_pointer) -> `maya_tools.Rigging.mocap.hik_ui.get_main_window_pointer` - Shares module and name terms; may be useful in the same workflow.; source [hik_ui.py:45](C:/depot/tools/maya_tools/Rigging/mocap/hik_ui.py:45)
- Source: [hik_ui.py:34](C:/depot/tools/maya_tools/Rigging/mocap/hik_ui.py:34)

### `api.dcc.maya.get_descendant_joints(...)`

- Target: `maya_tools.Rigging.mocap.setup_hik.get_descendant_joints`
- Signature: `get_descendant_joints(root_joint)`
- API names: `get_descendant_joints`
- Args:
  - `root_joint`, required
- Related functions:
  - same_module: [`api.dcc.maya.find_face_joints(...)`](#apidccmayafind_face_joints) -> `maya_tools.Rigging.mocap.setup_hik.find_face_joints` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:205](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:205)
  - same_module: [`api.dcc.maya.get_world_position(...)`](#apidccmayaget_world_position) -> `maya_tools.Rigging.mocap.setup_hik.get_world_position` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:225](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:225)
- Description: Returns all descendant joints of root_joint (including root). :param root_joint: root joint :return: result
- Source: [setup_hik.py:194](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:194)

### `api.dcc.maya.get_display_range(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range`
- Signature: `get_display_range()`
- API names: `get_display_range`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.set_display_range(...)`](#apidccmayaset_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.set_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:73](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:73)
  - same_module: [`api.dcc.maya.display_warning(...)`](#apidccmayadisplay_warning) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.display_warning` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:85](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:85)
  - same_module: [`api.dcc.maya.get_camera_sequencer_data(...)`](#apidccmayaget_camera_sequencer_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:42](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:42)
  - same_module: [`api.dcc.maya.get_cameras_from_selection(...)`](#apidccmayaget_cameras_from_selection) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:94](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:94)
  - same_module: [`api.dcc.maya.get_export_node_data(...)`](#apidccmayaget_export_node_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:271](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:271)
- Description: :return: start and end frames of the time slider
- Source: [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)

### `api.dcc.maya.get_enum_attrs(...)`

- Target: `maya_tools.Rigging.enum_attrs.get_enum_attrs`
- Signature: `get_enum_attrs(node)`
- API names: `get_enum_attrs`
- Args:
  - `node`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_enum_labels(...)`](#apidccmayaget_enum_labels) -> `maya_tools.Rigging.enum_attrs.get_enum_labels` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:66](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:66)
  - same_module: [`api.dcc.maya.apply_enum_data(...)`](#apidccmayaapply_enum_data) -> `maya_tools.Rigging.enum_attrs.apply_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:348](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:348)
  - same_module: [`api.dcc.maya.collect_enum_data(...)`](#apidccmayacollect_enum_data) -> `maya_tools.Rigging.enum_attrs.collect_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:86](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:86)
  - same_module: [`api.dcc.maya.export_selected_enum_orders(...)`](#apidccmayaexport_selected_enum_orders) -> `maya_tools.Rigging.enum_attrs.export_selected_enum_orders` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:427](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:427)
  - same_module: [`api.dcc.maya.get_attr_connections(...)`](#apidccmayaget_attr_connections) -> `maya_tools.Rigging.enum_attrs.get_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:176](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:176)
- Source: [enum_attrs.py:73](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:73)

### `api.dcc.maya.get_enum_labels(...)`

- Target: `maya_tools.Rigging.enum_attrs.get_enum_labels`
- Signature: `get_enum_labels(node, attr)`
- API names: `get_enum_labels`
- Args:
  - `node`, required
  - `attr`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_enum_attrs(...)`](#apidccmayaget_enum_attrs) -> `maya_tools.Rigging.enum_attrs.get_enum_attrs` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:73](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:73)
  - same_module: [`api.dcc.maya.apply_enum_data(...)`](#apidccmayaapply_enum_data) -> `maya_tools.Rigging.enum_attrs.apply_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:348](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:348)
  - same_module: [`api.dcc.maya.collect_enum_data(...)`](#apidccmayacollect_enum_data) -> `maya_tools.Rigging.enum_attrs.collect_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:86](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:86)
  - same_module: [`api.dcc.maya.export_selected_enum_orders(...)`](#apidccmayaexport_selected_enum_orders) -> `maya_tools.Rigging.enum_attrs.export_selected_enum_orders` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:427](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:427)
  - same_module: [`api.dcc.maya.get_attr_connections(...)`](#apidccmayaget_attr_connections) -> `maya_tools.Rigging.enum_attrs.get_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:176](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:176)
- Source: [enum_attrs.py:66](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:66)

### `api.dcc.maya.get_export_node_data(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data`
- Signature: `get_export_node_data()`
- API names: `get_export_node_data`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.create_and_populate_export_node(...)`](#apidccmayacreate_and_populate_export_node) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.create_and_populate_export_node` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:241](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:241)
  - same_module: [`api.dcc.maya.export_node_exists(...)`](#apidccmayaexport_node_exists) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.export_node_exists` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:59](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:59)
  - same_module: [`api.dcc.maya.get_camera_sequencer_data(...)`](#apidccmayaget_camera_sequencer_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:42](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:42)
  - same_module: [`api.dcc.maya.get_cameras_from_selection(...)`](#apidccmayaget_cameras_from_selection) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:94](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:94)
  - same_module: [`api.dcc.maya.get_display_range(...)`](#apidccmayaget_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)
- Source: [sequence_utils.py:271](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:271)

### `api.dcc.maya.get_facial_joints(...)`

- Target: `maya_tools.Animation.anim_export.anim_export_utils.get_facial_joints`
- Signature: `get_facial_joints(namespace)`
- API names: `get_facial_joints`
- Args:
  - `namespace`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_facial_sliders(...)`](#apidccmayaget_facial_sliders) -> `maya_tools.Animation.anim_export.anim_export_utils.get_facial_sliders` - Shares module and name terms; may be useful in the same workflow.; source [anim_export_utils.py:4](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_utils.py:4)
- Description: Detects joints with 'FACIAL_' in their name within the given namespace (including nested ones). Returns the list of joints and the actual namespace. :param namespace: Base namespace to filter by (e.g., 'MyChar') :return: Tuple (facial_joints, actual_namespace) or (None, None) if not found.
- Source: [anim_export_utils.py:28](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_utils.py:28)

### `api.dcc.maya.get_facial_sliders(...)`

- Target: `maya_tools.Animation.anim_export.anim_export_utils.get_facial_sliders`
- Signature: `get_facial_sliders(namespace=None)`
- API names: `get_facial_sliders`
- Args:
  - `namespace`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.get_facial_joints(...)`](#apidccmayaget_facial_joints) -> `maya_tools.Animation.anim_export.anim_export_utils.get_facial_joints` - Shares module and name terms; may be useful in the same workflow.; source [anim_export_utils.py:28](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_utils.py:28)
- Description: Detects the 'FacialControls' set under any namespace (including nested ones) and returns the slider nodes and the actual namespace they belong to. :param namespace: (optional) A base namespace to filter by. :return: Tuple (slider_nodes, actual_namespace) or None if not found.
- Source: [anim_export_utils.py:4](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_utils.py:4)

### `api.dcc.maya.get_joint_position(...)`

- Target: `maya_tools.Rigging.auto_skinner.get_joint_position`
- Signature: `get_joint_position(joint: str) -> om.MVector`
- API names: `get_joint_position`
- Args:
  - `joint` (str), required
- Related functions:
  - same_module: [`api.dcc.maya.get_mesh_vertices(...)`](#apidccmayaget_mesh_vertices) -> `maya_tools.Rigging.auto_skinner.get_mesh_vertices` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:147](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:147)
  - same_module: [`api.dcc.maya.get_skin_joints(...)`](#apidccmayaget_skin_joints) -> `maya_tools.Rigging.auto_skinner.get_skin_joints` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:93](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:93)
  - same_module: [`api.dcc.maya.solve_vertex_weights_from_position(...)`](#apidccmayasolve_vertex_weights_from_position) -> `maya_tools.Rigging.auto_skinner.solve_vertex_weights_from_position` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:451](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:451)
- Source: [auto_skinner.py:69](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:69)

### `api.dcc.maya.get_maya_fps(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.get_maya_fps`
- Signature: `get_maya_fps()`
- API names: `get_maya_fps`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.get_camera_sequencer_data(...)`](#apidccmayaget_camera_sequencer_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:42](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:42)
  - same_module: [`api.dcc.maya.get_cameras_from_selection(...)`](#apidccmayaget_cameras_from_selection) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:94](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:94)
  - same_module: [`api.dcc.maya.get_display_range(...)`](#apidccmayaget_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)
  - same_module: [`api.dcc.maya.get_export_node_data(...)`](#apidccmayaget_export_node_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:271](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:271)
  - same_module: [`api.dcc.maya.call('maya_tools.Cinematics.SequenceUI.sequence_utils.get_main_window_pointer', ...)`](#apidccmayacallmaya_toolscinematicssequenceuisequence_utilsget_main_window_pointer) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_main_window_pointer` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:33](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:33)
- Source: [sequence_utils.py:202](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:202)

### `api.dcc.maya.get_mesh_bounds(...)`

- Target: `maya_tools.Rigging.joint_placer.get_mesh_bounds`
- Signature: `get_mesh_bounds(mesh: str) -> Dict[str, object]`
- API names: `get_mesh_bounds`
- Args:
  - `mesh` (str), required
- Related functions:
  - same_module: [`api.dcc.maya.create_auto_joints_for_mesh(...)`](#apidccmayacreate_auto_joints_for_mesh) -> `maya_tools.Rigging.joint_placer.create_auto_joints_for_mesh` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:560](C:/depot/tools/maya_tools/Rigging/joint_placer.py:560)
  - same_module: [`api.dcc.maya.create_auto_joints_for_selected_mesh(...)`](#apidccmayacreate_auto_joints_for_selected_mesh) -> `maya_tools.Rigging.joint_placer.create_auto_joints_for_selected_mesh` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:575](C:/depot/tools/maya_tools/Rigging/joint_placer.py:575)
  - same_module: [`api.dcc.maya.point_from_normalized_bounds(...)`](#apidccmayapoint_from_normalized_bounds) -> `maya_tools.Rigging.joint_placer.point_from_normalized_bounds` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:267](C:/depot/tools/maya_tools/Rigging/joint_placer.py:267)
- Source: [joint_placer.py:250](C:/depot/tools/maya_tools/Rigging/joint_placer.py:250)

### `api.dcc.maya.get_mesh_vertices(...)`

- Target: `maya_tools.Rigging.auto_skinner.get_mesh_vertices`
- Signature: `get_mesh_vertices(mesh: str) -> List[str]`
- API names: `get_mesh_vertices`
- Args:
  - `mesh` (str), required
- Related functions:
  - same_module: [`api.dcc.maya.auto_skin_mesh(...)`](#apidccmayaauto_skin_mesh) -> `maya_tools.Rigging.auto_skinner.auto_skin_mesh` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:588](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:588)
  - same_module: [`api.dcc.maya.bind_mesh(...)`](#apidccmayabind_mesh) -> `maya_tools.Rigging.auto_skinner.bind_mesh` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:375](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:375)
  - same_module: [`api.dcc.maya.get_joint_position(...)`](#apidccmayaget_joint_position) -> `maya_tools.Rigging.auto_skinner.get_joint_position` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:69](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:69)
  - same_module: [`api.dcc.maya.get_skin_joints(...)`](#apidccmayaget_skin_joints) -> `maya_tools.Rigging.auto_skinner.get_skin_joints` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:93](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:93)
- Source: [auto_skinner.py:147](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:147)

### `api.dcc.maya.get_module_controls(...)`

- Target: `maya_tools.Rigging.create_rig.get_module_controls`
- Signature: `get_module_controls(module_id, existing_only=True)`
- API names: `get_module_controls`
- Args:
  - `module_id`, required
  - `existing_only`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.get_all_module_metadata(...)`](#apidccmayaget_all_module_metadata) -> `maya_tools.Rigging.create_rig.get_all_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6594](C:/depot/tools/maya_tools/Rigging/create_rig.py:6594)
  - same_module: [`api.dcc.maya.clear_module_metadata(...)`](#apidccmayaclear_module_metadata) -> `maya_tools.Rigging.create_rig.clear_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6613](C:/depot/tools/maya_tools/Rigging/create_rig.py:6613)
  - same_module: [`api.dcc.maya.constrain_controls_to_two_parents(...)`](#apidccmayaconstrain_controls_to_two_parents) -> `maya_tools.Rigging.create_rig.constrain_controls_to_two_parents` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1868](C:/depot/tools/maya_tools/Rigging/create_rig.py:1868)
  - same_module: [`api.dcc.maya.create_joint_controls(...)`](#apidccmayacreate_joint_controls) -> `maya_tools.Rigging.create_rig.create_joint_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:975](C:/depot/tools/maya_tools/Rigging/create_rig.py:975)
  - same_module: [`api.dcc.maya.get_ctrl_shape_cvs(...)`](#apidccmayaget_ctrl_shape_cvs) -> `maya_tools.Rigging.create_rig.get_ctrl_shape_cvs` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2501](C:/depot/tools/maya_tools/Rigging/create_rig.py:2501)
- Description: Return controls recorded/discovered for a stored rig module. :param module_id: unique module identifier :param existing_only: only return controls that exist in the current scene :return: list[str]
- Source: [create_rig.py:5820](C:/depot/tools/maya_tools/Rigging/create_rig.py:5820)

### `api.dcc.maya.get_nose_joints(...)`

- Target: `maya_tools.Rigging.create_rig.get_nose_joints`
- Signature: `get_nose_joints(face_joint_map=None)`
- API names: `get_nose_joints`
- Args:
  - `face_joint_map`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.get_region_size_from_joints(...)`](#apidccmayaget_region_size_from_joints) -> `maya_tools.Rigging.create_rig.get_region_size_from_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1119](C:/depot/tools/maya_tools/Rigging/create_rig.py:1119)
  - same_module: [`api.dcc.maya.create_loft_surface_with_follicle_joints(...)`](#apidccmayacreate_loft_surface_with_follicle_joints) -> `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)
  - same_module: [`api.dcc.maya.create_rfl_joints_template(...)`](#apidccmayacreate_rfl_joints_template) -> `maya_tools.Rigging.create_rig.create_rfl_joints_template` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)
  - same_module: [`api.dcc.maya.create_surface_from_joints_original(...)`](#apidccmayacreate_surface_from_joints_original) -> `maya_tools.Rigging.create_rig.create_surface_from_joints_original` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1217](C:/depot/tools/maya_tools/Rigging/create_rig.py:1217)
  - same_module: [`api.dcc.maya.get_all_module_metadata(...)`](#apidccmayaget_all_module_metadata) -> `maya_tools.Rigging.create_rig.get_all_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6594](C:/depot/tools/maya_tools/Rigging/create_rig.py:6594)
- Description: Gets nose joints. :param face_joint_map: mapping for face joint map :return: result
- Source: [create_rig.py:583](C:/depot/tools/maya_tools/Rigging/create_rig.py:583)

### `api.dcc.maya.get_ordered_hierarchy(...)`

- Target: `maya_tools.Rigging.create_rig.get_ordered_hierarchy`
- Signature: `get_ordered_hierarchy(root)`
- API names: `get_ordered_hierarchy`
- Args:
  - `root`, required
- Related functions:
  - same_module: [`api.dcc.maya.duplicate_static_hierarchy(...)`](#apidccmayaduplicate_static_hierarchy) -> `maya_tools.Rigging.create_rig.duplicate_static_hierarchy` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4489](C:/depot/tools/maya_tools/Rigging/create_rig.py:4489)
  - same_module: [`api.dcc.maya.get_all_module_metadata(...)`](#apidccmayaget_all_module_metadata) -> `maya_tools.Rigging.create_rig.get_all_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6594](C:/depot/tools/maya_tools/Rigging/create_rig.py:6594)
  - same_module: [`api.dcc.maya.get_ctrl_shape_cvs(...)`](#apidccmayaget_ctrl_shape_cvs) -> `maya_tools.Rigging.create_rig.get_ctrl_shape_cvs` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2501](C:/depot/tools/maya_tools/Rigging/create_rig.py:2501)
  - same_module: [`api.dcc.maya.get_module_controls(...)`](#apidccmayaget_module_controls) -> `maya_tools.Rigging.create_rig.get_module_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5820](C:/depot/tools/maya_tools/Rigging/create_rig.py:5820)
  - same_module: [`api.dcc.maya.get_nose_joints(...)`](#apidccmayaget_nose_joints) -> `maya_tools.Rigging.create_rig.get_nose_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:583](C:/depot/tools/maya_tools/Rigging/create_rig.py:583)
- Description: Gets ordered hierarchy. :param root: root :return: result
- Source: [create_rig.py:4466](C:/depot/tools/maya_tools/Rigging/create_rig.py:4466)

### `api.dcc.maya.get_region_size_from_joints(...)`

- Target: `maya_tools.Rigging.create_rig.get_region_size_from_joints`
- Signature: `get_region_size_from_joints(joints)`
- API names: `get_region_size_from_joints`
- Args:
  - `joints`, required
- Related functions:
  - same_module: [`api.dcc.maya.create_surface_from_joints_original(...)`](#apidccmayacreate_surface_from_joints_original) -> `maya_tools.Rigging.create_rig.create_surface_from_joints_original` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1217](C:/depot/tools/maya_tools/Rigging/create_rig.py:1217)
  - same_module: [`api.dcc.maya.get_nose_joints(...)`](#apidccmayaget_nose_joints) -> `maya_tools.Rigging.create_rig.get_nose_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:583](C:/depot/tools/maya_tools/Rigging/create_rig.py:583)
  - same_module: [`api.dcc.maya.create_loft_surface_with_follicle_joints(...)`](#apidccmayacreate_loft_surface_with_follicle_joints) -> `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)
  - same_module: [`api.dcc.maya.create_rfl_joints_template(...)`](#apidccmayacreate_rfl_joints_template) -> `maya_tools.Rigging.create_rig.create_rfl_joints_template` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)
  - same_module: [`api.dcc.maya.create_rig(...)`](#apidccmayacreate_rig) -> `maya_tools.Rigging.create_rig.create_rig_from_mapping` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4127](C:/depot/tools/maya_tools/Rigging/create_rig.py:4127)
- Description: Returns average spatial size of a joint region. Useful for auto-scaling controls (mouth, eyelids, brows). :param joints: list of joints :return: Average of results
- Source: [create_rig.py:1119](C:/depot/tools/maya_tools/Rigging/create_rig.py:1119)

### `api.dcc.maya.get_rig_namespaces(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.get_rig_namespaces`
- Signature: `get_rig_namespaces(selection = True)`
- API names: `get_rig_namespaces`
- Args:
  - `selection`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.get_camera_sequencer_data(...)`](#apidccmayaget_camera_sequencer_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:42](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:42)
  - same_module: [`api.dcc.maya.get_cameras_from_selection(...)`](#apidccmayaget_cameras_from_selection) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:94](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:94)
  - same_module: [`api.dcc.maya.get_display_range(...)`](#apidccmayaget_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)
  - same_module: [`api.dcc.maya.get_export_node_data(...)`](#apidccmayaget_export_node_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:271](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:271)
  - same_module: [`api.dcc.maya.call('maya_tools.Cinematics.SequenceUI.sequence_utils.get_main_window_pointer', ...)`](#apidccmayacallmaya_toolscinematicssequenceuisequence_utilsget_main_window_pointer) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_main_window_pointer` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:33](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:33)
- Description: Detects namespaces of selected rigs that contain joints with 'origin' as the top joint. :return: Set of valid namespaces
- Source: [sequence_utils.py:111](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:111)

### `api.dcc.maya.get_scene_path(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.get_scene_path`
- Signature: `get_scene_path()`
- API names: `get_scene_path`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.get_shot_name_from_path(...)`](#apidccmayaget_shot_name_from_path) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_shot_name_from_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:143](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:143)
  - same_module: [`api.dcc.maya.get_camera_sequencer_data(...)`](#apidccmayaget_camera_sequencer_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:42](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:42)
  - same_module: [`api.dcc.maya.get_cameras_from_selection(...)`](#apidccmayaget_cameras_from_selection) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:94](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:94)
  - same_module: [`api.dcc.maya.get_display_range(...)`](#apidccmayaget_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)
  - same_module: [`api.dcc.maya.get_export_node_data(...)`](#apidccmayaget_export_node_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:271](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:271)
- Source: [sequence_utils.py:105](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:105)

### `api.dcc.maya.get_shot_name_from_path(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.get_shot_name_from_path`
- Signature: `get_shot_name_from_path(export_path)`
- API names: `get_shot_name_from_path`
- Args:
  - `export_path`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_cameras_from_selection(...)`](#apidccmayaget_cameras_from_selection) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:94](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:94)
  - same_module: [`api.dcc.maya.get_scene_path(...)`](#apidccmayaget_scene_path) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_scene_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:105](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:105)
  - same_module: [`api.dcc.maya.generate_sequence_dict_from_anim_dict(...)`](#apidccmayagenerate_sequence_dict_from_anim_dict) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.generate_sequence_dict_from_anim_dict` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:165](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:165)
  - same_module: [`api.dcc.maya.get_camera_sequencer_data(...)`](#apidccmayaget_camera_sequencer_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:42](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:42)
  - same_module: [`api.dcc.maya.get_display_range(...)`](#apidccmayaget_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)
- Description: Extracts the shot name from the export path. If the 'shot' part does not contain digits, appends the next part. :param export_path: The export path (e.g., '/Game/Cinematics/Shot_Animation_01.fbx'). :return: The shot name (e.g., 'Shot_Animation' or 'Shot_01').
- Source: [sequence_utils.py:143](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:143)

### `api.dcc.maya.get_side_from_node(...)`

- Target: `maya_tools.Rigging.enum_attrs.get_side_from_node`
- Signature: `get_side_from_node(node)`
- API names: `get_side_from_node`
- Args:
  - `node`, required
- Related functions:
  - same_module: [`api.dcc.maya.build_node_lookup(...)`](#apidccmayabuild_node_lookup) -> `maya_tools.Rigging.enum_attrs.build_node_lookup` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:328](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:328)
  - same_module: [`api.dcc.maya.get_attr_connections(...)`](#apidccmayaget_attr_connections) -> `maya_tools.Rigging.enum_attrs.get_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:176](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:176)
  - same_module: [`api.dcc.maya.get_enum_attrs(...)`](#apidccmayaget_enum_attrs) -> `maya_tools.Rigging.enum_attrs.get_enum_attrs` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:73](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:73)
  - same_module: [`api.dcc.maya.get_enum_labels(...)`](#apidccmayaget_enum_labels) -> `maya_tools.Rigging.enum_attrs.get_enum_labels` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:66](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:66)
  - same_module: [`api.dcc.maya.load_enum_data_from_json(...)`](#apidccmayaload_enum_data_from_json) -> `maya_tools.Rigging.enum_attrs.load_enum_data_from_json` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:168](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:168)
- Source: [enum_attrs.py:23](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:23)

### `api.dcc.maya.get_side_prefix(...)`

- Target: `maya_tools.Rigging.create_rig.get_side_prefix`
- Signature: `get_side_prefix(name)`
- API names: `get_side_prefix`
- Args:
  - `name`, required
- Related functions:
  - same_module: [`api.dcc.maya.apply_side_color_override(...)`](#apidccmayaapply_side_color_override) -> `maya_tools.Rigging.create_rig.apply_side_color_override` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:948](C:/depot/tools/maya_tools/Rigging/create_rig.py:948)
  - same_module: [`api.dcc.maya.get_all_module_metadata(...)`](#apidccmayaget_all_module_metadata) -> `maya_tools.Rigging.create_rig.get_all_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6594](C:/depot/tools/maya_tools/Rigging/create_rig.py:6594)
  - same_module: [`api.dcc.maya.get_ctrl_shape_cvs(...)`](#apidccmayaget_ctrl_shape_cvs) -> `maya_tools.Rigging.create_rig.get_ctrl_shape_cvs` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2501](C:/depot/tools/maya_tools/Rigging/create_rig.py:2501)
  - same_module: [`api.dcc.maya.get_module_controls(...)`](#apidccmayaget_module_controls) -> `maya_tools.Rigging.create_rig.get_module_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5820](C:/depot/tools/maya_tools/Rigging/create_rig.py:5820)
  - same_module: [`api.dcc.maya.get_nose_joints(...)`](#apidccmayaget_nose_joints) -> `maya_tools.Rigging.create_rig.get_nose_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:583](C:/depot/tools/maya_tools/Rigging/create_rig.py:583)
- Description: gets side if it exists for node :param name: node to check :return: Returns 'l', 'r', or None based on joint naming.
- Source: [create_rig.py:1076](C:/depot/tools/maya_tools/Rigging/create_rig.py:1076)

### `api.dcc.maya.get_skin_joints(...)`

- Target: `maya_tools.Rigging.auto_skinner.get_skin_joints`
- Signature: `get_skin_joints(root_joint: str, include_ignored: bool = False) -> List[str]`
- API names: `get_skin_joints`
- Args:
  - `root_joint` (str), required
  - `include_ignored` (bool), default `False`
- Related functions:
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.auto_skin_mesh(...)`](#apidccmayaauto_skin_mesh) -> `maya_tools.Rigging.auto_skinner.auto_skin_mesh` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:588](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:588)
  - same_module: [`api.dcc.maya.auto_skin_selected(...)`](#apidccmayaauto_skin_selected) -> `maya_tools.Rigging.auto_skinner.auto_skin_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:622](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:622)
  - same_module: [`api.dcc.maya.find_skin_cluster(...)`](#apidccmayafind_skin_cluster) -> `maya_tools.Rigging.auto_skinner.find_skin_cluster` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:62](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:62)
  - same_module: [`api.dcc.maya.get_joint_position(...)`](#apidccmayaget_joint_position) -> `maya_tools.Rigging.auto_skinner.get_joint_position` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:69](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:69)
- Source: [auto_skinner.py:93](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:93)

### `api.dcc.maya.get_world_position(...)`

- Target: `maya_tools.Rigging.mocap.setup_hik.get_world_position`
- Signature: `get_world_position(obj)`
- API names: `get_world_position`
- Args:
  - `obj`, required
- Related functions:
  - same_module: [`api.dcc.maya.aim_joint_x_axis_to_world_x(...)`](#apidccmayaaim_joint_x_axis_to_world_x) -> `maya_tools.Rigging.mocap.setup_hik.aim_joint_x_axis_to_world_x` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:271](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:271)
  - same_module: [`api.dcc.maya.get_descendant_joints(...)`](#apidccmayaget_descendant_joints) -> `maya_tools.Rigging.mocap.setup_hik.get_descendant_joints` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:194](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:194)
- Description: Gets the world position :param obj: name of object :return:
- Source: [setup_hik.py:225](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:225)

### `api.dcc.maya.guess_joint_map_from_root(...)`

- Target: `maya_tools.Rigging.mocap.setup_hik.guess_joint_map_from_root`
- Signature: `guess_joint_map_from_root(root_joint, base_joint_map=None)`
- API names: `guess_joint_map_from_root`
- Args:
  - `root_joint`, required
  - `base_joint_map`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.populate_default_face_map_from_scene(...)`](#apidccmayapopulate_default_face_map_from_scene) -> `maya_tools.Rigging.mocap.setup_hik.populate_default_face_map_from_scene` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:466](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:466)
  - same_module: [`api.dcc.maya.aim_joint_x_axis_to_world_x(...)`](#apidccmayaaim_joint_x_axis_to_world_x) -> `maya_tools.Rigging.mocap.setup_hik.aim_joint_x_axis_to_world_x` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:271](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:271)
- Description: Guesses HIK joint slots from a root joint based on name matching. :param root_joint: The root joint of the skeleton. :param base_joint_map: Optional dict to write results into (e.g. self.default_map). If None, a deep copy of setup_hik.DEFAULT_JOINT_MAP is used. :return: A dict with HIK slots and their mapped joint names.
- Source: [setup_hik.py:554](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:554)

### `api.dcc.maya.hik_map_to_rig_args(...)`

- Target: `maya_tools.Rigging.create_rig.hik_map_to_rig_args`
- Signature: `hik_map_to_rig_args(body_joint_map, face_joint_map)`
- API names: `hik_map_to_rig_args`
- Args:
  - `body_joint_map`, required
  - `face_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.create_full_rig(...)`](#apidccmayacreate_full_rig) -> `maya_tools.Rigging.create_rig.create_full_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3870](C:/depot/tools/maya_tools/Rigging/create_rig.py:3870)
  - same_module: [`api.dcc.maya.create_rig(...)`](#apidccmayacreate_rig) -> `maya_tools.Rigging.create_rig.create_rig_from_mapping` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4127](C:/depot/tools/maya_tools/Rigging/create_rig.py:4127)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.remove_full_rig(...)`](#apidccmayaremove_full_rig) -> `maya_tools.Rigging.create_rig.remove_full_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4064](C:/depot/tools/maya_tools/Rigging/create_rig.py:4064)
  - same_module: [`api.dcc.maya.restore_rig_connections(...)`](#apidccmayarestore_rig_connections) -> `maya_tools.Rigging.create_rig.restore_rig_connections` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6777](C:/depot/tools/maya_tools/Rigging/create_rig.py:6777)
- Description: Translate body and face mappings into rig arguments. Only joints that exist in the scene are included. Face slots are read from face_joint_map rather than body_joint_map. :param body_joint_map: mapping for body joint map :param face_joint_map: mapping for face joint map :return: result
- Source: [create_rig.py:3478](C:/depot/tools/maya_tools/Rigging/create_rig.py:3478)

### `api.dcc.maya.import_enum_orders(...)`

- Target: `maya_tools.Rigging.enum_attrs.import_enum_orders`
- Signature: `import_enum_orders(filepath)`
- API names: `import_enum_orders`
- Args:
  - `filepath`, required
- Related functions:
  - same_module: [`api.dcc.maya.export_selected_enum_orders(...)`](#apidccmayaexport_selected_enum_orders) -> `maya_tools.Rigging.enum_attrs.export_selected_enum_orders` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:427](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:427)
  - same_module: [`api.dcc.maya.apply_enum_data(...)`](#apidccmayaapply_enum_data) -> `maya_tools.Rigging.enum_attrs.apply_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:348](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:348)
  - same_module: [`api.dcc.maya.collect_enum_data(...)`](#apidccmayacollect_enum_data) -> `maya_tools.Rigging.enum_attrs.collect_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:86](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:86)
  - same_module: [`api.dcc.maya.get_enum_attrs(...)`](#apidccmayaget_enum_attrs) -> `maya_tools.Rigging.enum_attrs.get_enum_attrs` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:73](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:73)
  - same_module: [`api.dcc.maya.get_enum_labels(...)`](#apidccmayaget_enum_labels) -> `maya_tools.Rigging.enum_attrs.get_enum_labels` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:66](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:66)
- Description: Import enum label orders from JSON and apply them to matching nodes in the currently opened scene.
- Source: [enum_attrs.py:439](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:439)

### `api.dcc.maya.import_reference_and_strip_namespace_test(...)`

- Target: `maya_tools.Animation.anim_export.anim_export.import_reference_and_strip_namespace_test`
- Signature: `import_reference_and_strip_namespace_test(namespace, root)`
- API names: `import_reference_and_strip_namespace_test`
- Args:
  - `namespace`, required
  - `root`, required
- Related functions:
  - same_module: [`api.dcc.maya.update_joint_setup_for_import(...)`](#apidccmayaupdate_joint_setup_for_import) -> `maya_tools.Animation.anim_export.anim_export.update_joint_setup_for_import` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:206](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:206)
- Description: Imports objects from a reference associated with the given namespace, imports any nested references, strips all namespaces, renames duplicates, and returns a list of renamed transform nodes. :param namespace: The namespace of the reference. :param root: Root transform node to collect hierarchy from. :return: List of renamed transform nodes.
- Source: [anim_export.py:247](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:247)

### `api.dcc.maya.import_skin_weights(...)`

- Target: `maya_tools.Rigging.skinning_utils.import_skin_weights`
- Signature: `import_skin_weights(meshes, export_dir="C:/temp/weights")`
- API names: `import_skin_weights`
- Args:
  - `meshes`, required
  - `export_dir`, default `'C:/temp/weights'`
- Related functions:
  - same_module: [`api.dcc.maya.export_skin_weights(...)`](#apidccmayaexport_skin_weights) -> `maya_tools.Rigging.skinning_utils.export_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:173](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:173)
  - same_module: [`api.dcc.maya.transfer_skin_weights(...)`](#apidccmayatransfer_skin_weights) -> `maya_tools.Rigging.skinning_utils.transfer_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:24](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:24)
  - same_module: [`api.dcc.maya.transfer_skin_weights_from_selection(...)`](#apidccmayatransfer_skin_weights_from_selection) -> `maya_tools.Rigging.skinning_utils.transfer_skin_weights_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:8](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:8)
- Description: Imports skin weights for a list of meshes from XML and JSON files. :param meshes: list of mesh names to import to :param export_dir: directory where XML and JSON files are stored
- Source: [skinning_utils.py:229](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:229)

### `api.dcc.maya.initialize_command_port(...)`

- Target: `maya_tools.maya_menu.initialize_command_port`
- Signature: `initialize_command_port()`
- API names: `initialize_command_port`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.apply_command_port_python3_patches(...)`](#apidccmayaapply_command_port_python3_patches) -> `maya_tools.maya_menu.apply_command_port_python3_patches` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:67](C:/depot/tools/maya_tools/maya_menu.py:67)
  - same_module: [`api.dcc.maya.cleanup_command_port_files(...)`](#apidccmayacleanup_command_port_files) -> `maya_tools.maya_menu.cleanup_command_port_files` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:196](C:/depot/tools/maya_tools/maya_menu.py:196)
  - same_module: [`api.dcc.maya.create_command_port(...)`](#apidccmayacreate_command_port) -> `maya_tools.maya_menu.create_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:287](C:/depot/tools/maya_tools/maya_menu.py:287)
  - same_module: [`api.dcc.maya.get_command_port(...)`](#apidccmayaget_command_port) -> `maya_tools.maya_menu.get_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:232](C:/depot/tools/maya_tools/maya_menu.py:232)
  - same_module: [`api.dcc.maya.save_port_to_file(...)`](#apidccmayasave_port_to_file) -> `maya_tools.maya_menu.save_port_to_file` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:216](C:/depot/tools/maya_tools/maya_menu.py:216)
- Source: [maya_menu.py:322](C:/depot/tools/maya_tools/maya_menu.py:322)

### `api.dcc.maya.is_maya(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_ui.is_maya`
- Signature: `is_maya()`
- API names: `is_maya`
- Args: none
- Source: [sequence_ui.py:12](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_ui.py:12)

### `api.dcc.maya.is_motionbuilder(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_ui.is_motionbuilder`
- Signature: `is_motionbuilder()`
- API names: `is_motionbuilder`
- Args: none
- Source: [sequence_ui.py:19](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_ui.py:19)

### `api.dcc.maya.launch_hik_ui(...)`

- Target: `maya_tools.Rigging.mocap.hik_ui.launch_hik_ui`
- Signature: `launch_hik_ui()`
- API names: `launch_hik_ui`
- Args: none
- Source: [hik_ui.py:3320](C:/depot/tools/maya_tools/Rigging/mocap/hik_ui.py:3320)

### `api.dcc.maya.learn_shoulder_profile_from_selected(...)`

- Target: `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_selected`
- Signature: `learn_shoulder_profile_from_selected(`
- API names: `learn_shoulder_profile_from_selected`
- Args:
  - `root_joint` (str), default `'origin'`
  - `output_path` (Optional[str]), default `None`
  - `radius_scale` (float), default `0.45`
- Related functions:
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_skin(...)`](#apidccmayalearn_shoulder_profile_from_skin) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:228](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:228)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.build_default_shoulder_profile(...)`](#apidccmayabuild_default_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.build_default_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:164](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:164)
  - same_module: [`api.dcc.maya.load_shoulder_profile(...)`](#apidccmayaload_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.load_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:213](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:213)
- Source: [auto_skinner.py:277](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:277)

### `api.dcc.maya.learn_shoulder_profile_from_skin(...)`

- Target: `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_skin`
- Signature: `learn_shoulder_profile_from_skin(`
- API names: `learn_shoulder_profile_from_skin`
- Args:
  - `mesh` (str), required
  - `root_joint` (str), default `'origin'`
  - `radius_scale` (float), default `0.45`
  - `min_vertices` (int), default `6`
- Related functions:
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_selected(...)`](#apidccmayalearn_shoulder_profile_from_selected) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:277](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:277)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.build_default_shoulder_profile(...)`](#apidccmayabuild_default_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.build_default_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:164](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:164)
  - same_module: [`api.dcc.maya.load_shoulder_profile(...)`](#apidccmayaload_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.load_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:213](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:213)
- Source: [auto_skinner.py:228](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:228)

### `api.dcc.maya.load_enum_data_from_json(...)`

- Target: `maya_tools.Rigging.enum_attrs.load_enum_data_from_json`
- Signature: `load_enum_data_from_json(filepath)`
- API names: `load_enum_data_from_json`
- Args:
  - `filepath`, required
- Related functions:
  - same_module: [`api.dcc.maya.save_enum_data_to_json(...)`](#apidccmayasave_enum_data_to_json) -> `maya_tools.Rigging.enum_attrs.save_enum_data_to_json` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:150](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:150)
  - same_module: [`api.dcc.maya.apply_enum_data(...)`](#apidccmayaapply_enum_data) -> `maya_tools.Rigging.enum_attrs.apply_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:348](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:348)
  - same_module: [`api.dcc.maya.collect_enum_data(...)`](#apidccmayacollect_enum_data) -> `maya_tools.Rigging.enum_attrs.collect_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:86](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:86)
  - same_module: [`api.dcc.maya.export_selected_enum_orders(...)`](#apidccmayaexport_selected_enum_orders) -> `maya_tools.Rigging.enum_attrs.export_selected_enum_orders` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:427](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:427)
  - same_module: [`api.dcc.maya.get_enum_attrs(...)`](#apidccmayaget_enum_attrs) -> `maya_tools.Rigging.enum_attrs.get_enum_attrs` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:73](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:73)
- Source: [enum_attrs.py:168](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:168)

### `api.dcc.maya.load_module_metadata(...)`

- Target: `maya_tools.Rigging.create_rig.load_module_metadata`
- Signature: `load_module_metadata(module_id)`
- API names: `load_module_metadata`
- Args:
  - `module_id`, required
- Related functions:
  - same_module: [`api.dcc.maya.clear_module_metadata(...)`](#apidccmayaclear_module_metadata) -> `maya_tools.Rigging.create_rig.clear_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6613](C:/depot/tools/maya_tools/Rigging/create_rig.py:6613)
  - same_module: [`api.dcc.maya.get_all_module_metadata(...)`](#apidccmayaget_all_module_metadata) -> `maya_tools.Rigging.create_rig.get_all_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6594](C:/depot/tools/maya_tools/Rigging/create_rig.py:6594)
  - same_module: [`api.dcc.maya.save_module_metadata(...)`](#apidccmayasave_module_metadata) -> `maya_tools.Rigging.create_rig.save_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6549](C:/depot/tools/maya_tools/Rigging/create_rig.py:6549)
  - same_module: [`api.dcc.maya.get_module_controls(...)`](#apidccmayaget_module_controls) -> `maya_tools.Rigging.create_rig.get_module_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5820](C:/depot/tools/maya_tools/Rigging/create_rig.py:5820)
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
- Description: Return the stored dict for module_id, or {} if not found. :param module_id: unique module identifier :return: dict
- Source: [create_rig.py:6575](C:/depot/tools/maya_tools/Rigging/create_rig.py:6575)

### `api.dcc.maya.load_shoulder_profile(...)`

- Target: `maya_tools.Rigging.auto_skinner.load_shoulder_profile`
- Signature: `load_shoulder_profile(path: str) -> dict`
- API names: `load_shoulder_profile`
- Args:
  - `path` (str), required
- Related functions:
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.build_default_shoulder_profile(...)`](#apidccmayabuild_default_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.build_default_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:164](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:164)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_selected(...)`](#apidccmayalearn_shoulder_profile_from_selected) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:277](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:277)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_skin(...)`](#apidccmayalearn_shoulder_profile_from_skin) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:228](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:228)
- Source: [auto_skinner.py:213](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:213)

### `api.dcc.maya.log(...)`

- Target: `maya_tools.maya_menu.log`
- Signature: `log(message)`
- API names: `log`
- Args:
  - `message`, required
- Related functions:
  - same_module: [`api.dcc.maya.log_exception(...)`](#apidccmayalog_exception) -> `maya_tools.maya_menu.log_exception` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:34](C:/depot/tools/maya_tools/maya_menu.py:34)
- Source: [maya_menu.py:30](C:/depot/tools/maya_tools/maya_menu.py:30)

### `api.dcc.maya.log_exception(...)`

- Target: `maya_tools.maya_menu.log_exception`
- Signature: `log_exception(message)`
- API names: `log_exception`
- Args:
  - `message`, required
- Related functions:
  - same_module: [`api.dcc.maya.log(...)`](#apidccmayalog) -> `maya_tools.maya_menu.log` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:30](C:/depot/tools/maya_tools/maya_menu.py:30)
- Source: [maya_menu.py:34](C:/depot/tools/maya_tools/maya_menu.py:34)

### `api.dcc.maya.make_hik_maps_from_root(...)`

- Target: `maya_tools.Rigging.joint_placer.make_hik_maps_from_root`
- Signature: `make_hik_maps_from_root(root_joint: str) -> Tuple[dict, dict]`
- API names: `make_hik_maps_from_root`
- Args:
  - `root_joint` (str), required
- Related functions:
  - same_module: [`api.dcc.maya.build_skeleton_from_points(...)`](#apidccmayabuild_skeleton_from_points) -> `maya_tools.Rigging.joint_placer.build_skeleton_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:424](C:/depot/tools/maya_tools/Rigging/joint_placer.py:424)
  - same_module: [`api.dcc.maya.create_guides_from_points(...)`](#apidccmayacreate_guides_from_points) -> `maya_tools.Rigging.joint_placer.create_guides_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:498](C:/depot/tools/maya_tools/Rigging/joint_placer.py:498)
  - same_module: [`api.dcc.maya.point_from_normalized_bounds(...)`](#apidccmayapoint_from_normalized_bounds) -> `maya_tools.Rigging.joint_placer.point_from_normalized_bounds` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:267](C:/depot/tools/maya_tools/Rigging/joint_placer.py:267)
- Source: [joint_placer.py:455](C:/depot/tools/maya_tools/Rigging/joint_placer.py:455)

### `api.dcc.maya.maya_execute_and_capture(...)`

- Target: `maya_tools.maya_menu.maya_execute_and_capture`
- Signature: `maya_execute_and_capture(encoded_code)`
- API names: `maya_execute_and_capture`
- Args:
  - `encoded_code`, required
- Related functions:
  - same_module: [`api.dcc.maya.create_maya_menu(...)`](#apidccmayacreate_maya_menu) -> `maya_tools.maya_menu.create_maya_menu` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:422](C:/depot/tools/maya_tools/maya_menu.py:422)
- Source: [maya_menu.py:39](C:/depot/tools/maya_tools/maya_menu.py:39)

### `api.dcc.maya.measure_planar_deviation(...)`

- Target: `maya_tools.Rigging.joint_placer.measure_planar_deviation`
- Signature: `measure_planar_deviation(points: Dict[str, Vector3]) -> Dict[str, float]`
- API names: `measure_planar_deviation`
- Args:
  - `points` (Dict[str, Vector3]), required
- Source: [joint_placer.py:214](C:/depot/tools/maya_tools/Rigging/joint_placer.py:214)

### `api.dcc.maya.mirror_face_joints(...)`

- Target: `maya_tools.Rigging.create_rig.mirror_face_joints`
- Signature: `mirror_face_joints(`
- API names: `mirror_face_joints`
- Args:
  - `joints`, required
  - `search_replace`, default `('l_', 'r_')`
  - `mirror_axis`, default `'YZ'`
  - `rotate_z_180`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.create_loft_surface_with_follicle_joints(...)`](#apidccmayacreate_loft_surface_with_follicle_joints) -> `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)
  - same_module: [`api.dcc.maya.create_rfl_joints_template(...)`](#apidccmayacreate_rfl_joints_template) -> `maya_tools.Rigging.create_rig.create_rfl_joints_template` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)
  - same_module: [`api.dcc.maya.create_surface_from_joints_original(...)`](#apidccmayacreate_surface_from_joints_original) -> `maya_tools.Rigging.create_rig.create_surface_from_joints_original` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1217](C:/depot/tools/maya_tools/Rigging/create_rig.py:1217)
  - same_module: [`api.dcc.maya.get_nose_joints(...)`](#apidccmayaget_nose_joints) -> `maya_tools.Rigging.create_rig.get_nose_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:583](C:/depot/tools/maya_tools/Rigging/create_rig.py:583)
  - same_module: [`api.dcc.maya.get_region_size_from_joints(...)`](#apidccmayaget_region_size_from_joints) -> `maya_tools.Rigging.create_rig.get_region_size_from_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1119](C:/depot/tools/maya_tools/Rigging/create_rig.py:1119)
- Description: Mirrors face joints and optionally rotates them 180 degrees in Z (object space). :param joints: list of joint names to mirror :param search_replace: tuple (search, replace) for naming :param mirror_axis: 'YZ', 'XZ', or 'XY' :param rotate_z_180: bool, apply local Z 180 rotation after mirror :return: list of mirrored joints
- Source: [create_rig.py:2167](C:/depot/tools/maya_tools/Rigging/create_rig.py:2167)

### `api.dcc.maya.mirror_joint_yz_behavior_with_label_flip(...)`

- Target: `maya_tools.Rigging.create_rig.mirror_joint_yz_behavior_with_label_flip`
- Signature: `mirror_joint_yz_behavior_with_label_flip(root_joint=None, rename_first_char=True)`
- API names: `mirror_joint_yz_behavior_with_label_flip`
- Args:
  - `root_joint`, default `None`
  - `rename_first_char`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.bake_joint_orient_to_rotate(...)`](#apidccmayabake_joint_orient_to_rotate) -> `maya_tools.Rigging.create_rig.bake_joint_orient_to_rotate` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1935](C:/depot/tools/maya_tools/Rigging/create_rig.py:1935)
  - same_module: [`api.dcc.maya.create_joint_controls(...)`](#apidccmayacreate_joint_controls) -> `maya_tools.Rigging.create_rig.create_joint_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:975](C:/depot/tools/maya_tools/Rigging/create_rig.py:975)
  - same_module: [`api.dcc.maya.create_loft_surface_with_follicle_joints(...)`](#apidccmayacreate_loft_surface_with_follicle_joints) -> `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)
  - same_module: [`api.dcc.maya.mirror_face_joints(...)`](#apidccmayamirror_face_joints) -> `maya_tools.Rigging.create_rig.mirror_face_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2167](C:/depot/tools/maya_tools/Rigging/create_rig.py:2167)
  - same_module: [`api.dcc.maya.setup_surface_rig_with_drivers(...)`](#apidccmayasetup_surface_rig_with_drivers) -> `maya_tools.Rigging.create_rig.setup_surface_rig_with_drivers` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1506](C:/depot/tools/maya_tools/Rigging/create_rig.py:1506)
- Description: Mirror a joint chain across YZ using behavior mirroring. Then flip joint label Side from Left<->Right on the mirrored chain. Optionally swaps first character of the mirrored names: l/r/L/R. :param root_joint: root joint name to mirror; sl=True if None :param rename_first_char: whether to swap first character l/r :return: list[str]
- Source: [create_rig.py:2655](C:/depot/tools/maya_tools/Rigging/create_rig.py:2655)

### `api.dcc.maya.normalize(...)`

- Target: `maya_tools.Rigging.create_rig.normalize`
- Signature: `normalize(v)`
- API names: `normalize`
- Args:
  - `v`, required
- Description: Normalises a 3D vector. :param v: input 3D vector :return: list[float]
- Source: [create_rig.py:1193](C:/depot/tools/maya_tools/Rigging/create_rig.py:1193)

### `api.dcc.maya.normalize_and_limit_weights(...)`

- Target: `maya_tools.Rigging.auto_skinner.normalize_and_limit_weights`
- Signature: `normalize_and_limit_weights(weights: WeightList, max_influences: int = DEFAULT_MAX_INFLUENCES) -> WeightList`
- API names: `normalize_and_limit_weights`
- Args:
  - `weights` (WeightList), required
  - `max_influences` (int), default `DEFAULT_MAX_INFLUENCES`
- Related functions:
  - same_module: [`api.dcc.maya.apply_auto_weights(...)`](#apidccmayaapply_auto_weights) -> `maya_tools.Rigging.auto_skinner.apply_auto_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:475](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:475)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.smooth_skin_weights(...)`](#apidccmayasmooth_skin_weights) -> `maya_tools.Rigging.auto_skinner.smooth_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:570](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:570)
  - same_module: [`api.dcc.maya.solve_vertex_weights(...)`](#apidccmayasolve_vertex_weights) -> `maya_tools.Rigging.auto_skinner.solve_vertex_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:433](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:433)
  - same_module: [`api.dcc.maya.solve_vertex_weights_from_position(...)`](#apidccmayasolve_vertex_weights_from_position) -> `maya_tools.Rigging.auto_skinner.solve_vertex_weights_from_position` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:451](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:451)
- Source: [auto_skinner.py:152](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:152)

### `api.dcc.maya.offset_pv_pad(...)`

- Target: `maya_tools.Rigging.create_rig.offset_pv_pad`
- Signature: `offset_pv_pad(pad, side, amount=5.0)`
- API names: `offset_pv_pad`
- Args:
  - `pad`, required
  - `side`, required
  - `amount`, default `5.0`
- Related functions:
  - same_module: [`api.dcc.maya.orient_control_pad_to_world_safely(...)`](#apidccmayaorient_control_pad_to_world_safely) -> `maya_tools.Rigging.create_rig.orient_control_pad_to_world_safely` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:885](C:/depot/tools/maya_tools/Rigging/create_rig.py:885)
  - same_module: [`api.dcc.maya.rename_brow_pad_hierarchies(...)`](#apidccmayarename_brow_pad_hierarchies) -> `maya_tools.Rigging.create_rig.rename_brow_pad_hierarchies` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3745](C:/depot/tools/maya_tools/Rigging/create_rig.py:3745)
- Description: :param pad: pad to offset :param side: side of ctrl :param amount: offset amount :return:
- Source: [create_rig.py:1178](C:/depot/tools/maya_tools/Rigging/create_rig.py:1178)

### `api.dcc.maya.on_before_save(...)`

- Target: `maya_tools.maya_menu.on_before_save`
- Signature: `on_before_save(*args)`
- API names: `on_before_save`
- Args:
  - `*args`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_save_callback(...)`](#apidccmayaremove_save_callback) -> `maya_tools.maya_menu.remove_save_callback` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:346](C:/depot/tools/maya_tools/maya_menu.py:346)
  - same_module: [`api.dcc.maya.save_port_to_file(...)`](#apidccmayasave_port_to_file) -> `maya_tools.maya_menu.save_port_to_file` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:216](C:/depot/tools/maya_tools/maya_menu.py:216)
  - same_module: [`api.dcc.maya.save_session_to_file(...)`](#apidccmayasave_session_to_file) -> `maya_tools.maya_menu.save_session_to_file` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:185](C:/depot/tools/maya_tools/maya_menu.py:185)
- Source: [maya_menu.py:328](C:/depot/tools/maya_tools/maya_menu.py:328)

### `api.dcc.maya.open_scene_with_specific_references(...)`

- Target: `maya_tools.Animation.anim_export.anim_export_utils.open_scene_with_specific_references`
- Signature: `open_scene_with_specific_references(maya_file, reference_list)`
- API names: `open_scene_with_specific_references`
- Args:
  - `maya_file`, required
  - `reference_list`, required
- Related functions:
  - same_module: [`api.dcc.maya.find_references_from_namespace(...)`](#apidccmayafind_references_from_namespace) -> `maya_tools.Animation.anim_export.anim_export_utils.find_references_from_namespace` - Shares module and name terms; may be useful in the same workflow.; source [anim_export_utils.py:81](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_utils.py:81)
- Description: Opens a Maya scene and loads only the specified references, ignoring any others. :param maya_file: Full path to the .ma or .mb file :param reference_list: List of dictionaries [{"path": "...", "namespace": "..."}, ...]
- Source: [anim_export_utils.py:55](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_utils.py:55)

### `api.dcc.maya.orient_control_pad_to_world_safely(...)`

- Target: `maya_tools.Rigging.create_rig.orient_control_pad_to_world_safely`
- Signature: `orient_control_pad_to_world_safely(ctrl, jnt)`
- API names: `orient_control_pad_to_world_safely`
- Args:
  - `ctrl`, required
  - `jnt`, required
- Related functions:
  - same_module: [`api.dcc.maya.bake_joint_orient_to_rotate(...)`](#apidccmayabake_joint_orient_to_rotate) -> `maya_tools.Rigging.create_rig.bake_joint_orient_to_rotate` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1935](C:/depot/tools/maya_tools/Rigging/create_rig.py:1935)
  - same_module: [`api.dcc.maya.offset_pv_pad(...)`](#apidccmayaoffset_pv_pad) -> `maya_tools.Rigging.create_rig.offset_pv_pad` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1178](C:/depot/tools/maya_tools/Rigging/create_rig.py:1178)
  - same_module: [`api.dcc.maya.rename_brow_pad_hierarchies(...)`](#apidccmayarename_brow_pad_hierarchies) -> `maya_tools.Rigging.create_rig.rename_brow_pad_hierarchies` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3745](C:/depot/tools/maya_tools/Rigging/create_rig.py:3745)
  - same_module: [`api.dcc.maya.restore_all_control_cv_positions(...)`](#apidccmayarestore_all_control_cv_positions) -> `maya_tools.Rigging.create_rig.restore_all_control_cv_positions` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2551](C:/depot/tools/maya_tools/Rigging/create_rig.py:2551)
  - same_module: [`api.dcc.maya.store_all_control_cv_positions(...)`](#apidccmayastore_all_control_cv_positions) -> `maya_tools.Rigging.create_rig.store_all_control_cv_positions` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2525](C:/depot/tools/maya_tools/Rigging/create_rig.py:2525)
- Description: Safely orients the control's pad to world coordinate space without moving the joint, unparenting children first, resetting world rotation on the pad, recreating parent/scale constraints, and then reparenting the children back under the control. :param ctrl: ctrl :param jnt: jnt
- Source: [create_rig.py:885](C:/depot/tools/maya_tools/Rigging/create_rig.py:885)

### `api.dcc.maya.orient_skeleton(...)`

- Target: `maya_tools.Rigging.joint_placer.orient_skeleton`
- Signature: `orient_skeleton(root_joint: str) -> None`
- API names: `orient_skeleton`
- Args:
  - `root_joint` (str), required
- Related functions:
  - same_module: [`api.dcc.maya.build_basic_biped_skeleton(...)`](#apidccmayabuild_basic_biped_skeleton) -> `maya_tools.Rigging.joint_placer.build_basic_biped_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:516](C:/depot/tools/maya_tools/Rigging/joint_placer.py:516)
  - same_module: [`api.dcc.maya.build_skeleton_from_points(...)`](#apidccmayabuild_skeleton_from_points) -> `maya_tools.Rigging.joint_placer.build_skeleton_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:424](C:/depot/tools/maya_tools/Rigging/joint_placer.py:424)
  - same_module: [`api.dcc.maya.delete_existing_generated_skeleton(...)`](#apidccmayadelete_existing_generated_skeleton) -> `maya_tools.Rigging.joint_placer.delete_existing_generated_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:341](C:/depot/tools/maya_tools/Rigging/joint_placer.py:341)
- Source: [joint_placer.py:370](C:/depot/tools/maya_tools/Rigging/joint_placer.py:370)

### `api.dcc.maya.point_from_normalized_bounds(...)`

- Target: `maya_tools.Rigging.joint_placer.point_from_normalized_bounds`
- Signature: `point_from_normalized_bounds(bounds: Dict[str, object], xyz: Vector3) -> Vector3`
- API names: `point_from_normalized_bounds`
- Args:
  - `bounds` (Dict[str, object]), required
  - `xyz` (Vector3), required
- Related functions:
  - same_module: [`api.dcc.maya.build_skeleton_from_points(...)`](#apidccmayabuild_skeleton_from_points) -> `maya_tools.Rigging.joint_placer.build_skeleton_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:424](C:/depot/tools/maya_tools/Rigging/joint_placer.py:424)
  - same_module: [`api.dcc.maya.create_guides_from_points(...)`](#apidccmayacreate_guides_from_points) -> `maya_tools.Rigging.joint_placer.create_guides_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:498](C:/depot/tools/maya_tools/Rigging/joint_placer.py:498)
  - same_module: [`api.dcc.maya.get_mesh_bounds(...)`](#apidccmayaget_mesh_bounds) -> `maya_tools.Rigging.joint_placer.get_mesh_bounds` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:250](C:/depot/tools/maya_tools/Rigging/joint_placer.py:250)
  - same_module: [`api.dcc.maya.make_hik_maps_from_root(...)`](#apidccmayamake_hik_maps_from_root) -> `maya_tools.Rigging.joint_placer.make_hik_maps_from_root` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:455](C:/depot/tools/maya_tools/Rigging/joint_placer.py:455)
- Source: [joint_placer.py:267](C:/depot/tools/maya_tools/Rigging/joint_placer.py:267)

### `api.dcc.maya.populate_default_face_map_from_scene(...)`

- Target: `maya_tools.Rigging.mocap.setup_hik.populate_default_face_map_from_scene`
- Signature: `populate_default_face_map_from_scene(base_face_map=None)`
- API names: `populate_default_face_map_from_scene`
- Args:
  - `base_face_map`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.guess_joint_map_from_root(...)`](#apidccmayaguess_joint_map_from_root) -> `maya_tools.Rigging.mocap.setup_hik.guess_joint_map_from_root` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:554](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:554)
  - same_module: [`api.dcc.maya.find_face_joints(...)`](#apidccmayafind_face_joints) -> `maya_tools.Rigging.mocap.setup_hik.find_face_joints` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:205](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:205)
- Description: Fill face map with default scene joints under HIK head reference. :param base_face_map: mapping for base face map :return: result
- Source: [setup_hik.py:466](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:466)

### `api.dcc.maya.preserve_rfl_pivot_joints(...)`

- Target: `maya_tools.Rigging.create_rig.preserve_rfl_pivot_joints`
- Signature: `preserve_rfl_pivot_joints(side=None)`
- API names: `preserve_rfl_pivot_joints`
- Args:
  - `side`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.create_rfl_joints_template(...)`](#apidccmayacreate_rfl_joints_template) -> `maya_tools.Rigging.create_rig.create_rfl_joints_template` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)
  - same_module: [`api.dcc.maya.resolve_rfl_joints(...)`](#apidccmayaresolve_rfl_joints) -> `maya_tools.Rigging.create_rig.resolve_rfl_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5891](C:/depot/tools/maya_tools/Rigging/create_rig.py:5891)
  - same_module: [`api.dcc.maya.build_rfl_ik_and_constraints(...)`](#apidccmayabuild_rfl_ik_and_constraints) -> `maya_tools.Rigging.create_rig.build_rfl_ik_and_constraints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:779](C:/depot/tools/maya_tools/Rigging/create_rig.py:779)
  - same_module: [`api.dcc.maya.create_loft_surface_with_follicle_joints(...)`](#apidccmayacreate_loft_surface_with_follicle_joints) -> `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)
  - same_module: [`api.dcc.maya.create_surface_from_joints_original(...)`](#apidccmayacreate_surface_from_joints_original) -> `maya_tools.Rigging.create_rig.create_surface_from_joints_original` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1217](C:/depot/tools/maya_tools/Rigging/create_rig.py:1217)
- Description: Preserve rfl pivot joints. :param side: side :return: result
- Source: [create_rig.py:5511](C:/depot/tools/maya_tools/Rigging/create_rig.py:5511)

### `api.dcc.maya.query_space_switches(...)`

- Target: `maya_tools.Rigging.create_rig.query_space_switches`
- Signature: `query_space_switches(driven)`
- API names: `query_space_switches`
- Args:
  - `driven`, required
- Related functions:
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_leg_space_switches(...)`](#apidccmayacreate_leg_space_switches) -> `maya_tools.Rigging.create_rig.create_leg_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2711](C:/depot/tools/maya_tools/Rigging/create_rig.py:2711)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.rebuild_all_space_switches(...)`](#apidccmayarebuild_all_space_switches) -> `maya_tools.Rigging.create_rig.rebuild_all_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6699](C:/depot/tools/maya_tools/Rigging/create_rig.py:6699)
  - same_module: [`api.dcc.maya.build_enum_names_for_space_targets(...)`](#apidccmayabuild_enum_names_for_space_targets) -> `maya_tools.Rigging.create_rig.build_enum_names_for_space_targets` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2403](C:/depot/tools/maya_tools/Rigging/create_rig.py:2403)
- Description: Queries and returns any space switches driving 'driven' checking control and pad levels. :param driven: control node to query :return: list[dict]
- Source: [create_rig.py:4197](C:/depot/tools/maya_tools/Rigging/create_rig.py:4197)

### `api.dcc.maya.rebind_metahuman_face_to_body(...)`

- Target: `maya_tools.Rigging.metahuman_utils.rebind_metahuman_face_to_body`
- Signature: `rebind_metahuman_face_to_body(face_mesh, face_joints, body_joints, skin_weights_path, dna_file_path)`
- API names: `rebind_metahuman_face_to_body`
- Args:
  - `face_mesh`, required
  - `face_joints`, required
  - `body_joints`, required
  - `skin_weights_path`, required
  - `dna_file_path`, required
- Description: Rebind MetaHuman head mesh to a different body rig, transfer skin weights, and update the DNA. :param face_mesh: Name of the MetaHuman face mesh (e.g. "Face_Mesh") :param face_joints: List of face rig joints to snap (e.g. ["root", "pelvis", "spine_01", "spine_02","spine_03", "spine_04", "spine_05", "neck_01", "neck_02", "head"]) :param body_joints: Corresponding joints on the new body rig. :param skin_weights_path: File path to export/import skin weights. :param dna_file_path: Path to the MetaHu
- Source: [metahuman_utils.py:7](C:/depot/tools/maya_tools/Rigging/metahuman_utils.py:7)

### `api.dcc.maya.rebuild_all_space_switches(...)`

- Target: `maya_tools.Rigging.create_rig.rebuild_all_space_switches`
- Signature: `rebuild_all_space_switches()`
- API names: `rebuild_all_space_switches`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.create_arm_space_switches(...)`](#apidccmayacreate_arm_space_switches) -> `maya_tools.Rigging.create_rig.create_arm_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2845](C:/depot/tools/maya_tools/Rigging/create_rig.py:2845)
  - same_module: [`api.dcc.maya.create_leg_space_switches(...)`](#apidccmayacreate_leg_space_switches) -> `maya_tools.Rigging.create_rig.create_leg_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2711](C:/depot/tools/maya_tools/Rigging/create_rig.py:2711)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.query_space_switches(...)`](#apidccmayaquery_space_switches) -> `maya_tools.Rigging.create_rig.query_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4197](C:/depot/tools/maya_tools/Rigging/create_rig.py:4197)
  - same_module: [`api.dcc.maya.build_enum_names_for_space_targets(...)`](#apidccmayabuild_enum_names_for_space_targets) -> `maya_tools.Rigging.create_rig.build_enum_names_for_space_targets` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2403](C:/depot/tools/maya_tools/Rigging/create_rig.py:2403)
- Description: Rebuilds all space switches in the scene using stored connections to ensure they are perfectly aligned with newly oriented controls.
- Source: [create_rig.py:6699](C:/depot/tools/maya_tools/Rigging/create_rig.py:6699)

### `api.dcc.maya.rebuild_enum_attr_with_order(...)`

- Target: `maya_tools.Rigging.enum_attrs.rebuild_enum_attr_with_order`
- Signature: `rebuild_enum_attr_with_order(node, attr, new_labels, preserve_value_by_label=True, stored_label=None, stored_value=None, verbose=True)`
- API names: `rebuild_enum_attr_with_order`
- Args:
  - `node`, required
  - `attr`, required
  - `new_labels`, required
  - `preserve_value_by_label`, default `True`
  - `stored_label`, default `None`
  - `stored_value`, default `None`
  - `verbose`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.apply_enum_data(...)`](#apidccmayaapply_enum_data) -> `maya_tools.Rigging.enum_attrs.apply_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:348](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:348)
  - same_module: [`api.dcc.maya.collect_enum_data(...)`](#apidccmayacollect_enum_data) -> `maya_tools.Rigging.enum_attrs.collect_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:86](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:86)
  - same_module: [`api.dcc.maya.disconnect_attr_connections(...)`](#apidccmayadisconnect_attr_connections) -> `maya_tools.Rigging.enum_attrs.disconnect_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:185](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:185)
  - same_module: [`api.dcc.maya.export_selected_enum_orders(...)`](#apidccmayaexport_selected_enum_orders) -> `maya_tools.Rigging.enum_attrs.export_selected_enum_orders` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:427](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:427)
  - same_module: [`api.dcc.maya.get_attr_connections(...)`](#apidccmayaget_attr_connections) -> `maya_tools.Rigging.enum_attrs.get_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:176](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:176)
- Description: Rebuild enum order on an existing attr while preserving connections. Notes ----- - This preserves raw connections by disconnecting and reconnecting them. - It remaps the attr's local current value by label when possible. - If stored_label is supplied, it will restore the saved enum selection by label. - It does NOT remap animated/int-driven upstream values by semantic label. If you need that too, this can be expanded later.
- Source: [enum_attrs.py:212](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:212)

### `api.dcc.maya.reconnect_attr_connections(...)`

- Target: `maya_tools.Rigging.enum_attrs.reconnect_attr_connections`
- Signature: `reconnect_attr_connections(plug, incoming, outgoing)`
- API names: `reconnect_attr_connections`
- Args:
  - `plug`, required
  - `incoming`, required
  - `outgoing`, required
- Related functions:
  - same_module: [`api.dcc.maya.disconnect_attr_connections(...)`](#apidccmayadisconnect_attr_connections) -> `maya_tools.Rigging.enum_attrs.disconnect_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:185](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:185)
  - same_module: [`api.dcc.maya.get_attr_connections(...)`](#apidccmayaget_attr_connections) -> `maya_tools.Rigging.enum_attrs.get_attr_connections` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:176](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:176)
  - same_module: [`api.dcc.maya.rebuild_enum_attr_with_order(...)`](#apidccmayarebuild_enum_attr_with_order) -> `maya_tools.Rigging.enum_attrs.rebuild_enum_attr_with_order` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:212](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:212)
- Source: [enum_attrs.py:198](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:198)

### `api.dcc.maya.remove_arm_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_arm_module`
- Signature: `remove_arm_module(side, body_joint_map)`
- API names: `remove_arm_module`
- Args:
  - `side`, required
  - `body_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
  - same_module: [`api.dcc.maya.remove_head_module(...)`](#apidccmayaremove_head_module) -> `maya_tools.Rigging.create_rig.remove_head_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6527](C:/depot/tools/maya_tools/Rigging/create_rig.py:6527)
- Description: Remove rig nodes and space switches for the given arm side. :param side: left or right side (l/r) :param body_joint_map: body joint mapping dictionary :return: int
- Source: [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)

### `api.dcc.maya.remove_brows_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_brows_module`
- Signature: `remove_brows_module(side, face_joint_map)`
- API names: `remove_brows_module`
- Args:
  - `side`, required
  - `face_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
  - same_module: [`api.dcc.maya.remove_head_module(...)`](#apidccmayaremove_head_module) -> `maya_tools.Rigging.create_rig.remove_head_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6527](C:/depot/tools/maya_tools/Rigging/create_rig.py:6527)
- Description: Removes all controls and constraints built for eyebrows. :param side: left or right side (l/r) :param face_joint_map: face joint mapping dictionary :return: int
- Source: [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)

### `api.dcc.maya.remove_clavicle_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_clavicle_module`
- Signature: `remove_clavicle_module(side, body_joint_map)`
- API names: `remove_clavicle_module`
- Args:
  - `side`, required
  - `body_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
  - same_module: [`api.dcc.maya.remove_head_module(...)`](#apidccmayaremove_head_module) -> `maya_tools.Rigging.create_rig.remove_head_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6527](C:/depot/tools/maya_tools/Rigging/create_rig.py:6527)
- Description: Removes the Clavicle control setup. :param side: left or right side (l/r) :param body_joint_map: body joint mapping dictionary :return: int
- Source: [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)

### `api.dcc.maya.remove_eyelids_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_eyelids_module`
- Signature: `remove_eyelids_module(side, face_joint_map)`
- API names: `remove_eyelids_module`
- Args:
  - `side`, required
  - `face_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
  - same_module: [`api.dcc.maya.remove_head_module(...)`](#apidccmayaremove_head_module) -> `maya_tools.Rigging.create_rig.remove_head_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6527](C:/depot/tools/maya_tools/Rigging/create_rig.py:6527)
- Description: Removes all controls and constraints built for eyelids. :param side: left or right side (l/r) :param face_joint_map: face joint mapping dictionary :return: int
- Source: [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)

### `api.dcc.maya.remove_eyes_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_eyes_module`
- Signature: `remove_eyes_module(face_joint_map)`
- API names: `remove_eyes_module`
- Args:
  - `face_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_head_module(...)`](#apidccmayaremove_head_module) -> `maya_tools.Rigging.create_rig.remove_head_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6527](C:/depot/tools/maya_tools/Rigging/create_rig.py:6527)
- Description: Removes all controls built for the eyes. :param face_joint_map: face joint mapping dictionary :return: int
- Source: [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)

### `api.dcc.maya.remove_file_open_callback(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.remove_file_open_callback`
- Signature: `remove_file_open_callback()`
- API names: `remove_file_open_callback`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.add_file_open_callback(...)`](#apidccmayaadd_file_open_callback) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.add_file_open_callback` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:10](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:10)
- Description: Removes all previously registered Maya scene callbacks.
- Source: [sequence_utils.py:21](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:21)

### `api.dcc.maya.remove_full_rig(...)`

- Target: `maya_tools.Rigging.create_rig.remove_full_rig`
- Signature: `remove_full_rig(body_joint_map, face_joint_map=None)`
- API names: `remove_full_rig`
- Args:
  - `body_joint_map`, required
  - `face_joint_map`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.create_full_rig(...)`](#apidccmayacreate_full_rig) -> `maya_tools.Rigging.create_rig.create_full_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3870](C:/depot/tools/maya_tools/Rigging/create_rig.py:3870)
  - same_module: [`api.dcc.maya.create_rig(...)`](#apidccmayacreate_rig) -> `maya_tools.Rigging.create_rig.create_rig_from_mapping` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4127](C:/depot/tools/maya_tools/Rigging/create_rig.py:4127)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.hik_map_to_rig_args(...)`](#apidccmayahik_map_to_rig_args) -> `maya_tools.Rigging.create_rig.hik_map_to_rig_args` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3478](C:/depot/tools/maya_tools/Rigging/create_rig.py:3478)
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
- Description: Removes all controls, rig nodes, and clears the Do_Not_Touch group. :param body_joint_map: body joint mapping dictionary :param face_joint_map: face joint mapping dictionary :return: None
- Source: [create_rig.py:4064](C:/depot/tools/maya_tools/Rigging/create_rig.py:4064)

### `api.dcc.maya.remove_head_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_head_module`
- Signature: `remove_head_module(body_joint_map)`
- API names: `remove_head_module`
- Args:
  - `body_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
- Description: Removes the head control setup. :param body_joint_map: body joint mapping dictionary :return: int
- Source: [create_rig.py:6527](C:/depot/tools/maya_tools/Rigging/create_rig.py:6527)

### `api.dcc.maya.remove_leg_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_leg_module`
- Signature: `remove_leg_module(side, body_joint_map)`
- API names: `remove_leg_module`
- Args:
  - `side`, required
  - `body_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
- Description: Remove rig nodes and RFL setups for the given leg side. :param side: left or right side (l/r) :param body_joint_map: body joint mapping dictionary :return: int
- Source: [create_rig.py:6217](C:/depot/tools/maya_tools/Rigging/create_rig.py:6217)

### `api.dcc.maya.remove_mouth_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_mouth_module`
- Signature: `remove_mouth_module(face_joint_map)`
- API names: `remove_mouth_module`
- Args:
  - `face_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
- Description: Removes all controls and constraints built for the mouth. :param face_joint_map: face joint mapping dictionary :return: int
- Source: [create_rig.py:4644](C:/depot/tools/maya_tools/Rigging/create_rig.py:4644)

### `api.dcc.maya.remove_neck_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_neck_module`
- Signature: `remove_neck_module(body_joint_map)`
- API names: `remove_neck_module`
- Args:
  - `body_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
- Description: Removes the neck control setup. :param body_joint_map: body joint mapping dictionary :return: int
- Source: [create_rig.py:6467](C:/depot/tools/maya_tools/Rigging/create_rig.py:6467)

### `api.dcc.maya.remove_other_face_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_other_face_module`
- Signature: `remove_other_face_module(face_joint_map)`
- API names: `remove_other_face_module`
- Args:
  - `face_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.rig_other_face_module(...)`](#apidccmayarig_other_face_module) -> `maya_tools.Rigging.create_rig.rig_other_face_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4868](C:/depot/tools/maya_tools/Rigging/create_rig.py:4868)
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
- Description: Removes all secondary controls built for other face joints. :param face_joint_map: face joint mapping dictionary :return: int
- Source: [create_rig.py:4975](C:/depot/tools/maya_tools/Rigging/create_rig.py:4975)

### `api.dcc.maya.remove_pelvis_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_pelvis_module`
- Signature: `remove_pelvis_module(body_joint_map)`
- API names: `remove_pelvis_module`
- Args:
  - `body_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
- Description: Removes the pelvis and hipswing control setup. :param body_joint_map: body joint mapping dictionary :return: int
- Source: [create_rig.py:6329](C:/depot/tools/maya_tools/Rigging/create_rig.py:6329)

### `api.dcc.maya.remove_root_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_root_module`
- Signature: `remove_root_module(body_joint_map)`
- API names: `remove_root_module`
- Args:
  - `body_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
- Description: Removes the root origin control setup. :param body_joint_map: body joint mapping dictionary :return: int
- Source: [create_rig.py:6274](C:/depot/tools/maya_tools/Rigging/create_rig.py:6274)

### `api.dcc.maya.remove_save_callback(...)`

- Target: `maya_tools.maya_menu.remove_save_callback`
- Signature: `remove_save_callback()`
- API names: `remove_save_callback`
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.on_before_save(...)`](#apidccmayaon_before_save) -> `maya_tools.maya_menu.on_before_save` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:328](C:/depot/tools/maya_tools/maya_menu.py:328)
  - same_module: [`api.dcc.maya.save_port_to_file(...)`](#apidccmayasave_port_to_file) -> `maya_tools.maya_menu.save_port_to_file` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:216](C:/depot/tools/maya_tools/maya_menu.py:216)
  - same_module: [`api.dcc.maya.save_session_to_file(...)`](#apidccmayasave_session_to_file) -> `maya_tools.maya_menu.save_session_to_file` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:185](C:/depot/tools/maya_tools/maya_menu.py:185)
- Source: [maya_menu.py:346](C:/depot/tools/maya_tools/maya_menu.py:346)

### `api.dcc.maya.remove_spine_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_spine_module`
- Signature: `remove_spine_module(body_joint_map)`
- API names: `remove_spine_module`
- Args:
  - `body_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
- Description: Removes the spine control setup. :param body_joint_map: body joint mapping dictionary :return: int
- Source: [create_rig.py:6385](C:/depot/tools/maya_tools/Rigging/create_rig.py:6385)

### `api.dcc.maya.remove_teeth_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_teeth_module`
- Signature: `remove_teeth_module(face_joint_map)`
- API names: `remove_teeth_module`
- Args:
  - `face_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
- Description: Removes all controls built for the teeth. :param face_joint_map: face joint mapping dictionary :return: int
- Source: [create_rig.py:4848](C:/depot/tools/maya_tools/Rigging/create_rig.py:4848)

### `api.dcc.maya.remove_tongue_module(...)`

- Target: `maya_tools.Rigging.create_rig.remove_tongue_module`
- Signature: `remove_tongue_module(face_joint_map)`
- API names: `remove_tongue_module`
- Args:
  - `face_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
- Description: Removes all controls built for the tongue. :param face_joint_map: face joint mapping dictionary :return: int
- Source: [create_rig.py:4794](C:/depot/tools/maya_tools/Rigging/create_rig.py:4794)

### `api.dcc.maya.rename_brow_pad_hierarchies(...)`

- Target: `maya_tools.Rigging.create_rig.rename_brow_pad_hierarchies`
- Signature: `rename_brow_pad_hierarchies(side)`
- API names: `rename_brow_pad_hierarchies`
- Args:
  - `side`, required
- Related functions:
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.offset_pv_pad(...)`](#apidccmayaoffset_pv_pad) -> `maya_tools.Rigging.create_rig.offset_pv_pad` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1178](C:/depot/tools/maya_tools/Rigging/create_rig.py:1178)
  - same_module: [`api.dcc.maya.orient_control_pad_to_world_safely(...)`](#apidccmayaorient_control_pad_to_world_safely) -> `maya_tools.Rigging.create_rig.orient_control_pad_to_world_safely` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:885](C:/depot/tools/maya_tools/Rigging/create_rig.py:885)
  - same_module: [`api.dcc.maya.strip_ctrl_shape_and_rename(...)`](#apidccmayastrip_ctrl_shape_and_rename) -> `maya_tools.Rigging.create_rig.strip_ctrl_shape_and_rename` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3101](C:/depot/tools/maya_tools/Rigging/create_rig.py:3101)
- Description: Rename these hierarchies for the given side: 1. side_browX_ctrl_pad -> side_browX_driver_pad and rename entire hierarchy ctrl -> driver 2. side_browX_main_ctrl_pad -> side_browX_ctrl_pad and rename entire hierarchy main_ctrl -> ctrl Also deletes shapes on nodes renamed to 'driver'. Args: side (str): 'l' or 'r' Returns: dict: { "ctrl_to_driver": {pad_name: rename_map, ...}, "main_ctrl_to_ctrl": {pad_name: rename_map, ...} } :param side: side :return: result
- Source: [create_rig.py:3745](C:/depot/tools/maya_tools/Rigging/create_rig.py:3745)

### `api.dcc.maya.resolve_rfl_joints(...)`

- Target: `maya_tools.Rigging.create_rig.resolve_rfl_joints`
- Signature: `resolve_rfl_joints(side)`
- API names: `resolve_rfl_joints`
- Args:
  - `side`, required
- Related functions:
  - same_module: [`api.dcc.maya.create_rfl_joints_template(...)`](#apidccmayacreate_rfl_joints_template) -> `maya_tools.Rigging.create_rig.create_rfl_joints_template` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)
  - same_module: [`api.dcc.maya.preserve_rfl_pivot_joints(...)`](#apidccmayapreserve_rfl_pivot_joints) -> `maya_tools.Rigging.create_rig.preserve_rfl_pivot_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5511](C:/depot/tools/maya_tools/Rigging/create_rig.py:5511)
  - same_module: [`api.dcc.maya.build_rfl_ik_and_constraints(...)`](#apidccmayabuild_rfl_ik_and_constraints) -> `maya_tools.Rigging.create_rig.build_rfl_ik_and_constraints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:779](C:/depot/tools/maya_tools/Rigging/create_rig.py:779)
  - same_module: [`api.dcc.maya.create_loft_surface_with_follicle_joints(...)`](#apidccmayacreate_loft_surface_with_follicle_joints) -> `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)
  - same_module: [`api.dcc.maya.create_surface_from_joints_original(...)`](#apidccmayacreate_surface_from_joints_original) -> `maya_tools.Rigging.create_rig.create_surface_from_joints_original` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1217](C:/depot/tools/maya_tools/Rigging/create_rig.py:1217)
- Description: Resolve an existing reverse-foot hierarchy. Supports both the newer toe pivot name and older/manual ball pivot name: <side>_toe_RFL <side>_ball_RFL Returns joints in the order expected by build_rfl_ik_and_constraints: heel, outerBank, innerBank, toeTip, toe/ball, ankle Returns [] when a complete setup cannot be found. :param side: side :return: result
- Source: [create_rig.py:5891](C:/depot/tools/maya_tools/Rigging/create_rig.py:5891)

### `api.dcc.maya.resolve_shoulder_profile(...)`

- Target: `maya_tools.Rigging.auto_skinner.resolve_shoulder_profile`
- Signature: `resolve_shoulder_profile(`
- API names: `resolve_shoulder_profile`
- Args:
  - `shoulder_profile` (Optional[object]), required
  - `joints` (Sequence[str]), required
- Related functions:
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.build_default_shoulder_profile(...)`](#apidccmayabuild_default_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.build_default_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:164](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:164)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_selected(...)`](#apidccmayalearn_shoulder_profile_from_selected) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:277](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:277)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_skin(...)`](#apidccmayalearn_shoulder_profile_from_skin) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:228](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:228)
- Source: [auto_skinner.py:359](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:359)

### `api.dcc.maya.resolve_space_target(...)`

- Target: `maya_tools.Rigging.enum_attrs.resolve_space_target`
- Signature: `resolve_space_target(label, node=None, side=None)`
- API names: `resolve_space_target`
- Args:
  - `label`, required
  - `node`, default `None`
  - `side`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.resolve_space_targets_from_labels(...)`](#apidccmayaresolve_space_targets_from_labels) -> `maya_tools.Rigging.enum_attrs.resolve_space_targets_from_labels` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:46](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:46)
- Source: [enum_attrs.py:32](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:32)

### `api.dcc.maya.resolve_space_targets_from_labels(...)`

- Target: `maya_tools.Rigging.enum_attrs.resolve_space_targets_from_labels`
- Signature: `resolve_space_targets_from_labels(labels, node=None, side=None, require_existing=True)`
- API names: `resolve_space_targets_from_labels`
- Args:
  - `labels`, required
  - `node`, default `None`
  - `side`, default `None`
  - `require_existing`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.resolve_space_target(...)`](#apidccmayaresolve_space_target) -> `maya_tools.Rigging.enum_attrs.resolve_space_target` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:32](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:32)
  - same_module: [`api.dcc.maya.get_enum_labels(...)`](#apidccmayaget_enum_labels) -> `maya_tools.Rigging.enum_attrs.get_enum_labels` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:66](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:66)
  - same_module: [`api.dcc.maya.get_side_from_node(...)`](#apidccmayaget_side_from_node) -> `maya_tools.Rigging.enum_attrs.get_side_from_node` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:23](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:23)
  - same_module: [`api.dcc.maya.load_enum_data_from_json(...)`](#apidccmayaload_enum_data_from_json) -> `maya_tools.Rigging.enum_attrs.load_enum_data_from_json` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:168](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:168)
- Source: [enum_attrs.py:46](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:46)

### `api.dcc.maya.restore_all_control_cv_positions(...)`

- Target: `maya_tools.Rigging.create_rig.restore_all_control_cv_positions`
- Signature: `restore_all_control_cv_positions(store_node=MODULE_STORE_NODE)`
- API names: `restore_all_control_cv_positions`
- Args:
  - `store_node`, default `MODULE_STORE_NODE`
- Related functions:
  - same_module: [`api.dcc.maya.store_all_control_cv_positions(...)`](#apidccmayastore_all_control_cv_positions) -> `maya_tools.Rigging.create_rig.store_all_control_cv_positions` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2525](C:/depot/tools/maya_tools/Rigging/create_rig.py:2525)
  - same_module: [`api.dcc.maya.get_all_module_metadata(...)`](#apidccmayaget_all_module_metadata) -> `maya_tools.Rigging.create_rig.get_all_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6594](C:/depot/tools/maya_tools/Rigging/create_rig.py:6594)
  - same_module: [`api.dcc.maya.orient_control_pad_to_world_safely(...)`](#apidccmayaorient_control_pad_to_world_safely) -> `maya_tools.Rigging.create_rig.orient_control_pad_to_world_safely` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:885](C:/depot/tools/maya_tools/Rigging/create_rig.py:885)
  - same_module: [`api.dcc.maya.rebuild_all_space_switches(...)`](#apidccmayarebuild_all_space_switches) -> `maya_tools.Rigging.create_rig.rebuild_all_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6699](C:/depot/tools/maya_tools/Rigging/create_rig.py:6699)
  - same_module: [`api.dcc.maya.restore_rig_connections(...)`](#apidccmayarestore_rig_connections) -> `maya_tools.Rigging.create_rig.restore_rig_connections` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6777](C:/depot/tools/maya_tools/Rigging/create_rig.py:6777)
- Description: Restore all control cv positions. :param store_node: store node :return: result
- Source: [create_rig.py:2551](C:/depot/tools/maya_tools/Rigging/create_rig.py:2551)

### `api.dcc.maya.restore_rig_connections(...)`

- Target: `maya_tools.Rigging.create_rig.restore_rig_connections`
- Signature: `restore_rig_connections(module_name)`
- API names: `restore_rig_connections`
- Args:
  - `module_name`, required
- Related functions:
  - same_module: [`api.dcc.maya.store_rig_connections(...)`](#apidccmayastore_rig_connections) -> `maya_tools.Rigging.create_rig.store_rig_connections` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6624](C:/depot/tools/maya_tools/Rigging/create_rig.py:6624)
  - same_module: [`api.dcc.maya.create_full_rig(...)`](#apidccmayacreate_full_rig) -> `maya_tools.Rigging.create_rig.create_full_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3870](C:/depot/tools/maya_tools/Rigging/create_rig.py:3870)
  - same_module: [`api.dcc.maya.create_rig(...)`](#apidccmayacreate_rig) -> `maya_tools.Rigging.create_rig.create_rig_from_mapping` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4127](C:/depot/tools/maya_tools/Rigging/create_rig.py:4127)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.hik_map_to_rig_args(...)`](#apidccmayahik_map_to_rig_args) -> `maya_tools.Rigging.create_rig.hik_map_to_rig_args` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3478](C:/depot/tools/maya_tools/Rigging/create_rig.py:3478)
- Description: Restores space switches, constraints, and output connections stored for module_name. :param module_name: name of the module :return: int
- Source: [create_rig.py:6777](C:/depot/tools/maya_tools/Rigging/create_rig.py:6777)

### `api.dcc.maya.rig_arm_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_arm_module`
- Signature: `rig_arm_module(side, body_joint_map, parent_ctrl=None)`
- API names: `rig_arm_module`
- Args:
  - `side`, required
  - `body_joint_map`, required
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
  - same_module: [`api.dcc.maya.rig_eyes_module(...)`](#apidccmayarig_eyes_module) -> `maya_tools.Rigging.create_rig.rig_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4714](C:/depot/tools/maya_tools/Rigging/create_rig.py:4714)
- Description: Rigs the Arm (IK/FK limb, Fingers, and Twist surface rigs). :param side: left or right side (l/r) :param body_joint_map: body joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)

### `api.dcc.maya.rig_brows_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_brows_module`
- Signature: `rig_brows_module(side, face_joint_map, parent_ctrl=None)`
- API names: `rig_brows_module`
- Args:
  - `side`, required
  - `face_joint_map`, required
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_brows_module(...)`](#apidccmayaremove_brows_module) -> `maya_tools.Rigging.create_rig.remove_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4382](C:/depot/tools/maya_tools/Rigging/create_rig.py:4382)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
  - same_module: [`api.dcc.maya.rig_eyes_module(...)`](#apidccmayarig_eyes_module) -> `maya_tools.Rigging.create_rig.rig_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4714](C:/depot/tools/maya_tools/Rigging/create_rig.py:4714)
- Description: Builds the eyebrows setup with lofted surfaces and driver controls. :param side: left or right side (l/r) :param face_joint_map: face joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)

### `api.dcc.maya.rig_clavicle_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_clavicle_module`
- Signature: `rig_clavicle_module(side, body_joint_map, parent_ctrl=None)`
- API names: `rig_clavicle_module`
- Args:
  - `side`, required
  - `body_joint_map`, required
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_clavicle_module(...)`](#apidccmayaremove_clavicle_module) -> `maya_tools.Rigging.create_rig.remove_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6908](C:/depot/tools/maya_tools/Rigging/create_rig.py:6908)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
  - same_module: [`api.dcc.maya.rig_eyes_module(...)`](#apidccmayarig_eyes_module) -> `maya_tools.Rigging.create_rig.rig_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4714](C:/depot/tools/maya_tools/Rigging/create_rig.py:4714)
- Description: Builds the Clavicle control setup. :param side: left or right side (l/r) :param body_joint_map: body joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)

### `api.dcc.maya.rig_eyelids_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_eyelids_module`
- Signature: `rig_eyelids_module(side, face_joint_map, parent_ctrl=None)`
- API names: `rig_eyelids_module`
- Args:
  - `side`, required
  - `face_joint_map`, required
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_eyelids_module(...)`](#apidccmayaremove_eyelids_module) -> `maya_tools.Rigging.create_rig.remove_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4532](C:/depot/tools/maya_tools/Rigging/create_rig.py:4532)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyes_module(...)`](#apidccmayarig_eyes_module) -> `maya_tools.Rigging.create_rig.rig_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4714](C:/depot/tools/maya_tools/Rigging/create_rig.py:4714)
- Description: Builds the eyelids setup with lofted surfaces and driver controls. :param side: left or right side (l/r) :param face_joint_map: face joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)

### `api.dcc.maya.rig_eyes_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_eyes_module`
- Signature: `rig_eyes_module(face_joint_map, parent_ctrl=None)`
- API names: `rig_eyes_module`
- Args:
  - `face_joint_map`, required
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_eyes_module(...)`](#apidccmayaremove_eyes_module) -> `maya_tools.Rigging.create_rig.remove_eyes_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4740](C:/depot/tools/maya_tools/Rigging/create_rig.py:4740)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Builds the eye aim control setup. :param face_joint_map: face joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:4714](C:/depot/tools/maya_tools/Rigging/create_rig.py:4714)

### `api.dcc.maya.rig_head_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_head_module`
- Signature: `rig_head_module(body_joint_map, face_joint_map=None, parent_ctrl=None)`
- API names: `rig_head_module`
- Args:
  - `body_joint_map`, required
  - `face_joint_map`, default `None`
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_head_module(...)`](#apidccmayaremove_head_module) -> `maya_tools.Rigging.create_rig.remove_head_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6527](C:/depot/tools/maya_tools/Rigging/create_rig.py:6527)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Builds the head control setup and space switches. :param body_joint_map: body joint mapping dictionary :param face_joint_map: face joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:6487](C:/depot/tools/maya_tools/Rigging/create_rig.py:6487)

### `api.dcc.maya.rig_leg_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_leg_module`
- Signature: `rig_leg_module(side, body_joint_map, parent_ctrl=None)`
- API names: `rig_leg_module`
- Args:
  - `side`, required
  - `body_joint_map`, required
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_leg_module(...)`](#apidccmayaremove_leg_module) -> `maya_tools.Rigging.create_rig.remove_leg_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6217](C:/depot/tools/maya_tools/Rigging/create_rig.py:6217)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Rigs the Leg (IK/FK limb, Twist surface rigs, foot roll RFL, and switches). :param side: left or right side (l/r) :param body_joint_map: body joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:5998](C:/depot/tools/maya_tools/Rigging/create_rig.py:5998)

### `api.dcc.maya.rig_mouth_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_mouth_module`
- Signature: `rig_mouth_module(face_joint_map, parent_ctrl=None, jaw_ctrl=None)`
- API names: `rig_mouth_module`
- Args:
  - `face_joint_map`, required
  - `parent_ctrl`, default `None`
  - `jaw_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_mouth_module(...)`](#apidccmayaremove_mouth_module) -> `maya_tools.Rigging.create_rig.remove_mouth_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4644](C:/depot/tools/maya_tools/Rigging/create_rig.py:4644)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Builds the mouth setup with lofted surfaces, follicle controls, and jaw drivers. :param face_joint_map: face joint mapping dictionary :param parent_ctrl: parent control node name :param jaw_ctrl: jaw control node name :return: None
- Source: [create_rig.py:4584](C:/depot/tools/maya_tools/Rigging/create_rig.py:4584)

### `api.dcc.maya.rig_neck_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_neck_module`
- Signature: `rig_neck_module(body_joint_map, parent_ctrl=None)`
- API names: `rig_neck_module`
- Args:
  - `body_joint_map`, required
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_neck_module(...)`](#apidccmayaremove_neck_module) -> `maya_tools.Rigging.create_rig.remove_neck_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6467](C:/depot/tools/maya_tools/Rigging/create_rig.py:6467)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Builds the neck control setup and space switches. :param body_joint_map: body joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:6405](C:/depot/tools/maya_tools/Rigging/create_rig.py:6405)

### `api.dcc.maya.rig_other_face_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_other_face_module`
- Signature: `rig_other_face_module(face_joint_map, parent_ctrl=None, jaw_ctrl=None, jaw_joint=None)`
- API names: `rig_other_face_module`
- Args:
  - `face_joint_map`, required
  - `parent_ctrl`, default `None`
  - `jaw_ctrl`, default `None`
  - `jaw_joint`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_other_face_module(...)`](#apidccmayaremove_other_face_module) -> `maya_tools.Rigging.create_rig.remove_other_face_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4975](C:/depot/tools/maya_tools/Rigging/create_rig.py:4975)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Rig other face module. :param face_joint_map: mapping for face joint map :param parent_ctrl: parent ctrl :param jaw_ctrl: jaw ctrl :param jaw_joint: jaw joint :return:
- Source: [create_rig.py:4868](C:/depot/tools/maya_tools/Rigging/create_rig.py:4868)

### `api.dcc.maya.rig_pelvis_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_pelvis_module`
- Signature: `rig_pelvis_module(body_joint_map, parent_ctrl=None)`
- API names: `rig_pelvis_module`
- Args:
  - `body_joint_map`, required
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_pelvis_module(...)`](#apidccmayaremove_pelvis_module) -> `maya_tools.Rigging.create_rig.remove_pelvis_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6329](C:/depot/tools/maya_tools/Rigging/create_rig.py:6329)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Builds the pelvis and hipswing control setup. :param body_joint_map: body joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:6286](C:/depot/tools/maya_tools/Rigging/create_rig.py:6286)

### `api.dcc.maya.rig_root_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_root_module`
- Signature: `rig_root_module(body_joint_map)`
- API names: `rig_root_module`
- Args:
  - `body_joint_map`, required
- Related functions:
  - same_module: [`api.dcc.maya.remove_root_module(...)`](#apidccmayaremove_root_module) -> `maya_tools.Rigging.create_rig.remove_root_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6274](C:/depot/tools/maya_tools/Rigging/create_rig.py:6274)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Builds the root origin control setup. :param body_joint_map: body joint mapping dictionary :return: None
- Source: [create_rig.py:6252](C:/depot/tools/maya_tools/Rigging/create_rig.py:6252)

### `api.dcc.maya.rig_spine_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_spine_module`
- Signature: `rig_spine_module(body_joint_map, parent_ctrl=None)`
- API names: `rig_spine_module`
- Args:
  - `body_joint_map`, required
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_spine_module(...)`](#apidccmayaremove_spine_module) -> `maya_tools.Rigging.create_rig.remove_spine_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6385](C:/depot/tools/maya_tools/Rigging/create_rig.py:6385)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Builds the spine control setup. :param body_joint_map: body joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:6348](C:/depot/tools/maya_tools/Rigging/create_rig.py:6348)

### `api.dcc.maya.rig_teeth_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_teeth_module`
- Signature: `rig_teeth_module(face_joint_map, parent_ctrl=None, jaw_ctrl=None)`
- API names: `rig_teeth_module`
- Args:
  - `face_joint_map`, required
  - `parent_ctrl`, default `None`
  - `jaw_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_teeth_module(...)`](#apidccmayaremove_teeth_module) -> `maya_tools.Rigging.create_rig.remove_teeth_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4848](C:/depot/tools/maya_tools/Rigging/create_rig.py:4848)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Builds the upper and lower teeth controls setup. :param face_joint_map: face joint mapping dictionary :param parent_ctrl: parent control node name :param jaw_ctrl: jaw control node name :return: None
- Source: [create_rig.py:4813](C:/depot/tools/maya_tools/Rigging/create_rig.py:4813)

### `api.dcc.maya.rig_tongue_module(...)`

- Target: `maya_tools.Rigging.create_rig.rig_tongue_module`
- Signature: `rig_tongue_module(face_joint_map, parent_ctrl=None)`
- API names: `rig_tongue_module`
- Args:
  - `face_joint_map`, required
  - `parent_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.remove_tongue_module(...)`](#apidccmayaremove_tongue_module) -> `maya_tools.Rigging.create_rig.remove_tongue_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4794](C:/depot/tools/maya_tools/Rigging/create_rig.py:4794)
  - same_module: [`api.dcc.maya.rig_arm_module(...)`](#apidccmayarig_arm_module) -> `maya_tools.Rigging.create_rig.rig_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4991](C:/depot/tools/maya_tools/Rigging/create_rig.py:4991)
  - same_module: [`api.dcc.maya.rig_brows_module(...)`](#apidccmayarig_brows_module) -> `maya_tools.Rigging.create_rig.rig_brows_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4346](C:/depot/tools/maya_tools/Rigging/create_rig.py:4346)
  - same_module: [`api.dcc.maya.rig_clavicle_module(...)`](#apidccmayarig_clavicle_module) -> `maya_tools.Rigging.create_rig.rig_clavicle_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6865](C:/depot/tools/maya_tools/Rigging/create_rig.py:6865)
  - same_module: [`api.dcc.maya.rig_eyelids_module(...)`](#apidccmayarig_eyelids_module) -> `maya_tools.Rigging.create_rig.rig_eyelids_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4409](C:/depot/tools/maya_tools/Rigging/create_rig.py:4409)
- Description: Builds the tongue controls setup. :param face_joint_map: face joint mapping dictionary :param parent_ctrl: parent control node name :return: None
- Source: [create_rig.py:4765](C:/depot/tools/maya_tools/Rigging/create_rig.py:4765)

### `api.dcc.maya.run_export(...)`

- Target: `maya_tools.Animation.anim_export.anim_export_command.run_export`
- Signature: `run_export(cmd, maya_env, export_path)`
- API names: `run_export`
- Args:
  - `cmd`, required
  - `maya_env`, required
  - `export_path`, required
- Related functions:
  - same_module: [`api.dcc.maya.export_animation_async(...)`](#apidccmayaexport_animation_async) -> `maya_tools.Animation.anim_export.anim_export_command.export_animation_async` - Shares module and name terms; may be useful in the same workflow.; source [anim_export_command.py:88](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_command.py:88)
  - same_module: [`api.dcc.maya.export_animation_to_fbx(...)`](#apidccmayaexport_animation_to_fbx) -> `maya_tools.Animation.anim_export.anim_export_command.export_animation_to_fbx` - Shares module and name terms; may be useful in the same workflow.; source [anim_export_command.py:8](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_command.py:8)
- Description: exports using subprocess to keep maya scene unchanged / non-destructive :param cmd: subprocess command string for export :param maya_env: maya env settings from os.environ.copy() :param export_path: actual fbx export location :return:
- Source: [anim_export_command.py:62](C:/depot/tools/maya_tools/Animation/anim_export/anim_export_command.py:62)

### `api.dcc.maya.run_geodesic_voxel_bind(...)`

- Target: `maya_tools.Rigging.auto_skinner.run_geodesic_voxel_bind`
- Signature: `run_geodesic_voxel_bind(`
- API names: `run_geodesic_voxel_bind`
- Args:
  - `skin_cluster` (str), required
  - `max_influences` (int), default `DEFAULT_MAX_INFLUENCES`
  - `falloff` (float), default `0.0`
  - `voxel_resolution` (int), default `256`
  - `validate_voxels` (bool), default `True`
- Related functions:
  - same_module: [`api.dcc.maya.bind_mesh(...)`](#apidccmayabind_mesh) -> `maya_tools.Rigging.auto_skinner.bind_mesh` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:375](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:375)
- Source: [auto_skinner.py:409](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:409)

### `api.dcc.maya.safe_constrain_two_parents(...)`

- Target: `maya_tools.Rigging.create_rig.safe_constrain_two_parents`
- Signature: `safe_constrain_two_parents(controls, parent1, parent2, **kwargs)`
- API names: `safe_constrain_two_parents`
- Args:
  - `controls`, required
  - `parent1`, required
  - `parent2`, required
  - `**kwargs`, required
- Related functions:
  - same_module: [`api.dcc.maya.constrain_controls_to_two_parents(...)`](#apidccmayaconstrain_controls_to_two_parents) -> `maya_tools.Rigging.create_rig.constrain_controls_to_two_parents` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1868](C:/depot/tools/maya_tools/Rigging/create_rig.py:1868)
- Description: Safe constrain two parents. :param controls: list of controls :param parent1: parent1 :param parent2: parent2 :param kwargs: list of kwargs :return:
- Source: [create_rig.py:3853](C:/depot/tools/maya_tools/Rigging/create_rig.py:3853)

### `api.dcc.maya.save_enum_data_to_json(...)`

- Target: `maya_tools.Rigging.enum_attrs.save_enum_data_to_json`
- Signature: `save_enum_data_to_json(filepath, nodes=None, attr_filter=None, strip_namespaces=True)`
- API names: `save_enum_data_to_json`
- Args:
  - `filepath`, required
  - `nodes`, default `None`
  - `attr_filter`, default `None`
  - `strip_namespaces`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.load_enum_data_from_json(...)`](#apidccmayaload_enum_data_from_json) -> `maya_tools.Rigging.enum_attrs.load_enum_data_from_json` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:168](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:168)
  - same_module: [`api.dcc.maya.apply_enum_data(...)`](#apidccmayaapply_enum_data) -> `maya_tools.Rigging.enum_attrs.apply_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:348](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:348)
  - same_module: [`api.dcc.maya.collect_enum_data(...)`](#apidccmayacollect_enum_data) -> `maya_tools.Rigging.enum_attrs.collect_enum_data` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:86](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:86)
  - same_module: [`api.dcc.maya.export_selected_enum_orders(...)`](#apidccmayaexport_selected_enum_orders) -> `maya_tools.Rigging.enum_attrs.export_selected_enum_orders` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:427](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:427)
  - same_module: [`api.dcc.maya.get_enum_attrs(...)`](#apidccmayaget_enum_attrs) -> `maya_tools.Rigging.enum_attrs.get_enum_attrs` - Shares module and name terms; may be useful in the same workflow.; source [enum_attrs.py:73](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:73)
- Source: [enum_attrs.py:150](C:/depot/tools/maya_tools/Rigging/enum_attrs.py:150)

### `api.dcc.maya.save_module_metadata(...)`

- Target: `maya_tools.Rigging.create_rig.save_module_metadata`
- Signature: `save_module_metadata(module_id, data_dict)`
- API names: `save_module_metadata`
- Args:
  - `module_id`, required
  - `data_dict`, required
- Related functions:
  - same_module: [`api.dcc.maya.clear_module_metadata(...)`](#apidccmayaclear_module_metadata) -> `maya_tools.Rigging.create_rig.clear_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6613](C:/depot/tools/maya_tools/Rigging/create_rig.py:6613)
  - same_module: [`api.dcc.maya.get_all_module_metadata(...)`](#apidccmayaget_all_module_metadata) -> `maya_tools.Rigging.create_rig.get_all_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6594](C:/depot/tools/maya_tools/Rigging/create_rig.py:6594)
  - same_module: [`api.dcc.maya.load_module_metadata(...)`](#apidccmayaload_module_metadata) -> `maya_tools.Rigging.create_rig.load_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6575](C:/depot/tools/maya_tools/Rigging/create_rig.py:6575)
  - same_module: [`api.dcc.maya.get_module_controls(...)`](#apidccmayaget_module_controls) -> `maya_tools.Rigging.create_rig.get_module_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5820](C:/depot/tools/maya_tools/Rigging/create_rig.py:5820)
  - same_module: [`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module) -> `maya_tools.Rigging.create_rig.remove_arm_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5857](C:/depot/tools/maya_tools/Rigging/create_rig.py:5857)
- Description: Persist data_dict for module_id on the scene-level store node. :param module_id: unique module identifier :param data_dict: dictionary containing module properties :return: None
- Source: [create_rig.py:6549](C:/depot/tools/maya_tools/Rigging/create_rig.py:6549)

### `api.dcc.maya.save_port_to_file(...)`

- Target: `maya_tools.maya_menu.save_port_to_file`
- Signature: `save_port_to_file(port)`
- API names: `save_port_to_file`
- Args:
  - `port`, required
- Related functions:
  - same_module: [`api.dcc.maya.save_session_to_file(...)`](#apidccmayasave_session_to_file) -> `maya_tools.maya_menu.save_session_to_file` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:185](C:/depot/tools/maya_tools/maya_menu.py:185)
  - same_module: [`api.dcc.maya.apply_command_port_python3_patches(...)`](#apidccmayaapply_command_port_python3_patches) -> `maya_tools.maya_menu.apply_command_port_python3_patches` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:67](C:/depot/tools/maya_tools/maya_menu.py:67)
  - same_module: [`api.dcc.maya.cleanup_command_port_files(...)`](#apidccmayacleanup_command_port_files) -> `maya_tools.maya_menu.cleanup_command_port_files` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:196](C:/depot/tools/maya_tools/maya_menu.py:196)
  - same_module: [`api.dcc.maya.create_command_port(...)`](#apidccmayacreate_command_port) -> `maya_tools.maya_menu.create_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:287](C:/depot/tools/maya_tools/maya_menu.py:287)
  - same_module: [`api.dcc.maya.get_command_port(...)`](#apidccmayaget_command_port) -> `maya_tools.maya_menu.get_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:232](C:/depot/tools/maya_tools/maya_menu.py:232)
- Source: [maya_menu.py:216](C:/depot/tools/maya_tools/maya_menu.py:216)

### `api.dcc.maya.save_session_to_file(...)`

- Target: `maya_tools.maya_menu.save_session_to_file`
- Signature: `save_session_to_file(port)`
- API names: `save_session_to_file`
- Args:
  - `port`, required
- Related functions:
  - same_module: [`api.dcc.maya.save_port_to_file(...)`](#apidccmayasave_port_to_file) -> `maya_tools.maya_menu.save_port_to_file` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:216](C:/depot/tools/maya_tools/maya_menu.py:216)
  - same_module: [`api.dcc.maya.on_before_save(...)`](#apidccmayaon_before_save) -> `maya_tools.maya_menu.on_before_save` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:328](C:/depot/tools/maya_tools/maya_menu.py:328)
  - same_module: [`api.dcc.maya.remove_save_callback(...)`](#apidccmayaremove_save_callback) -> `maya_tools.maya_menu.remove_save_callback` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:346](C:/depot/tools/maya_tools/maya_menu.py:346)
- Source: [maya_menu.py:185](C:/depot/tools/maya_tools/maya_menu.py:185)

### `api.dcc.maya.save_shoulder_profile(...)`

- Target: `maya_tools.Rigging.auto_skinner.save_shoulder_profile`
- Signature: `save_shoulder_profile(profile: dict, path: str) -> str`
- API names: `save_shoulder_profile`
- Args:
  - `profile` (dict), required
  - `path` (str), required
- Related functions:
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.build_default_shoulder_profile(...)`](#apidccmayabuild_default_shoulder_profile) -> `maya_tools.Rigging.auto_skinner.build_default_shoulder_profile` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:164](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:164)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_selected(...)`](#apidccmayalearn_shoulder_profile_from_selected) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:277](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:277)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_skin(...)`](#apidccmayalearn_shoulder_profile_from_skin) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:228](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:228)
- Source: [auto_skinner.py:204](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:204)

### `api.dcc.maya.scale_ctrl_cvs_local(...)`

- Target: `maya_tools.Rigging.create_rig.scale_ctrl_cvs_local`
- Signature: `scale_ctrl_cvs_local(ctrl, scale=(1.0, 1.0, 1.0))`
- API names: `scale_ctrl_cvs_local`
- Args:
  - `ctrl`, required
  - `scale`, default `(1.0, 1.0, 1.0)`
- Related functions:
  - same_module: [`api.dcc.maya.get_ctrl_shape_cvs(...)`](#apidccmayaget_ctrl_shape_cvs) -> `maya_tools.Rigging.create_rig.get_ctrl_shape_cvs` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2501](C:/depot/tools/maya_tools/Rigging/create_rig.py:2501)
  - same_module: [`api.dcc.maya.scale_ctrl_to_region(...)`](#apidccmayascale_ctrl_to_region) -> `maya_tools.Rigging.create_rig.scale_ctrl_to_region` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1149](C:/depot/tools/maya_tools/Rigging/create_rig.py:1149)
  - same_module: [`api.dcc.maya.snap_ctrl_cvs_to_child(...)`](#apidccmayasnap_ctrl_cvs_to_child) -> `maya_tools.Rigging.create_rig.snap_ctrl_cvs_to_child` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:134](C:/depot/tools/maya_tools/Rigging/create_rig.py:134)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
- Description: Scales CVs of a NURBS curve or surface relative to the control's local space. :param ctrl: transform of the control :param scale: (sx, sy, sz) local scale multiplier :return:
- Source: [create_rig.py:1091](C:/depot/tools/maya_tools/Rigging/create_rig.py:1091)

### `api.dcc.maya.scale_ctrl_to_region(...)`

- Target: `maya_tools.Rigging.create_rig.scale_ctrl_to_region`
- Signature: `scale_ctrl_to_region(`
- API names: `scale_ctrl_to_region`
- Args:
  - `ctrl`, required
  - `region_joints`, required
  - `base_size`, default `1.0`
  - `multiplier`, default `1.0`
- Related functions:
  - same_module: [`api.dcc.maya.scale_ctrl_cvs_local(...)`](#apidccmayascale_ctrl_cvs_local) -> `maya_tools.Rigging.create_rig.scale_ctrl_cvs_local` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1091](C:/depot/tools/maya_tools/Rigging/create_rig.py:1091)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
  - same_module: [`api.dcc.maya.create_diamond_ctrl(...)`](#apidccmayacreate_diamond_ctrl) -> `maya_tools.Rigging.create_rig.create_diamond_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:35](C:/depot/tools/maya_tools/Rigging/create_rig.py:35)
  - same_module: [`api.dcc.maya.create_prism_ctrl(...)`](#apidccmayacreate_prism_ctrl) -> `maya_tools.Rigging.create_rig.create_prism_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:66](C:/depot/tools/maya_tools/Rigging/create_rig.py:66)
- Description: Scales control CVs based on the size of a joint region. :param ctrl: ctrl to scale :param region_joints: list of joints :param base_size: reference size (tweak once per rig) :param multiplier: artistic tuning knob :return:
- Source: [create_rig.py:1149](C:/depot/tools/maya_tools/Rigging/create_rig.py:1149)

### `api.dcc.maya.send_command(...)`

- Target: `maya_tools.maya_menu.send_command`
- Signature: `send_command(command, port=COMMAND_PORT_START)`
- API names: `send_command`
- Args:
  - `command`, required
  - `port`, default `COMMAND_PORT_START`
- Related functions:
  - same_module: [`api.dcc.maya.apply_command_port_python3_patches(...)`](#apidccmayaapply_command_port_python3_patches) -> `maya_tools.maya_menu.apply_command_port_python3_patches` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:67](C:/depot/tools/maya_tools/maya_menu.py:67)
  - same_module: [`api.dcc.maya.cleanup_command_port_files(...)`](#apidccmayacleanup_command_port_files) -> `maya_tools.maya_menu.cleanup_command_port_files` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:196](C:/depot/tools/maya_tools/maya_menu.py:196)
  - same_module: [`api.dcc.maya.create_command_port(...)`](#apidccmayacreate_command_port) -> `maya_tools.maya_menu.create_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:287](C:/depot/tools/maya_tools/maya_menu.py:287)
  - same_module: [`api.dcc.maya.get_command_port(...)`](#apidccmayaget_command_port) -> `maya_tools.maya_menu.get_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:232](C:/depot/tools/maya_tools/maya_menu.py:232)
  - same_module: [`api.dcc.maya.initialize_command_port(...)`](#apidccmayainitialize_command_port) -> `maya_tools.maya_menu.initialize_command_port` - Shares module and name terms; may be useful in the same workflow.; source [maya_menu.py:322](C:/depot/tools/maya_tools/maya_menu.py:322)
- Source: [maya_menu.py:239](C:/depot/tools/maya_tools/maya_menu.py:239)

### `api.dcc.maya.set_display_range(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.set_display_range`
- Signature: `set_display_range(start_frame, end_frame)`
- API names: `set_display_range`
- Args:
  - `start_frame`, required
  - `end_frame`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_display_range(...)`](#apidccmayaget_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)
  - same_module: [`api.dcc.maya.display_warning(...)`](#apidccmayadisplay_warning) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.display_warning` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:85](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:85)
- Description: :param start_frame: :param end_frame: :return:
- Source: [sequence_utils.py:73](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:73)

### `api.dcc.maya.set_sdk(...)`

- Target: `maya_tools.Rigging.create_rig.set_sdk`
- Signature: `set_sdk(driver, driven_attr, keys)`
- API names: `set_sdk`
- Args:
  - `driver`, required
  - `driven_attr`, required
  - `keys`, required
- Description: set driven key function :param driver: 'ctrl.attr' :param driven_attr: 'node.attr' :param keys: list of tuples [(driver_value, driven_value)] :return:
- Source: [create_rig.py:618](C:/depot/tools/maya_tools/Rigging/create_rig.py:618)

### `api.dcc.maya.setup_hik_character(...)`

- Target: `maya_tools.Rigging.mocap.setup_hik.setup_hik_character`
- Signature: `setup_hik_character(character_name, joint_map, fbx_export_path, namespace)`
- API names: `setup_hik_character`
- Args:
  - `character_name`, required
  - `joint_map`, required
  - `fbx_export_path`, required
  - `namespace`, required
- Related functions:
  - same_module: [`api.dcc.maya.t_pose_character(...)`](#apidccmayat_pose_character) -> `maya_tools.Rigging.mocap.setup_hik.t_pose_character` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:325](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:325)
- Description: Setup a HIK character definition and export to FBX for MotionBuilder. :param character_name: Name of the HIK character to create. :param joint_map: Mapping of HIK slots to joint names. :param fbx_export_path: Full path to export the FBX file. :param namespace: namespace to apply on export :return:
- Source: [setup_hik.py:358](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:358)

### `api.dcc.maya.setup_jaw_lip_driver(...)`

- Target: `maya_tools.Rigging.create_rig.setup_jaw_lip_driver`
- Signature: `setup_jaw_lip_driver(jaw_ctrl, lip_driver_ctrls, lip_ctrl_dict, head_ctrl="head1_ctrl")`
- API names: `setup_jaw_lip_driver`
- Args:
  - `jaw_ctrl`, required
  - `lip_driver_ctrls`, required
  - `lip_ctrl_dict`, required
  - `head_ctrl`, default `'head1_ctrl'`
- Related functions:
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.create_eye_aim_setup(...)`](#apidccmayacreate_eye_aim_setup) -> `maya_tools.Rigging.create_rig.create_eye_aim_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3001](C:/depot/tools/maya_tools/Rigging/create_rig.py:3001)
  - same_module: [`api.dcc.maya.create_twist_driver(...)`](#apidccmayacreate_twist_driver) -> `maya_tools.Rigging.create_rig.create_twist_driver` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3322](C:/depot/tools/maya_tools/Rigging/create_rig.py:3322)
  - same_module: [`api.dcc.maya.setup_rfl_sdks(...)`](#apidccmayasetup_rfl_sdks) -> `maya_tools.Rigging.create_rig.setup_rfl_sdks` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:708](C:/depot/tools/maya_tools/Rigging/create_rig.py:708)
  - same_module: [`api.dcc.maya.setup_secondary_face_constraints(...)`](#apidccmayasetup_secondary_face_constraints) -> `maya_tools.Rigging.create_rig.setup_secondary_face_constraints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3797](C:/depot/tools/maya_tools/Rigging/create_rig.py:3797)
- Description: Initial setup for driving mouth and lips via the jaw control. Args: jaw_ctrl (str): Name of the jaw control. lip_driver_ctrls (list[str]): List of driver controls for the lips. lip_ctrl_dict (dict): Dictionary mapping joints to lip controls. head_ctrl (str): Name of the head control. Returns: None :param jaw_ctrl: jaw ctrl :param lip_driver_ctrls: list of lip driver ctrls :param lip_ctrl_dict: mapping for lip ctrl dict :param head_ctrl: head ctrl :return: result
- Source: [create_rig.py:3131](C:/depot/tools/maya_tools/Rigging/create_rig.py:3131)

### `api.dcc.maya.setup_rfl_sdks(...)`

- Target: `maya_tools.Rigging.create_rig.setup_rfl_sdks`
- Signature: `setup_rfl_sdks(ik_leg_ctrl, rfl_joints)`
- API names: `setup_rfl_sdks`
- Args:
  - `ik_leg_ctrl`, required
  - `rfl_joints`, required
- Related functions:
  - same_module: [`api.dcc.maya.build_rfl_ik_and_constraints(...)`](#apidccmayabuild_rfl_ik_and_constraints) -> `maya_tools.Rigging.create_rig.build_rfl_ik_and_constraints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:779](C:/depot/tools/maya_tools/Rigging/create_rig.py:779)
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.create_eye_aim_setup(...)`](#apidccmayacreate_eye_aim_setup) -> `maya_tools.Rigging.create_rig.create_eye_aim_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3001](C:/depot/tools/maya_tools/Rigging/create_rig.py:3001)
  - same_module: [`api.dcc.maya.create_rfl_joints_template(...)`](#apidccmayacreate_rfl_joints_template) -> `maya_tools.Rigging.create_rig.create_rfl_joints_template` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:5955](C:/depot/tools/maya_tools/Rigging/create_rig.py:5955)
  - same_module: [`api.dcc.maya.ensure_rfl_attrs(...)`](#apidccmayaensure_rfl_attrs) -> `maya_tools.Rigging.create_rig.ensure_rfl_attrs` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:672](C:/depot/tools/maya_tools/Rigging/create_rig.py:672)
- Description: Connect the reverse-foot attributes to the RFL control SDK groups. RFL joints may be resolved as long DAG paths, but generated controls use short names. Always strip the joint path before constructing control names. :param ik_leg_ctrl: ik leg ctrl :param rfl_joints: list of rfl joints
- Source: [create_rig.py:708](C:/depot/tools/maya_tools/Rigging/create_rig.py:708)

### `api.dcc.maya.setup_secondary_face_constraints(...)`

- Target: `maya_tools.Rigging.create_rig.setup_secondary_face_constraints`
- Signature: `setup_secondary_face_constraints(face_joint_map=None, head_ctrl=None)`
- API names: `setup_secondary_face_constraints`
- Args:
  - `face_joint_map`, default `None`
  - `head_ctrl`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.build_rfl_ik_and_constraints(...)`](#apidccmayabuild_rfl_ik_and_constraints) -> `maya_tools.Rigging.create_rig.build_rfl_ik_and_constraints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:779](C:/depot/tools/maya_tools/Rigging/create_rig.py:779)
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.create_eye_aim_setup(...)`](#apidccmayacreate_eye_aim_setup) -> `maya_tools.Rigging.create_rig.create_eye_aim_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3001](C:/depot/tools/maya_tools/Rigging/create_rig.py:3001)
  - same_module: [`api.dcc.maya.mirror_face_joints(...)`](#apidccmayamirror_face_joints) -> `maya_tools.Rigging.create_rig.mirror_face_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2167](C:/depot/tools/maya_tools/Rigging/create_rig.py:2167)
  - same_module: [`api.dcc.maya.remove_other_face_module(...)`](#apidccmayaremove_other_face_module) -> `maya_tools.Rigging.create_rig.remove_other_face_module` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4975](C:/depot/tools/maya_tools/Rigging/create_rig.py:4975)
- Description: Setup secondary face constraints. :param face_joint_map: mapping for face joint map :param head_ctrl: head ctrl :return:
- Source: [create_rig.py:3797](C:/depot/tools/maya_tools/Rigging/create_rig.py:3797)

### `api.dcc.maya.setup_show_twist_ctrls(...)`

- Target: `maya_tools.Rigging.create_rig.setup_show_twist_ctrls`
- Signature: `setup_show_twist_ctrls(side, limb, twist_joints=None, attr_nice_name="Show Twist Ctrls")`
- API names: `setup_show_twist_ctrls`
- Args:
  - `side`, required
  - `limb`, required
  - `twist_joints`, default `None`
  - `attr_nice_name`, default `'Show Twist Ctrls'`
- Related functions:
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.create_eye_aim_setup(...)`](#apidccmayacreate_eye_aim_setup) -> `maya_tools.Rigging.create_rig.create_eye_aim_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3001](C:/depot/tools/maya_tools/Rigging/create_rig.py:3001)
  - same_module: [`api.dcc.maya.create_twist_driver(...)`](#apidccmayacreate_twist_driver) -> `maya_tools.Rigging.create_rig.create_twist_driver` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3322](C:/depot/tools/maya_tools/Rigging/create_rig.py:3322)
  - same_module: [`api.dcc.maya.setup_jaw_lip_driver(...)`](#apidccmayasetup_jaw_lip_driver) -> `maya_tools.Rigging.create_rig.setup_jaw_lip_driver` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3131](C:/depot/tools/maya_tools/Rigging/create_rig.py:3131)
  - same_module: [`api.dcc.maya.setup_rfl_sdks(...)`](#apidccmayasetup_rfl_sdks) -> `maya_tools.Rigging.create_rig.setup_rfl_sdks` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:708](C:/depot/tools/maya_tools/Rigging/create_rig.py:708)
- Description: Setup show twist ctrls. :param side: side :param limb: limb :param twist_joints: list of twist joints :param attr_nice_name: attr nice name :return: result
- Source: [create_rig.py:256](C:/depot/tools/maya_tools/Rigging/create_rig.py:256)

### `api.dcc.maya.setup_surface_rig(...)`

- Target: `maya_tools.Rigging.create_rig.setup_surface_rig`
- Signature: `setup_surface_rig(joint_chain, loft_name="eyelid", offset=0.5, region="eyelid", root_parent=None,`
- API names: `setup_surface_rig`
- Args:
  - `joint_chain`, required
  - `loft_name`, default `'eyelid'`
  - `offset`, default `0.5`
  - `region`, default `'eyelid'`
  - `root_parent`, default `None`
  - `create_controls`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.setup_surface_rig_with_drivers(...)`](#apidccmayasetup_surface_rig_with_drivers) -> `maya_tools.Rigging.create_rig.setup_surface_rig_with_drivers` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1506](C:/depot/tools/maya_tools/Rigging/create_rig.py:1506)
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.create_eye_aim_setup(...)`](#apidccmayacreate_eye_aim_setup) -> `maya_tools.Rigging.create_rig.create_eye_aim_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3001](C:/depot/tools/maya_tools/Rigging/create_rig.py:3001)
  - same_module: [`api.dcc.maya.create_full_rig(...)`](#apidccmayacreate_full_rig) -> `maya_tools.Rigging.create_rig.create_full_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3870](C:/depot/tools/maya_tools/Rigging/create_rig.py:3870)
  - same_module: [`api.dcc.maya.create_loft_surface_with_follicle_joints(...)`](#apidccmayacreate_loft_surface_with_follicle_joints) -> `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)
- Description: Sets up the eyelid rig: - Duplicates first joint to close the chain - Creates loft + follicles + follicle joints - Deletes temp joint - Creates controls and aims them at follicle joints :param joint_chain: list of joints :param loft_name: surface name :param offset: amount to offset :param region: region can be eyelid, mouth, or other(doesn't matter name) :param root_parent: what to parent system to :param create_controls: whether to create controls for each joint in the chain :return: dict mapp
- Source: [create_rig.py:1372](C:/depot/tools/maya_tools/Rigging/create_rig.py:1372)

### `api.dcc.maya.setup_surface_rig_with_drivers(...)`

- Target: `maya_tools.Rigging.create_rig.setup_surface_rig_with_drivers`
- Signature: `setup_surface_rig_with_drivers(`
- API names: `setup_surface_rig_with_drivers`
- Args:
  - `joint_list`, required
  - `loft_name`, default `'eyelid'`
  - `offset`, default `0.5`
  - `driver_follicle_indices`, default `None`
  - `side`, default `'r'`
  - `region`, default `'eyelid'`
  - `root_parent`, default `None`
  - `face_joint_map`, default `None`
- Related functions:
  - same_module: [`api.dcc.maya.setup_surface_rig(...)`](#apidccmayasetup_surface_rig) -> `maya_tools.Rigging.create_rig.setup_surface_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1372](C:/depot/tools/maya_tools/Rigging/create_rig.py:1372)
  - same_module: [`api.dcc.maya.create_loft_surface_with_follicle_joints(...)`](#apidccmayacreate_loft_surface_with_follicle_joints) -> `maya_tools.Rigging.create_rig.create_loft_surface_with_follicle_joints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1296](C:/depot/tools/maya_tools/Rigging/create_rig.py:1296)
  - same_module: [`api.dcc.maya.create_brow_main_setup(...)`](#apidccmayacreate_brow_main_setup) -> `maya_tools.Rigging.create_rig.create_brow_main_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3609](C:/depot/tools/maya_tools/Rigging/create_rig.py:3609)
  - same_module: [`api.dcc.maya.create_eye_aim_setup(...)`](#apidccmayacreate_eye_aim_setup) -> `maya_tools.Rigging.create_rig.create_eye_aim_setup` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3001](C:/depot/tools/maya_tools/Rigging/create_rig.py:3001)
  - same_module: [`api.dcc.maya.create_full_rig(...)`](#apidccmayacreate_full_rig) -> `maya_tools.Rigging.create_rig.create_full_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3870](C:/depot/tools/maya_tools/Rigging/create_rig.py:3870)
- Description: Sets up a driver based surface rig (great for Mouth and eyelid setups) :param joint_list: list of joints :param loft_name: surface name :param offset: amount to offset curves to loft from joints :param driver_follicle_indices: mapping indices; if None, they are auto-detected :param side: right or left :param region: mouth, eyelid, or other :param root_parent: what to parent system to :param face_joint_map: dictionary containing face mapping data :return: tuple
- Source: [create_rig.py:1506](C:/depot/tools/maya_tools/Rigging/create_rig.py:1506)

### `api.dcc.maya.show_animation_manager(...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_ui.show_animation_manager`
- Signature: `show_animation_manager()`
- API names: `show_animation_manager`
- Args: none
- Description: Launches the Animation Manager UI in Maya. :return:
- Source: [sequence_ui.py:1287](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_ui.py:1287)

### `api.dcc.maya.smooth_skin_weights(...)`

- Target: `maya_tools.Rigging.auto_skinner.smooth_skin_weights`
- Signature: `smooth_skin_weights(mesh: str, iterations: int = 2) -> Optional[str]`
- API names: `smooth_skin_weights`
- Args:
  - `mesh` (str), required
  - `iterations` (int), default `2`
- Related functions:
  - same_module: [`api.dcc.maya.apply_auto_weights(...)`](#apidccmayaapply_auto_weights) -> `maya_tools.Rigging.auto_skinner.apply_auto_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:475](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:475)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_skin(...)`](#apidccmayaapply_shoulder_profile_to_skin) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_skin` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:329](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:329)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.auto_skin_mesh(...)`](#apidccmayaauto_skin_mesh) -> `maya_tools.Rigging.auto_skinner.auto_skin_mesh` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:588](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:588)
  - same_module: [`api.dcc.maya.auto_skin_selected(...)`](#apidccmayaauto_skin_selected) -> `maya_tools.Rigging.auto_skinner.auto_skin_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:622](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:622)
- Source: [auto_skinner.py:570](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:570)

### `api.dcc.maya.snap_ctrl_cvs_to_child(...)`

- Target: `maya_tools.Rigging.create_rig.snap_ctrl_cvs_to_child`
- Signature: `snap_ctrl_cvs_to_child(ctrl, child_joint, axis="x", flip_direction=False)`
- API names: `snap_ctrl_cvs_to_child`
- Args:
  - `ctrl`, required
  - `child_joint`, required
  - `axis`, default `'x'`
  - `flip_direction`, default `False`
- Related functions:
  - same_module: [`api.dcc.maya.get_ctrl_shape_cvs(...)`](#apidccmayaget_ctrl_shape_cvs) -> `maya_tools.Rigging.create_rig.get_ctrl_shape_cvs` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2501](C:/depot/tools/maya_tools/Rigging/create_rig.py:2501)
  - same_module: [`api.dcc.maya.scale_ctrl_cvs_local(...)`](#apidccmayascale_ctrl_cvs_local) -> `maya_tools.Rigging.create_rig.scale_ctrl_cvs_local` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1091](C:/depot/tools/maya_tools/Rigging/create_rig.py:1091)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
  - same_module: [`api.dcc.maya.create_diamond_ctrl(...)`](#apidccmayacreate_diamond_ctrl) -> `maya_tools.Rigging.create_rig.create_diamond_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:35](C:/depot/tools/maya_tools/Rigging/create_rig.py:35)
- Description: Snaps control CVs toward the child joint along a local axis. :param ctrl: control transform :param child_joint: child joint or pad :param axis: 'x', 'y', or 'z' (local axis to operate on) :param flip_direction: reverse child-facing side
- Source: [create_rig.py:134](C:/depot/tools/maya_tools/Rigging/create_rig.py:134)

### `api.dcc.maya.snap_to_joint_matrix(...)`

- Target: `maya_tools.Rigging.create_rig.snap_to_joint_matrix`
- Signature: `snap_to_joint_matrix(jnt, node)`
- API names: `snap_to_joint_matrix`
- Args:
  - `jnt`, required
  - `node`, required
- Related functions:
  - same_module: [`api.dcc.maya.bake_joint_orient_to_rotate(...)`](#apidccmayabake_joint_orient_to_rotate) -> `maya_tools.Rigging.create_rig.bake_joint_orient_to_rotate` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:1935](C:/depot/tools/maya_tools/Rigging/create_rig.py:1935)
  - same_module: [`api.dcc.maya.create_joint_controls(...)`](#apidccmayacreate_joint_controls) -> `maya_tools.Rigging.create_rig.create_joint_controls` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:975](C:/depot/tools/maya_tools/Rigging/create_rig.py:975)
  - same_module: [`api.dcc.maya.mirror_joint_yz_behavior_with_label_flip(...)`](#apidccmayamirror_joint_yz_behavior_with_label_flip) -> `maya_tools.Rigging.create_rig.mirror_joint_yz_behavior_with_label_flip` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2655](C:/depot/tools/maya_tools/Rigging/create_rig.py:2655)
  - same_module: [`api.dcc.maya.snap_ctrl_cvs_to_child(...)`](#apidccmayasnap_ctrl_cvs_to_child) -> `maya_tools.Rigging.create_rig.snap_ctrl_cvs_to_child` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:134](C:/depot/tools/maya_tools/Rigging/create_rig.py:134)
- Description: snaps node to the joint using world matrix :param jnt: joint to snap to :param node: node to snap :return:
- Source: [create_rig.py:874](C:/depot/tools/maya_tools/Rigging/create_rig.py:874)

### `api.dcc.maya.solve_basic_biped_points(...)`

- Target: `maya_tools.Rigging.joint_placer.solve_basic_biped_points`
- Signature: `solve_basic_biped_points(mesh: str) -> Tuple[Dict[str, Vector3], Dict[str, float]]`
- API names: `solve_basic_biped_points`
- Args:
  - `mesh` (str), required
- Related functions:
  - same_module: [`api.dcc.maya.build_basic_biped_skeleton(...)`](#apidccmayabuild_basic_biped_skeleton) -> `maya_tools.Rigging.joint_placer.build_basic_biped_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:516](C:/depot/tools/maya_tools/Rigging/joint_placer.py:516)
  - same_module: [`api.dcc.maya.build_skeleton_from_points(...)`](#apidccmayabuild_skeleton_from_points) -> `maya_tools.Rigging.joint_placer.build_skeleton_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:424](C:/depot/tools/maya_tools/Rigging/joint_placer.py:424)
  - same_module: [`api.dcc.maya.create_guides_from_points(...)`](#apidccmayacreate_guides_from_points) -> `maya_tools.Rigging.joint_placer.create_guides_from_points` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:498](C:/depot/tools/maya_tools/Rigging/joint_placer.py:498)
- Description: Return first-pass biped joint positions. The current implementation is proportional, with confidence set low/medium. This gives a stable baseline that can later be refined by landmark or mesh cross-section solvers without changing the downstream rigging code.
- Source: [joint_placer.py:278](C:/depot/tools/maya_tools/Rigging/joint_placer.py:278)

### `api.dcc.maya.solve_vertex_weights(...)`

- Target: `maya_tools.Rigging.auto_skinner.solve_vertex_weights`
- Signature: `solve_vertex_weights(`
- API names: `solve_vertex_weights`
- Args:
  - `vertex` (str), required
  - `segments` (Sequence[Tuple[str, str]]), required
  - `max_influences` (int), default `DEFAULT_MAX_INFLUENCES`
  - `falloff_power` (float), default `2.0`
- Related functions:
  - same_module: [`api.dcc.maya.solve_vertex_weights_from_position(...)`](#apidccmayasolve_vertex_weights_from_position) -> `maya_tools.Rigging.auto_skinner.solve_vertex_weights_from_position` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:451](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:451)
  - same_module: [`api.dcc.maya.apply_auto_weights(...)`](#apidccmayaapply_auto_weights) -> `maya_tools.Rigging.auto_skinner.apply_auto_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:475](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:475)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.normalize_and_limit_weights(...)`](#apidccmayanormalize_and_limit_weights) -> `maya_tools.Rigging.auto_skinner.normalize_and_limit_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:152](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:152)
  - same_module: [`api.dcc.maya.smooth_skin_weights(...)`](#apidccmayasmooth_skin_weights) -> `maya_tools.Rigging.auto_skinner.smooth_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:570](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:570)
- Source: [auto_skinner.py:433](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:433)

### `api.dcc.maya.solve_vertex_weights_from_position(...)`

- Target: `maya_tools.Rigging.auto_skinner.solve_vertex_weights_from_position`
- Signature: `solve_vertex_weights_from_position(`
- API names: `solve_vertex_weights_from_position`
- Args:
  - `pos` (om.MVector), required
  - `segments` (Sequence[BindSegment]), required
  - `max_influences` (int), default `DEFAULT_MAX_INFLUENCES`
  - `falloff_power` (float), default `2.0`
- Related functions:
  - same_module: [`api.dcc.maya.solve_vertex_weights(...)`](#apidccmayasolve_vertex_weights) -> `maya_tools.Rigging.auto_skinner.solve_vertex_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:433](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:433)
  - same_module: [`api.dcc.maya.apply_auto_weights(...)`](#apidccmayaapply_auto_weights) -> `maya_tools.Rigging.auto_skinner.apply_auto_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:475](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:475)
  - same_module: [`api.dcc.maya.apply_shoulder_profile_to_weights(...)`](#apidccmayaapply_shoulder_profile_to_weights) -> `maya_tools.Rigging.auto_skinner.apply_shoulder_profile_to_weights` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:296](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:296)
  - same_module: [`api.dcc.maya.get_joint_position(...)`](#apidccmayaget_joint_position) -> `maya_tools.Rigging.auto_skinner.get_joint_position` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:69](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:69)
  - same_module: [`api.dcc.maya.learn_shoulder_profile_from_selected(...)`](#apidccmayalearn_shoulder_profile_from_selected) -> `maya_tools.Rigging.auto_skinner.learn_shoulder_profile_from_selected` - Shares module and name terms; may be useful in the same workflow.; source [auto_skinner.py:277](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:277)
- Source: [auto_skinner.py:451](C:/depot/tools/maya_tools/Rigging/auto_skinner.py:451)

### `api.dcc.maya.sort_reverse_hierarchy(...)`

- Target: `maya_tools.Animation.anim_export.anim_export.sort_reverse_hierarchy`
- Signature: `sort_reverse_hierarchy(node_list)`
- API names: `sort_reverse_hierarchy`
- Args:
  - `node_list`, required
- Description: Sorts DAG nodes in reverse hierarchy order (children before parents). Assumes all nodes are given as full paths or unique enough to convert to full paths.
- Source: [anim_export.py:340](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:340)

### `api.dcc.maya.store_all_control_cv_positions(...)`

- Target: `maya_tools.Rigging.create_rig.store_all_control_cv_positions`
- Signature: `store_all_control_cv_positions(store_node=MODULE_STORE_NODE)`
- API names: `store_all_control_cv_positions`
- Args:
  - `store_node`, default `MODULE_STORE_NODE`
- Related functions:
  - same_module: [`api.dcc.maya.restore_all_control_cv_positions(...)`](#apidccmayarestore_all_control_cv_positions) -> `maya_tools.Rigging.create_rig.restore_all_control_cv_positions` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2551](C:/depot/tools/maya_tools/Rigging/create_rig.py:2551)
  - same_module: [`api.dcc.maya.get_all_module_metadata(...)`](#apidccmayaget_all_module_metadata) -> `maya_tools.Rigging.create_rig.get_all_module_metadata` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6594](C:/depot/tools/maya_tools/Rigging/create_rig.py:6594)
  - same_module: [`api.dcc.maya.orient_control_pad_to_world_safely(...)`](#apidccmayaorient_control_pad_to_world_safely) -> `maya_tools.Rigging.create_rig.orient_control_pad_to_world_safely` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:885](C:/depot/tools/maya_tools/Rigging/create_rig.py:885)
  - same_module: [`api.dcc.maya.rebuild_all_space_switches(...)`](#apidccmayarebuild_all_space_switches) -> `maya_tools.Rigging.create_rig.rebuild_all_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6699](C:/depot/tools/maya_tools/Rigging/create_rig.py:6699)
  - same_module: [`api.dcc.maya.store_rig_connections(...)`](#apidccmayastore_rig_connections) -> `maya_tools.Rigging.create_rig.store_rig_connections` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6624](C:/depot/tools/maya_tools/Rigging/create_rig.py:6624)
- Description: Store all control cv positions. :param store_node: store node :return: result
- Source: [create_rig.py:2525](C:/depot/tools/maya_tools/Rigging/create_rig.py:2525)

### `api.dcc.maya.store_rig_connections(...)`

- Target: `maya_tools.Rigging.create_rig.store_rig_connections`
- Signature: `store_rig_connections(controls_list, module_name)`
- API names: `store_rig_connections`
- Args:
  - `controls_list`, required
  - `module_name`, required
- Related functions:
  - same_module: [`api.dcc.maya.restore_rig_connections(...)`](#apidccmayarestore_rig_connections) -> `maya_tools.Rigging.create_rig.restore_rig_connections` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:6777](C:/depot/tools/maya_tools/Rigging/create_rig.py:6777)
  - same_module: [`api.dcc.maya.create_full_rig(...)`](#apidccmayacreate_full_rig) -> `maya_tools.Rigging.create_rig.create_full_rig` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3870](C:/depot/tools/maya_tools/Rigging/create_rig.py:3870)
  - same_module: [`api.dcc.maya.create_rig(...)`](#apidccmayacreate_rig) -> `maya_tools.Rigging.create_rig.create_rig_from_mapping` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:4127](C:/depot/tools/maya_tools/Rigging/create_rig.py:4127)
  - same_module: [`api.dcc.maya.create_rig_space_switches(...)`](#apidccmayacreate_rig_space_switches) -> `maya_tools.Rigging.create_rig.create_rig_space_switches` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2991](C:/depot/tools/maya_tools/Rigging/create_rig.py:2991)
  - same_module: [`api.dcc.maya.hik_map_to_rig_args(...)`](#apidccmayahik_map_to_rig_args) -> `maya_tools.Rigging.create_rig.hik_map_to_rig_args` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:3478](C:/depot/tools/maya_tools/Rigging/create_rig.py:3478)
- Description: Queries space switches, external constraints, and output connections for controls_list and stores them in GLOBAL_RIG_STORE[module_name]. :param controls_list: list of control nodes to query :param module_name: name of the module :return: None
- Source: [create_rig.py:6624](C:/depot/tools/maya_tools/Rigging/create_rig.py:6624)

### `api.dcc.maya.strip_ctrl_shape_and_rename(...)`

- Target: `maya_tools.Rigging.create_rig.strip_ctrl_shape_and_rename`
- Signature: `strip_ctrl_shape_and_rename(ctrl)`
- API names: `strip_ctrl_shape_and_rename`
- Args:
  - `ctrl`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_ctrl_shape_cvs(...)`](#apidccmayaget_ctrl_shape_cvs) -> `maya_tools.Rigging.create_rig.get_ctrl_shape_cvs` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:2501](C:/depot/tools/maya_tools/Rigging/create_rig.py:2501)
  - same_module: [`api.dcc.maya.build_rfl_ik_and_constraints(...)`](#apidccmayabuild_rfl_ik_and_constraints) -> `maya_tools.Rigging.create_rig.build_rfl_ik_and_constraints` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:779](C:/depot/tools/maya_tools/Rigging/create_rig.py:779)
  - same_module: [`api.dcc.maya.create_bi_arrow_ctrl(...)`](#apidccmayacreate_bi_arrow_ctrl) -> `maya_tools.Rigging.create_rig.create_bi_arrow_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:226](C:/depot/tools/maya_tools/Rigging/create_rig.py:226)
  - same_module: [`api.dcc.maya.create_cube_ctrl(...)`](#apidccmayacreate_cube_ctrl) -> `maya_tools.Rigging.create_rig.create_cube_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:114](C:/depot/tools/maya_tools/Rigging/create_rig.py:114)
  - same_module: [`api.dcc.maya.create_diamond_ctrl(...)`](#apidccmayacreate_diamond_ctrl) -> `maya_tools.Rigging.create_rig.create_diamond_ctrl` - Shares module and name terms; may be useful in the same workflow.; source [create_rig.py:35](C:/depot/tools/maya_tools/Rigging/create_rig.py:35)
- Description: Delete all shapes under the transform and rename it. Args: ctrl (str): Control node name to process. Returns: str: The new node name. :param ctrl: ctrl :return: result
- Source: [create_rig.py:3101](C:/depot/tools/maya_tools/Rigging/create_rig.py:3101)

### `api.dcc.maya.t_pose_character(...)`

- Target: `maya_tools.Rigging.mocap.setup_hik.t_pose_character`
- Signature: `t_pose_character(l_upperarm, r_upperarm, l_clav, r_clav, l_elbow, r_elbow, l_hand, r_hand)`
- API names: `t_pose_character`
- Args:
  - `l_upperarm`, required
  - `r_upperarm`, required
  - `l_clav`, required
  - `r_clav`, required
  - `l_elbow`, required
  - `r_elbow`, required
  - `l_hand`, required
  - `r_hand`, required
- Related functions:
  - same_module: [`api.dcc.maya.setup_hik_character(...)`](#apidccmayasetup_hik_character) -> `maya_tools.Rigging.mocap.setup_hik.setup_hik_character` - Shares module and name terms; may be useful in the same workflow.; source [setup_hik.py:358](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:358)
- Description: Tposes the arms, currently pointed down X :param l_upperarm: actual joint name for slot :param r_upperarm: actual joint name for slot :param l_clav: actual joint name for slot :param r_clav: actual joint name for slot :param l_elbow: actual joint name for slot :param r_elbow: actual joint name for slot :param l_hand: actual joint name for slot :param r_hand: actual joint name for slot :return:
- Source: [setup_hik.py:325](C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py:325)

### `api.dcc.maya.tag_pose_metadata(...)`

- Target: `maya_tools.Rigging.joint_placer.tag_pose_metadata`
- Signature: `tag_pose_metadata(root_joint: str, pose_type: str, pose_angle_degrees: float) -> None`
- API names: `tag_pose_metadata`
- Args:
  - `root_joint` (str), required
  - `pose_type` (str), required
  - `pose_angle_degrees` (float), required
- Related functions:
  - same_module: [`api.dcc.maya.classify_arm_pose(...)`](#apidccmayaclassify_arm_pose) -> `maya_tools.Rigging.joint_placer.classify_arm_pose` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:149](C:/depot/tools/maya_tools/Rigging/joint_placer.py:149)
- Source: [joint_placer.py:336](C:/depot/tools/maya_tools/Rigging/joint_placer.py:336)

### `api.dcc.maya.transfer_skin_weights(...)`

- Target: `maya_tools.Rigging.skinning_utils.transfer_skin_weights`
- Signature: `transfer_skin_weights(`
- API names: `transfer_skin_weights`
- Args:
  - `source_meshes`, required
  - `target_mesh`, required
- Related functions:
  - same_module: [`api.dcc.maya.transfer_skin_weights_from_selection(...)`](#apidccmayatransfer_skin_weights_from_selection) -> `maya_tools.Rigging.skinning_utils.transfer_skin_weights_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:8](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:8)
  - same_module: [`api.dcc.maya.export_skin_weights(...)`](#apidccmayaexport_skin_weights) -> `maya_tools.Rigging.skinning_utils.export_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:173](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:173)
  - same_module: [`api.dcc.maya.import_skin_weights(...)`](#apidccmayaimport_skin_weights) -> `maya_tools.Rigging.skinning_utils.import_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:229](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:229)
- Description: Transfer skin weights from source meshes to a target mesh. Args: source_meshes (list[str]) target_mesh (str) Returns: dict | bool
- Source: [skinning_utils.py:24](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:24)

### `api.dcc.maya.transfer_skin_weights_from_selection(...)`

- Target: `maya_tools.Rigging.skinning_utils.transfer_skin_weights_from_selection`
- Signature: `transfer_skin_weights_from_selection(remove_unused_influences=True)`
- API names: `transfer_skin_weights_from_selection`
- Args:
  - `remove_unused_influences`, default `True`
- Related functions:
  - same_module: [`api.dcc.maya.transfer_skin_weights(...)`](#apidccmayatransfer_skin_weights) -> `maya_tools.Rigging.skinning_utils.transfer_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:24](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:24)
  - same_module: [`api.dcc.maya.export_skin_weights(...)`](#apidccmayaexport_skin_weights) -> `maya_tools.Rigging.skinning_utils.export_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:173](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:173)
  - same_module: [`api.dcc.maya.import_skin_weights(...)`](#apidccmayaimport_skin_weights) -> `maya_tools.Rigging.skinning_utils.import_skin_weights` - Shares module and name terms; may be useful in the same workflow.; source [skinning_utils.py:229](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:229)
- Description: Transfer skin weights from selected source meshes to the last selected mesh.
- Source: [skinning_utils.py:8](C:/depot/tools/maya_tools/Rigging/skinning_utils.py:8)

### `api.dcc.maya.update_joint_setup_for_import(...)`

- Target: `maya_tools.Animation.anim_export.anim_export.update_joint_setup_for_import`
- Signature: `update_joint_setup_for_import(facial_joints)`
- API names: `update_joint_setup_for_import`
- Args:
  - `facial_joints`, required
- Related functions:
  - same_module: [`api.dcc.maya.get_all_joint_children(...)`](#apidccmayaget_all_joint_children) -> `maya_tools.Animation.anim_export.anim_export.get_all_joint_children` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:121](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:121)
  - same_module: [`api.dcc.maya.import_reference_and_strip_namespace_test(...)`](#apidccmayaimport_reference_and_strip_namespace_test) -> `maya_tools.Animation.anim_export.anim_export.import_reference_and_strip_namespace_test` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:247](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:247)
- Description: Sets up hierachy to match the Face Archetype Skeleton :param facial_joints: list of facial joints :return:
- Source: [anim_export.py:206](C:/depot/tools/maya_tools/Animation/anim_export/anim_export.py:206)

### `api.dcc.maya.update_maya_script_path(...)`

- Target: `maya_tools.maya_setup.update_maya_script_path`
- Signature: `update_maya_script_path(new_path)`
- API names: `update_maya_script_path`
- Args:
  - `new_path`, required
- Description: Update the MAYA_SCRIPT_PATH environment variable for the current Windows user. If it already exists, append the new_path if not already present. If it doesn't exist, create it. :param new_path: Path to add to MAYA_SCRIPT_PATH
- Source: [maya_setup.py:7](C:/depot/tools/maya_tools/maya_setup.py:7)

### `api.dcc.maya.validate_body_joint_map(...)`

- Target: `maya_tools.Rigging.joint_placer.validate_body_joint_map`
- Signature: `validate_body_joint_map(body_joint_map: dict, required_slots: Iterable[str] = CORE_HIK_SLOTS) -> List[str]`
- API names: `validate_body_joint_map`
- Args:
  - `body_joint_map` (dict), required
  - `required_slots` (Iterable[str]), default `CORE_HIK_SLOTS`
- Related functions:
  - same_module: [`api.dcc.maya.create_joint(...)`](#apidccmayacreate_joint) -> `maya_tools.Rigging.joint_placer.create_joint` - Shares module and name terms; may be useful in the same workflow.; source [joint_placer.py:351](C:/depot/tools/maya_tools/Rigging/joint_placer.py:351)
- Source: [joint_placer.py:489](C:/depot/tools/maya_tools/Rigging/joint_placer.py:489)

### `api.dcc.maya.world_align_origin_and_pelvis(...)`

- Target: `maya_tools.Rigging.joint_placer.world_align_origin_and_pelvis`
- Signature: `world_align_origin_and_pelvis(root_joint: str) -> None`
- API names: `world_align_origin_and_pelvis`
- Args:
  - `root_joint` (str), required
- Source: [joint_placer.py:415](C:/depot/tools/maya_tools/Rigging/joint_placer.py:415)

### `api.dcc.maya.call('maya_tools.Cinematics.SequenceUI.sequence_utils.get_main_window_pointer', ...)`

- Target: `maya_tools.Cinematics.SequenceUI.sequence_utils.get_main_window_pointer`
- Signature: `get_main_window_pointer()`
- Name status: ambiguous; use the full target path.
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.get_camera_sequencer_data(...)`](#apidccmayaget_camera_sequencer_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:42](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:42)
  - same_module: [`api.dcc.maya.get_cameras_from_selection(...)`](#apidccmayaget_cameras_from_selection) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:94](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:94)
  - same_module: [`api.dcc.maya.get_display_range(...)`](#apidccmayaget_display_range) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:63](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:63)
  - same_module: [`api.dcc.maya.get_export_node_data(...)`](#apidccmayaget_export_node_data) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:271](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:271)
  - same_module: [`api.dcc.maya.get_maya_fps(...)`](#apidccmayaget_maya_fps) -> `maya_tools.Cinematics.SequenceUI.sequence_utils.get_maya_fps` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:202](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:202)
- Description: Get the Maya main window pointer :return:
- Source: [sequence_utils.py:33](C:/depot/tools/maya_tools/Cinematics/SequenceUI/sequence_utils.py:33)

### `api.dcc.maya.call('maya_tools.Rigging.mocap.hik_ui.get_main_window_pointer', ...)`

- Target: `maya_tools.Rigging.mocap.hik_ui.get_main_window_pointer`
- Signature: `get_main_window_pointer()`
- Name status: ambiguous; use the full target path.
- Args: none
- Related functions:
  - same_module: [`api.dcc.maya.get_default_export_path(...)`](#apidccmayaget_default_export_path) -> `maya_tools.Rigging.mocap.hik_ui.get_default_export_path` - Shares module and name terms; may be useful in the same workflow.; source [hik_ui.py:34](C:/depot/tools/maya_tools/Rigging/mocap/hik_ui.py:34)
- Description: Get the Maya main window pointer :return:
- Source: [hik_ui.py:45](C:/depot/tools/maya_tools/Rigging/mocap/hik_ui.py:45)

## motionbuilder

### `api.dcc.motionbuilder.add_file_open_callback(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.add_file_open_callback`
- Signature: `add_file_open_callback(widget)`
- API names: `add_file_open_callback`
- Args:
  - `widget`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.remove_file_open_callback(...)`](#apidccmotionbuilderremove_file_open_callback) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.remove_file_open_callback` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:21](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:21)
- Source: [sequence_utils.py:9](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:9)

### `api.dcc.motionbuilder.create_and_populate_export_node(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.create_and_populate_export_node`
- Signature: `create_and_populate_export_node(anim_dict, skeletons, uproject, log_path, cmd_path, export_directory, namespace_skeleton_map)`
- API names: `create_and_populate_export_node`
- Args:
  - `anim_dict`, required
  - `skeletons`, required
  - `uproject`, required
  - `log_path`, required
  - `cmd_path`, required
  - `export_directory`, required
  - `namespace_skeleton_map`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.export_node_exists(...)`](#apidccmotionbuilderexport_node_exists) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.export_node_exists` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:88](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:88)
  - same_module: [`api.dcc.motionbuilder.get_export_node_data(...)`](#apidccmotionbuilderget_export_node_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:334](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:334)
  - same_module: [`api.dcc.motionbuilder.create_string_property(...)`](#apidccmotionbuildercreate_string_property) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.create_string_property` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:288](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:288)
- Description: Data is passed from the UI, likely wont need to call from Maya directly (just separating out cmds calls into this file) :param anim_dict: :param skeletons: :param uproject: :param log_path: :param cmd_path: :param export_directory: :param namespace_skeleton_map: :return:
- Source: [sequence_utils.py:304](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:304)

### `api.dcc.motionbuilder.create_motionbuilder_menu(...)`

- Target: `motionbuilder_tools.motionbuilder_menu.create_motionbuilder_menu`
- Signature: `create_motionbuilder_menu()`
- API names: `create_motionbuilder_menu`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.on_menu_click(...)`](#apidccmotionbuilderon_menu_click) -> `motionbuilder_tools.motionbuilder_menu.on_menu_click` - Shares module and name terms; may be useful in the same workflow.; source [motionbuilder_menu.py:19](C:/depot/tools/motionbuilder_tools/motionbuilder_menu.py:19)
- Description: Create a custom menu in MotionBuilder UI.
- Source: [motionbuilder_menu.py:6](C:/depot/tools/motionbuilder_tools/motionbuilder_menu.py:6)

### `api.dcc.motionbuilder.create_string_property(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.create_string_property`
- Signature: `create_string_property(model, prop_name, value)`
- API names: `create_string_property`
- Args:
  - `model`, required
  - `prop_name`, required
  - `value`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.create_and_populate_export_node(...)`](#apidccmotionbuildercreate_and_populate_export_node) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.create_and_populate_export_node` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:304](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:304)
- Description: :param model: The actual object you want to add the property to :param prop_name: name of property :param value: value to define the property with :return:
- Source: [sequence_utils.py:288](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:288)

### `api.dcc.motionbuilder.deselect_all_models(...)`

- Target: `motionbuilder_tools.Animation.anim_export.anim_export.deselect_all_models`
- Signature: `deselect_all_models()`
- API names: `deselect_all_models`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_all_descendants(...)`](#apidccmotionbuilderget_all_descendants) -> `motionbuilder_tools.Animation.anim_export.anim_export.get_all_descendants` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:102](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:102)
  - same_module: [`api.dcc.motionbuilder.get_selected_models(...)`](#apidccmotionbuilderget_selected_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.get_selected_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:167](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:167)
  - same_module: [`api.dcc.motionbuilder.plot_selected_models(...)`](#apidccmotionbuilderplot_selected_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.plot_selected_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:198](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:198)
  - same_module: [`api.dcc.motionbuilder.select_models(...)`](#apidccmotionbuilderselect_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.select_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:187](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:187)
- Description: Deselect all models :return:
- Source: [anim_export.py:177](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:177)

### `api.dcc.motionbuilder.display_warning(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.display_warning`
- Signature: `display_warning(warning)`
- API names: `display_warning`
- Args:
  - `warning`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_display_range(...)`](#apidccmotionbuilderget_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)
  - same_module: [`api.dcc.motionbuilder.set_display_range(...)`](#apidccmotionbuilderset_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.set_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:101](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:101)
- Description: :param warning: Text to warn user with :return:
- Source: [sequence_utils.py:120](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:120)

### `api.dcc.motionbuilder.export_animation(...)`

- Target: `motionbuilder_tools.Animation.anim_export.anim_export.export_animation`
- Signature: `export_animation(motionbuilder_file, export_path, namespace, start_frame, end_frame, nodes=None)`
- API names: `export_animation`
- Args:
  - `motionbuilder_file`, required
  - `export_path`, required
  - `namespace`, required
  - `start_frame`, required
  - `end_frame`, required
  - `nodes`, default `None`
- Description: Opens MotionBuilder scene and exports animation to FBX. :param motionbuilder_file: (str): Path to the Maya scene file (if you need it). :param export_path: (str): Path where the FBX should be saved. :param namespace: (str): Namespace of the skeleton. :param start_frame: (int): Start frame of the animation. :param end_frame: (int): End frame of the animation. :param nodes: (list, optional): Specific nodes to export instead. :return:
- Source: [anim_export.py:9](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:9)

### `api.dcc.motionbuilder.export_node_exists(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.export_node_exists`
- Signature: `export_node_exists()`
- API names: `export_node_exists`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.create_and_populate_export_node(...)`](#apidccmotionbuildercreate_and_populate_export_node) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.create_and_populate_export_node` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:304](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:304)
  - same_module: [`api.dcc.motionbuilder.get_export_node_data(...)`](#apidccmotionbuilderget_export_node_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:334](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:334)
- Source: [sequence_utils.py:88](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:88)

### `api.dcc.motionbuilder.find_skinned_or_top_joints(...)`

- Target: `motionbuilder_tools.Animation.anim_export.anim_export.find_skinned_or_top_joints`
- Signature: `find_skinned_or_top_joints(namespace)`
- API names: `find_skinned_or_top_joints`
- Args:
  - `namespace`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.call('motionbuilder_tools.Animation.anim_export.anim_export.find_top_joint', ...)`](#apidccmotionbuildercallmotionbuilder_toolsanimationanim_exportanim_exportfind_top_joint) -> `motionbuilder_tools.Animation.anim_export.anim_export.find_top_joint` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:115](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:115)
  - same_module: [`api.dcc.motionbuilder.list_joints_by_namespace(...)`](#apidccmotionbuilderlist_joints_by_namespace) -> `motionbuilder_tools.Animation.anim_export.anim_export.list_joints_by_namespace` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:90](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:90)
- Description: Detects the top-level joint in a given namespace. It looks for the joint with no parent, or the joint closest to the top in the hierarchy. :param namespace: (str): The namespace to search for joints. :return: (list): List of top-level joints in the namespace.
- Source: [anim_export.py:127](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:127)

### `api.dcc.motionbuilder.generate_sequence_dict_from_anim_dict(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.generate_sequence_dict_from_anim_dict`
- Signature: `generate_sequence_dict_from_anim_dict(anim_dict)`
- API names: `generate_sequence_dict_from_anim_dict`
- Args:
  - `anim_dict`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_shot_name_from_path(...)`](#apidccmotionbuilderget_shot_name_from_path) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_shot_name_from_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:209](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:209)
- Description: Generates a new dictionary with shot_number as the key, and a list of animations as the value. Each animation has export path, skeleton, blueprint (default to None), nodes, start frame, and end frame. :param anim_dict: The original animation dictionary, where the key is the export path and the value contains start frame, end frame, namespace, skeleton, color, and nodes. :return: new dictionary with shot_number as keys.
- Source: [sequence_utils.py:231](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:231)

### `api.dcc.motionbuilder.get_all_descendants(...)`

- Target: `motionbuilder_tools.Animation.anim_export.anim_export.get_all_descendants`
- Signature: `get_all_descendants(model)`
- API names: `get_all_descendants`
- Args:
  - `model`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.deselect_all_models(...)`](#apidccmotionbuilderdeselect_all_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.deselect_all_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:177](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:177)
  - same_module: [`api.dcc.motionbuilder.get_selected_models(...)`](#apidccmotionbuilderget_selected_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.get_selected_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:167](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:167)
- Description: Gets all children of a selected model :param model: Model to search for children under :return:
- Source: [anim_export.py:102](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:102)

### `api.dcc.motionbuilder.get_camera_sequencer_data(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data`
- Signature: `get_camera_sequencer_data()`
- API names: `get_camera_sequencer_data`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_export_node_data(...)`](#apidccmotionbuilderget_export_node_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:334](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:334)
  - same_module: [`api.dcc.motionbuilder.get_story_camera_shots(...)`](#apidccmotionbuilderget_story_camera_shots) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_story_camera_shots` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:54](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:54)
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_components_in_namespace(...)`](#apidccmotionbuilderget_components_in_namespace) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)
  - same_module: [`api.dcc.motionbuilder.get_display_range(...)`](#apidccmotionbuilderget_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)
- Description: Retrieves all shots, shot ranges, and corresponding shot cameras from MotionBuilder's CameraSwitcher. :return: List of tuples (shot_number, start_frame, end_frame, camera)
- Source: [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)

### `api.dcc.motionbuilder.get_cameras_from_selection(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection`
- Signature: `get_cameras_from_selection()`
- API names: `get_cameras_from_selection`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_shot_name_from_path(...)`](#apidccmotionbuilderget_shot_name_from_path) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_shot_name_from_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:209](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:209)
  - same_module: [`api.dcc.motionbuilder.generate_sequence_dict_from_anim_dict(...)`](#apidccmotionbuildergenerate_sequence_dict_from_anim_dict) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.generate_sequence_dict_from_anim_dict` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:231](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:231)
  - same_module: [`api.dcc.motionbuilder.get_camera_sequencer_data(...)`](#apidccmotionbuilderget_camera_sequencer_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)
  - same_module: [`api.dcc.motionbuilder.get_components_in_namespace(...)`](#apidccmotionbuilderget_components_in_namespace) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)
  - same_module: [`api.dcc.motionbuilder.get_display_range(...)`](#apidccmotionbuilderget_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)
- Description: :return: Cameras in selection
- Source: [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)

### `api.dcc.motionbuilder.get_components_in_namespace(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace`
- Signature: `get_components_in_namespace(namespace)`
- API names: `get_components_in_namespace`
- Args:
  - `namespace`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_camera_sequencer_data(...)`](#apidccmotionbuilderget_camera_sequencer_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_display_range(...)`](#apidccmotionbuilderget_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)
  - same_module: [`api.dcc.motionbuilder.get_export_node_data(...)`](#apidccmotionbuilderget_export_node_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:334](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:334)
  - same_module: [`api.dcc.motionbuilder.get_main_window_pointer(...)`](#apidccmotionbuilderget_main_window_pointer) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_main_window_pointer` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:32](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:32)
- Description: Returns all components in the scene that belong to the given namespace. Namespace format should be: 'MyNamespace::'
- Source: [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)

### `api.dcc.motionbuilder.get_display_range(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range`
- Signature: `get_display_range()`
- API names: `get_display_range`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.set_display_range(...)`](#apidccmotionbuilderset_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.set_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:101](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:101)
  - same_module: [`api.dcc.motionbuilder.display_warning(...)`](#apidccmotionbuilderdisplay_warning) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.display_warning` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:120](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:120)
  - same_module: [`api.dcc.motionbuilder.get_camera_sequencer_data(...)`](#apidccmotionbuilderget_camera_sequencer_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_components_in_namespace(...)`](#apidccmotionbuilderget_components_in_namespace) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)
- Description: Gets the motionbuilder range to match the start and end frame listed :return: start and end frame
- Source: [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)

### `api.dcc.motionbuilder.get_export_node_data(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data`
- Signature: `get_export_node_data()`
- API names: `get_export_node_data`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.create_and_populate_export_node(...)`](#apidccmotionbuildercreate_and_populate_export_node) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.create_and_populate_export_node` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:304](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:304)
  - same_module: [`api.dcc.motionbuilder.export_node_exists(...)`](#apidccmotionbuilderexport_node_exists) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.export_node_exists` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:88](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:88)
  - same_module: [`api.dcc.motionbuilder.get_camera_sequencer_data(...)`](#apidccmotionbuilderget_camera_sequencer_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_components_in_namespace(...)`](#apidccmotionbuilderget_components_in_namespace) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)
- Source: [sequence_utils.py:334](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:334)

### `api.dcc.motionbuilder.get_main_window_pointer(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_main_window_pointer`
- Signature: `get_main_window_pointer()`
- API names: `get_main_window_pointer`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_camera_sequencer_data(...)`](#apidccmotionbuilderget_camera_sequencer_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_components_in_namespace(...)`](#apidccmotionbuilderget_components_in_namespace) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)
  - same_module: [`api.dcc.motionbuilder.get_display_range(...)`](#apidccmotionbuilderget_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)
  - same_module: [`api.dcc.motionbuilder.get_export_node_data(...)`](#apidccmotionbuilderget_export_node_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:334](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:334)
- Description: :return: Main Window for Motionbuilder
- Source: [sequence_utils.py:32](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:32)

### `api.dcc.motionbuilder.get_motionbuilder_fps(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_motionbuilder_fps`
- Signature: `get_motionbuilder_fps()`
- API names: `get_motionbuilder_fps`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_camera_sequencer_data(...)`](#apidccmotionbuilderget_camera_sequencer_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_components_in_namespace(...)`](#apidccmotionbuilderget_components_in_namespace) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)
  - same_module: [`api.dcc.motionbuilder.get_display_range(...)`](#apidccmotionbuilderget_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)
  - same_module: [`api.dcc.motionbuilder.get_export_node_data(...)`](#apidccmotionbuilderget_export_node_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:334](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:334)
- Description: :return: Which playback fps the scene is set with
- Source: [sequence_utils.py:267](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:267)

### `api.dcc.motionbuilder.get_motionbuilder_version_string(...)`

- Target: `motionbuilder_tools.motionbuilder_setup.get_motionbuilder_version_string`
- Signature: `get_motionbuilder_version_string()`
- API names: `get_motionbuilder_version_string`
- Args: none
- Source: [motionbuilder_setup.py:4](C:/depot/tools/motionbuilder_tools/motionbuilder_setup.py:4)

### `api.dcc.motionbuilder.get_rig_namespaces(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_rig_namespaces`
- Signature: `get_rig_namespaces(selection=True)`
- API names: `get_rig_namespaces`
- Args:
  - `selection`, default `True`
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_camera_sequencer_data(...)`](#apidccmotionbuilderget_camera_sequencer_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_components_in_namespace(...)`](#apidccmotionbuilderget_components_in_namespace) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)
  - same_module: [`api.dcc.motionbuilder.get_display_range(...)`](#apidccmotionbuilderget_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)
  - same_module: [`api.dcc.motionbuilder.get_export_node_data(...)`](#apidccmotionbuilderget_export_node_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:334](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:334)
- Description: Detects namespaces of selected rigs that contain joints with 'origin' as the top joint. :return: Set of valid namespaces
- Source: [sequence_utils.py:166](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:166)

### `api.dcc.motionbuilder.get_scene_path(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_scene_path`
- Signature: `get_scene_path()`
- API names: `get_scene_path`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_shot_name_from_path(...)`](#apidccmotionbuilderget_shot_name_from_path) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_shot_name_from_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:209](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:209)
  - same_module: [`api.dcc.motionbuilder.get_camera_sequencer_data(...)`](#apidccmotionbuilderget_camera_sequencer_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_components_in_namespace(...)`](#apidccmotionbuilderget_components_in_namespace) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)
  - same_module: [`api.dcc.motionbuilder.get_display_range(...)`](#apidccmotionbuilderget_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)
- Description: :return: Actual saved file name currently open
- Source: [sequence_utils.py:140](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:140)

### `api.dcc.motionbuilder.get_selected_models(...)`

- Target: `motionbuilder_tools.Animation.anim_export.anim_export.get_selected_models`
- Signature: `get_selected_models()`
- API names: `get_selected_models`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.plot_selected_models(...)`](#apidccmotionbuilderplot_selected_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.plot_selected_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:198](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:198)
  - same_module: [`api.dcc.motionbuilder.deselect_all_models(...)`](#apidccmotionbuilderdeselect_all_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.deselect_all_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:177](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:177)
  - same_module: [`api.dcc.motionbuilder.get_all_descendants(...)`](#apidccmotionbuilderget_all_descendants) -> `motionbuilder_tools.Animation.anim_export.anim_export.get_all_descendants` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:102](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:102)
  - same_module: [`api.dcc.motionbuilder.select_models(...)`](#apidccmotionbuilderselect_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.select_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:187](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:187)
- Description: Get selected models :return FBModelList: list of selected models
- Source: [anim_export.py:167](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:167)

### `api.dcc.motionbuilder.get_shot_name_from_path(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_shot_name_from_path`
- Signature: `get_shot_name_from_path(export_path)`
- API names: `get_shot_name_from_path`
- Args:
  - `export_path`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_scene_path(...)`](#apidccmotionbuilderget_scene_path) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_scene_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:140](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:140)
  - same_module: [`api.dcc.motionbuilder.generate_sequence_dict_from_anim_dict(...)`](#apidccmotionbuildergenerate_sequence_dict_from_anim_dict) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.generate_sequence_dict_from_anim_dict` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:231](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:231)
  - same_module: [`api.dcc.motionbuilder.get_camera_sequencer_data(...)`](#apidccmotionbuilderget_camera_sequencer_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)
  - same_module: [`api.dcc.motionbuilder.get_components_in_namespace(...)`](#apidccmotionbuilderget_components_in_namespace) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)
- Description: Extracts the shot name from the export path. If the 'shot' part does not contain digits, appends the next part. :param export_path: The export path (e.g., '/Game/Cinematics/Shot_Animation_01.fbx'). :return: The shot name (e.g., 'Shot_Animation' or 'Shot_01').
- Source: [sequence_utils.py:209](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:209)

### `api.dcc.motionbuilder.get_story_camera_shots(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_story_camera_shots`
- Signature: `get_story_camera_shots()`
- API names: `get_story_camera_shots`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_camera_sequencer_data(...)`](#apidccmotionbuilderget_camera_sequencer_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_camera_sequencer_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:39](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:39)
  - same_module: [`api.dcc.motionbuilder.get_cameras_from_selection(...)`](#apidccmotionbuilderget_cameras_from_selection) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_cameras_from_selection` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:128](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:128)
  - same_module: [`api.dcc.motionbuilder.get_components_in_namespace(...)`](#apidccmotionbuilderget_components_in_namespace) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_components_in_namespace` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:148](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:148)
  - same_module: [`api.dcc.motionbuilder.get_display_range(...)`](#apidccmotionbuilderget_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)
  - same_module: [`api.dcc.motionbuilder.get_export_node_data(...)`](#apidccmotionbuilderget_export_node_data) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_export_node_data` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:334](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:334)
- Description: Retrieves all clips in the Shot Track (kFBStoryTrackShot), including camera assignments. :return: a list of tuples: (clip_name, start_frame, end_frame, camera_name)
- Source: [sequence_utils.py:54](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:54)

### `api.dcc.motionbuilder.list_joints_by_namespace(...)`

- Target: `motionbuilder_tools.Animation.anim_export.anim_export.list_joints_by_namespace`
- Signature: `list_joints_by_namespace(namespace)`
- API names: `list_joints_by_namespace`
- Args:
  - `namespace`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.find_skinned_or_top_joints(...)`](#apidccmotionbuilderfind_skinned_or_top_joints) -> `motionbuilder_tools.Animation.anim_export.anim_export.find_skinned_or_top_joints` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:127](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:127)
- Description: Finds all joints in a namespace :param namespace: namespace to find joints for :return:
- Source: [anim_export.py:90](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:90)

### `api.dcc.motionbuilder.on_menu_click(...)`

- Target: `motionbuilder_tools.motionbuilder_menu.on_menu_click`
- Signature: `on_menu_click(control, event)`
- API names: `on_menu_click`
- Args:
  - `control`, required
  - `event`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.create_motionbuilder_menu(...)`](#apidccmotionbuildercreate_motionbuilder_menu) -> `motionbuilder_tools.motionbuilder_menu.create_motionbuilder_menu` - Shares module and name terms; may be useful in the same workflow.; source [motionbuilder_menu.py:6](C:/depot/tools/motionbuilder_tools/motionbuilder_menu.py:6)
- Source: [motionbuilder_menu.py:19](C:/depot/tools/motionbuilder_tools/motionbuilder_menu.py:19)

### `api.dcc.motionbuilder.plot_selected_models(...)`

- Target: `motionbuilder_tools.Animation.anim_export.anim_export.plot_selected_models`
- Signature: `plot_selected_models(models, start_frame, end_frame)`
- API names: `plot_selected_models`
- Args:
  - `models`, required
  - `start_frame`, required
  - `end_frame`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_selected_models(...)`](#apidccmotionbuilderget_selected_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.get_selected_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:167](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:167)
  - same_module: [`api.dcc.motionbuilder.deselect_all_models(...)`](#apidccmotionbuilderdeselect_all_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.deselect_all_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:177](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:177)
  - same_module: [`api.dcc.motionbuilder.select_models(...)`](#apidccmotionbuilderselect_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.select_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:187](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:187)
- Description: :param models: models to plot :param start_frame: start frame to plot :param end_frame: end frame to plot :return:
- Source: [anim_export.py:198](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:198)

### `api.dcc.motionbuilder.remove_file_open_callback(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.remove_file_open_callback`
- Signature: `remove_file_open_callback()`
- API names: `remove_file_open_callback`
- Args: none
- Related functions:
  - same_module: [`api.dcc.motionbuilder.add_file_open_callback(...)`](#apidccmotionbuilderadd_file_open_callback) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.add_file_open_callback` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:9](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:9)
- Source: [sequence_utils.py:21](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:21)

### `api.dcc.motionbuilder.select_models(...)`

- Target: `motionbuilder_tools.Animation.anim_export.anim_export.select_models`
- Signature: `select_models(models)`
- API names: `select_models`
- Args:
  - `models`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.deselect_all_models(...)`](#apidccmotionbuilderdeselect_all_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.deselect_all_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:177](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:177)
  - same_module: [`api.dcc.motionbuilder.get_selected_models(...)`](#apidccmotionbuilderget_selected_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.get_selected_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:167](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:167)
  - same_module: [`api.dcc.motionbuilder.plot_selected_models(...)`](#apidccmotionbuilderplot_selected_models) -> `motionbuilder_tools.Animation.anim_export.anim_export.plot_selected_models` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:198](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:198)
- Description: :param models: List of models :return:
- Source: [anim_export.py:187](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:187)

### `api.dcc.motionbuilder.set_display_range(...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.set_display_range`
- Signature: `set_display_range(start_frame, end_frame)`
- API names: `set_display_range`
- Args:
  - `start_frame`, required
  - `end_frame`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.get_display_range(...)`](#apidccmotionbuilderget_display_range) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.get_display_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:92](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:92)
  - same_module: [`api.dcc.motionbuilder.display_warning(...)`](#apidccmotionbuilderdisplay_warning) -> `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.display_warning` - Shares module and name terms; may be useful in the same workflow.; source [sequence_utils.py:120](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:120)
- Description: Sets the motionbuilder range to match the start and end frame listed :param start_frame: start frame to set the time slider with :param end_frame: end frame to set the time slider with :return:
- Source: [sequence_utils.py:101](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:101)

### `api.dcc.motionbuilder.call('motionbuilder_tools.Animation.anim_export.anim_export.find_top_joint', ...)`

- Target: `motionbuilder_tools.Animation.anim_export.anim_export.find_top_joint`
- Signature: `find_top_joint(model)`
- Name status: ambiguous; use the full target path.
- Args:
  - `model`, required
- Related functions:
  - same_module: [`api.dcc.motionbuilder.find_skinned_or_top_joints(...)`](#apidccmotionbuilderfind_skinned_or_top_joints) -> `motionbuilder_tools.Animation.anim_export.anim_export.find_skinned_or_top_joints` - Shares module and name terms; may be useful in the same workflow.; source [anim_export.py:127](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:127)
- Description: Finds the top joint of the model (simulating the 'origin' joint check). :param model: FBModel object to check :return: True if it's a top joint, False otherwise
- Source: [anim_export.py:115](C:/depot/tools/motionbuilder_tools/Animation/anim_export/anim_export.py:115)

### `api.dcc.motionbuilder.call('motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.find_top_joint', ...)`

- Target: `motionbuilder_tools.Cinematics.SequenceUI.sequence_utils.find_top_joint`
- Signature: `find_top_joint(model)`
- Name status: ambiguous; use the full target path.
- Args:
  - `model`, required
- Description: Finds the top joint of the model (simulating the 'origin' joint check). :param model: FBModel object to check :return: True if it's a top joint, False otherwise
- Source: [sequence_utils.py:198](C:/depot/tools/motionbuilder_tools/Cinematics/SequenceUI/sequence_utils.py:198)

## substance_painter

No public functions discovered.

## unity

No public functions discovered.

## unreal

### `api.dcc.unreal.add_actor_to_level_sequence(...)`

- Target: `unreal_tools.sequence_importer.add_actor_to_level_sequence`
- Signature: `add_actor_to_level_sequence(sequence_path, asset_path, actor=None, possessable=None, namespace=None)`
- API names: `add_actor_to_level_sequence`
- Args:
  - `sequence_path`, required
  - `asset_path`, required
  - `actor`, default `None`
  - `possessable`, default `None`
  - `namespace`, default `None`
- Related functions:
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_camera_anim_to_level_sequence(...)`](#apidccunrealadd_camera_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:368](C:/depot/tools/unreal_tools/sequence_importer.py:368)
  - same_module: [`api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`](#apidccunrealadd_skeletal_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)
- Description: Adds a blueprint actor and its components to a level sequence, creating and binding the actor and components. :param sequence_path: The level sequence path to which the actor and components will be added. :param asset_path: The path to the blueprint or skeletal mesh asset to load and spawn. :param actor: The actor to be added to the sequence (optional). If not provided, the actor will be spawned. :param possessable: The possessable to bind to the actor (optional). If not provided, it will be cre
- Source: [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)

### `api.dcc.unreal.add_anim_to_level_sequence(...)`

- Target: `unreal_tools.sequence_importer.add_anim_to_level_sequence`
- Signature: `add_anim_to_level_sequence(animation_path, anim_track, anim_section=None, start_frame=0)`
- API names: `add_anim_to_level_sequence`
- Args:
  - `animation_path`, required
  - `anim_track`, required
  - `anim_section`, default `None`
  - `start_frame`, default `0`
- Related functions:
  - same_module: [`api.dcc.unreal.add_camera_anim_to_level_sequence(...)`](#apidccunrealadd_camera_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:368](C:/depot/tools/unreal_tools/sequence_importer.py:368)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
  - same_module: [`api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`](#apidccunrealadd_skeletal_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)
- Description: Adds an animation to a track in the level sequence without shifting animation keyframe timing. Places the animation so its first keyframe starts exactly at start_frame. :param animation_path: Path to the animation asset. :param anim_track: The track to add the animation to. :param anim_section: Optional pre-existing section to add animation to. :param start_frame: Frame number to start the animation from. :return: The end frame of the animation.
- Source: [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)

### `api.dcc.unreal.add_anim_track_to_possessable(...)`

- Target: `unreal_tools.sequence_importer.add_anim_track_to_possessable`
- Signature: `add_anim_track_to_possessable(possessable, animation_asset_path=None)`
- API names: `add_anim_track_to_possessable`
- Args:
  - `possessable`, required
  - `animation_asset_path`, default `None`
- Related functions:
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_camera_anim_to_level_sequence(...)`](#apidccunrealadd_camera_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:368](C:/depot/tools/unreal_tools/sequence_importer.py:368)
  - same_module: [`api.dcc.unreal.add_shot_sequence_section_to_shot_track(...)`](#apidccunrealadd_shot_sequence_section_to_shot_track) -> `unreal_tools.sequence_importer.add_shot_sequence_section_to_shot_track` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:171](C:/depot/tools/unreal_tools/sequence_importer.py:171)
  - same_module: [`api.dcc.unreal.add_shot_track_to_master_sequence(...)`](#apidccunrealadd_shot_track_to_master_sequence) -> `unreal_tools.sequence_importer.add_shot_track_to_master_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:153](C:/depot/tools/unreal_tools/sequence_importer.py:153)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
- Description: Adds an animation track and section to the possessable, ensuring no duplicates. :param possessable: The possessable to which the animation track will be added. :param animation_asset_path: The path to the animation asset (e.g. FBX). :return: None
- Source: [sequence_importer.py:221](C:/depot/tools/unreal_tools/sequence_importer.py:221)

### `api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`

- Target: `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence`
- Signature: `add_blueprint_mesh_components_to_level_sequence(blueprint_path, sequence_path, actor, control_rig=True)`
- API names: `add_blueprint_mesh_components_to_level_sequence`
- Args:
  - `blueprint_path`, required
  - `sequence_path`, required
  - `actor`, required
  - `control_rig`, default `True`
- Related functions:
  - same_module: [`api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`](#apidccunrealadd_skeletal_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)
  - same_module: [`api.dcc.unreal.get_existing_blueprint_mesh_components_in_level_sequence(...)`](#apidccunrealget_existing_blueprint_mesh_components_in_level_sequence) -> `unreal_tools.sequence_importer.get_existing_blueprint_mesh_components_in_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1037](C:/depot/tools/unreal_tools/sequence_importer.py:1037)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
- Description: Adds specific mesh components from a blueprint actor to a level sequence. Adds 'Mesh' (typically CharacterMesh0), 'Body', and 'Face' components if they exist. :param blueprint_path: The blueprint asset path bound in the Level Sequence. :param sequence_path: The Level Sequence asset path. :param actor: (Optional) Actor to use. If None, the actor will be spawned from the blueprint. :param control_rig: (Optional) Whether to add control rig for track if it is found :return: A list of added SkeletalM
- Source: [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)

### `api.dcc.unreal.add_camera_actor_to_level_sequence(...)`

- Target: `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence`
- Signature: `add_camera_actor_to_level_sequence(sequence, camera_actor=None, camera_name=None)`
- API names: `add_camera_actor_to_level_sequence`
- Args:
  - `sequence`, required
  - `camera_actor`, default `None`
  - `camera_name`, default `None`
- Related functions:
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_camera_anim_to_level_sequence(...)`](#apidccunrealadd_camera_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:368](C:/depot/tools/unreal_tools/sequence_importer.py:368)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`](#apidccunrealadd_skeletal_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)
- Description: Adds a CineCameraActor to the level sequence. :param sequence: The LevelSequence asset where the camera should be added. :param camera_actor: (Optional) The CineCameraActor to add. If None, a new one will be created. :param camera_name: (Optional) Updates camera name otherwise uses default name :return: The CineCameraActor that was added to the sequence.
- Source: [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)

### `api.dcc.unreal.add_camera_anim_to_level_sequence(...)`

- Target: `unreal_tools.sequence_importer.add_camera_anim_to_level_sequence`
- Signature: `add_camera_anim_to_level_sequence(shot_sequence, camera_actor, world, export_path, anim_range)`
- API names: `add_camera_anim_to_level_sequence`
- Args:
  - `shot_sequence`, required
  - `camera_actor`, required
  - `world`, required
  - `export_path`, required
  - `anim_range`, required
- Related functions:
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`](#apidccunrealadd_skeletal_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)
- Description: Imports and applies a camera animation to a CineCameraActor inside a Level Sequence, and offsets the animation so that the first keyframe is at frame 0 of the sequence. Also adds a Camera Cut Track to switch the camera at frame 0. :param shot_sequence: The LevelSequence asset where the animation should be added. :param camera_actor: The CineCameraActor that will receive the animation. :param world: The Unreal world context. :param export_path: The path to the FBX file containing the camera anima
- Source: [sequence_importer.py:368](C:/depot/tools/unreal_tools/sequence_importer.py:368)

### `api.dcc.unreal.add_custom_events_to_blueprint(...)`

- Target: `unreal_tools.blueprint_events.add_custom_events_to_blueprint`
- Signature: `add_custom_events_to_blueprint(bp_path, event_names)`
- API names: `add_custom_events_to_blueprint`
- Args:
  - `bp_path`, required
  - `event_names`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_blueprint_graphs(...)`](#apidccunrealget_blueprint_graphs) -> `unreal_tools.blueprint_events.get_blueprint_graphs` - Shares module and name terms; may be useful in the same workflow.; source [blueprint_events.py:4](C:/depot/tools/unreal_tools/blueprint_events.py:4)
  - same_module: [`api.dcc.unreal.get_valid_events_from_import(...)`](#apidccunrealget_valid_events_from_import) -> `unreal_tools.blueprint_events.get_valid_events_from_import` - Shares module and name terms; may be useful in the same workflow.; source [blueprint_events.py:68](C:/depot/tools/unreal_tools/blueprint_events.py:68)
- Description: Ensures each name in `event_names` exists as a custom event inside the Blueprint at `bp_path`. If it doesn't exist, it creates the event. :param event_names: List of new attribute events to add to the bp :param bp_path: Path to the Blueprint to update (e.g., "/Game/Blueprints/MyBP")
- Source: [blueprint_events.py:14](C:/depot/tools/unreal_tools/blueprint_events.py:14)

### `api.dcc.unreal.add_parent_constraint_node(...)`

- Target: `unreal_tools.control_rig.add_parent_constraint_node`
- Signature: `add_parent_constraint_node(`
- API names: `add_parent_constraint_node`
- Args:
  - `control_rig_bp`, required
  - `graph` (unreal.RigVMGraph), required
  - `child_name` (str), required
  - `parent_name` (str), required
  - `child_type`, default `unreal.RigElementType.BONE`
  - `parent_type`, default `unreal.RigElementType.CONTROL`
  - `maintain_offset`, default `True`
  - `weight`, default `1.0`
  - `translation`, default `True`
  - `rotation`, default `True`
  - `scale`, default `False`
  - `node_position`, default `unreal.Vector2D(0.0, 0.0)`
  - `node_name`, default `'ParentConstraintNode'`
  - `input_node`, default `None`
- Source: [control_rig.py:20](C:/depot/tools/unreal_tools/control_rig.py:20)

### `api.dcc.unreal.add_shot_sequence_section_to_shot_track(...)`

- Target: `unreal_tools.sequence_importer.add_shot_sequence_section_to_shot_track`
- Signature: `add_shot_sequence_section_to_shot_track(shot_track, shot_sequence, start_frame, end_frame)`
- API names: `add_shot_sequence_section_to_shot_track`
- Args:
  - `shot_track`, required
  - `shot_sequence`, required
  - `start_frame`, required
  - `end_frame`, required
- Related functions:
  - same_module: [`api.dcc.unreal.add_shot_track_to_master_sequence(...)`](#apidccunrealadd_shot_track_to_master_sequence) -> `unreal_tools.sequence_importer.add_shot_track_to_master_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:153](C:/depot/tools/unreal_tools/sequence_importer.py:153)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_anim_track_to_possessable(...)`](#apidccunrealadd_anim_track_to_possessable) -> `unreal_tools.sequence_importer.add_anim_track_to_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:221](C:/depot/tools/unreal_tools/sequence_importer.py:221)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
- Description: Adds section for shot sequence to shot track if it doesn't exist :param shot_track: :param shot_sequence: :param start_frame: :param end_frame: :return:
- Source: [sequence_importer.py:171](C:/depot/tools/unreal_tools/sequence_importer.py:171)

### `api.dcc.unreal.add_shot_track_to_master_sequence(...)`

- Target: `unreal_tools.sequence_importer.add_shot_track_to_master_sequence`
- Signature: `add_shot_track_to_master_sequence(master_sequence)`
- API names: `add_shot_track_to_master_sequence`
- Args:
  - `master_sequence`, required
- Related functions:
  - same_module: [`api.dcc.unreal.add_shot_sequence_section_to_shot_track(...)`](#apidccunrealadd_shot_sequence_section_to_shot_track) -> `unreal_tools.sequence_importer.add_shot_sequence_section_to_shot_track` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:171](C:/depot/tools/unreal_tools/sequence_importer.py:171)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_anim_track_to_possessable(...)`](#apidccunrealadd_anim_track_to_possessable) -> `unreal_tools.sequence_importer.add_anim_track_to_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:221](C:/depot/tools/unreal_tools/sequence_importer.py:221)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
- Description: Adds shot track if it doesnt exist to master sequence :param master_sequence: Master sequence asset :return:
- Source: [sequence_importer.py:153](C:/depot/tools/unreal_tools/sequence_importer.py:153)

### `api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`

- Target: `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence`
- Signature: `add_skeletal_mesh_components_to_level_sequence(actor, possessable)`
- API names: `add_skeletal_mesh_components_to_level_sequence`
- Args:
  - `actor`, required
  - `possessable`, required
- Related functions:
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.get_existing_blueprint_mesh_components_in_level_sequence(...)`](#apidccunrealget_existing_blueprint_mesh_components_in_level_sequence) -> `unreal_tools.sequence_importer.get_existing_blueprint_mesh_components_in_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1037](C:/depot/tools/unreal_tools/sequence_importer.py:1037)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
- Description: Adds skeletal mesh components to the level sequence. :param actor: The actor containing the skeletal mesh components. :param possessable: The possessable associated with the actor. :return: A list of components added to the sequence.
- Source: [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)

### `api.dcc.unreal.add_unreal_startup_script(...)`

- Target: `unreal_tools.unreal_project_data.add_unreal_startup_script`
- Signature: `add_unreal_startup_script(uproject_path, script_path)`
- API names: `add_unreal_startup_script`
- Args:
  - `uproject_path`, required
  - `script_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.ensure_unreal_python_plugin_enabled(...)`](#apidccunrealensure_unreal_python_plugin_enabled) -> `unreal_tools.unreal_project_data.ensure_unreal_python_plugin_enabled` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:114](C:/depot/tools/unreal_tools/unreal_project_data.py:114)
  - same_module: [`api.dcc.unreal.get_latest_unreal_log(...)`](#apidccunrealget_latest_unreal_log) -> `unreal_tools.unreal_project_data.get_latest_unreal_log` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:88](C:/depot/tools/unreal_tools/unreal_project_data.py:88)
  - same_module: [`api.dcc.unreal.get_unreal_cmd_exe(...)`](#apidccunrealget_unreal_cmd_exe) -> `unreal_tools.unreal_project_data.get_unreal_cmd_exe` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:19](C:/depot/tools/unreal_tools/unreal_project_data.py:19)
  - same_module: [`api.dcc.unreal.get_unreal_install_path(...)`](#apidccunrealget_unreal_install_path) -> `unreal_tools.unreal_project_data.get_unreal_install_path` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:49](C:/depot/tools/unreal_tools/unreal_project_data.py:49)
- Description: Adds a startup script to DefaultEngine.ini for a given Unreal project. Appends to StartupScripts[N]=... under [PythonScriptPlugin.PythonScriptPluginSettings]. :param uproject_path: actual uproject path :param script_path: Full path to the Python script to add
- Source: [unreal_project_data.py:145](C:/depot/tools/unreal_tools/unreal_project_data.py:145)

### `api.dcc.unreal.add_variables_to_blueprint(...)`

- Target: `unreal_tools.blueprint_variables.add_variables_to_blueprint`
- Signature: `add_variables_to_blueprint(bp_path, variable_names)`
- API names: `add_variables_to_blueprint`
- Args:
  - `bp_path`, required
  - `variable_names`, required
- Description: Adds a list of variables to a Blueprint and exposes them to cinematics. :param bp_path: Blueprint path to add the variables to :param variable_names: List of variable names from curves
- Source: [blueprint_variables.py:18](C:/depot/tools/unreal_tools/blueprint_variables.py:18)

### `api.dcc.unreal.assign_origin_to_root(...)`

- Target: `unreal_tools.control_rig.assign_origin_to_root`
- Signature: `assign_origin_to_root(controller, root_joint)`
- API names: `assign_origin_to_root`
- Args:
  - `controller`, required
  - `root_joint`, required
- Description: :param controller: control_rig_bp.get_modular_rig_controller() :param root_joint: actual top joint name :return:
- Source: [control_rig.py:514](C:/depot/tools/unreal_tools/control_rig.py:514)

### `api.dcc.unreal.build_arm_modules(...)`

- Target: `unreal_tools.control_rig.build_arm_modules`
- Signature: `build_arm_modules(controller, arm_joints)`
- API names: `build_arm_modules`
- Args:
  - `controller`, required
  - `arm_joints`, required
- Related functions:
  - same_module: [`api.dcc.unreal.build_feet_modules(...)`](#apidccunrealbuild_feet_modules) -> `unreal_tools.control_rig.build_feet_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:459](C:/depot/tools/unreal_tools/control_rig.py:459)
  - same_module: [`api.dcc.unreal.build_finger_modules(...)`](#apidccunrealbuild_finger_modules) -> `unreal_tools.control_rig.build_finger_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:306](C:/depot/tools/unreal_tools/control_rig.py:306)
  - same_module: [`api.dcc.unreal.build_leg_modules(...)`](#apidccunrealbuild_leg_modules) -> `unreal_tools.control_rig.build_leg_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:208](C:/depot/tools/unreal_tools/control_rig.py:208)
  - same_module: [`api.dcc.unreal.build_shoulder_modules(...)`](#apidccunrealbuild_shoulder_modules) -> `unreal_tools.control_rig.build_shoulder_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:356](C:/depot/tools/unreal_tools/control_rig.py:356)
  - same_module: [`api.dcc.unreal.build_modular_fk_control_rig(...)`](#apidccunrealbuild_modular_fk_control_rig) -> `unreal_tools.control_rig.build_modular_fk_control_rig` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:556](C:/depot/tools/unreal_tools/control_rig.py:556)
- Description: :param controller: control_rig_bp.get_modular_rig_controller() :param arm_joints: :return:
- Source: [control_rig.py:386](C:/depot/tools/unreal_tools/control_rig.py:386)

### `api.dcc.unreal.build_feet_modules(...)`

- Target: `unreal_tools.control_rig.build_feet_modules`
- Signature: `build_feet_modules(controller, foot_joints)`
- API names: `build_feet_modules`
- Args:
  - `controller`, required
  - `foot_joints`, required
- Related functions:
  - same_module: [`api.dcc.unreal.build_arm_modules(...)`](#apidccunrealbuild_arm_modules) -> `unreal_tools.control_rig.build_arm_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:386](C:/depot/tools/unreal_tools/control_rig.py:386)
  - same_module: [`api.dcc.unreal.build_finger_modules(...)`](#apidccunrealbuild_finger_modules) -> `unreal_tools.control_rig.build_finger_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:306](C:/depot/tools/unreal_tools/control_rig.py:306)
  - same_module: [`api.dcc.unreal.build_leg_modules(...)`](#apidccunrealbuild_leg_modules) -> `unreal_tools.control_rig.build_leg_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:208](C:/depot/tools/unreal_tools/control_rig.py:208)
  - same_module: [`api.dcc.unreal.build_shoulder_modules(...)`](#apidccunrealbuild_shoulder_modules) -> `unreal_tools.control_rig.build_shoulder_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:356](C:/depot/tools/unreal_tools/control_rig.py:356)
  - same_module: [`api.dcc.unreal.build_modular_fk_control_rig(...)`](#apidccunrealbuild_modular_fk_control_rig) -> `unreal_tools.control_rig.build_modular_fk_control_rig` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:556](C:/depot/tools/unreal_tools/control_rig.py:556)
- Description: :param controller: control_rig_bp.get_modular_rig_controller() :param foot_joints: :return:
- Source: [control_rig.py:459](C:/depot/tools/unreal_tools/control_rig.py:459)

### `api.dcc.unreal.build_finger_modules(...)`

- Target: `unreal_tools.control_rig.build_finger_modules`
- Signature: `build_finger_modules(controller, joint_map)`
- API names: `build_finger_modules`
- Args:
  - `controller`, required
  - `joint_map`, required
- Related functions:
  - same_module: [`api.dcc.unreal.build_arm_modules(...)`](#apidccunrealbuild_arm_modules) -> `unreal_tools.control_rig.build_arm_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:386](C:/depot/tools/unreal_tools/control_rig.py:386)
  - same_module: [`api.dcc.unreal.build_feet_modules(...)`](#apidccunrealbuild_feet_modules) -> `unreal_tools.control_rig.build_feet_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:459](C:/depot/tools/unreal_tools/control_rig.py:459)
  - same_module: [`api.dcc.unreal.build_leg_modules(...)`](#apidccunrealbuild_leg_modules) -> `unreal_tools.control_rig.build_leg_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:208](C:/depot/tools/unreal_tools/control_rig.py:208)
  - same_module: [`api.dcc.unreal.build_shoulder_modules(...)`](#apidccunrealbuild_shoulder_modules) -> `unreal_tools.control_rig.build_shoulder_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:356](C:/depot/tools/unreal_tools/control_rig.py:356)
  - same_module: [`api.dcc.unreal.build_modular_fk_control_rig(...)`](#apidccunrealbuild_modular_fk_control_rig) -> `unreal_tools.control_rig.build_modular_fk_control_rig` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:556](C:/depot/tools/unreal_tools/control_rig.py:556)
- Description: :param controller: control_rig_bp.get_modular_rig_controller() :param joint_map: :return:
- Source: [control_rig.py:306](C:/depot/tools/unreal_tools/control_rig.py:306)

### `api.dcc.unreal.build_import_options(...)`

- Target: `unreal_tools.sequence_importer.build_import_options`
- Signature: `build_import_options(skeleton_path)`
- API names: `build_import_options`
- Args:
  - `skeleton_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.import_animation(...)`](#apidccunrealimport_animation) -> `unreal_tools.sequence_importer.import_animation` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:851](C:/depot/tools/unreal_tools/sequence_importer.py:851)
  - same_module: [`api.dcc.unreal.import_gameplay_animations_from_json(...)`](#apidccunrealimport_gameplay_animations_from_json) -> `unreal_tools.sequence_importer.import_gameplay_animations_from_json` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:812](C:/depot/tools/unreal_tools/sequence_importer.py:812)
- Description: Creates the import options for importing an animation in Unreal Engine. :param skeleton_path: Path to the skeleton asset for the animation. :return: Unreal FBX import UI object with specified settings.
- Source: [sequence_importer.py:882](C:/depot/tools/unreal_tools/sequence_importer.py:882)

### `api.dcc.unreal.build_leg_modules(...)`

- Target: `unreal_tools.control_rig.build_leg_modules`
- Signature: `build_leg_modules(controller, leg_joints, spine_joints)`
- API names: `build_leg_modules`
- Args:
  - `controller`, required
  - `leg_joints`, required
  - `spine_joints`, required
- Related functions:
  - same_module: [`api.dcc.unreal.build_arm_modules(...)`](#apidccunrealbuild_arm_modules) -> `unreal_tools.control_rig.build_arm_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:386](C:/depot/tools/unreal_tools/control_rig.py:386)
  - same_module: [`api.dcc.unreal.build_feet_modules(...)`](#apidccunrealbuild_feet_modules) -> `unreal_tools.control_rig.build_feet_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:459](C:/depot/tools/unreal_tools/control_rig.py:459)
  - same_module: [`api.dcc.unreal.build_finger_modules(...)`](#apidccunrealbuild_finger_modules) -> `unreal_tools.control_rig.build_finger_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:306](C:/depot/tools/unreal_tools/control_rig.py:306)
  - same_module: [`api.dcc.unreal.build_shoulder_modules(...)`](#apidccunrealbuild_shoulder_modules) -> `unreal_tools.control_rig.build_shoulder_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:356](C:/depot/tools/unreal_tools/control_rig.py:356)
  - same_module: [`api.dcc.unreal.build_modular_fk_control_rig(...)`](#apidccunrealbuild_modular_fk_control_rig) -> `unreal_tools.control_rig.build_modular_fk_control_rig` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:556](C:/depot/tools/unreal_tools/control_rig.py:556)
- Description: :param controller: control_rig_bp.get_modular_rig_controller() :param leg_joints: :param spine_joints: :return:
- Source: [control_rig.py:208](C:/depot/tools/unreal_tools/control_rig.py:208)

### `api.dcc.unreal.build_modular_fk_control_rig(...)`

- Target: `unreal_tools.control_rig.build_modular_fk_control_rig`
- Signature: `build_modular_fk_control_rig(skeletal_mesh_name, rig_name, joint_map)`
- API names: `build_modular_fk_control_rig`
- Args:
  - `skeletal_mesh_name`, required
  - `rig_name`, required
  - `joint_map`, required
- Related functions:
  - same_module: [`api.dcc.unreal.create_control_rig_from_asset(...)`](#apidccunrealcreate_control_rig_from_asset) -> `unreal_tools.control_rig.create_control_rig_from_asset` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:5](C:/depot/tools/unreal_tools/control_rig.py:5)
  - same_module: [`api.dcc.unreal.build_arm_modules(...)`](#apidccunrealbuild_arm_modules) -> `unreal_tools.control_rig.build_arm_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:386](C:/depot/tools/unreal_tools/control_rig.py:386)
  - same_module: [`api.dcc.unreal.build_feet_modules(...)`](#apidccunrealbuild_feet_modules) -> `unreal_tools.control_rig.build_feet_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:459](C:/depot/tools/unreal_tools/control_rig.py:459)
  - same_module: [`api.dcc.unreal.build_finger_modules(...)`](#apidccunrealbuild_finger_modules) -> `unreal_tools.control_rig.build_finger_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:306](C:/depot/tools/unreal_tools/control_rig.py:306)
  - same_module: [`api.dcc.unreal.build_leg_modules(...)`](#apidccunrealbuild_leg_modules) -> `unreal_tools.control_rig.build_leg_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:208](C:/depot/tools/unreal_tools/control_rig.py:208)
- Description: :param skeletal_mesh_name: :param rig_name: :param joint_map: :return:
- Source: [control_rig.py:556](C:/depot/tools/unreal_tools/control_rig.py:556)

### `api.dcc.unreal.build_neck_module(...)`

- Target: `unreal_tools.control_rig.build_neck_module`
- Signature: `build_neck_module(controller, neck_joints)`
- API names: `build_neck_module`
- Args:
  - `controller`, required
  - `neck_joints`, required
- Related functions:
  - same_module: [`api.dcc.unreal.build_spine_module(...)`](#apidccunrealbuild_spine_module) -> `unreal_tools.control_rig.build_spine_module` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:165](C:/depot/tools/unreal_tools/control_rig.py:165)
  - same_module: [`api.dcc.unreal.build_arm_modules(...)`](#apidccunrealbuild_arm_modules) -> `unreal_tools.control_rig.build_arm_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:386](C:/depot/tools/unreal_tools/control_rig.py:386)
  - same_module: [`api.dcc.unreal.build_feet_modules(...)`](#apidccunrealbuild_feet_modules) -> `unreal_tools.control_rig.build_feet_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:459](C:/depot/tools/unreal_tools/control_rig.py:459)
  - same_module: [`api.dcc.unreal.build_finger_modules(...)`](#apidccunrealbuild_finger_modules) -> `unreal_tools.control_rig.build_finger_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:306](C:/depot/tools/unreal_tools/control_rig.py:306)
  - same_module: [`api.dcc.unreal.build_leg_modules(...)`](#apidccunrealbuild_leg_modules) -> `unreal_tools.control_rig.build_leg_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:208](C:/depot/tools/unreal_tools/control_rig.py:208)
- Description: :param controller: control_rig_bp.get_modular_rig_controller() :param neck_joints: :return:
- Source: [control_rig.py:262](C:/depot/tools/unreal_tools/control_rig.py:262)

### `api.dcc.unreal.build_shoulder_modules(...)`

- Target: `unreal_tools.control_rig.build_shoulder_modules`
- Signature: `build_shoulder_modules(controller)`
- API names: `build_shoulder_modules`
- Args:
  - `controller`, required
- Related functions:
  - same_module: [`api.dcc.unreal.build_arm_modules(...)`](#apidccunrealbuild_arm_modules) -> `unreal_tools.control_rig.build_arm_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:386](C:/depot/tools/unreal_tools/control_rig.py:386)
  - same_module: [`api.dcc.unreal.build_feet_modules(...)`](#apidccunrealbuild_feet_modules) -> `unreal_tools.control_rig.build_feet_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:459](C:/depot/tools/unreal_tools/control_rig.py:459)
  - same_module: [`api.dcc.unreal.build_finger_modules(...)`](#apidccunrealbuild_finger_modules) -> `unreal_tools.control_rig.build_finger_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:306](C:/depot/tools/unreal_tools/control_rig.py:306)
  - same_module: [`api.dcc.unreal.build_leg_modules(...)`](#apidccunrealbuild_leg_modules) -> `unreal_tools.control_rig.build_leg_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:208](C:/depot/tools/unreal_tools/control_rig.py:208)
  - same_module: [`api.dcc.unreal.build_modular_fk_control_rig(...)`](#apidccunrealbuild_modular_fk_control_rig) -> `unreal_tools.control_rig.build_modular_fk_control_rig` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:556](C:/depot/tools/unreal_tools/control_rig.py:556)
- Description: :param controller: control_rig_bp.get_modular_rig_controller() :return:
- Source: [control_rig.py:356](C:/depot/tools/unreal_tools/control_rig.py:356)

### `api.dcc.unreal.build_spine_module(...)`

- Target: `unreal_tools.control_rig.build_spine_module`
- Signature: `build_spine_module(controller, spine_joints)`
- API names: `build_spine_module`
- Args:
  - `controller`, required
  - `spine_joints`, required
- Related functions:
  - same_module: [`api.dcc.unreal.build_neck_module(...)`](#apidccunrealbuild_neck_module) -> `unreal_tools.control_rig.build_neck_module` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:262](C:/depot/tools/unreal_tools/control_rig.py:262)
  - same_module: [`api.dcc.unreal.build_arm_modules(...)`](#apidccunrealbuild_arm_modules) -> `unreal_tools.control_rig.build_arm_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:386](C:/depot/tools/unreal_tools/control_rig.py:386)
  - same_module: [`api.dcc.unreal.build_feet_modules(...)`](#apidccunrealbuild_feet_modules) -> `unreal_tools.control_rig.build_feet_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:459](C:/depot/tools/unreal_tools/control_rig.py:459)
  - same_module: [`api.dcc.unreal.build_finger_modules(...)`](#apidccunrealbuild_finger_modules) -> `unreal_tools.control_rig.build_finger_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:306](C:/depot/tools/unreal_tools/control_rig.py:306)
  - same_module: [`api.dcc.unreal.build_leg_modules(...)`](#apidccunrealbuild_leg_modules) -> `unreal_tools.control_rig.build_leg_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:208](C:/depot/tools/unreal_tools/control_rig.py:208)
- Description: :param controller: control_rig_bp.get_modular_rig_controller() :param spine_joints: :return:
- Source: [control_rig.py:165](C:/depot/tools/unreal_tools/control_rig.py:165)

### `api.dcc.unreal.compile_blueprint(...)`

- Target: `unreal_tools.blueprint.compile_blueprint`
- Signature: `compile_blueprint(asset_path)`
- API names: `compile_blueprint`
- Args:
  - `asset_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.scan_blueprint(...)`](#apidccunrealscan_blueprint) -> `unreal_tools.blueprint.scan_blueprint` - Shares module and name terms; may be useful in the same workflow.; source [blueprint.py:15](C:/depot/tools/unreal_tools/blueprint.py:15)
- Source: [blueprint.py:63](C:/depot/tools/unreal_tools/blueprint.py:63)

### `api.dcc.unreal.connect_to_forward_solve(...)`

- Target: `unreal_tools.control_rig.connect_to_forward_solve`
- Signature: `connect_to_forward_solve(controller, graph, unit_node, forward_entry_node=None)`
- API names: `connect_to_forward_solve`
- Args:
  - `controller`, required
  - `graph`, required
  - `unit_node`, required
  - `forward_entry_node`, default `None`
- Description: :param controller: :param graph: :param unit_node: :param forward_entry_node: :return:
- Source: [control_rig.py:70](C:/depot/tools/unreal_tools/control_rig.py:70)

### `api.dcc.unreal.create_cinematic_sequence(...)`

- Target: `unreal_tools.sequence_importer.create_cinematic_sequence`
- Signature: `create_cinematic_sequence(anim_dict, sequence_name, destination_path="/Game/Cinematics")`
- API names: `create_cinematic_sequence`
- Args:
  - `anim_dict`, required
  - `sequence_name`, required
  - `destination_path`, default `'/Game/Cinematics'`
- Related functions:
  - same_module: [`api.dcc.unreal.call('unreal_tools.sequence_importer.create_cinematic_sequence_from_json', ...)`](#apidccunrealcallunreal_toolssequence_importercreate_cinematic_sequence_from_json) -> `unreal_tools.sequence_importer.create_cinematic_sequence_from_json` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1369](C:/depot/tools/unreal_tools/sequence_importer.py:1369)
  - same_module: [`api.dcc.unreal.create_level_sequence(...)`](#apidccunrealcreate_level_sequence) -> `unreal_tools.sequence_importer.create_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1343](C:/depot/tools/unreal_tools/sequence_importer.py:1343)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
- Description: Creates a master cinematic sequence and sub-sequences for each shot. Imports animations and adds actors accordingly. :param anim_dict: anim dictionary containing animation data, generated from maya export :param sequence_name: name of master sequence :param destination_path: Path to the directory where the cinematic sequence will be saved in Unreal Engine. :return: Path to the created master sequence.
- Source: [sequence_importer.py:1393](C:/depot/tools/unreal_tools/sequence_importer.py:1393)

### `api.dcc.unreal.create_control_rig_from_asset(...)`

- Target: `unreal_tools.control_rig.create_control_rig_from_asset`
- Signature: `create_control_rig_from_asset(asset_path)`
- API names: `create_control_rig_from_asset`
- Args:
  - `asset_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.build_modular_fk_control_rig(...)`](#apidccunrealbuild_modular_fk_control_rig) -> `unreal_tools.control_rig.build_modular_fk_control_rig` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:556](C:/depot/tools/unreal_tools/control_rig.py:556)
- Source: [control_rig.py:5](C:/depot/tools/unreal_tools/control_rig.py:5)

### `api.dcc.unreal.create_from_template(...)`

- Target: `unreal_tools.blueprint.create_from_template`
- Signature: `create_from_template(template, asset_path, parent_class="", parameters=None)`
- API names: `create_from_template`
- Args:
  - `template`, required
  - `asset_path`, required
  - `parent_class`, default `''`
  - `parameters`, default `None`
- Source: [blueprint.py:71](C:/depot/tools/unreal_tools/blueprint.py:71)

### `api.dcc.unreal.create_level_sequence(...)`

- Target: `unreal_tools.sequence_importer.create_level_sequence`
- Signature: `create_level_sequence(sequence_name, destination_path="/Game/Cinematics/")`
- API names: `create_level_sequence`
- Args:
  - `sequence_name`, required
  - `destination_path`, default `'/Game/Cinematics/'`
- Related functions:
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
  - same_module: [`api.dcc.unreal.add_camera_anim_to_level_sequence(...)`](#apidccunrealadd_camera_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:368](C:/depot/tools/unreal_tools/sequence_importer.py:368)
- Description: Creates a new Level Sequence asset in the specified path. :param sequence_name: Name for the new Level Sequence. :param destination_path: Path where the Level Sequence will be created. :return: List containing the created Level Sequence asset and a boolean indicating if it was pre-existing.
- Source: [sequence_importer.py:1343](C:/depot/tools/unreal_tools/sequence_importer.py:1343)

### `api.dcc.unreal.create_or_update_animation_blueprint(...)`

- Target: `unreal_tools.animation.create_or_update_animation_blueprint`
- Signature: `create_or_update_animation_blueprint(skeleton_path, asset_path, template="locomotion")`
- API names: `create_or_update_animation_blueprint`
- Args:
  - `skeleton_path`, required
  - `asset_path`, required
  - `template`, default `'locomotion'`
- Source: [animation.py:27](C:/depot/tools/unreal_tools/animation.py:27)

### `api.dcc.unreal.detect_new_custom_attrs_from_animation(...)`

- Target: `unreal_tools.blueprint_variables.detect_new_custom_attrs_from_animation`
- Signature: `detect_new_custom_attrs_from_animation(anim_path, bp_path)`
- API names: `detect_new_custom_attrs_from_animation`
- Args:
  - `anim_path`, required
  - `bp_path`, required
- Description: :param anim_path: Path to Anim Sequence :param bp_path: Path to the Blueprint to query and edit :return:
- Source: [blueprint_variables.py:3](C:/depot/tools/unreal_tools/blueprint_variables.py:3)

### `api.dcc.unreal.ensure_unreal_python_plugin_enabled(...)`

- Target: `unreal_tools.unreal_project_data.ensure_unreal_python_plugin_enabled`
- Signature: `ensure_unreal_python_plugin_enabled(uproject_path)`
- API names: `ensure_unreal_python_plugin_enabled`
- Args:
  - `uproject_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.add_unreal_startup_script(...)`](#apidccunrealadd_unreal_startup_script) -> `unreal_tools.unreal_project_data.add_unreal_startup_script` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:145](C:/depot/tools/unreal_tools/unreal_project_data.py:145)
  - same_module: [`api.dcc.unreal.get_latest_unreal_log(...)`](#apidccunrealget_latest_unreal_log) -> `unreal_tools.unreal_project_data.get_latest_unreal_log` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:88](C:/depot/tools/unreal_tools/unreal_project_data.py:88)
  - same_module: [`api.dcc.unreal.get_unreal_cmd_exe(...)`](#apidccunrealget_unreal_cmd_exe) -> `unreal_tools.unreal_project_data.get_unreal_cmd_exe` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:19](C:/depot/tools/unreal_tools/unreal_project_data.py:19)
  - same_module: [`api.dcc.unreal.get_unreal_install_path(...)`](#apidccunrealget_unreal_install_path) -> `unreal_tools.unreal_project_data.get_unreal_install_path` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:49](C:/depot/tools/unreal_tools/unreal_project_data.py:49)
- Description: Enables PythonScriptPlugin in the .uproject if the project does not already declare it. Unreal needs this plugin for startup Python scripts.
- Source: [unreal_project_data.py:114](C:/depot/tools/unreal_tools/unreal_project_data.py:114)

### `api.dcc.unreal.extract_shot_number_from_path(...)`

- Target: `unreal_tools.sequence_importer.extract_shot_number_from_path`
- Signature: `extract_shot_number_from_path(export_path)`
- API names: `extract_shot_number_from_path`
- Args:
  - `export_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.add_shot_sequence_section_to_shot_track(...)`](#apidccunrealadd_shot_sequence_section_to_shot_track) -> `unreal_tools.sequence_importer.add_shot_sequence_section_to_shot_track` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:171](C:/depot/tools/unreal_tools/sequence_importer.py:171)
  - same_module: [`api.dcc.unreal.add_shot_track_to_master_sequence(...)`](#apidccunrealadd_shot_track_to_master_sequence) -> `unreal_tools.sequence_importer.add_shot_track_to_master_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:153](C:/depot/tools/unreal_tools/sequence_importer.py:153)
  - same_module: [`api.dcc.unreal.call('unreal_tools.sequence_importer.create_cinematic_sequence_from_json', ...)`](#apidccunrealcallunreal_toolssequence_importercreate_cinematic_sequence_from_json) -> `unreal_tools.sequence_importer.create_cinematic_sequence_from_json` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1369](C:/depot/tools/unreal_tools/sequence_importer.py:1369)
  - same_module: [`api.dcc.unreal.call('unreal_tools.sequence_importer.find_uasset_path', ...)`](#apidccunrealcallunreal_toolssequence_importerfind_uasset_path) -> `unreal_tools.sequence_importer.find_uasset_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1152](C:/depot/tools/unreal_tools/sequence_importer.py:1152)
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
- Description: Extracts the shot number from the export path, which contains 'shot' as part of its name. :param export_path: The export path containing the shot number (e.g., "MyAnimation_Shot1_Anim.fbx"). :return: The shot number as an integer (e.g., 1 for "Shot1"), or None if not found.
- Source: [sequence_importer.py:795](C:/depot/tools/unreal_tools/sequence_importer.py:795)

### `api.dcc.unreal.find_actor_by_blueprint_or_skeletal_mesh(...)`

- Target: `unreal_tools.sequence_importer.find_actor_by_blueprint_or_skeletal_mesh`
- Signature: `find_actor_by_blueprint_or_skeletal_mesh(blueprint_path=None, skeletal_mesh_path=None, shot_sequence=None, namespace=None)`
- API names: `find_actor_by_blueprint_or_skeletal_mesh`
- Args:
  - `blueprint_path`, default `None`
  - `skeletal_mesh_path`, default `None`
  - `shot_sequence`, default `None`
  - `namespace`, default `None`
- Related functions:
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`](#apidccunrealadd_skeletal_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)
  - same_module: [`api.dcc.unreal.find_possessable_for_actor(...)`](#apidccunrealfind_possessable_for_actor) -> `unreal_tools.sequence_importer.find_possessable_for_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1226](C:/depot/tools/unreal_tools/sequence_importer.py:1226)
  - same_module: [`api.dcc.unreal.find_skeletal_meshes_using_skeleton(...)`](#apidccunrealfind_skeletal_meshes_using_skeleton) -> `unreal_tools.sequence_importer.find_skeletal_meshes_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:546](C:/depot/tools/unreal_tools/sequence_importer.py:546)
  - same_module: [`api.dcc.unreal.get_existing_blueprint_mesh_components_in_level_sequence(...)`](#apidccunrealget_existing_blueprint_mesh_components_in_level_sequence) -> `unreal_tools.sequence_importer.get_existing_blueprint_mesh_components_in_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1037](C:/depot/tools/unreal_tools/sequence_importer.py:1037)
- Description: Helper function to find an actor in the current level by its blueprint or directly by SkeletalMeshActor. It also returns the possessable for the found actor and the actor's components. :param blueprint_path: (Optional) The path to the blueprint asset. Can be None if searching for SkeletalMeshActor. :param skeletal_mesh_path: (Optional) The path to the Skeletal Mesh asset if no blueprint exists. :param shot_sequence: The LevelSequence to search for the possessable. :return: Tuple (actor, possessa
- Source: [sequence_importer.py:1174](C:/depot/tools/unreal_tools/sequence_importer.py:1174)

### `api.dcc.unreal.find_asset_path_by_name(...)`

- Target: `unreal_tools.assets.find_asset_path_by_name`
- Signature: `find_asset_path_by_name(file_name, expected_class="", directory="/Game", allow_engine=False)`
- API names: `find_asset_path_by_name`, `find_assets`
- Args:
  - `file_name`, required
  - `expected_class`, default `''`
  - `directory`, default `'/Game'`
  - `allow_engine`, default `False`
- Related functions:
  - same_module: [`api.dcc.unreal.inspect_asset(...)`](#apidccunrealinspect_asset) -> `unreal_tools.assets.inspect_asset` - Shares module and name terms; may be useful in the same workflow.; source [assets.py:23](C:/depot/tools/unreal_tools/assets.py:23)
  - same_module: [`api.dcc.unreal.resolve_asset(...)`](#apidccunrealresolve_asset) -> `unreal_tools.assets.resolve_asset` - Shares module and name terms; may be useful in the same workflow.; source [assets.py:121](C:/depot/tools/unreal_tools/assets.py:121)
- Description: Resolve a user-facing Unreal asset name/path to a package path. This is the shared version of the old `find_uasset_path` pattern. It accepts `/Game/...`, `/Game/Asset.Asset`, or a bare asset name such as `Run_Fwd`. Returns the package path form expected by most EditorAssetLibrary/load_asset APIs, for example `/Game/Animations/Run_Fwd`.
- Source: [assets.py:45](C:/depot/tools/unreal_tools/assets.py:45)

### `api.dcc.unreal.find_binding_for_component(...)`

- Target: `unreal_tools.sequence_importer.find_binding_for_component`
- Signature: `find_binding_for_component(sequence_path, component_name)`
- API names: `find_binding_for_component`
- Args:
  - `sequence_path`, required
  - `component_name`, required
- Related functions:
  - same_module: [`api.dcc.unreal.find_camera_component_in_scene(...)`](#apidccunrealfind_camera_component_in_scene) -> `unreal_tools.sequence_importer.find_camera_component_in_scene` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1263](C:/depot/tools/unreal_tools/sequence_importer.py:1263)
  - same_module: [`api.dcc.unreal.find_possessable_for_actor(...)`](#apidccunrealfind_possessable_for_actor) -> `unreal_tools.sequence_importer.find_possessable_for_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1226](C:/depot/tools/unreal_tools/sequence_importer.py:1226)
  - same_module: [`api.dcc.unreal.find_actor_by_blueprint_or_skeletal_mesh(...)`](#apidccunrealfind_actor_by_blueprint_or_skeletal_mesh) -> `unreal_tools.sequence_importer.find_actor_by_blueprint_or_skeletal_mesh` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1174](C:/depot/tools/unreal_tools/sequence_importer.py:1174)
  - same_module: [`api.dcc.unreal.find_skeletal_meshes_using_skeleton(...)`](#apidccunrealfind_skeletal_meshes_using_skeleton) -> `unreal_tools.sequence_importer.find_skeletal_meshes_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:546](C:/depot/tools/unreal_tools/sequence_importer.py:546)
  - same_module: [`api.dcc.unreal.call('unreal_tools.sequence_importer.find_uasset_path', ...)`](#apidccunrealcallunreal_toolssequence_importerfind_uasset_path) -> `unreal_tools.sequence_importer.find_uasset_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1152](C:/depot/tools/unreal_tools/sequence_importer.py:1152)
- Description: Finds the MovieSceneBinding in the Level Sequence located at the given path that corresponds to the specified component in the current level. :param sequence_path: The path to the Level Sequence asset in the content browser. :param component_name: The component name to match against the Level Sequence bindings. :return: The MovieSceneBinding if found, else None.
- Source: [sequence_importer.py:1241](C:/depot/tools/unreal_tools/sequence_importer.py:1241)

### `api.dcc.unreal.find_camera_component_in_scene(...)`

- Target: `unreal_tools.sequence_importer.find_camera_component_in_scene`
- Signature: `find_camera_component_in_scene()`
- API names: `find_camera_component_in_scene`
- Args: none
- Related functions:
  - same_module: [`api.dcc.unreal.find_binding_for_component(...)`](#apidccunrealfind_binding_for_component) -> `unreal_tools.sequence_importer.find_binding_for_component` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1241](C:/depot/tools/unreal_tools/sequence_importer.py:1241)
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
  - same_module: [`api.dcc.unreal.add_camera_anim_to_level_sequence(...)`](#apidccunrealadd_camera_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:368](C:/depot/tools/unreal_tools/sequence_importer.py:368)
  - same_module: [`api.dcc.unreal.find_actor_by_blueprint_or_skeletal_mesh(...)`](#apidccunrealfind_actor_by_blueprint_or_skeletal_mesh) -> `unreal_tools.sequence_importer.find_actor_by_blueprint_or_skeletal_mesh` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1174](C:/depot/tools/unreal_tools/sequence_importer.py:1174)
  - same_module: [`api.dcc.unreal.find_possessable_for_actor(...)`](#apidccunrealfind_possessable_for_actor) -> `unreal_tools.sequence_importer.find_possessable_for_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1226](C:/depot/tools/unreal_tools/sequence_importer.py:1226)
- Description: Finds the CineCameraActor in the scene that should be used for the camera animation. :return: The CineCameraActor component if found, else None.
- Source: [sequence_importer.py:1263](C:/depot/tools/unreal_tools/sequence_importer.py:1263)

### `api.dcc.unreal.find_compatible_animations(...)`

- Target: `unreal_tools.animation.find_compatible_animations`
- Signature: `find_compatible_animations(skeleton_path, directory="/Game/")`
- API names: `find_compatible_animations`
- Args:
  - `skeleton_path`, required
  - `directory`, default `'/Game/'`
- Source: [animation.py:8](C:/depot/tools/unreal_tools/animation.py:8)

### `api.dcc.unreal.find_possessable_for_actor(...)`

- Target: `unreal_tools.sequence_importer.find_possessable_for_actor`
- Signature: `find_possessable_for_actor(actor, shot_sequence)`
- API names: `find_possessable_for_actor`
- Args:
  - `actor`, required
  - `shot_sequence`, required
- Related functions:
  - same_module: [`api.dcc.unreal.find_actor_by_blueprint_or_skeletal_mesh(...)`](#apidccunrealfind_actor_by_blueprint_or_skeletal_mesh) -> `unreal_tools.sequence_importer.find_actor_by_blueprint_or_skeletal_mesh` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1174](C:/depot/tools/unreal_tools/sequence_importer.py:1174)
  - same_module: [`api.dcc.unreal.find_binding_for_component(...)`](#apidccunrealfind_binding_for_component) -> `unreal_tools.sequence_importer.find_binding_for_component` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1241](C:/depot/tools/unreal_tools/sequence_importer.py:1241)
  - same_module: [`api.dcc.unreal.get_actor_from_possessable(...)`](#apidccunrealget_actor_from_possessable) -> `unreal_tools.sequence_importer.get_actor_from_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:961](C:/depot/tools/unreal_tools/sequence_importer.py:961)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_track_to_possessable(...)`](#apidccunrealadd_anim_track_to_possessable) -> `unreal_tools.sequence_importer.add_anim_track_to_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:221](C:/depot/tools/unreal_tools/sequence_importer.py:221)
- Description: Find the possessable for the given actor in the provided shot sequence. :param actor: The actor to search for. :param shot_sequence: The LevelSequence to search within. :return: The possessable object if found, otherwise None.
- Source: [sequence_importer.py:1226](C:/depot/tools/unreal_tools/sequence_importer.py:1226)

### `api.dcc.unreal.find_skeletal_meshes_using_skeleton(...)`

- Target: `unreal_tools.sequence_importer.find_skeletal_meshes_using_skeleton`
- Signature: `find_skeletal_meshes_using_skeleton(skeleton_asset_path)`
- API names: `find_skeletal_meshes_using_skeleton`
- Args:
  - `skeleton_asset_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_skeleton_from_skeletal_mesh_using_metadata(...)`](#apidccunrealget_skeleton_from_skeletal_mesh_using_metadata) -> `unreal_tools.sequence_importer.get_skeleton_from_skeletal_mesh_using_metadata` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:532](C:/depot/tools/unreal_tools/sequence_importer.py:532)
  - same_module: [`api.dcc.unreal.find_actor_by_blueprint_or_skeletal_mesh(...)`](#apidccunrealfind_actor_by_blueprint_or_skeletal_mesh) -> `unreal_tools.sequence_importer.find_actor_by_blueprint_or_skeletal_mesh` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1174](C:/depot/tools/unreal_tools/sequence_importer.py:1174)
  - same_module: [`api.dcc.unreal.get_blueprints_using_skeleton(...)`](#apidccunrealget_blueprints_using_skeleton) -> `unreal_tools.sequence_importer.get_blueprints_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:668](C:/depot/tools/unreal_tools/sequence_importer.py:668)
  - same_module: [`api.dcc.unreal.get_blueprints_using_skeleton_cmd(...)`](#apidccunrealget_blueprints_using_skeleton_cmd) -> `unreal_tools.sequence_importer.get_blueprints_using_skeleton_cmd` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:588](C:/depot/tools/unreal_tools/sequence_importer.py:588)
  - same_module: [`api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`](#apidccunrealadd_skeletal_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)
- Description: Finds all Skeletal Mesh assets that use the given Skeleton asset. :param skeleton_asset_path: The full asset path to the Skeleton (e.g. "/Game/Characters/Hero/Hero_Skeleton") :return: A list of SkeletalMesh asset objects that use the given Skeleton.
- Source: [sequence_importer.py:546](C:/depot/tools/unreal_tools/sequence_importer.py:546)

### `api.dcc.unreal.get_actor_from_binding(...)`

- Target: `unreal_tools.sequence_importer.get_actor_from_binding`
- Signature: `get_actor_from_binding(sequence_path, blueprint_binding)`
- API names: `get_actor_from_binding`
- Args:
  - `sequence_path`, required
  - `blueprint_binding`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_actor_from_possessable(...)`](#apidccunrealget_actor_from_possessable) -> `unreal_tools.sequence_importer.get_actor_from_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:961](C:/depot/tools/unreal_tools/sequence_importer.py:961)
  - same_module: [`api.dcc.unreal.get_blueprint_class_from_binding(...)`](#apidccunrealget_blueprint_class_from_binding) -> `unreal_tools.sequence_importer.get_blueprint_class_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1013](C:/depot/tools/unreal_tools/sequence_importer.py:1013)
  - same_module: [`api.dcc.unreal.get_blueprint_binding_in_sequence(...)`](#apidccunrealget_blueprint_binding_in_sequence) -> `unreal_tools.sequence_importer.get_blueprint_binding_in_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:731](C:/depot/tools/unreal_tools/sequence_importer.py:731)
  - same_module: [`api.dcc.unreal.get_level_sequence_actor(...)`](#apidccunrealget_level_sequence_actor) -> `unreal_tools.sequence_importer.get_level_sequence_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:929](C:/depot/tools/unreal_tools/sequence_importer.py:929)
  - same_module: [`api.dcc.unreal.get_skeleton_from_skeletal_mesh_using_metadata(...)`](#apidccunrealget_skeleton_from_skeletal_mesh_using_metadata) -> `unreal_tools.sequence_importer.get_skeleton_from_skeletal_mesh_using_metadata` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:532](C:/depot/tools/unreal_tools/sequence_importer.py:532)
- Description: Retrieve the actor bound to a sequence via the blueprint binding. :param sequence_path: Path to the Level Sequence. :param blueprint_binding: The binding that we are checking. :return: Actor or None if not found.
- Source: [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)

### `api.dcc.unreal.get_actor_from_possessable(...)`

- Target: `unreal_tools.sequence_importer.get_actor_from_possessable`
- Signature: `get_actor_from_possessable(sequence_path, actor_binding)`
- API names: `get_actor_from_possessable`
- Args:
  - `sequence_path`, required
  - `actor_binding`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
  - same_module: [`api.dcc.unreal.find_possessable_for_actor(...)`](#apidccunrealfind_possessable_for_actor) -> `unreal_tools.sequence_importer.find_possessable_for_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1226](C:/depot/tools/unreal_tools/sequence_importer.py:1226)
  - same_module: [`api.dcc.unreal.get_blueprint_class_from_binding(...)`](#apidccunrealget_blueprint_class_from_binding) -> `unreal_tools.sequence_importer.get_blueprint_class_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1013](C:/depot/tools/unreal_tools/sequence_importer.py:1013)
  - same_module: [`api.dcc.unreal.get_level_sequence_actor(...)`](#apidccunrealget_level_sequence_actor) -> `unreal_tools.sequence_importer.get_level_sequence_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:929](C:/depot/tools/unreal_tools/sequence_importer.py:929)
  - same_module: [`api.dcc.unreal.get_skeleton_from_skeletal_mesh_using_metadata(...)`](#apidccunrealget_skeleton_from_skeletal_mesh_using_metadata) -> `unreal_tools.sequence_importer.get_skeleton_from_skeletal_mesh_using_metadata` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:532](C:/depot/tools/unreal_tools/sequence_importer.py:532)
- Description: Retrieves the actor bound to the given possessable within a Level Sequence. :param actor_binding: The possessable (actor binding) in the sequence. :param sequence_path: The level sequence to search within. :return: The actor bound to the possessable, or None if not found.
- Source: [sequence_importer.py:961](C:/depot/tools/unreal_tools/sequence_importer.py:961)

### `api.dcc.unreal.get_all_assets_of_type(...)`

- Target: `unreal_tools.get_skeletons.get_all_assets_of_type`
- Signature: `get_all_assets_of_type(type='Skeleton', directory="/Game/")`
- API names: `get_all_assets_of_type`
- Args:
  - `type`, default `'Skeleton'`
  - `directory`, default `'/Game/'`
- Source: [get_skeletons.py:4](C:/depot/tools/unreal_tools/get_skeletons.py:4)

### `api.dcc.unreal.get_blueprint_binding_in_sequence(...)`

- Target: `unreal_tools.sequence_importer.get_blueprint_binding_in_sequence`
- Signature: `get_blueprint_binding_in_sequence(blueprint_path, sequence_path)`
- API names: `get_blueprint_binding_in_sequence`
- Args:
  - `blueprint_path`, required
  - `sequence_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_blueprint_class_from_binding(...)`](#apidccunrealget_blueprint_class_from_binding) -> `unreal_tools.sequence_importer.get_blueprint_class_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1013](C:/depot/tools/unreal_tools/sequence_importer.py:1013)
  - same_module: [`api.dcc.unreal.get_existing_blueprint_mesh_components_in_level_sequence(...)`](#apidccunrealget_existing_blueprint_mesh_components_in_level_sequence) -> `unreal_tools.sequence_importer.get_existing_blueprint_mesh_components_in_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1037](C:/depot/tools/unreal_tools/sequence_importer.py:1037)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
  - same_module: [`api.dcc.unreal.get_level_sequence_actor(...)`](#apidccunrealget_level_sequence_actor) -> `unreal_tools.sequence_importer.get_level_sequence_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:929](C:/depot/tools/unreal_tools/sequence_importer.py:929)
- Description: Returns the binding for a Blueprint actor in the Level Sequence, if it exists. Compares the binding name to the actor name. :param blueprint_path: Path to the Blueprint asset (e.g., "/Game/Blueprints/MyActorBP") :param sequence_path: Path to the Level Sequence asset (e.g., "/Game/Cinematics/MySequence") :return: The binding (MovieSceneBindingProxy) if found, else None
- Source: [sequence_importer.py:731](C:/depot/tools/unreal_tools/sequence_importer.py:731)

### `api.dcc.unreal.get_blueprint_class_from_binding(...)`

- Target: `unreal_tools.sequence_importer.get_blueprint_class_from_binding`
- Signature: `get_blueprint_class_from_binding(blueprint_binding)`
- API names: `get_blueprint_class_from_binding`
- Args:
  - `blueprint_binding`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
  - same_module: [`api.dcc.unreal.get_blueprint_binding_in_sequence(...)`](#apidccunrealget_blueprint_binding_in_sequence) -> `unreal_tools.sequence_importer.get_blueprint_binding_in_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:731](C:/depot/tools/unreal_tools/sequence_importer.py:731)
  - same_module: [`api.dcc.unreal.get_actor_from_possessable(...)`](#apidccunrealget_actor_from_possessable) -> `unreal_tools.sequence_importer.get_actor_from_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:961](C:/depot/tools/unreal_tools/sequence_importer.py:961)
  - same_module: [`api.dcc.unreal.get_control_rig_class(...)`](#apidccunrealget_control_rig_class) -> `unreal_tools.sequence_importer.get_control_rig_class` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:448](C:/depot/tools/unreal_tools/sequence_importer.py:448)
  - same_module: [`api.dcc.unreal.get_existing_blueprint_mesh_components_in_level_sequence(...)`](#apidccunrealget_existing_blueprint_mesh_components_in_level_sequence) -> `unreal_tools.sequence_importer.get_existing_blueprint_mesh_components_in_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1037](C:/depot/tools/unreal_tools/sequence_importer.py:1037)
- Description: Retrieves the Blueprint class from the binding. :param blueprint_binding: The MovieSceneBindingProxy for the blueprint. :return: The BlueprintGeneratedClass for the actor in the binding.
- Source: [sequence_importer.py:1013](C:/depot/tools/unreal_tools/sequence_importer.py:1013)

### `api.dcc.unreal.get_blueprint_graphs(...)`

- Target: `unreal_tools.blueprint_events.get_blueprint_graphs`
- Signature: `get_blueprint_graphs(blueprint)`
- API names: `get_blueprint_graphs`
- Args:
  - `blueprint`, required
- Related functions:
  - same_module: [`api.dcc.unreal.add_custom_events_to_blueprint(...)`](#apidccunrealadd_custom_events_to_blueprint) -> `unreal_tools.blueprint_events.add_custom_events_to_blueprint` - Shares module and name terms; may be useful in the same workflow.; source [blueprint_events.py:14](C:/depot/tools/unreal_tools/blueprint_events.py:14)
  - same_module: [`api.dcc.unreal.get_valid_events_from_import(...)`](#apidccunrealget_valid_events_from_import) -> `unreal_tools.blueprint_events.get_valid_events_from_import` - Shares module and name terms; may be useful in the same workflow.; source [blueprint_events.py:68](C:/depot/tools/unreal_tools/blueprint_events.py:68)
- Source: [blueprint_events.py:4](C:/depot/tools/unreal_tools/blueprint_events.py:4)

### `api.dcc.unreal.get_blueprints_using_skeleton(...)`

- Target: `unreal_tools.sequence_importer.get_blueprints_using_skeleton`
- Signature: `get_blueprints_using_skeleton(skeleton_path, asset_registry=None, mesh_string=None)`
- API names: `get_blueprints_using_skeleton`
- Args:
  - `skeleton_path`, required
  - `asset_registry`, default `None`
  - `mesh_string`, default `None`
- Related functions:
  - same_module: [`api.dcc.unreal.get_blueprints_using_skeleton_cmd(...)`](#apidccunrealget_blueprints_using_skeleton_cmd) -> `unreal_tools.sequence_importer.get_blueprints_using_skeleton_cmd` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:588](C:/depot/tools/unreal_tools/sequence_importer.py:588)
  - same_module: [`api.dcc.unreal.get_skeleton_from_skeletal_mesh_using_metadata(...)`](#apidccunrealget_skeleton_from_skeletal_mesh_using_metadata) -> `unreal_tools.sequence_importer.get_skeleton_from_skeletal_mesh_using_metadata` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:532](C:/depot/tools/unreal_tools/sequence_importer.py:532)
  - same_module: [`api.dcc.unreal.find_skeletal_meshes_using_skeleton(...)`](#apidccunrealfind_skeletal_meshes_using_skeleton) -> `unreal_tools.sequence_importer.find_skeletal_meshes_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:546](C:/depot/tools/unreal_tools/sequence_importer.py:546)
  - same_module: [`api.dcc.unreal.get_skeleton_path_by_name(...)`](#apidccunrealget_skeleton_path_by_name) -> `unreal_tools.sequence_importer.get_skeleton_path_by_name` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:775](C:/depot/tools/unreal_tools/sequence_importer.py:775)
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
- Description: Finds all Blueprints using a given skeleton, prioritizing CinematicCharacter Blueprints, and only checks for CinematicCharacter, Actor, and Character Blueprints. :param skeleton_path: The asset path of the skeleton (e.g., "/Game/Characters/Hero/Hero_Skeleton") :return: A list of Blueprint asset paths, prioritizing CinematicCharacter BPs.
- Source: [sequence_importer.py:668](C:/depot/tools/unreal_tools/sequence_importer.py:668)

### `api.dcc.unreal.get_blueprints_using_skeleton_cmd(...)`

- Target: `unreal_tools.sequence_importer.get_blueprints_using_skeleton_cmd`
- Signature: `get_blueprints_using_skeleton_cmd(skeleton_path, asset_registry=None)`
- API names: `get_blueprints_using_skeleton_cmd`
- Args:
  - `skeleton_path`, required
  - `asset_registry`, default `None`
- Related functions:
  - same_module: [`api.dcc.unreal.get_blueprints_using_skeleton(...)`](#apidccunrealget_blueprints_using_skeleton) -> `unreal_tools.sequence_importer.get_blueprints_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:668](C:/depot/tools/unreal_tools/sequence_importer.py:668)
  - same_module: [`api.dcc.unreal.get_skeleton_from_skeletal_mesh_using_metadata(...)`](#apidccunrealget_skeleton_from_skeletal_mesh_using_metadata) -> `unreal_tools.sequence_importer.get_skeleton_from_skeletal_mesh_using_metadata` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:532](C:/depot/tools/unreal_tools/sequence_importer.py:532)
  - same_module: [`api.dcc.unreal.find_skeletal_meshes_using_skeleton(...)`](#apidccunrealfind_skeletal_meshes_using_skeleton) -> `unreal_tools.sequence_importer.find_skeletal_meshes_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:546](C:/depot/tools/unreal_tools/sequence_importer.py:546)
  - same_module: [`api.dcc.unreal.get_skeleton_path_by_name(...)`](#apidccunrealget_skeleton_path_by_name) -> `unreal_tools.sequence_importer.get_skeleton_path_by_name` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:775](C:/depot/tools/unreal_tools/sequence_importer.py:775)
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
- Description: Finds all Blueprints using a given skeleton, prioritizing CinematicCharacter Blueprints, and only checks for CinematicCharacter, Actor, and Character Blueprints. :param skeleton_path: The asset path of the skeleton (e.g., "/Game/Characters/Hero/Hero_Skeleton") :return: A list of Blueprint asset paths, prioritizing CinematicCharacter BPs.
- Source: [sequence_importer.py:588](C:/depot/tools/unreal_tools/sequence_importer.py:588)

### `api.dcc.unreal.get_bone_hierarchy(...)`

- Target: `unreal_tools.control_rig.get_bone_hierarchy`
- Signature: `get_bone_hierarchy(skeletal_mesh_path)`
- API names: `get_bone_hierarchy`
- Args:
  - `skeletal_mesh_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_finger_joints(...)`](#apidccunrealget_finger_joints) -> `unreal_tools.control_rig.get_finger_joints` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:140](C:/depot/tools/unreal_tools/control_rig.py:140)
- Description: :param skeletal_mesh_path: Path to skeletal mesh being used :return:
- Source: [control_rig.py:113](C:/depot/tools/unreal_tools/control_rig.py:113)

### `api.dcc.unreal.get_control_rig_class(...)`

- Target: `unreal_tools.sequence_importer.get_control_rig_class`
- Signature: `get_control_rig_class(control_rig_path = "Face_ControlBoard_CtrlRig")`
- API names: `get_control_rig_class`
- Args:
  - `control_rig_path`, default `'Face_ControlBoard_CtrlRig'`
- Related functions:
  - same_module: [`api.dcc.unreal.get_blueprint_class_from_binding(...)`](#apidccunrealget_blueprint_class_from_binding) -> `unreal_tools.sequence_importer.get_blueprint_class_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1013](C:/depot/tools/unreal_tools/sequence_importer.py:1013)
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
  - same_module: [`api.dcc.unreal.get_actor_from_possessable(...)`](#apidccunrealget_actor_from_possessable) -> `unreal_tools.sequence_importer.get_actor_from_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:961](C:/depot/tools/unreal_tools/sequence_importer.py:961)
  - same_module: [`api.dcc.unreal.get_blueprint_binding_in_sequence(...)`](#apidccunrealget_blueprint_binding_in_sequence) -> `unreal_tools.sequence_importer.get_blueprint_binding_in_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:731](C:/depot/tools/unreal_tools/sequence_importer.py:731)
  - same_module: [`api.dcc.unreal.get_blueprints_using_skeleton(...)`](#apidccunrealget_blueprints_using_skeleton) -> `unreal_tools.sequence_importer.get_blueprints_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:668](C:/depot/tools/unreal_tools/sequence_importer.py:668)
- Description: :param control_rig_path: :return:
- Source: [sequence_importer.py:448](C:/depot/tools/unreal_tools/sequence_importer.py:448)

### `api.dcc.unreal.get_dependencies(...)`

- Target: `unreal_tools.assets.get_dependencies`
- Signature: `get_dependencies(asset_path, recursive=True)`
- API names: `get_dependencies`
- Args:
  - `asset_path`, required
  - `recursive`, default `True`
- Source: [assets.py:8](C:/depot/tools/unreal_tools/assets.py:8)

### `api.dcc.unreal.get_engine_association(...)`

- Target: `unreal_tools.unreal_project_data.get_engine_association`
- Signature: `get_engine_association(uproject_path)`
- API names: `get_engine_association`
- Args:
  - `uproject_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_latest_unreal_log(...)`](#apidccunrealget_latest_unreal_log) -> `unreal_tools.unreal_project_data.get_latest_unreal_log` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:88](C:/depot/tools/unreal_tools/unreal_project_data.py:88)
  - same_module: [`api.dcc.unreal.get_unreal_cmd_exe(...)`](#apidccunrealget_unreal_cmd_exe) -> `unreal_tools.unreal_project_data.get_unreal_cmd_exe` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:19](C:/depot/tools/unreal_tools/unreal_project_data.py:19)
  - same_module: [`api.dcc.unreal.get_unreal_install_path(...)`](#apidccunrealget_unreal_install_path) -> `unreal_tools.unreal_project_data.get_unreal_install_path` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:49](C:/depot/tools/unreal_tools/unreal_project_data.py:49)
- Description: Returns the Engine Version for the uproject :param uproject_path: actual uproject path :return: If found, returns the Engine Version for the unreal version
- Source: [unreal_project_data.py:8](C:/depot/tools/unreal_tools/unreal_project_data.py:8)

### `api.dcc.unreal.get_existing_blueprint_mesh_components_in_level_sequence(...)`

- Target: `unreal_tools.sequence_importer.get_existing_blueprint_mesh_components_in_level_sequence`
- Signature: `get_existing_blueprint_mesh_components_in_level_sequence(blueprint, sequence_path, actor =None)`
- API names: `get_existing_blueprint_mesh_components_in_level_sequence`
- Args:
  - `blueprint`, required
  - `sequence_path`, required
  - `actor`, default `None`
- Related functions:
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`](#apidccunrealadd_skeletal_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)
  - same_module: [`api.dcc.unreal.get_blueprint_binding_in_sequence(...)`](#apidccunrealget_blueprint_binding_in_sequence) -> `unreal_tools.sequence_importer.get_blueprint_binding_in_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:731](C:/depot/tools/unreal_tools/sequence_importer.py:731)
  - same_module: [`api.dcc.unreal.get_level_sequence_actor(...)`](#apidccunrealget_level_sequence_actor) -> `unreal_tools.sequence_importer.get_level_sequence_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:929](C:/depot/tools/unreal_tools/sequence_importer.py:929)
  - same_module: [`api.dcc.unreal.get_top_level_mesh_component(...)`](#apidccunrealget_top_level_mesh_component) -> `unreal_tools.sequence_importer.get_top_level_mesh_component` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:761](C:/depot/tools/unreal_tools/sequence_importer.py:761)
- Description: Detects existing mesh components (such as 'Mesh', 'Body', and 'Face') that have already been added to the Level Sequence from the given blueprint. :param blueprint: The Blueprint path to check for mesh components. :param sequence_path: The Level Sequence path to check for bindings. :return: A list of detected mesh components that are already bound in the sequence.
- Source: [sequence_importer.py:1037](C:/depot/tools/unreal_tools/sequence_importer.py:1037)

### `api.dcc.unreal.get_finger_joints(...)`

- Target: `unreal_tools.control_rig.get_finger_joints`
- Signature: `get_finger_joints(joint_map, finger_name, side="Left")`
- API names: `get_finger_joints`
- Args:
  - `joint_map`, required
  - `finger_name`, required
  - `side`, default `'Left'`
- Related functions:
  - same_module: [`api.dcc.unreal.build_finger_modules(...)`](#apidccunrealbuild_finger_modules) -> `unreal_tools.control_rig.build_finger_modules` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:306](C:/depot/tools/unreal_tools/control_rig.py:306)
  - same_module: [`api.dcc.unreal.get_bone_hierarchy(...)`](#apidccunrealget_bone_hierarchy) -> `unreal_tools.control_rig.get_bone_hierarchy` - Shares module and name terms; may be useful in the same workflow.; source [control_rig.py:113](C:/depot/tools/unreal_tools/control_rig.py:113)
- Description: :param joint_map: mapping from HIK UI (maya_tools/Rigging/mocap) :param finger_name: :param side: :return:
- Source: [control_rig.py:140](C:/depot/tools/unreal_tools/control_rig.py:140)

### `api.dcc.unreal.get_full_range(...)`

- Target: `unreal_tools.sequence_importer.get_full_range`
- Signature: `get_full_range(level_sequence)`
- API names: `get_full_range`
- Args:
  - `level_sequence`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_section_range(...)`](#apidccunrealget_section_range) -> `unreal_tools.sequence_importer.get_section_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1293](C:/depot/tools/unreal_tools/sequence_importer.py:1293)
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
  - same_module: [`api.dcc.unreal.get_actor_from_possessable(...)`](#apidccunrealget_actor_from_possessable) -> `unreal_tools.sequence_importer.get_actor_from_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:961](C:/depot/tools/unreal_tools/sequence_importer.py:961)
  - same_module: [`api.dcc.unreal.get_blueprint_binding_in_sequence(...)`](#apidccunrealget_blueprint_binding_in_sequence) -> `unreal_tools.sequence_importer.get_blueprint_binding_in_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:731](C:/depot/tools/unreal_tools/sequence_importer.py:731)
  - same_module: [`api.dcc.unreal.get_blueprint_class_from_binding(...)`](#apidccunrealget_blueprint_class_from_binding) -> `unreal_tools.sequence_importer.get_blueprint_class_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1013](C:/depot/tools/unreal_tools/sequence_importer.py:1013)
- Description: gets range for use in get_bound_objects :param level_sequence: level sequence asset :return:
- Source: [sequence_importer.py:947](C:/depot/tools/unreal_tools/sequence_importer.py:947)

### `api.dcc.unreal.get_latest_unreal_log(...)`

- Target: `unreal_tools.unreal_project_data.get_latest_unreal_log`
- Signature: `get_latest_unreal_log(uproject_path)`
- API names: `get_latest_unreal_log`
- Args:
  - `uproject_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_unreal_cmd_exe(...)`](#apidccunrealget_unreal_cmd_exe) -> `unreal_tools.unreal_project_data.get_unreal_cmd_exe` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:19](C:/depot/tools/unreal_tools/unreal_project_data.py:19)
  - same_module: [`api.dcc.unreal.get_unreal_install_path(...)`](#apidccunrealget_unreal_install_path) -> `unreal_tools.unreal_project_data.get_unreal_install_path` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:49](C:/depot/tools/unreal_tools/unreal_project_data.py:49)
  - same_module: [`api.dcc.unreal.add_unreal_startup_script(...)`](#apidccunrealadd_unreal_startup_script) -> `unreal_tools.unreal_project_data.add_unreal_startup_script` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:145](C:/depot/tools/unreal_tools/unreal_project_data.py:145)
  - same_module: [`api.dcc.unreal.ensure_unreal_python_plugin_enabled(...)`](#apidccunrealensure_unreal_python_plugin_enabled) -> `unreal_tools.unreal_project_data.ensure_unreal_python_plugin_enabled` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:114](C:/depot/tools/unreal_tools/unreal_project_data.py:114)
  - same_module: [`api.dcc.unreal.get_engine_association(...)`](#apidccunrealget_engine_association) -> `unreal_tools.unreal_project_data.get_engine_association` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:8](C:/depot/tools/unreal_tools/unreal_project_data.py:8)
- Description: Finds the latest modified Unreal Engine log file for a given .uproject. :param uproject_path: actual uproject path :return:
- Source: [unreal_project_data.py:88](C:/depot/tools/unreal_tools/unreal_project_data.py:88)

### `api.dcc.unreal.get_level_sequence_actor(...)`

- Target: `unreal_tools.sequence_importer.get_level_sequence_actor`
- Signature: `get_level_sequence_actor(level_sequence_asset)`
- API names: `get_level_sequence_actor`
- Args:
  - `level_sequence_asset`, required
- Related functions:
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
  - same_module: [`api.dcc.unreal.get_existing_blueprint_mesh_components_in_level_sequence(...)`](#apidccunrealget_existing_blueprint_mesh_components_in_level_sequence) -> `unreal_tools.sequence_importer.get_existing_blueprint_mesh_components_in_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1037](C:/depot/tools/unreal_tools/sequence_importer.py:1037)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
- Description: Returns the Level Sequence Actor that references the given LevelSequence asset in the level. :param level_sequence_asset: The LevelSequence asset to search for in the level. :return: The Level Sequence Actor if found, else None.
- Source: [sequence_importer.py:929](C:/depot/tools/unreal_tools/sequence_importer.py:929)

### `api.dcc.unreal.get_possessables_for_sequence(...)`

- Target: `unreal_tools.sequence_importer.get_possessables_for_sequence`
- Signature: `get_possessables_for_sequence(level_sequence)`
- API names: `get_possessables_for_sequence`
- Args:
  - `level_sequence`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_blueprint_binding_in_sequence(...)`](#apidccunrealget_blueprint_binding_in_sequence) -> `unreal_tools.sequence_importer.get_blueprint_binding_in_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:731](C:/depot/tools/unreal_tools/sequence_importer.py:731)
  - same_module: [`api.dcc.unreal.get_existing_blueprint_mesh_components_in_level_sequence(...)`](#apidccunrealget_existing_blueprint_mesh_components_in_level_sequence) -> `unreal_tools.sequence_importer.get_existing_blueprint_mesh_components_in_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1037](C:/depot/tools/unreal_tools/sequence_importer.py:1037)
  - same_module: [`api.dcc.unreal.get_level_sequence_actor(...)`](#apidccunrealget_level_sequence_actor) -> `unreal_tools.sequence_importer.get_level_sequence_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:929](C:/depot/tools/unreal_tools/sequence_importer.py:929)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
- Description: Retrieves all possessables (actors) bound to the given level sequence. :param level_sequence: The Level Sequence asset to get the possessables from. :return: A list of possessable objects (MovieSceneBindingProxy).
- Source: [sequence_importer.py:656](C:/depot/tools/unreal_tools/sequence_importer.py:656)

### `api.dcc.unreal.get_section_range(...)`

- Target: `unreal_tools.sequence_importer.get_section_range`
- Signature: `get_section_range(section)`
- API names: `get_section_range`
- Args:
  - `section`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_full_range(...)`](#apidccunrealget_full_range) -> `unreal_tools.sequence_importer.get_full_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:947](C:/depot/tools/unreal_tools/sequence_importer.py:947)
  - same_module: [`api.dcc.unreal.call('unreal_tools.sequence_importer.set_section_range', ...)`](#apidccunrealcallunreal_toolssequence_importerset_section_range) -> `unreal_tools.sequence_importer.set_section_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1281](C:/depot/tools/unreal_tools/sequence_importer.py:1281)
  - same_module: [`api.dcc.unreal.add_shot_sequence_section_to_shot_track(...)`](#apidccunrealadd_shot_sequence_section_to_shot_track) -> `unreal_tools.sequence_importer.add_shot_sequence_section_to_shot_track` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:171](C:/depot/tools/unreal_tools/sequence_importer.py:171)
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
- Description: Gets the range for the defined section :param section: actual section object in sequencer :return: list of the start and end frames
- Source: [sequence_importer.py:1293](C:/depot/tools/unreal_tools/sequence_importer.py:1293)

### `api.dcc.unreal.get_skeleton_from_skeletal_mesh_using_metadata(...)`

- Target: `unreal_tools.sequence_importer.get_skeleton_from_skeletal_mesh_using_metadata`
- Signature: `get_skeleton_from_skeletal_mesh_using_metadata(skeletal_mesh_path)`
- API names: `get_skeleton_from_skeletal_mesh_using_metadata`
- Args:
  - `skeletal_mesh_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.find_skeletal_meshes_using_skeleton(...)`](#apidccunrealfind_skeletal_meshes_using_skeleton) -> `unreal_tools.sequence_importer.find_skeletal_meshes_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:546](C:/depot/tools/unreal_tools/sequence_importer.py:546)
  - same_module: [`api.dcc.unreal.get_blueprints_using_skeleton(...)`](#apidccunrealget_blueprints_using_skeleton) -> `unreal_tools.sequence_importer.get_blueprints_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:668](C:/depot/tools/unreal_tools/sequence_importer.py:668)
  - same_module: [`api.dcc.unreal.get_blueprints_using_skeleton_cmd(...)`](#apidccunrealget_blueprints_using_skeleton_cmd) -> `unreal_tools.sequence_importer.get_blueprints_using_skeleton_cmd` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:588](C:/depot/tools/unreal_tools/sequence_importer.py:588)
  - same_module: [`api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`](#apidccunrealadd_skeletal_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)
  - same_module: [`api.dcc.unreal.find_actor_by_blueprint_or_skeletal_mesh(...)`](#apidccunrealfind_actor_by_blueprint_or_skeletal_mesh) -> `unreal_tools.sequence_importer.find_actor_by_blueprint_or_skeletal_mesh` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1174](C:/depot/tools/unreal_tools/sequence_importer.py:1174)
- Description: Get the skeleton from a given skeletal mesh by retrieving metadata tags. :param skeletal_mesh_path: The asset path of the skeletal mesh (e.g., "/Game/Characters/Hero/Hero_SkeletalMesh") :return: The skeleton associated with the given skeletal mesh, or None if not found.
- Source: [sequence_importer.py:532](C:/depot/tools/unreal_tools/sequence_importer.py:532)

### `api.dcc.unreal.get_skeleton_path_by_name(...)`

- Target: `unreal_tools.sequence_importer.get_skeleton_path_by_name`
- Signature: `get_skeleton_path_by_name(skeleton_name)`
- API names: `get_skeleton_path_by_name`
- Args:
  - `skeleton_name`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_blueprints_using_skeleton(...)`](#apidccunrealget_blueprints_using_skeleton) -> `unreal_tools.sequence_importer.get_blueprints_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:668](C:/depot/tools/unreal_tools/sequence_importer.py:668)
  - same_module: [`api.dcc.unreal.get_blueprints_using_skeleton_cmd(...)`](#apidccunrealget_blueprints_using_skeleton_cmd) -> `unreal_tools.sequence_importer.get_blueprints_using_skeleton_cmd` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:588](C:/depot/tools/unreal_tools/sequence_importer.py:588)
  - same_module: [`api.dcc.unreal.get_skeleton_from_skeletal_mesh_using_metadata(...)`](#apidccunrealget_skeleton_from_skeletal_mesh_using_metadata) -> `unreal_tools.sequence_importer.get_skeleton_from_skeletal_mesh_using_metadata` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:532](C:/depot/tools/unreal_tools/sequence_importer.py:532)
  - same_module: [`api.dcc.unreal.extract_shot_number_from_path(...)`](#apidccunrealextract_shot_number_from_path) -> `unreal_tools.sequence_importer.extract_shot_number_from_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:795](C:/depot/tools/unreal_tools/sequence_importer.py:795)
  - same_module: [`api.dcc.unreal.find_skeletal_meshes_using_skeleton(...)`](#apidccunrealfind_skeletal_meshes_using_skeleton) -> `unreal_tools.sequence_importer.find_skeletal_meshes_using_skeleton` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:546](C:/depot/tools/unreal_tools/sequence_importer.py:546)
- Description: Retrieves the asset path of a skeleton based on its name using Unreal's Asset Registry. :param skeleton_name: Name of the skeleton asset (e.g., "SK_Mannequin"). :return: The asset path of the skeleton (e.g., "/Game/Characters/Hero/Hero_Skeleton") or None if not found.
- Source: [sequence_importer.py:775](C:/depot/tools/unreal_tools/sequence_importer.py:775)

### `api.dcc.unreal.get_top_level_mesh_component(...)`

- Target: `unreal_tools.sequence_importer.get_top_level_mesh_component`
- Signature: `get_top_level_mesh_component(actor)`
- API names: `get_top_level_mesh_component`
- Args:
  - `actor`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_existing_blueprint_mesh_components_in_level_sequence(...)`](#apidccunrealget_existing_blueprint_mesh_components_in_level_sequence) -> `unreal_tools.sequence_importer.get_existing_blueprint_mesh_components_in_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1037](C:/depot/tools/unreal_tools/sequence_importer.py:1037)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_skeletal_mesh_components_to_level_sequence(...)`](#apidccunrealadd_skeletal_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_skeletal_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:89](C:/depot/tools/unreal_tools/sequence_importer.py:89)
  - same_module: [`api.dcc.unreal.get_level_sequence_actor(...)`](#apidccunrealget_level_sequence_actor) -> `unreal_tools.sequence_importer.get_level_sequence_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:929](C:/depot/tools/unreal_tools/sequence_importer.py:929)
  - same_module: [`api.dcc.unreal.get_skeleton_from_skeletal_mesh_using_metadata(...)`](#apidccunrealget_skeleton_from_skeletal_mesh_using_metadata) -> `unreal_tools.sequence_importer.get_skeleton_from_skeletal_mesh_using_metadata` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:532](C:/depot/tools/unreal_tools/sequence_importer.py:532)
- Source: [sequence_importer.py:761](C:/depot/tools/unreal_tools/sequence_importer.py:761)

### `api.dcc.unreal.get_unreal_cmd_exe(...)`

- Target: `unreal_tools.unreal_project_data.get_unreal_cmd_exe`
- Signature: `get_unreal_cmd_exe(uproject_path)`
- API names: `get_unreal_cmd_exe`
- Args:
  - `uproject_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_latest_unreal_log(...)`](#apidccunrealget_latest_unreal_log) -> `unreal_tools.unreal_project_data.get_latest_unreal_log` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:88](C:/depot/tools/unreal_tools/unreal_project_data.py:88)
  - same_module: [`api.dcc.unreal.get_unreal_install_path(...)`](#apidccunrealget_unreal_install_path) -> `unreal_tools.unreal_project_data.get_unreal_install_path` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:49](C:/depot/tools/unreal_tools/unreal_project_data.py:49)
  - same_module: [`api.dcc.unreal.add_unreal_startup_script(...)`](#apidccunrealadd_unreal_startup_script) -> `unreal_tools.unreal_project_data.add_unreal_startup_script` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:145](C:/depot/tools/unreal_tools/unreal_project_data.py:145)
  - same_module: [`api.dcc.unreal.ensure_unreal_python_plugin_enabled(...)`](#apidccunrealensure_unreal_python_plugin_enabled) -> `unreal_tools.unreal_project_data.ensure_unreal_python_plugin_enabled` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:114](C:/depot/tools/unreal_tools/unreal_project_data.py:114)
  - same_module: [`api.dcc.unreal.get_engine_association(...)`](#apidccunrealget_engine_association) -> `unreal_tools.unreal_project_data.get_engine_association` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:8](C:/depot/tools/unreal_tools/unreal_project_data.py:8)
- Description: Returns the Engine cmd exe location for the uproject :param uproject_path: actual uproject path :return: If found, returns the cmd.exe for the unreal version
- Source: [unreal_project_data.py:19](C:/depot/tools/unreal_tools/unreal_project_data.py:19)

### `api.dcc.unreal.get_unreal_install_path(...)`

- Target: `unreal_tools.unreal_project_data.get_unreal_install_path`
- Signature: `get_unreal_install_path(engine_version)`
- API names: `get_unreal_install_path`
- Args:
  - `engine_version`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_latest_unreal_log(...)`](#apidccunrealget_latest_unreal_log) -> `unreal_tools.unreal_project_data.get_latest_unreal_log` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:88](C:/depot/tools/unreal_tools/unreal_project_data.py:88)
  - same_module: [`api.dcc.unreal.get_unreal_cmd_exe(...)`](#apidccunrealget_unreal_cmd_exe) -> `unreal_tools.unreal_project_data.get_unreal_cmd_exe` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:19](C:/depot/tools/unreal_tools/unreal_project_data.py:19)
  - same_module: [`api.dcc.unreal.add_unreal_startup_script(...)`](#apidccunrealadd_unreal_startup_script) -> `unreal_tools.unreal_project_data.add_unreal_startup_script` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:145](C:/depot/tools/unreal_tools/unreal_project_data.py:145)
  - same_module: [`api.dcc.unreal.ensure_unreal_python_plugin_enabled(...)`](#apidccunrealensure_unreal_python_plugin_enabled) -> `unreal_tools.unreal_project_data.ensure_unreal_python_plugin_enabled` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:114](C:/depot/tools/unreal_tools/unreal_project_data.py:114)
  - same_module: [`api.dcc.unreal.get_engine_association(...)`](#apidccunrealget_engine_association) -> `unreal_tools.unreal_project_data.get_engine_association` - Shares module and name terms; may be useful in the same workflow.; source [unreal_project_data.py:8](C:/depot/tools/unreal_tools/unreal_project_data.py:8)
- Description: Check the Windows Registry for Unreal Engine install locations. :param engine_version: after finding engine version, it fills in the rest :return:
- Source: [unreal_project_data.py:49](C:/depot/tools/unreal_tools/unreal_project_data.py:49)

### `api.dcc.unreal.get_valid_events_from_import(...)`

- Target: `unreal_tools.blueprint_events.get_valid_events_from_import`
- Signature: `get_valid_events_from_import(imported_events, bp_class)`
- API names: `get_valid_events_from_import`
- Args:
  - `imported_events`, required
  - `bp_class`, required
- Related functions:
  - same_module: [`api.dcc.unreal.add_custom_events_to_blueprint(...)`](#apidccunrealadd_custom_events_to_blueprint) -> `unreal_tools.blueprint_events.add_custom_events_to_blueprint` - Shares module and name terms; may be useful in the same workflow.; source [blueprint_events.py:14](C:/depot/tools/unreal_tools/blueprint_events.py:14)
  - same_module: [`api.dcc.unreal.get_blueprint_graphs(...)`](#apidccunrealget_blueprint_graphs) -> `unreal_tools.blueprint_events.get_blueprint_graphs` - Shares module and name terms; may be useful in the same workflow.; source [blueprint_events.py:4](C:/depot/tools/unreal_tools/blueprint_events.py:4)
- Description: :param imported_events: :param bp_class: :return:
- Source: [blueprint_events.py:68](C:/depot/tools/unreal_tools/blueprint_events.py:68)

### `api.dcc.unreal.import_animation(...)`

- Target: `unreal_tools.sequence_importer.import_animation`
- Signature: `import_animation(anim_path, skeleton_path, destination_path, destination_name)`
- API names: `import_animation`
- Args:
  - `anim_path`, required
  - `skeleton_path`, required
  - `destination_path`, required
  - `destination_name`, required
- Related functions:
  - same_module: [`api.dcc.unreal.build_import_options(...)`](#apidccunrealbuild_import_options) -> `unreal_tools.sequence_importer.build_import_options` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:882](C:/depot/tools/unreal_tools/sequence_importer.py:882)
  - same_module: [`api.dcc.unreal.import_gameplay_animations_from_json(...)`](#apidccunrealimport_gameplay_animations_from_json) -> `unreal_tools.sequence_importer.import_gameplay_animations_from_json` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:812](C:/depot/tools/unreal_tools/sequence_importer.py:812)
- Description: Imports an animation asset into Unreal Engine, optionally reimporting if it already exists. :param anim_path: Path to the animation FBX file. :param skeleton_path: Path to the skeleton asset for the animation. :param destination_path: Destination path in Unreal where the asset will be imported. :param destination_name: Name for the imported animation asset. :return: The path to the imported animation asset.
- Source: [sequence_importer.py:851](C:/depot/tools/unreal_tools/sequence_importer.py:851)

### `api.dcc.unreal.import_animations_from_json(...)`

- Target: `unreal_tools.gameplay_import_func.import_animations_from_json`
- Signature: `import_animations_from_json(anim_dict_path)`
- API names: `import_animations_from_json`
- Args:
  - `anim_dict_path`, required
- Description: Function to call via the subprocess version / unreal cmd.exe version of the gameplay import to import all anims in json :param anim_dict_path: path to json with sequence_data :return:
- Source: [gameplay_import_func.py:7](C:/depot/tools/unreal_tools/gameplay_import_func.py:7)

### `api.dcc.unreal.import_function(...)`

- Target: `unreal_tools.http_server.import_function`
- Signature: `import_function(func_path)`
- API names: `import_function`
- Args:
  - `func_path`, required
- Description: Dynamically import a function from a module path string. used in a payload for the HTTP Handler POST :param func_path: Example func "unreal_tools.get_skeletons.get_all_assets_of_type" :return:
- Source: [http_server.py:43](C:/depot/tools/unreal_tools/http_server.py:43)

### `api.dcc.unreal.import_gameplay_animations_from_json(...)`

- Target: `unreal_tools.sequence_importer.import_gameplay_animations_from_json`
- Signature: `import_gameplay_animations_from_json(anim_dict_path)`
- API names: `import_gameplay_animations_from_json`
- Args:
  - `anim_dict_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.call('unreal_tools.sequence_importer.create_cinematic_sequence_from_json', ...)`](#apidccunrealcallunreal_toolssequence_importercreate_cinematic_sequence_from_json) -> `unreal_tools.sequence_importer.create_cinematic_sequence_from_json` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1369](C:/depot/tools/unreal_tools/sequence_importer.py:1369)
  - same_module: [`api.dcc.unreal.build_import_options(...)`](#apidccunrealbuild_import_options) -> `unreal_tools.sequence_importer.build_import_options` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:882](C:/depot/tools/unreal_tools/sequence_importer.py:882)
  - same_module: [`api.dcc.unreal.extract_shot_number_from_path(...)`](#apidccunrealextract_shot_number_from_path) -> `unreal_tools.sequence_importer.extract_shot_number_from_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:795](C:/depot/tools/unreal_tools/sequence_importer.py:795)
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
  - same_module: [`api.dcc.unreal.get_actor_from_possessable(...)`](#apidccunrealget_actor_from_possessable) -> `unreal_tools.sequence_importer.get_actor_from_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:961](C:/depot/tools/unreal_tools/sequence_importer.py:961)
- Description: Import gameplay animations, replaces Art Source Dir with Content Dir :param anim_dict_path: Exported Dict with the data to import :return:
- Source: [sequence_importer.py:812](C:/depot/tools/unreal_tools/sequence_importer.py:812)

### `api.dcc.unreal.inspect_asset(...)`

- Target: `unreal_tools.assets.inspect_asset`
- Signature: `inspect_asset(asset_path)`
- API names: `inspect_asset`
- Args:
  - `asset_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.find_asset_path_by_name(...)`](#apidccunrealfind_asset_path_by_name) -> `unreal_tools.assets.find_asset_path_by_name` - Shares module and name terms; may be useful in the same workflow.; source [assets.py:45](C:/depot/tools/unreal_tools/assets.py:45)
  - same_module: [`api.dcc.unreal.resolve_asset(...)`](#apidccunrealresolve_asset) -> `unreal_tools.assets.resolve_asset` - Shares module and name terms; may be useful in the same workflow.; source [assets.py:121](C:/depot/tools/unreal_tools/assets.py:121)
- Source: [assets.py:23](C:/depot/tools/unreal_tools/assets.py:23)

### `api.dcc.unreal.is_port_in_use(...)`

- Target: `unreal_tools.http_server.is_port_in_use`
- Signature: `is_port_in_use(port)`
- API names: `is_port_in_use`
- Args:
  - `port`, required
- Source: [http_server.py:125](C:/depot/tools/unreal_tools/http_server.py:125)

### `api.dcc.unreal.list_all_maps(...)`

- Target: `unreal_tools.sequence_importer.list_all_maps`
- Signature: `list_all_maps()`
- API names: `list_all_maps`
- Args: none
- Related functions:
  - same_module: [`api.dcc.unreal.list_all_tracks_in_sequence(...)`](#apidccunreallist_all_tracks_in_sequence) -> `unreal_tools.sequence_importer.list_all_tracks_in_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:521](C:/depot/tools/unreal_tools/sequence_importer.py:521)
- Source: [sequence_importer.py:1142](C:/depot/tools/unreal_tools/sequence_importer.py:1142)

### `api.dcc.unreal.list_all_tracks_in_sequence(...)`

- Target: `unreal_tools.sequence_importer.list_all_tracks_in_sequence`
- Signature: `list_all_tracks_in_sequence(sequence)`
- API names: `list_all_tracks_in_sequence`
- Args:
  - `sequence`, required
- Related functions:
  - same_module: [`api.dcc.unreal.list_all_maps(...)`](#apidccunreallist_all_maps) -> `unreal_tools.sequence_importer.list_all_maps` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1142](C:/depot/tools/unreal_tools/sequence_importer.py:1142)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
- Description: :param sequence: The Sequence asset to parse :return:
- Source: [sequence_importer.py:521](C:/depot/tools/unreal_tools/sequence_importer.py:521)

### `api.dcc.unreal.load_level_sequence(...)`

- Target: `unreal_tools.sequence_importer.load_level_sequence`
- Signature: `load_level_sequence(sequence_path="/Game/Cinematics/Test_Anim/Test_Anim_shot1/Test_Anim_shot1")`
- API names: `load_level_sequence`
- Args:
  - `sequence_path`, default `'/Game/Cinematics/Test_Anim/Test_Anim_shot1/Test_Anim_shot1'`
- Related functions:
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
  - same_module: [`api.dcc.unreal.add_camera_anim_to_level_sequence(...)`](#apidccunrealadd_camera_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:368](C:/depot/tools/unreal_tools/sequence_importer.py:368)
- Description: :param sequence_path: full path to sequence to load, checks current sequence for match first :return:
- Source: [sequence_importer.py:908](C:/depot/tools/unreal_tools/sequence_importer.py:908)

### `api.dcc.unreal.offset_float_track_keys(...)`

- Target: `unreal_tools.sequence_importer.offset_float_track_keys`
- Signature: `offset_float_track_keys(track, offset_frames)`
- API names: `offset_float_track_keys`
- Args:
  - `track`, required
  - `offset_frames`, required
- Related functions:
  - same_module: [`api.dcc.unreal.offset_transform_track_keys(...)`](#apidccunrealoffset_transform_track_keys) -> `unreal_tools.sequence_importer.offset_transform_track_keys` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:497](C:/depot/tools/unreal_tools/sequence_importer.py:497)
  - same_module: [`api.dcc.unreal.add_anim_track_to_possessable(...)`](#apidccunrealadd_anim_track_to_possessable) -> `unreal_tools.sequence_importer.add_anim_track_to_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:221](C:/depot/tools/unreal_tools/sequence_importer.py:221)
  - same_module: [`api.dcc.unreal.add_shot_sequence_section_to_shot_track(...)`](#apidccunrealadd_shot_sequence_section_to_shot_track) -> `unreal_tools.sequence_importer.add_shot_sequence_section_to_shot_track` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:171](C:/depot/tools/unreal_tools/sequence_importer.py:171)
  - same_module: [`api.dcc.unreal.add_shot_track_to_master_sequence(...)`](#apidccunrealadd_shot_track_to_master_sequence) -> `unreal_tools.sequence_importer.add_shot_track_to_master_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:153](C:/depot/tools/unreal_tools/sequence_importer.py:153)
  - same_module: [`api.dcc.unreal.offset_key_times_in_section(...)`](#apidccunrealoffset_key_times_in_section) -> `unreal_tools.sequence_importer.offset_key_times_in_section` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:462](C:/depot/tools/unreal_tools/sequence_importer.py:462)
- Description: Offsets all float keys in a MovieSceneFloatTrack by a given number of frames. :param track: The MovieSceneFloatTrack to modify. :param offset_frames: The number of frames to offset the keys by.
- Source: [sequence_importer.py:486](C:/depot/tools/unreal_tools/sequence_importer.py:486)

### `api.dcc.unreal.offset_key_times_in_section(...)`

- Target: `unreal_tools.sequence_importer.offset_key_times_in_section`
- Signature: `offset_key_times_in_section(section, offset_frames)`
- API names: `offset_key_times_in_section`
- Args:
  - `section`, required
  - `offset_frames`, required
- Related functions:
  - same_module: [`api.dcc.unreal.add_shot_sequence_section_to_shot_track(...)`](#apidccunrealadd_shot_sequence_section_to_shot_track) -> `unreal_tools.sequence_importer.add_shot_sequence_section_to_shot_track` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:171](C:/depot/tools/unreal_tools/sequence_importer.py:171)
  - same_module: [`api.dcc.unreal.get_section_range(...)`](#apidccunrealget_section_range) -> `unreal_tools.sequence_importer.get_section_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1293](C:/depot/tools/unreal_tools/sequence_importer.py:1293)
  - same_module: [`api.dcc.unreal.offset_float_track_keys(...)`](#apidccunrealoffset_float_track_keys) -> `unreal_tools.sequence_importer.offset_float_track_keys` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:486](C:/depot/tools/unreal_tools/sequence_importer.py:486)
  - same_module: [`api.dcc.unreal.offset_transform_track_keys(...)`](#apidccunrealoffset_transform_track_keys) -> `unreal_tools.sequence_importer.offset_transform_track_keys` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:497](C:/depot/tools/unreal_tools/sequence_importer.py:497)
  - same_module: [`api.dcc.unreal.call('unreal_tools.sequence_importer.set_section_range', ...)`](#apidccunrealcallunreal_toolssequence_importerset_section_range) -> `unreal_tools.sequence_importer.set_section_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1281](C:/depot/tools/unreal_tools/sequence_importer.py:1281)
- Description: :param section: section to offset :param offset_frames: frame value to offset :return:
- Source: [sequence_importer.py:462](C:/depot/tools/unreal_tools/sequence_importer.py:462)

### `api.dcc.unreal.offset_transform_track_keys(...)`

- Target: `unreal_tools.sequence_importer.offset_transform_track_keys`
- Signature: `offset_transform_track_keys(track, offset_frames)`
- API names: `offset_transform_track_keys`
- Args:
  - `track`, required
  - `offset_frames`, required
- Related functions:
  - same_module: [`api.dcc.unreal.offset_float_track_keys(...)`](#apidccunrealoffset_float_track_keys) -> `unreal_tools.sequence_importer.offset_float_track_keys` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:486](C:/depot/tools/unreal_tools/sequence_importer.py:486)
  - same_module: [`api.dcc.unreal.add_anim_track_to_possessable(...)`](#apidccunrealadd_anim_track_to_possessable) -> `unreal_tools.sequence_importer.add_anim_track_to_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:221](C:/depot/tools/unreal_tools/sequence_importer.py:221)
  - same_module: [`api.dcc.unreal.add_shot_sequence_section_to_shot_track(...)`](#apidccunrealadd_shot_sequence_section_to_shot_track) -> `unreal_tools.sequence_importer.add_shot_sequence_section_to_shot_track` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:171](C:/depot/tools/unreal_tools/sequence_importer.py:171)
  - same_module: [`api.dcc.unreal.add_shot_track_to_master_sequence(...)`](#apidccunrealadd_shot_track_to_master_sequence) -> `unreal_tools.sequence_importer.add_shot_track_to_master_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:153](C:/depot/tools/unreal_tools/sequence_importer.py:153)
  - same_module: [`api.dcc.unreal.offset_key_times_in_section(...)`](#apidccunrealoffset_key_times_in_section) -> `unreal_tools.sequence_importer.offset_key_times_in_section` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:462](C:/depot/tools/unreal_tools/sequence_importer.py:462)
- Description: :param track: Should be a MovieScene3DTransformTrack :param offset_frames: The number of frames to offset the keys by. :return:
- Source: [sequence_importer.py:497](C:/depot/tools/unreal_tools/sequence_importer.py:497)

### `api.dcc.unreal.prototype_from_template(...)`

- Target: `unreal_tools.gameplay.prototype_from_template`
- Signature: `prototype_from_template(template, target_path, parameters=None)`
- API names: `prototype_from_template`
- Args:
  - `template`, required
  - `target_path`, required
  - `parameters`, default `None`
- Description: Create a scan-backed prototype plan from a controlled template.
- Source: [gameplay.py:125](C:/depot/tools/unreal_tools/gameplay.py:125)

### `api.dcc.unreal.read_dict_from_file(...)`

- Target: `unreal_tools.sequence_importer.read_dict_from_file`
- Signature: `read_dict_from_file(file_path)`
- API names: `read_dict_from_file`
- Args:
  - `file_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.write_dict_to_file(...)`](#apidccunrealwrite_dict_to_file) -> `unreal_tools.sequence_importer.write_dict_to_file` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1105](C:/depot/tools/unreal_tools/sequence_importer.py:1105)
  - same_module: [`api.dcc.unreal.call('unreal_tools.sequence_importer.create_cinematic_sequence_from_json', ...)`](#apidccunrealcallunreal_toolssequence_importercreate_cinematic_sequence_from_json) -> `unreal_tools.sequence_importer.create_cinematic_sequence_from_json` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1369](C:/depot/tools/unreal_tools/sequence_importer.py:1369)
  - same_module: [`api.dcc.unreal.extract_shot_number_from_path(...)`](#apidccunrealextract_shot_number_from_path) -> `unreal_tools.sequence_importer.extract_shot_number_from_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:795](C:/depot/tools/unreal_tools/sequence_importer.py:795)
  - same_module: [`api.dcc.unreal.get_actor_from_binding(...)`](#apidccunrealget_actor_from_binding) -> `unreal_tools.sequence_importer.get_actor_from_binding` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:982](C:/depot/tools/unreal_tools/sequence_importer.py:982)
  - same_module: [`api.dcc.unreal.get_actor_from_possessable(...)`](#apidccunrealget_actor_from_possessable) -> `unreal_tools.sequence_importer.get_actor_from_possessable` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:961](C:/depot/tools/unreal_tools/sequence_importer.py:961)
- Description: Reads a dictionary from a JSON file. :param file_path: Path to the JSON file. :return: The dictionary read from the file.
- Source: [sequence_importer.py:1122](C:/depot/tools/unreal_tools/sequence_importer.py:1122)

### `api.dcc.unreal.references(...)`

- Target: `unreal_tools.validate.references`
- Signature: `references(paths=None, compile_blueprints=True, save=False)`
- API names: `references`
- Args:
  - `paths`, default `None`
  - `compile_blueprints`, default `True`
  - `save`, default `False`
- Description: Validate paths and optionally compile Blueprints without saving by default.
- Source: [validate.py:15](C:/depot/tools/unreal_tools/validate.py:15)

### `api.dcc.unreal.render_level_sequence(...)`

- Target: `unreal_tools.sequence_importer.render_level_sequence`
- Signature: `render_level_sequence(level_sequence_path, output_directory, resolution=(1920, 1080))`
- API names: `render_level_sequence`
- Args:
  - `level_sequence_path`, required
  - `output_directory`, required
  - `resolution`, default `(1920, 1080)`
- Related functions:
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
  - same_module: [`api.dcc.unreal.add_camera_actor_to_level_sequence(...)`](#apidccunrealadd_camera_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:120](C:/depot/tools/unreal_tools/sequence_importer.py:120)
  - same_module: [`api.dcc.unreal.add_camera_anim_to_level_sequence(...)`](#apidccunrealadd_camera_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_camera_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:368](C:/depot/tools/unreal_tools/sequence_importer.py:368)
- Description: Renders a level sequence to the specified directory. :param level_sequence_path: Path to the level sequence to render. :param output_directory: Directory where the rendered output will be saved. :param resolution: Resolution of the render. :return: Path to the output directory.
- Source: [sequence_importer.py:1081](C:/depot/tools/unreal_tools/sequence_importer.py:1081)

### `api.dcc.unreal.resolve_actor(...)`

- Target: `unreal_tools.level.resolve_actor`
- Signature: `resolve_actor(query="selected", allow_asset_lookup=True)`
- API names: `resolve_actor`
- Args:
  - `query`, default `'selected'`
  - `allow_asset_lookup`, default `True`
- Description: Resolve a name/label/path/tag/Blueprint or mesh asset name to level actors.
- Source: [level.py:117](C:/depot/tools/unreal_tools/level.py:117)

### `api.dcc.unreal.resolve_asset(...)`

- Target: `unreal_tools.assets.resolve_asset`
- Signature: `resolve_asset(file_name, expected_class="", directory="/Game")`
- API names: `resolve_asset`
- Args:
  - `file_name`, required
  - `expected_class`, default `''`
  - `directory`, default `'/Game'`
- Related functions:
  - same_module: [`api.dcc.unreal.find_asset_path_by_name(...)`](#apidccunrealfind_asset_path_by_name) -> `unreal_tools.assets.find_asset_path_by_name` - Shares module and name terms; may be useful in the same workflow.; source [assets.py:45](C:/depot/tools/unreal_tools/assets.py:45)
  - same_module: [`api.dcc.unreal.inspect_asset(...)`](#apidccunrealinspect_asset) -> `unreal_tools.assets.inspect_asset` - Shares module and name terms; may be useful in the same workflow.; source [assets.py:23](C:/depot/tools/unreal_tools/assets.py:23)
- Description: Return a compact serializable asset handle by name/path.
- Source: [assets.py:121](C:/depot/tools/unreal_tools/assets.py:121)

### `api.dcc.unreal.run_create_cinematic_sequence(...)`

- Target: `unreal_tools.unreal_subprocess.run_create_cinematic_sequence`
- Signature: `run_create_cinematic_sequence(anim_dict_path, destination_path, unreal_project_path, log_file_path,`
- API names: `run_create_cinematic_sequence`
- Args:
  - `anim_dict_path`, required
  - `destination_path`, required
  - `unreal_project_path`, required
  - `log_file_path`, required
  - `unreal_command_path`, default `'C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe'`
- Related functions:
  - same_module: [`api.dcc.unreal.run_create_modular_control_rig(...)`](#apidccunrealrun_create_modular_control_rig) -> `unreal_tools.unreal_subprocess.run_create_modular_control_rig` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:186](C:/depot/tools/unreal_tools/unreal_subprocess.py:186)
  - same_module: [`api.dcc.unreal.run_get_skeletons(...)`](#apidccunrealrun_get_skeletons) -> `unreal_tools.unreal_subprocess.run_get_skeletons` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:8](C:/depot/tools/unreal_tools/unreal_subprocess.py:8)
  - same_module: [`api.dcc.unreal.run_import_gameplay_animations(...)`](#apidccunrealrun_import_gameplay_animations) -> `unreal_tools.unreal_subprocess.run_import_gameplay_animations` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:127](C:/depot/tools/unreal_tools/unreal_subprocess.py:127)
- Description: :param anim_dict_path: Path of Json data :param destination_path: Path to save Cinematic :param unreal_project_path: path to the unreal project :param log_file_path: log file path for returning output (function exists to find this in unreal_project_data.py) :param unreal_command_path: unreal cmd exe for version of editor (function exists to find this in unreal_project_data.py) :return:
- Source: [unreal_subprocess.py:63](C:/depot/tools/unreal_tools/unreal_subprocess.py:63)

### `api.dcc.unreal.run_create_modular_control_rig(...)`

- Target: `unreal_tools.unreal_subprocess.run_create_modular_control_rig`
- Signature: `run_create_modular_control_rig(skeletal_mesh_name, rig_name, joint_map, unreal_project_path, log_file_path,`
- API names: `run_create_modular_control_rig`
- Args:
  - `skeletal_mesh_name`, required
  - `rig_name`, required
  - `joint_map`, required
  - `unreal_project_path`, required
  - `log_file_path`, required
  - `unreal_command_path`, default `'C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe'`
- Related functions:
  - same_module: [`api.dcc.unreal.run_create_cinematic_sequence(...)`](#apidccunrealrun_create_cinematic_sequence) -> `unreal_tools.unreal_subprocess.run_create_cinematic_sequence` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:63](C:/depot/tools/unreal_tools/unreal_subprocess.py:63)
  - same_module: [`api.dcc.unreal.run_get_skeletons(...)`](#apidccunrealrun_get_skeletons) -> `unreal_tools.unreal_subprocess.run_get_skeletons` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:8](C:/depot/tools/unreal_tools/unreal_subprocess.py:8)
  - same_module: [`api.dcc.unreal.run_import_gameplay_animations(...)`](#apidccunrealrun_import_gameplay_animations) -> `unreal_tools.unreal_subprocess.run_import_gameplay_animations` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:127](C:/depot/tools/unreal_tools/unreal_subprocess.py:127)
- Description: :param joint_map: Joint Map from HumanIK UI, for clear mapping for biped body parts :param rig_name: control rig asset name (saved to same folder as skeletal mesh) :param skeletal_mesh_name: skeletal mesh to assign to rig :param unreal_project_path: path to the unreal project :param log_file_path: log file path for returning output (function exists to find this in unreal_project_data.py) :param unreal_command_path: unreal cmd exe for version of editor (function exists to find this in unreal_proj
- Source: [unreal_subprocess.py:186](C:/depot/tools/unreal_tools/unreal_subprocess.py:186)

### `api.dcc.unreal.run_get_skeletons(...)`

- Target: `unreal_tools.unreal_subprocess.run_get_skeletons`
- Signature: `run_get_skeletons(unreal_project_path, log_file_path,`
- API names: `run_get_skeletons`
- Args:
  - `unreal_project_path`, required
  - `log_file_path`, required
  - `unreal_command_path`, default `'C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe'`
  - `asset_type`, default `'Skeleton'`
- Related functions:
  - same_module: [`api.dcc.unreal.run_create_cinematic_sequence(...)`](#apidccunrealrun_create_cinematic_sequence) -> `unreal_tools.unreal_subprocess.run_create_cinematic_sequence` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:63](C:/depot/tools/unreal_tools/unreal_subprocess.py:63)
  - same_module: [`api.dcc.unreal.run_create_modular_control_rig(...)`](#apidccunrealrun_create_modular_control_rig) -> `unreal_tools.unreal_subprocess.run_create_modular_control_rig` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:186](C:/depot/tools/unreal_tools/unreal_subprocess.py:186)
  - same_module: [`api.dcc.unreal.run_import_gameplay_animations(...)`](#apidccunrealrun_import_gameplay_animations) -> `unreal_tools.unreal_subprocess.run_import_gameplay_animations` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:127](C:/depot/tools/unreal_tools/unreal_subprocess.py:127)
- Description: :param asset_type: type of asset to search for :param unreal_project_path: path to the unreal project :param log_file_path: log file path for returning output (function exists to find this in unreal_project_data.py) :param unreal_command_path: unreal cmd exe for version of editor (function exists to find this in unreal_project_data.py) :return:
- Source: [unreal_subprocess.py:8](C:/depot/tools/unreal_tools/unreal_subprocess.py:8)

### `api.dcc.unreal.run_import_gameplay_animations(...)`

- Target: `unreal_tools.unreal_subprocess.run_import_gameplay_animations`
- Signature: `run_import_gameplay_animations(anim_dict_path, unreal_project_path, log_file_path,`
- API names: `run_import_gameplay_animations`
- Args:
  - `anim_dict_path`, required
  - `unreal_project_path`, required
  - `log_file_path`, required
  - `unreal_command_path`, default `'C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe'`
- Related functions:
  - same_module: [`api.dcc.unreal.run_create_cinematic_sequence(...)`](#apidccunrealrun_create_cinematic_sequence) -> `unreal_tools.unreal_subprocess.run_create_cinematic_sequence` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:63](C:/depot/tools/unreal_tools/unreal_subprocess.py:63)
  - same_module: [`api.dcc.unreal.run_create_modular_control_rig(...)`](#apidccunrealrun_create_modular_control_rig) -> `unreal_tools.unreal_subprocess.run_create_modular_control_rig` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:186](C:/depot/tools/unreal_tools/unreal_subprocess.py:186)
  - same_module: [`api.dcc.unreal.run_get_skeletons(...)`](#apidccunrealrun_get_skeletons) -> `unreal_tools.unreal_subprocess.run_get_skeletons` - Shares module and name terms; may be useful in the same workflow.; source [unreal_subprocess.py:8](C:/depot/tools/unreal_tools/unreal_subprocess.py:8)
- Description: :param anim_dict_path: Path of Json data :param unreal_project_path: path to the unreal project :param log_file_path: log file path for returning output (function exists to find this in unreal_project_data.py) :param unreal_command_path: unreal cmd exe for version of editor (function exists to find this in unreal_project_data.py) :return:
- Source: [unreal_subprocess.py:127](C:/depot/tools/unreal_tools/unreal_subprocess.py:127)

### `api.dcc.unreal.run_server(...)`

- Target: `unreal_tools.http_server.run_server`
- Signature: `run_server()`
- API names: `run_server`
- Args: none
- Related functions:
  - same_module: [`api.dcc.unreal.start_http_server_in_thread(...)`](#apidccunrealstart_http_server_in_thread) -> `unreal_tools.http_server.start_http_server_in_thread` - Shares module and name terms; may be useful in the same workflow.; source [http_server.py:144](C:/depot/tools/unreal_tools/http_server.py:144)
- Source: [http_server.py:130](C:/depot/tools/unreal_tools/http_server.py:130)

### `api.dcc.unreal.scan_blueprint(...)`

- Target: `unreal_tools.blueprint.scan_blueprint`
- Signature: `scan_blueprint(asset_path, include_graphs=True, include_defaults=True)`
- API names: `scan_blueprint`
- Args:
  - `asset_path`, required
  - `include_graphs`, default `True`
  - `include_defaults`, default `True`
- Related functions:
  - same_module: [`api.dcc.unreal.compile_blueprint(...)`](#apidccunrealcompile_blueprint) -> `unreal_tools.blueprint.compile_blueprint` - Shares module and name terms; may be useful in the same workflow.; source [blueprint.py:63](C:/depot/tools/unreal_tools/blueprint.py:63)
- Source: [blueprint.py:15](C:/depot/tools/unreal_tools/blueprint.py:15)

### `api.dcc.unreal.scan_loaded_level(...)`

- Target: `unreal_tools.level.scan_loaded_level`
- Signature: `scan_loaded_level(include_components=True, max_actors=2000)`
- API names: `scan_loaded_level`
- Args:
  - `include_components`, default `True`
  - `max_actors`, default `2000`
- Description: Return JSON-serializable facts about the currently loaded editor level.
- Source: [level.py:49](C:/depot/tools/unreal_tools/level.py:49)

### `api.dcc.unreal.select_actors_by_query(...)`

- Target: `unreal_tools.level.select_actors_by_query`
- Signature: `select_actors_by_query(query)`
- API names: `select_actors_by_query`
- Args:
  - `query`, required
- Description: Resolve actor query/queries to real Actor objects and select them in-editor.
- Source: [level.py:219](C:/depot/tools/unreal_tools/level.py:219)

### `api.dcc.unreal.set_frame_rate(...)`

- Target: `unreal_tools.sequence_importer.set_frame_rate`
- Signature: `set_frame_rate(sequence, fps)`
- API names: `set_frame_rate`
- Args:
  - `sequence`, required
  - `fps`, required
- Related functions:
  - same_module: [`api.dcc.unreal.call('unreal_tools.sequence_importer.set_section_range', ...)`](#apidccunrealcallunreal_toolssequence_importerset_section_range) -> `unreal_tools.sequence_importer.set_section_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1281](C:/depot/tools/unreal_tools/sequence_importer.py:1281)
  - same_module: [`api.dcc.unreal.set_sequence_range(...)`](#apidccunrealset_sequence_range) -> `unreal_tools.sequence_importer.set_sequence_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1305](C:/depot/tools/unreal_tools/sequence_importer.py:1305)
- Description: Sets the start and end time for the given Level Sequence directly. :param sequence: The LevelSequence asset to modify. :param fps: Frame Rate from Export data
- Source: [sequence_importer.py:1330](C:/depot/tools/unreal_tools/sequence_importer.py:1330)

### `api.dcc.unreal.set_sequence_range(...)`

- Target: `unreal_tools.sequence_importer.set_sequence_range`
- Signature: `set_sequence_range(sequence, start_frame, end_frame)`
- API names: `set_sequence_range`
- Args:
  - `sequence`, required
  - `start_frame`, required
  - `end_frame`, required
- Related functions:
  - same_module: [`api.dcc.unreal.call('unreal_tools.sequence_importer.set_section_range', ...)`](#apidccunrealcallunreal_toolssequence_importerset_section_range) -> `unreal_tools.sequence_importer.set_section_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1281](C:/depot/tools/unreal_tools/sequence_importer.py:1281)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
  - same_module: [`api.dcc.unreal.add_blueprint_mesh_components_to_level_sequence(...)`](#apidccunrealadd_blueprint_mesh_components_to_level_sequence) -> `unreal_tools.sequence_importer.add_blueprint_mesh_components_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:249](C:/depot/tools/unreal_tools/sequence_importer.py:249)
- Description: Sets the start and end time for the given Level Sequence directly. :param sequence: The LevelSequence asset to modify. :param start_frame: The start time (in frames). :param end_frame: The end time (in frames).
- Source: [sequence_importer.py:1305](C:/depot/tools/unreal_tools/sequence_importer.py:1305)

### `api.dcc.unreal.start_http_server_in_thread(...)`

- Target: `unreal_tools.http_server.start_http_server_in_thread`
- Signature: `start_http_server_in_thread()`
- API names: `start_http_server_in_thread`
- Args: none
- Related functions:
  - same_module: [`api.dcc.unreal.run_server(...)`](#apidccunrealrun_server) -> `unreal_tools.http_server.run_server` - Shares module and name terms; may be useful in the same workflow.; source [http_server.py:130](C:/depot/tools/unreal_tools/http_server.py:130)
- Source: [http_server.py:144](C:/depot/tools/unreal_tools/http_server.py:144)

### `api.dcc.unreal.tick(...)`

- Target: `unreal_tools.http_server.tick`
- Signature: `tick(delta_time)`
- API names: `tick`
- Args:
  - `delta_time`, required
- Source: [http_server.py:54](C:/depot/tools/unreal_tools/http_server.py:54)

### `api.dcc.unreal.update_asset_registry_and_save(...)`

- Target: `unreal_tools.sequence_importer.update_asset_registry_and_save`
- Signature: `update_asset_registry_and_save(asset_directory, asset_path)`
- API names: `update_asset_registry_and_save`
- Args:
  - `asset_directory`, required
  - `asset_path`, required
- Description: Saves the asset after refreshing, seems necessary from cmd.exe :param asset_directory: directory to refresh assets for :param asset_path: asset path to save :return:
- Source: [sequence_importer.py:1318](C:/depot/tools/unreal_tools/sequence_importer.py:1318)

### `api.dcc.unreal.write_dict_to_file(...)`

- Target: `unreal_tools.sequence_importer.write_dict_to_file`
- Signature: `write_dict_to_file(anim_dict, file_path)`
- API names: `write_dict_to_file`
- Args:
  - `anim_dict`, required
  - `file_path`, required
- Related functions:
  - same_module: [`api.dcc.unreal.read_dict_from_file(...)`](#apidccunrealread_dict_from_file) -> `unreal_tools.sequence_importer.read_dict_from_file` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1122](C:/depot/tools/unreal_tools/sequence_importer.py:1122)
- Description: Writes a dictionary to a JSON file. :param anim_dict: The dictionary to write to a file. :param file_path: Path where the file will be saved. :return: Path to the saved file.
- Source: [sequence_importer.py:1105](C:/depot/tools/unreal_tools/sequence_importer.py:1105)

### `api.dcc.unreal.call('unreal_tools.sequence_func.create_cinematic_sequence_from_json', ...)`

- Target: `unreal_tools.sequence_func.create_cinematic_sequence_from_json`
- Signature: `create_cinematic_sequence_from_json(anim_dict_path, destination_path="/Game/Cinematics")`
- Name status: ambiguous; use the full target path.
- Args:
  - `anim_dict_path`, required
  - `destination_path`, default `'/Game/Cinematics'`
- Description: :param anim_dict_path: path to json with sequence_data :param destination_path: path to where Cinematics are stored in project :return:
- Source: [sequence_func.py:7](C:/depot/tools/unreal_tools/sequence_func.py:7)

### `api.dcc.unreal.call('unreal_tools.sequence_importer.create_cinematic_sequence_from_json', ...)`

- Target: `unreal_tools.sequence_importer.create_cinematic_sequence_from_json`
- Signature: `create_cinematic_sequence_from_json(anim_dict_path, destination_path="/Game/Cinematics/", from_cmd=True)`
- Name status: ambiguous; use the full target path.
- Args:
  - `anim_dict_path`, required
  - `destination_path`, default `'/Game/Cinematics/'`
  - `from_cmd`, default `True`
- Related functions:
  - same_module: [`api.dcc.unreal.create_cinematic_sequence(...)`](#apidccunrealcreate_cinematic_sequence) -> `unreal_tools.sequence_importer.create_cinematic_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1393](C:/depot/tools/unreal_tools/sequence_importer.py:1393)
  - same_module: [`api.dcc.unreal.create_level_sequence(...)`](#apidccunrealcreate_level_sequence) -> `unreal_tools.sequence_importer.create_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1343](C:/depot/tools/unreal_tools/sequence_importer.py:1343)
  - same_module: [`api.dcc.unreal.import_gameplay_animations_from_json(...)`](#apidccunrealimport_gameplay_animations_from_json) -> `unreal_tools.sequence_importer.import_gameplay_animations_from_json` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:812](C:/depot/tools/unreal_tools/sequence_importer.py:812)
  - same_module: [`api.dcc.unreal.add_actor_to_level_sequence(...)`](#apidccunrealadd_actor_to_level_sequence) -> `unreal_tools.sequence_importer.add_actor_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:11](C:/depot/tools/unreal_tools/sequence_importer.py:11)
  - same_module: [`api.dcc.unreal.add_anim_to_level_sequence(...)`](#apidccunrealadd_anim_to_level_sequence) -> `unreal_tools.sequence_importer.add_anim_to_level_sequence` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:196](C:/depot/tools/unreal_tools/sequence_importer.py:196)
- Description: Creates a cinematic sequence in Unreal Engine from a JSON file. :param anim_dict_path: Path to the JSON file containing animation data, generated from maya export :param destination_path: Path to the directory where the cinematic sequence will be saved in Unreal Engine. :return: Path to the created sequence.
- Source: [sequence_importer.py:1369](C:/depot/tools/unreal_tools/sequence_importer.py:1369)

### `api.dcc.unreal.call('unreal_tools.control_rig.find_uasset_path', ...)`

- Target: `unreal_tools.control_rig.find_uasset_path`
- Signature: `find_uasset_path(file_name)`
- Name status: ambiguous; use the full target path.
- Args:
  - `file_name`, required
- Description: Finds the path of a .uasset file by name. :param file_name: The name of the asset to find. :return: Path to the asset if found, None otherwise.
- Source: [control_rig.py:537](C:/depot/tools/unreal_tools/control_rig.py:537)

### `api.dcc.unreal.call('unreal_tools.sequence_importer.find_uasset_path', ...)`

- Target: `unreal_tools.sequence_importer.find_uasset_path`
- Signature: `find_uasset_path(file_name)`
- Name status: ambiguous; use the full target path.
- Args:
  - `file_name`, required
- Related functions:
  - same_module: [`api.dcc.unreal.extract_shot_number_from_path(...)`](#apidccunrealextract_shot_number_from_path) -> `unreal_tools.sequence_importer.extract_shot_number_from_path` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:795](C:/depot/tools/unreal_tools/sequence_importer.py:795)
  - same_module: [`api.dcc.unreal.find_actor_by_blueprint_or_skeletal_mesh(...)`](#apidccunrealfind_actor_by_blueprint_or_skeletal_mesh) -> `unreal_tools.sequence_importer.find_actor_by_blueprint_or_skeletal_mesh` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1174](C:/depot/tools/unreal_tools/sequence_importer.py:1174)
  - same_module: [`api.dcc.unreal.find_binding_for_component(...)`](#apidccunrealfind_binding_for_component) -> `unreal_tools.sequence_importer.find_binding_for_component` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1241](C:/depot/tools/unreal_tools/sequence_importer.py:1241)
  - same_module: [`api.dcc.unreal.find_camera_component_in_scene(...)`](#apidccunrealfind_camera_component_in_scene) -> `unreal_tools.sequence_importer.find_camera_component_in_scene` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1263](C:/depot/tools/unreal_tools/sequence_importer.py:1263)
  - same_module: [`api.dcc.unreal.find_possessable_for_actor(...)`](#apidccunrealfind_possessable_for_actor) -> `unreal_tools.sequence_importer.find_possessable_for_actor` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1226](C:/depot/tools/unreal_tools/sequence_importer.py:1226)
- Description: Finds the path of a .uasset file by name. :param file_name: The name of the asset to find. :return: Path to the asset if found, None otherwise.
- Source: [sequence_importer.py:1152](C:/depot/tools/unreal_tools/sequence_importer.py:1152)

### `api.dcc.unreal.call('unreal_tools.sequence_importer.set_section_range', ...)`

- Target: `unreal_tools.sequence_importer.set_section_range`
- Signature: `set_section_range(section, start_frame, end_frame)`
- Name status: ambiguous; use the full target path.
- Args:
  - `section`, required
  - `start_frame`, required
  - `end_frame`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_section_range(...)`](#apidccunrealget_section_range) -> `unreal_tools.sequence_importer.get_section_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1293](C:/depot/tools/unreal_tools/sequence_importer.py:1293)
  - same_module: [`api.dcc.unreal.set_sequence_range(...)`](#apidccunrealset_sequence_range) -> `unreal_tools.sequence_importer.set_sequence_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1305](C:/depot/tools/unreal_tools/sequence_importer.py:1305)
  - same_module: [`api.dcc.unreal.add_shot_sequence_section_to_shot_track(...)`](#apidccunrealadd_shot_sequence_section_to_shot_track) -> `unreal_tools.sequence_importer.add_shot_sequence_section_to_shot_track` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:171](C:/depot/tools/unreal_tools/sequence_importer.py:171)
  - same_module: [`api.dcc.unreal.get_full_range(...)`](#apidccunrealget_full_range) -> `unreal_tools.sequence_importer.get_full_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:947](C:/depot/tools/unreal_tools/sequence_importer.py:947)
  - same_module: [`api.dcc.unreal.offset_key_times_in_section(...)`](#apidccunrealoffset_key_times_in_section) -> `unreal_tools.sequence_importer.offset_key_times_in_section` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:462](C:/depot/tools/unreal_tools/sequence_importer.py:462)
- Description: Sets the start and end time for the given section directly. :param section: actual section object in sequencer :param start_frame: start frame to set the section to :param end_frame: end frame to set the section to :return:
- Source: [sequence_importer.py:509](C:/depot/tools/unreal_tools/sequence_importer.py:509)

### `api.dcc.unreal.call('unreal_tools.sequence_importer.set_section_range', ...)`

- Target: `unreal_tools.sequence_importer.set_section_range`
- Signature: `set_section_range(section, start_frame, end_frame)`
- Name status: ambiguous; use the full target path.
- Args:
  - `section`, required
  - `start_frame`, required
  - `end_frame`, required
- Related functions:
  - same_module: [`api.dcc.unreal.get_section_range(...)`](#apidccunrealget_section_range) -> `unreal_tools.sequence_importer.get_section_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1293](C:/depot/tools/unreal_tools/sequence_importer.py:1293)
  - same_module: [`api.dcc.unreal.set_sequence_range(...)`](#apidccunrealset_sequence_range) -> `unreal_tools.sequence_importer.set_sequence_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:1305](C:/depot/tools/unreal_tools/sequence_importer.py:1305)
  - same_module: [`api.dcc.unreal.add_shot_sequence_section_to_shot_track(...)`](#apidccunrealadd_shot_sequence_section_to_shot_track) -> `unreal_tools.sequence_importer.add_shot_sequence_section_to_shot_track` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:171](C:/depot/tools/unreal_tools/sequence_importer.py:171)
  - same_module: [`api.dcc.unreal.get_full_range(...)`](#apidccunrealget_full_range) -> `unreal_tools.sequence_importer.get_full_range` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:947](C:/depot/tools/unreal_tools/sequence_importer.py:947)
  - same_module: [`api.dcc.unreal.offset_key_times_in_section(...)`](#apidccunrealoffset_key_times_in_section) -> `unreal_tools.sequence_importer.offset_key_times_in_section` - Shares module and name terms; may be useful in the same workflow.; source [sequence_importer.py:462](C:/depot/tools/unreal_tools/sequence_importer.py:462)
- Description: Sets the start and end time for the given section directly. :param section: actual section object in sequencer :param start_frame: start frame to set the section to :param end_frame: end frame to set the section to :return:
- Source: [sequence_importer.py:1281](C:/depot/tools/unreal_tools/sequence_importer.py:1281)
