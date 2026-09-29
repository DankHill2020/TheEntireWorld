from __future__ import annotations

"""Adaptive scene commands for TC-native and bridged DCC scene elements.

This layer intentionally sits above individual DCC APIs. A user can activate one
tool, such as "split edge loop", and the command resolver decides whether the
selection should execute against a local Tech Connector mesh, a Maya bridge
instance, a Blender bridge instance, or a game-engine/plugin target.
"""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SceneCommandTarget:
    provider: str = "tech_connector"
    native_id: str = ""
    source_key: str = ""
    object_type: str = "mesh"
    component_type: str = "object"
    components: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def provider_base(self) -> str:
        return self.provider.split(":", 1)[0].strip().lower() or "tech_connector"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdaptiveSceneCommand:
    key: str
    label: str
    department: str
    subjects: tuple[str, ...]
    component_types: tuple[str, ...] = ("object",)
    preferred_hosts: tuple[str, ...] = ("tech_connector",)
    engine_import_required: bool = True
    tc_native_status: str = "planned"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        from tech_connector.game_engine.integration.capability_maturity_service import assess_capability

        assessment = assess_capability(self)
        data["verified_maturity"] = assessment.verified_maturity
        data["next_maturity"] = assessment.next_maturity
        data["missing_qualification_gates"] = list(assessment.missing_gates)
        return data


@dataclass
class SceneCommandRoute:
    command: dict[str, Any]
    target: dict[str, Any]
    host: str
    execution_mode: str
    status: str
    callable: str = ""
    script: str = ""
    required_payload: dict[str, Any] = field(default_factory=dict)
    validation: list[str] = field(default_factory=list)
    fallback: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ADAPTIVE_SCENE_COMMANDS: dict[str, AdaptiveSceneCommand] = {
    "scene.compose_usd": AdaptiveSceneCommand(
        key="scene.compose_usd",
        label="Compose OpenUSD Stage",
        department="pipeline",
        subjects=("scene", "asset", "layer", "variant", "payload"),
        component_types=("object",),
        preferred_hosts=("tech_connector",),
        tc_native_status="implemented",
        notes="Compose ordered USD layers through an isolated OpenUSD runtime with variants, payload policies, property overrides, cancellation, and bounded inspection.",
    ),
    "scene.inspect_usd_composition": AdaptiveSceneCommand(
        key="scene.inspect_usd_composition",
        label="Inspect OpenUSD Composition",
        department="pipeline",
        subjects=("scene", "asset", "layer", "variant", "payload"),
        component_types=("object",),
        preferred_hosts=("tech_connector",),
        engine_import_required=False,
        tc_native_status="implemented",
        notes="Report source-layer changes, authored opinions, composed prim inventory, diagnostics, and the last output manifest.",
    ),
    "scene.set_usd_variant": AdaptiveSceneCommand(
        key="scene.set_usd_variant",
        label="Set OpenUSD Variant",
        department="pipeline",
        subjects=("scene", "asset", "variant"),
        component_types=("object",),
        preferred_hosts=("tech_connector",),
        tc_native_status="implemented",
        notes="Author or remove a variant selection and asynchronously recompose the attached stage.",
    ),
    "scene.set_usd_payload": AdaptiveSceneCommand(
        key="scene.set_usd_payload",
        label="Set OpenUSD Payload Policy",
        department="pipeline",
        subjects=("scene", "asset", "payload"),
        component_types=("object",),
        preferred_hosts=("tech_connector",),
        tc_native_status="implemented",
        notes="Load, unload, or restore the default payload policy for a prim and recompose the attached stage.",
    ),
    "scene.set_usd_override": AdaptiveSceneCommand(
        key="scene.set_usd_override",
        label="Set OpenUSD Property Override",
        department="pipeline",
        subjects=("scene", "asset", "property", "animation"),
        component_types=("object",),
        preferred_hosts=("tech_connector",),
        tc_native_status="implemented",
        notes="Author or remove typed default or time-sampled property opinions and recompose the attached stage.",
    ),
    "scene.convert_to_tc": AdaptiveSceneCommand(
        key="scene.convert_to_tc",
        label="Convert To TC",
        department="pipeline",
        subjects=("asset", "mesh", "skeletal_mesh", "material", "animation", "camera"),
        component_types=("object",),
        preferred_hosts=("maya", "blender", "motionbuilder", "houdini", "unreal", "substance_painter", "tech_connector"),
        tc_native_status="implemented",
        notes="Convert a bridge/imported DCC scene into TC-native scene graph, meshes, rigs, materials, animation takes, shots, and transfer receipts.",
    ),
    "scene.convert_selection_to_tc": AdaptiveSceneCommand(
        key="scene.convert_selection_to_tc",
        label="Convert Selection To TC",
        department="pipeline",
        subjects=("asset", "mesh", "skeletal_mesh", "material", "animation", "camera"),
        component_types=("object", "face", "edge", "vertex"),
        preferred_hosts=("maya", "blender", "motionbuilder", "houdini", "unreal", "substance_painter", "tech_connector"),
        tc_native_status="implemented",
        notes="Convert only selected DCC elements to TC-native assets while keeping source links for round-trip or comparison.",
    ),
    "modeling.split_edge_loop": AdaptiveSceneCommand(
        key="modeling.split_edge_loop",
        label="Split Edge Loop",
        department="modeling",
        subjects=("mesh", "static_mesh", "skeletal_mesh"),
        component_types=("edge", "edge_loop", "object"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
        notes="Topology-aware quad-ring insertion supports multiple evenly spaced cuts; bridge targets use host-native loop cut APIs.",
    ),
    "modeling.restore_default_pose": AdaptiveSceneCommand(
        key="modeling.restore_default_pose",
        label="Restore Default Mesh Pose",
        department="modeling",
        subjects=("mesh", "static_mesh", "skeletal_mesh"),
        component_types=("object",),
        preferred_hosts=("tech_connector",),
        tc_native_status="implemented",
        notes="Restore the mesh-owned default vertex shape without changing topology, UVs, paint, or materials.",
    ),
    "modeling.update_default_pose": AdaptiveSceneCommand(
        key="modeling.update_default_pose",
        label="Update Default Mesh Pose",
        department="modeling",
        subjects=("mesh", "static_mesh", "skeletal_mesh"),
        component_types=("object",),
        preferred_hosts=("tech_connector",),
        tc_native_status="implemented",
        notes="Store the current vertex shape as the mesh-owned default pose for later restoration.",
    ),
    "modeling.bevel_edges": AdaptiveSceneCommand(
        key="modeling.bevel_edges",
        label="Bevel Edges",
        department="modeling",
        subjects=("mesh", "static_mesh", "skeletal_mesh"),
        component_types=("edge", "edge_loop", "object"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
        notes="TC-native single-segment bevel supports vertex-disjoint boundary and manifold edges with filled endpoint caps.",
    ),
    "modeling.extrude_faces": AdaptiveSceneCommand(
        key="modeling.extrude_faces",
        label="Extrude Faces",
        department="modeling",
        subjects=("mesh", "static_mesh", "skeletal_mesh"),
        component_types=("face", "object"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
        notes="TC-native region extrusion shares boundary vertices and creates walls only on region boundaries.",
    ),
    "modeling.delete_faces": AdaptiveSceneCommand(
        key="modeling.delete_faces",
        label="Delete Faces",
        department="modeling",
        subjects=("mesh", "static_mesh", "skeletal_mesh"),
        component_types=("face",),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
    ),
    "modeling.triangulate_faces": AdaptiveSceneCommand(
        key="modeling.triangulate_faces",
        label="Triangulate Faces",
        department="modeling",
        subjects=("mesh", "static_mesh", "skeletal_mesh"),
        component_types=("face", "object"),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Deterministic fan triangulation supports engine-safe export and topology receipts.",
    ),
    "modeling.merge_vertices": AdaptiveSceneCommand(
        key="modeling.merge_vertices",
        label="Merge Vertices",
        department="modeling",
        subjects=("mesh", "static_mesh", "skeletal_mesh"),
        component_types=("vertex", "vertex_set"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
    ),
    "modeling.bridge_edge_loops": AdaptiveSceneCommand(
        key="modeling.bridge_edge_loops",
        label="Bridge Edge Loops",
        department="modeling",
        subjects=("mesh", "static_mesh", "skeletal_mesh"),
        component_types=("edge", "edge_loop"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
        notes="TC-native bridge currently requires two ordered loops with equal vertex counts.",
    ),
    "rigging.parent_constraint": AdaptiveSceneCommand(
        key="rigging.parent_constraint",
        label="Parent Constraint",
        department="rigging",
        subjects=("transform", "joint", "control", "skeletal_mesh"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "motionbuilder", "blender", "unreal"),
        tc_native_status="implemented",
        notes="TC owns the semantic constraint and can drive live DCC targets or bake keys.",
    ),
    "rigging.create_joint": AdaptiveSceneCommand(
        key="rigging.create_joint",
        label="Create Joint",
        department="rigging",
        subjects=("joint", "skeletal_mesh", "transform"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "motionbuilder", "blender"),
        tc_native_status="implemented",
        notes="Maya-cmds-like joint authoring for TC-native rigs and bridge targets.",
    ),
    "rigging.create_ik_handle": AdaptiveSceneCommand(
        key="rigging.create_ik_handle",
        label="Create IK Handle",
        department="rigging",
        subjects=("joint", "skeletal_mesh", "control"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "motionbuilder", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Generic IK handle abstraction: RP, SC, spline, two-bone, FABRIK, CCD, full-body, and host-specific solvers.",
    ),
    "rigging.create_ribbon_ik": AdaptiveSceneCommand(
        key="rigging.create_ribbon_ik",
        label="Create Ribbon IK",
        department="rigging",
        subjects=("joint", "control", "skeletal_mesh"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Ribbon/twist rig for limbs, spines, lips, tentacles, bendy controls, and volume preservation.",
    ),
    "rigging.create_motion_path_ik": AdaptiveSceneCommand(
        key="rigging.create_motion_path_ik",
        label="Create Motion Path IK",
        department="rigging",
        subjects=("joint", "control", "curve", "animation"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Constrain joints/controls along a curve with banking, roll, path percentage, and time/arc-length modes.",
    ),
    "rigging.create_quadruped_leg_ik": AdaptiveSceneCommand(
        key="rigging.create_quadruped_leg_ik",
        label="Create Quadruped Leg IK",
        department="rigging",
        subjects=("joint", "control", "skeletal_mesh"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "motionbuilder", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Build a live four-joint hip/knee/hock/ankle leg from two native RP IK stages with pole, foot-roll/bank channels, and gait metadata.",
    ),
    "rigging.create_mechanical_ik": AdaptiveSceneCommand(
        key="rigging.create_mechanical_ik",
        label="Create Mechanical / Gear IK",
        department="rigging",
        subjects=("joint", "control", "transform"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Author editable gear, rack/pinion, pulley, hinge, piston, and hydraulic relationships as portable math nodes, plug connections, and live constraints.",
    ),
    "rigging.constrain_to_mesh": AdaptiveSceneCommand(
        key="rigging.constrain_to_mesh",
        label="Constrain To Mesh",
        department="rigging",
        subjects=("mesh", "transform", "joint", "control"),
        component_types=("object", "face", "vertex", "uv"),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Attach controls or joints to mesh surface by barycentric face, UV, follicle/rivet, or closest point.",
    ),
    "rigging.constrain_to_normal": AdaptiveSceneCommand(
        key="rigging.constrain_to_normal",
        label="Constrain To Surface Normal",
        department="rigging",
        subjects=("mesh", "transform", "joint", "control"),
        component_types=("object", "face", "vertex", "uv"),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Attach a transform to stable triangle IDs and barycentric coordinates, then orient it from a locally evaluated tangent/normal/binormal frame.",
    ),
    "rigging.create_pose_reader": AdaptiveSceneCommand(
        key="rigging.create_pose_reader",
        label="Create Pose Reader",
        department="rigging",
        subjects=("joint", "control", "deformer"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Angle/vector/pose-space readers for corrective shapes, rig logic, and game-engine driven deformation.",
    ),
    "rigging.create_space_switch": AdaptiveSceneCommand(
        key="rigging.create_space_switch",
        label="Create Space Switch",
        department="rigging",
        subjects=("control", "transform", "joint"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "motionbuilder", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Multi-parent/space switching with maintain offset, keyed space changes, and bake/readback support.",
    ),
    "skinning.bind_skin": AdaptiveSceneCommand(
        key="skinning.bind_skin",
        label="Bind Skin",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Bind selected mesh vertices to joint influences with distance, heat-map, geodesic voxel, current/existing, or TC auto-skin presets.",
    ),
    "skinning.auto_skin": AdaptiveSceneCommand(
        key="skinning.auto_skin",
        label="Auto Skin",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Run the TC/Maya auto-skinner path: bind, normalize, prune, smooth, and validate deformation parity.",
    ),
    "skinning.paint_weights": AdaptiveSceneCommand(
        key="skinning.paint_weights",
        label="Paint Skin Weights",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence", "vertex"),
        component_types=("object", "vertex", "vertex_set"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
        notes="Brush or component-based weight edits with replace/add/scale/smooth modes, normalization, and undo chunks.",
    ),
    "skinning.normalize_weights": AdaptiveSceneCommand(
        key="skinning.normalize_weights",
        label="Normalize Skin Weights",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence", "vertex"),
        component_types=("object", "vertex", "vertex_set"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
    ),
    "skinning.prune_weights": AdaptiveSceneCommand(
        key="skinning.prune_weights",
        label="Prune Skin Weights",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence", "vertex"),
        component_types=("object", "vertex", "vertex_set"),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Remove tiny weights and enforce max influences before engine export.",
    ),
    "skinning.smooth_weights": AdaptiveSceneCommand(
        key="skinning.smooth_weights",
        label="Smooth Skin Weights",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence", "vertex"),
        component_types=("object", "vertex", "vertex_set"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
    ),
    "skinning.mirror_weights": AdaptiveSceneCommand(
        key="skinning.mirror_weights",
        label="Mirror Skin Weights",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence", "vertex"),
        component_types=("object", "vertex", "vertex_set"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
        notes="Mirror left/right influence names and prepare for spatial mirror mapping.",
    ),
    "skinning.copy_weights": AdaptiveSceneCommand(
        key="skinning.copy_weights",
        label="Copy Skin Weights",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence"),
        component_types=("object", "vertex", "vertex_set"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
        notes="Copy by index now; UV, closest-point, barycentric, and topology modes should follow.",
    ),
    "skinning.transfer_weights": AdaptiveSceneCommand(
        key="skinning.transfer_weights",
        label="Transfer Skin Weights",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence"),
        component_types=("object", "vertex", "vertex_set"),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
        notes="Transfer weights between meshes by index now; closest point, UV, barycentric, and topology modes are routed as strategy metadata.",
    ),
    "skinning.add_influence": AdaptiveSceneCommand(
        key="skinning.add_influence",
        label="Add Skin Influence",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
    ),
    "skinning.remove_influence": AdaptiveSceneCommand(
        key="skinning.remove_influence",
        label="Remove Skin Influence",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "blender"),
        tc_native_status="implemented",
    ),
    "skinning.export_weights": AdaptiveSceneCommand(
        key="skinning.export_weights",
        label="Export Skin Weights",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence"),
        component_types=("object", "vertex_set"),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Export TC skin weights as checksummed tcskin/json with mesh-topology identity and up to 32 influences per vertex.",
    ),
    "skinning.import_weights": AdaptiveSceneCommand(
        key="skinning.import_weights",
        label="Import Skin Weights",
        department="skinning",
        subjects=("mesh", "skeletal_mesh", "joint", "influence"),
        component_types=("object", "vertex_set"),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="Import tcskin/json, Maya/Blender bridge readbacks, or engine-safe baked skin data.",
    ),
    "animation.set_keyframe": AdaptiveSceneCommand(
        key="animation.set_keyframe",
        label="Set Keyframe",
        department="animation",
        subjects=("transform", "joint", "control", "camera"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "maya", "motionbuilder", "blender", "unreal"),
        tc_native_status="implemented",
        notes="TC-native keyframes are stored in named takes and non-destructive animation layers.",
    ),
    "animation.create_take": AdaptiveSceneCommand(
        key="animation.create_take",
        label="Create Animation Take",
        department="animation",
        subjects=("animation", "transform", "joint", "control", "camera"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "motionbuilder", "maya", "blender", "unreal"),
        tc_native_status="implemented",
        notes="MotionBuilder-inspired named take with frame rate, range, and timecode metadata.",
    ),
    "animation.add_layer": AdaptiveSceneCommand(
        key="animation.add_layer",
        label="Add Animation Layer",
        department="animation",
        subjects=("animation", "transform", "joint", "control", "camera"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "motionbuilder", "maya", "blender"),
        tc_native_status="implemented",
    ),
    "characters.create": AdaptiveSceneCommand(
        key="characters.create", label="Create Intelligent Character", department="characters",
        subjects=("npc", "character", "agent", "world"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Create a serializable character profile with designer-owned parameters, traits, drives, values, rules, and dialogue style.",
    ),
    "characters.set_parameter": AdaptiveSceneCommand(
        key="characters.set_parameter", label="Set Character Parameter", department="characters",
        subjects=("npc", "character", "parameter", "personality"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Clamp authored values to their declared ranges and preserve designer locks.",
    ),
    "characters.add_rule": AdaptiveSceneCommand(
        key="characters.add_rule", label="Add Character Rule", department="characters",
        subjects=("npc", "character", "rule", "behavior"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "characters.add_objective": AdaptiveSceneCommand(
        key="characters.add_objective", label="Add Character Objective", department="characters",
        subjects=("npc", "character", "objective", "goal", "quest"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "characters.set_relationship": AdaptiveSceneCommand(
        key="characters.set_relationship", label="Set Character Relationship", department="characters",
        subjects=("npc", "character", "relationship", "social"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "characters.record_memory": AdaptiveSceneCommand(
        key="characters.record_memory", label="Record Character Memory", department="characters",
        subjects=("npc", "character", "memory", "knowledge", "belief"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "characters.choose_action": AdaptiveSceneCommand(
        key="characters.choose_action", label="Evaluate Character Actions", department="characters",
        subjects=("npc", "character", "action", "decision", "ai"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Return a deterministic why-receipt; optional model proposals cannot bypass authored rules or affordances.",
    ),
    "narrative.set_world_fact": AdaptiveSceneCommand(
        key="narrative.set_world_fact", label="Set Narrative World Fact", department="narrative",
        subjects=("world", "fact", "narrative", "state"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "narrative.add_beat": AdaptiveSceneCommand(
        key="narrative.add_beat", label="Add Narrative Beat", department="narrative",
        subjects=("narrative", "story", "beat", "quest"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "narrative.select_beat": AdaptiveSceneCommand(
        key="narrative.select_beat", label="Select Narrative Beat", department="narrative",
        subjects=("narrative", "story", "beat", "director"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Select and optionally apply an eligible beat without violating authored conditions, cooldowns, or one-shot rules.",
    ),
    "world_ai.add_sensor": AdaptiveSceneCommand(
        key="world_ai.add_sensor", label="Add Character Sensor", department="characters",
        subjects=("character", "perception", "sensor"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.add_navigation_graph": AdaptiveSceneCommand(
        key="world_ai.add_navigation_graph", label="Add Navigation Graph", department="characters",
        subjects=("world", "navigation", "crowd"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.add_smart_object": AdaptiveSceneCommand(
        key="world_ai.add_smart_object", label="Add Smart Object", department="characters",
        subjects=("world", "affordance", "interaction"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.add_behavior_graph": AdaptiveSceneCommand(
        key="world_ai.add_behavior_graph", label="Add Behavior Graph", department="characters",
        subjects=("character", "behavior", "state", "action"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.add_dialogue_set": AdaptiveSceneCommand(
        key="world_ai.add_dialogue_set", label="Add Dialogue Set", department="characters",
        subjects=("character", "dialogue", "narrative"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.add_group": AdaptiveSceneCommand(
        key="world_ai.add_group", label="Add Character Group", department="characters",
        subjects=("character", "group", "faction", "population"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.sense": AdaptiveSceneCommand(
        key="world_ai.sense", label="Evaluate Character Perception", department="characters",
        subjects=("character", "perception", "belief"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.find_path": AdaptiveSceneCommand(
        key="world_ai.find_path", label="Plan Character Path", department="characters",
        subjects=("character", "navigation", "path"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.reserve_smart_object": AdaptiveSceneCommand(
        key="world_ai.reserve_smart_object", label="Reserve Smart Object", department="characters",
        subjects=("character", "affordance", "interaction"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.evaluate_behavior": AdaptiveSceneCommand(
        key="world_ai.evaluate_behavior", label="Evaluate Behavior Graph", department="characters",
        subjects=("character", "behavior", "decision"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.choose_dialogue": AdaptiveSceneCommand(
        key="world_ai.choose_dialogue", label="Choose Dialogue Act", department="characters",
        subjects=("character", "dialogue", "intent"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.tick_group": AdaptiveSceneCommand(
        key="world_ai.tick_group", label="Simulate Character Group", department="characters",
        subjects=("character", "group", "population", "economy"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "world_ai.authorize_mutation": AdaptiveSceneCommand(
        key="world_ai.authorize_mutation", label="Authorize World Mutation", department="characters",
        subjects=("world", "network", "authority", "replication"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "gameplay.configure_experience": AdaptiveSceneCommand(
        key="gameplay.configure_experience", label="Configure Game Experience", department="gameplay",
        subjects=("game", "genre", "simulation", "education", "design"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "gameplay.validate_experience": AdaptiveSceneCommand(
        key="gameplay.validate_experience", label="Validate Game Experience", department="gameplay",
        subjects=("game", "accessibility", "education", "simulation", "design"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "gameplay.runtime_budget": AdaptiveSceneCommand(
        key="gameplay.runtime_budget", label="Plan Gameplay Runtime Budget", department="gameplay",
        subjects=("game", "performance", "scale", "simulation"), preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "gameplay.set_visual_style": AdaptiveSceneCommand(
        key="gameplay.set_visual_style", label="Set Visual Style", department="gameplay",
        subjects=("game", "visual", "style", "2d", "2.5d", "3d", "pixel", "realistic"),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Choose presentation independently from gameplay rules and simulation accuracy.",
    ),
    "gameplay.update_visual_setting": AdaptiveSceneCommand(
        key="gameplay.update_visual_setting", label="Change Visual Setting", department="gameplay",
        subjects=("game", "visual", "camera", "pixel", "animation", "presentation"),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "gameplay.explain_visual_settings": AdaptiveSceneCommand(
        key="gameplay.explain_visual_settings", label="Explain Visual Settings", department="gameplay",
        subjects=("game", "visual", "style", "help", "settings"),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "gameplay.preview_visual_plan": AdaptiveSceneCommand(
        key="gameplay.preview_visual_plan", label="Preview Visual Plan", department="gameplay",
        subjects=("game", "visual", "render", "performance", "preview"),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "procedural.create_scatter_graph": AdaptiveSceneCommand(
        key="procedural.create_scatter_graph",
        label="Create Procedural Scatter",
        department="procedural",
        subjects=("scene", "mesh", "terrain", "biome", "asset"),
        component_types=("object", "face", "volume"),
        preferred_hosts=("tech_connector", "unreal", "houdini", "blender", "unity", "godot"),
        tc_native_status="implemented",
        notes="Create an editable deterministic point, attribute, asset-selection, and instancing graph.",
    ),
    "procedural.generate_terrain": AdaptiveSceneCommand(
        key="procedural.generate_terrain",
        label="Generate Procedural Terrain",
        department="procedural",
        subjects=("terrain", "heightfield", "world", "landscape"),
        component_types=("object", "volume"),
        preferred_hosts=("tech_connector", "unreal", "houdini", "blender", "unity", "godot"),
        tc_native_status="implemented",
        notes="Generate deterministic multi-octave terrain with moisture and temperature layers and thermal erosion.",
    ),
    "procedural.erode_terrain": AdaptiveSceneCommand(
        key="procedural.erode_terrain",
        label="Hydraulically Erode Terrain",
        department="procedural",
        subjects=("terrain", "erosion", "river", "water", "sediment", "wetness"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "houdini", "unreal", "blender", "unity"),
        tc_native_status="implemented",
        notes="Produces deterministic height, flow, direction, sediment, wetness, and river-mask fields.",
    ),
    "procedural.generate_biome": AdaptiveSceneCommand(
        key="procedural.generate_biome",
        label="Generate Procedural Biome",
        department="procedural",
        subjects=("biome", "terrain", "vegetation", "world", "asset"),
        component_types=("object", "volume"),
        preferred_hosts=("tech_connector", "unreal", "houdini", "blender", "unity", "godot"),
        tc_native_status="implemented",
        notes="Place weighted species by elevation, slope, moisture, temperature, spacing, scale, tags, and runtime grid.",
    ),
    "procedural.generate_spline_layout": AdaptiveSceneCommand(
        key="procedural.generate_spline_layout",
        label="Generate Along Spline",
        department="procedural",
        subjects=("curve", "road", "rail", "fence", "pipe", "wall", "building"),
        component_types=("object", "curve", "control_point"),
        preferred_hosts=("tech_connector", "unreal", "houdini", "blender", "unity", "godot"),
        tc_native_status="implemented",
        notes="Expand bounded weighted shape grammar and place stable modular assets by arc length and tangent.",
    ),
    "procedural.create_mesh_graph": AdaptiveSceneCommand(
        key="procedural.create_mesh_graph",
        label="Create Procedural Mesh Graph",
        department="procedural",
        subjects=("mesh", "static_mesh", "terrain", "building", "asset"),
        component_types=("object", "face", "edge", "vertex"),
        preferred_hosts=("tech_connector", "unreal", "houdini", "blender", "unity", "godot"),
        tc_native_status="implemented",
        notes="Create TC mesh primitives and apply transactional transform, extrusion, and triangulation operators non-destructively.",
    ),
    "procedural.cook_graph": AdaptiveSceneCommand(
        key="procedural.cook_graph",
        label="Cook Procedural Graph",
        department="procedural",
        subjects=("scene", "procedural_graph", "terrain", "biome", "asset"),
        component_types=("object",),
        preferred_hosts=("tech_connector",),
        tc_native_status="implemented",
        notes="Incrementally evaluate only nodes whose parameters or upstream content changed.",
    ),
    "procedural.cook_task_graph": AdaptiveSceneCommand(
        key="procedural.cook_task_graph",
        label="Cook Procedural Task Graph",
        department="procedural",
        subjects=("procedural_graph", "pipeline", "world", "asset", "variation"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "houdini"),
        tc_native_status="implemented",
        notes="Cook fan-out, partitions, wedges, and dependency work items with parallel local execution and incremental cache reuse.",
    ),
    "procedural.attach_to_scene": AdaptiveSceneCommand(
        key="procedural.attach_to_scene",
        label="Attach Procedural Graph To Scene",
        department="procedural",
        subjects=("scene", "procedural_graph", "asset"),
        component_types=("object",),
        preferred_hosts=("tech_connector",),
        tc_native_status="implemented",
        notes="Store editable graph intent and deterministic cook receipts in the TC scene.",
    ),
    "procedural.build_transfer_manifest": AdaptiveSceneCommand(
        key="procedural.build_transfer_manifest",
        label="Build Procedural Transfer",
        department="procedural",
        subjects=("procedural_graph", "engine", "scene", "asset"),
        component_types=("object",),
        preferred_hosts=("tech_connector", "unreal", "houdini", "blender", "unity", "godot"),
        tc_native_status="implemented",
        notes="Translate supported nodes and retain a stable instance or baked fallback for every target.",
    ),
    "simulation.create_cloth": AdaptiveSceneCommand(
        key="simulation.create_cloth", label="Create Cloth Simulation", department="simulation",
        subjects=("mesh", "cloth", "skeletal_mesh"), component_types=("object", "face"),
        preferred_hosts=("tech_connector", "houdini", "maya", "blender", "unreal"), tc_native_status="implemented",
    ),
    "simulation.create_fluid": AdaptiveSceneCommand(
        key="simulation.create_fluid", label="Create Fluid Simulation", department="simulation",
        subjects=("mesh", "fluid", "particle"), component_types=("object",),
        preferred_hosts=("tech_connector", "houdini", "maya", "blender", "unreal"), tc_native_status="implemented",
    ),
    "simulation.fill_geometry_fluid": AdaptiveSceneCommand(
        key="simulation.fill_geometry_fluid", label="Fill Closed Geometry With Fluid", department="simulation",
        subjects=("mesh", "fluid", "particle"), component_types=("object",),
        preferred_hosts=("tech_connector", "houdini", "maya", "blender"), tc_native_status="implemented",
    ),
    "simulation.create_soft_body": AdaptiveSceneCommand(
        key="simulation.create_soft_body", label="Create Volume-Preserving Soft Body", department="simulation",
        subjects=("mesh", "softbody"), component_types=("object",),
        preferred_hosts=("tech_connector", "houdini", "blender"), tc_native_status="implemented",
    ),
    "simulation.create_reformable_dough": AdaptiveSceneCommand(
        key="simulation.create_reformable_dough", label="Create Tearable Reformable Dough", department="simulation",
        subjects=("mesh", "softbody", "plastic", "clay"), component_types=("object",),
        preferred_hosts=("tech_connector", "houdini", "blender"), tc_native_status="implemented",
        notes="Volumetric plastic particles tear under strain and form new cohesive bonds when pressed together.",
    ),
    "simulation.create_breakable_solid": AdaptiveSceneCommand(
        key="simulation.create_breakable_solid", label="Create Breakable Or Meltable Solid", department="simulation",
        subjects=("mesh", "rigid", "fracture", "metal", "glass"), component_types=("object",),
        preferred_hosts=("tech_connector", "houdini", "unreal", "blender"), tc_native_status="implemented",
    ),
    "simulation.create_volume": AdaptiveSceneCommand(
        key="simulation.create_volume", label="Create Fire / Plasma Volume", department="simulation",
        subjects=("volume", "fire", "smoke", "plasma"), component_types=("object",),
        preferred_hosts=("tech_connector", "houdini", "maya", "blender", "unreal"), tc_native_status="implemented",
    ),
    "simulation.create_effect": AdaptiveSceneCommand(
        key="simulation.create_effect", label="Create Modular Effect System", department="simulation",
        subjects=("effect", "particle", "weather", "atmosphere", "disaster"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal", "houdini", "unity", "blender"), tc_native_status="implemented",
    ),
    "simulation.set_effect_renderer": AdaptiveSceneCommand(
        key="simulation.set_effect_renderer", label="Set Effect Particle Renderer", department="simulation",
        subjects=("effect", "particle", "mesh", "ribbon", "beam"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal", "houdini", "unity"), tc_native_status="implemented",
    ),
    "simulation.set_effect_parameter": AdaptiveSceneCommand(
        key="simulation.set_effect_parameter", label="Edit Live Effect Parameter", department="simulation",
        subjects=("effect", "parameter", "emitter", "module"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal", "houdini", "unity"), tc_native_status="implemented",
    ),
    "simulation.add_effect_jiggle": AdaptiveSceneCommand(
        key="simulation.add_effect_jiggle", label="Add Effect Jiggle", department="simulation",
        subjects=("effect", "particle", "ribbon", "mesh", "jiggle", "secondary_motion"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal", "houdini", "unity"), tc_native_status="implemented",
        notes="Add paintable/per-particle spring secondary motion to an effect emitter.",
    ),
    "simulation.bake_effect": AdaptiveSceneCommand(
        key="simulation.bake_effect", label="Bake Effect Cache", department="simulation",
        subjects=("effect", "cache", "bake", "engine"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal", "houdini", "unity", "blender"), tc_native_status="implemented",
    ),
    "simulation.renderer_stats": AdaptiveSceneCommand(
        key="simulation.renderer_stats", label="Inspect Live FX Renderer", department="simulation",
        subjects=("effect", "renderer", "performance", "particles"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "simulation.configure_renderer_budget": AdaptiveSceneCommand(
        key="simulation.configure_renderer_budget", label="Configure Live FX Budget", department="simulation",
        subjects=("effect", "renderer", "performance", "quality", "budget"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "simulation.create_deformable_surface": AdaptiveSceneCommand(
        key="simulation.create_deformable_surface", label="Create Reactive Surface", department="simulation",
        subjects=("surface", "snow", "mud", "sand", "penetration"), component_types=("object", "face"),
        preferred_hosts=("tech_connector", "unreal", "houdini", "unity"), tc_native_status="implemented",
    ),
    "simulation.apply_footprint": AdaptiveSceneCommand(
        key="simulation.apply_footprint", label="Apply Surface Footprint", department="simulation",
        subjects=("surface", "footprint", "contact"), component_types=("object", "face"),
        preferred_hosts=("tech_connector", "unreal", "houdini"), tc_native_status="implemented",
    ),
    "simulation.apply_projectile": AdaptiveSceneCommand(
        key="simulation.apply_projectile", label="Apply Projectile Penetration", department="simulation",
        subjects=("surface", "projectile", "penetration", "impact"), component_types=("object", "face"),
        preferred_hosts=("tech_connector", "unreal", "houdini", "unity"), tc_native_status="implemented",
    ),
    "simulation.step": AdaptiveSceneCommand(
        key="simulation.step", label="Step Simulation", department="simulation",
        subjects=("simulation", "cloth", "fluid", "particle", "volume"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "simulation.add_geometry_emitter": AdaptiveSceneCommand(
        key="simulation.add_geometry_emitter", label="Use Geometry As Emitter", department="simulation",
        subjects=("mesh", "particle", "fluid", "volume"), component_types=("object", "face"),
        preferred_hosts=("tech_connector", "houdini", "maya", "blender", "unreal"), tc_native_status="implemented",
    ),
    "simulation.paint_emission_source": AdaptiveSceneCommand(
        key="simulation.paint_emission_source", label="Paint Mesh Emission Source", department="simulation",
        subjects=("mesh", "particle", "fluid", "volume", "emission", "paint"), component_types=("object", "face", "vertex"),
        preferred_hosts=("tech_connector", "houdini", "maya", "blender", "unreal", "unity"), tc_native_status="implemented",
        notes="Paints a transferable per-vertex density map; zero blocks emission and one emits at full density.",
    ),
    "simulation.add_geometry_collider": AdaptiveSceneCommand(
        key="simulation.add_geometry_collider", label="Use Geometry As Collider", department="simulation",
        subjects=("mesh", "collision"), component_types=("object", "face"),
        preferred_hosts=("tech_connector", "houdini", "maya", "blender", "unreal"), tc_native_status="implemented",
        notes="Preserves quad and n-gon source topology; temporary triangles are used only for narrow-phase contacts.",
    ),
    "simulation.create_physics_joint": AdaptiveSceneCommand(
        key="simulation.create_physics_joint", label="Create Physics Joint", department="simulation",
        subjects=("rigid_body", "joint", "constraint", "mechanism"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal", "unity", "maya", "blender"), tc_native_status="implemented",
        notes="Authors runtime body constraints independently from skeletal rig joints.",
    ),
    "simulation.edit_physics_joints": AdaptiveSceneCommand(
        key="simulation.edit_physics_joints", label="Edit Physics Joints", department="simulation",
        subjects=("rigid_body", "joint", "constraint", "motor", "limit"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "simulation.generate_ragdoll": AdaptiveSceneCommand(
        key="simulation.generate_ragdoll", label="Generate Ragdoll From Skeleton", department="simulation",
        subjects=("skeleton", "joint", "ragdoll", "physical_animation"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal", "unity", "maya", "blender"), tc_native_status="implemented",
    ),
    "simulation.build_physics_stress_scene": AdaptiveSceneCommand(
        key="simulation.build_physics_stress_scene", label="Build Physics Stress Scene", department="simulation",
        subjects=("physics", "constraint", "performance", "qualification"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
    ),
    "simulation.add_gravity_source": AdaptiveSceneCommand(
        key="simulation.add_gravity_source", label="Add Gravity Source", department="simulation",
        subjects=("field", "gravity", "simulation"), component_types=("object",),
        preferred_hosts=("tech_connector", "houdini", "maya", "blender", "unreal"), tc_native_status="implemented",
    ),
    "simulation.add_curve_flow": AdaptiveSceneCommand(
        key="simulation.add_curve_flow", label="Push Simulation Along Curve", department="simulation",
        subjects=("curve", "field", "fluid", "particle"), component_types=("object",),
        preferred_hosts=("tech_connector", "houdini", "maya", "blender"), tc_native_status="implemented",
    ),
    "simulation.add_temperature_source": AdaptiveSceneCommand(
        key="simulation.add_temperature_source", label="Add Heat Or Cold Field", department="simulation",
        subjects=("field", "temperature", "fire", "metal", "cloth"), component_types=("object",),
        preferred_hosts=("tech_connector", "houdini", "maya", "blender", "unreal"), tc_native_status="implemented",
    ),
    "simulation.build_transfer_manifest": AdaptiveSceneCommand(
        key="simulation.build_transfer_manifest", label="Build Simulation Transfer", department="simulation",
        subjects=("simulation", "cache", "engine"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal", "unity", "houdini", "maya", "blender"), tc_native_status="implemented",
    ),
    "simulation.compile_runtime_profile": AdaptiveSceneCommand(
        key="simulation.compile_runtime_profile", label="Compile Simulation Runtime Profile", department="simulation",
        subjects=("simulation", "effect", "cloth", "runtime", "performance"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Compile the authored graph to cinematic, photoreal, realtime, mobile, toony, stylized, or retro staged IR without replacing the source graph.",
    ),
    "simulation.inspect_execution_plan": AdaptiveSceneCommand(
        key="simulation.inspect_execution_plan", label="Inspect Simulation Execution Plan", department="simulation",
        subjects=("simulation", "effect", "cloth", "runtime", "performance", "diagnostics"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Report selected backend, stages, budgets, outputs, and explicit fallback diagnostics.",
    ),
    "deformation.add_jiggle": AdaptiveSceneCommand(
        key="deformation.add_jiggle", label="Add Jiggle Deformer", department="deformation",
        subjects=("mesh", "skin_cluster", "deformer", "jiggle", "secondary_motion"), component_types=("object", "vertex"),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal", "unity"), tc_native_status="implemented",
        notes="Insert paintable secondary motion after a skin cluster or any ordered deformer.",
    ),
    "deformation.add_muscle": AdaptiveSceneCommand(
        key="deformation.add_muscle", label="Add Muscle Tissue", department="deformation",
        subjects=("mesh", "skin_cluster", "deformer", "muscle", "flesh", "pose_space"),
        component_types=("object", "vertex"),
        preferred_hosts=("tech_connector", "maya", "blender", "houdini", "unreal", "unity"),
        tc_native_status="implemented",
        notes="Add paintable activation, fiber contraction, volume bulge, inertia, and pose-space tissue while preserving canonical skin weights.",
    ),
    "deformation.add_blend_shape": AdaptiveSceneCommand(
        key="deformation.add_blend_shape", label="Add Blend Shape Deformer", department="deformation",
        subjects=("mesh", "deformer", "blend_shape", "morph_target", "corrective"),
        component_types=("object", "vertex"),
        preferred_hosts=("tech_connector", "maya", "blender", "houdini", "unreal", "unity"),
        tc_native_status="implemented",
        notes="Create sparse targets with masks, in-betweens, corrective drivers, animation keys, and portable topology validation.",
    ),
    "deformation.set_blend_shape_weights": AdaptiveSceneCommand(
        key="deformation.set_blend_shape_weights", label="Set Blend Shape Weights", department="deformation",
        subjects=("deformer", "blend_shape", "morph_target", "animation", "corrective"),
        component_types=("object",), preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Update blend-shape channels, corrective driver values, or animation frame without rebuilding targets.",
    ),
    "deformation.set_muscle_activation": AdaptiveSceneCommand(
        key="deformation.set_muscle_activation", label="Set Muscle Activation", department="deformation",
        subjects=("deformer", "muscle", "activation", "pose_space", "animation"),
        component_types=("object",), preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Drive muscle activation and pose-reader values live without rebuilding the deformer.",
    ),
    "simulation.create_data_channel": AdaptiveSceneCommand(
        key="simulation.create_data_channel", label="Create FX Data Channel", department="simulation",
        subjects=("effect", "event", "gameplay", "data_channel", "performance"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal"), tc_native_status="implemented",
        notes="Creates a bounded typed event stream shared by effects, simulation, and gameplay.",
    ),
    "simulation.publish_data_channel": AdaptiveSceneCommand(
        key="simulation.publish_data_channel", label="Publish FX Data", department="simulation",
        subjects=("effect", "event", "gameplay", "data_channel"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal"), tc_native_status="implemented",
        notes="Queues a validated payload on an exact deterministic simulation tick.",
    ),
    "simulation.inspect_fx_profiler": AdaptiveSceneCommand(
        key="simulation.inspect_fx_profiler", label="Inspect FX Profiler", department="simulation",
        subjects=("effect", "gpu", "performance", "profiler", "data_channel"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Reports actual execution residency, budget status, timing history, and channel pressure.",
    ),
    "deformation.add_secondary_motion_preset": AdaptiveSceneCommand(
        key="deformation.add_secondary_motion_preset", label="Add Secondary Motion Preset", department="deformation",
        subjects=("mesh", "skin_cluster", "jiggle", "flesh", "muscle", "secondary_motion"),
        component_types=("object", "vertex"),
        preferred_hosts=("tech_connector", "maya", "blender", "houdini", "unreal", "unity"),
        tc_native_status="implemented",
        notes="Attach an editable collision-aware preset stack while preserving canonical skin weights.",
    ),
    "deformation.paint_influence": AdaptiveSceneCommand(
        key="deformation.paint_influence", label="Paint Deformation Influence", department="deformation",
        subjects=("mesh", "skin_cluster", "deformer", "simulation", "weight_map"), component_types=("object", "vertex"),
        preferred_hosts=("tech_connector", "maya", "blender", "unreal", "unity"), tc_native_status="implemented",
        notes="Paint a universal output map where zero preserves the upstream mesh and one follows skin, deformer, jiggle, or simulation output.",
    ),
    "engine.generate_mesh_lods": AdaptiveSceneCommand(
        key="engine.generate_mesh_lods", label="Generate Mesh LODs", department="engine",
        subjects=("mesh", "static_mesh", "skeletal_mesh", "asset"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal", "unity", "blender", "maya"), tc_native_status="implemented",
        notes="Generate GLB LOD assets in an isolated Blender backend with per-object triangle, UV, material, vertex-group, diagnostic, and source-fingerprint receipts.",
    ),
    "engine.audit_capability_maturity": AdaptiveSceneCommand(
        key="engine.audit_capability_maturity", label="Audit Capability Maturity", department="engine",
        subjects=("engine", "dcc", "capability", "readiness", "qualification"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Report evidence-backed maturity and the exact gates preventing each capability from advancing.",
    ),
    "engine.audit_dcc_hosts": AdaptiveSceneCommand(
        key="engine.audit_dcc_hosts", label="Audit DCC Host Profiles", department="engine",
        subjects=("engine", "dcc", "bridge", "host", "capability", "coverage"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Report executable operations, host-profile scope, and honest live-qualification limits across the ten external DCC/FX packages.",
    ),
    "engine.qualify_dcc_host": AdaptiveSceneCommand(
        key="engine.qualify_dcc_host", label="Qualify Live DCC Host", department="engine",
        subjects=("engine", "dcc", "bridge", "host", "session", "recovery"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Run read-only endpoint, identity, preferred-session, and multi-session checks against one role-specific live DCC profile and retain the receipt.",
    ),
    "engine.qualify_dcc_source_parity": AdaptiveSceneCommand(
        key="engine.qualify_dcc_source_parity", label="Qualify DCC Source Parity", department="engine",
        subjects=("engine", "dcc", "bridge", "session", "scene", "material", "parity"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Capture a bounded exact-session snapshot, verify role-appropriate source evidence and observer-state stability, and retain the receipt.",
    ),
    "engine.audit_dcc_workflows": AdaptiveSceneCommand(
        key="engine.audit_dcc_workflows", label="Audit DCC Production Workflows", department="engine",
        subjects=("engine", "dcc", "workflow", "parity", "restoration", "production"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Inspect the role-specific, portable, restorable, readback-gated production journey defined for every external host.",
    ),
    "engine.run_dcc_workflow": AdaptiveSceneCommand(
        key="engine.run_dcc_workflow", label="Run DCC Production Workflow", department="engine",
        subjects=("engine", "dcc", "workflow", "session", "artifact", "readback"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Execute an explicitly confirmed production journey on one pinned DCC session and return ordered operation, artifact, and readback receipts.",
    ),
    "engine.build_runtime_geometry_plan": AdaptiveSceneCommand(
        key="engine.build_runtime_geometry_plan", label="Plan Runtime Geometry", department="engine",
        subjects=("mesh", "material", "textures", "runtime", "performance"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Build a benchmark-gated hybrid plan for mesh LODs, clustered mesh pages, and optional PBR surfel pages.",
    ),
    "engine.configure_runtime": AdaptiveSceneCommand(
        key="engine.configure_runtime", label="Configure Game Runtime", department="engine",
        subjects=("simulation", "effect", "cloth", "game", "runtime", "platform", "performance"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Choose a target and creative goal through UI, API, or chat; TC resolves profiles, capabilities, budgets, and visible fallbacks.",
    ),
    "engine.live_update_scene": AdaptiveSceneCommand(
        key="engine.live_update_scene", label="Update Running Game", department="engine",
        subjects=("scene", "game", "runtime", "playtest", "hot_reload"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Compile dependency-closed changed scene chunks and update connected game sessions without packaging when compatible.",
    ),
    "engine.plan_playtest": AdaptiveSceneCommand(
        key="engine.plan_playtest", label="Plan Fast Playtest", department="engine",
        subjects=("game", "playtest", "package", "build", "runtime"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Select the fastest truthful iteration route: live update, reusable session, or incremental package.",
    ),
    "engine.compile_point_runtime_proxy": AdaptiveSceneCommand(
        key="engine.compile_point_runtime_proxy", label="Compile Point Runtime Proxy", department="engine",
        subjects=("mesh", "material", "textures", "point_cloud", "surfel"), component_types=("object",),
        preferred_hosts=("tech_connector",), tc_native_status="implemented",
        notes="Compile atomic oriented-PBR-surfel packages with Morton-ordered spatial pages, exact source-face IDs, and explicit mesh fallback policy.",
    ),
    "engine.compile_virtualized_hard_surface": AdaptiveSceneCommand(
        key="engine.compile_virtualized_hard_surface", label="Compile Virtualized Hard Surface", department="engine",
        subjects=("mesh", "static_mesh", "hard_surface", "material", "runtime"), component_types=("object",),
        preferred_hosts=("tech_connector", "unreal"), tc_native_status="implemented",
        notes="Compile atomic bounded meshlets, local index buffers, normal cones, bounds, stream pages, hierarchy, exact source IDs, and mesh fallback policy.",
    ),
}


def target_from_scene_proxy(
    proxy: dict[str, Any] | Any,
    *,
    component_type: str = "object",
    components: list[str] | tuple[str, ...] | None = None,
) -> SceneCommandTarget:
    data = dict(proxy or {}) if isinstance(proxy, dict) else {}
    provider = str(data.get("provider_id") or data.get("provider") or "tech_connector")
    native_id = str(data.get("native_id") or data.get("name") or "")
    return SceneCommandTarget(
        provider=provider,
        native_id=native_id,
        source_key=str(data.get("source_key") or ""),
        object_type=str(data.get("type") or data.get("object_type") or "mesh"),
        component_type=str(component_type or "object"),
        components=tuple(str(value) for value in (components or ())),
        metadata={
            "name": str(data.get("name") or native_id),
            "representation": str(data.get("representation") or ""),
            "local_transform": dict(data.get("local_transform") or {}),
        },
    )


def _maya_component_expr(target: SceneCommandTarget) -> str:
    if target.components:
        return ", ".join(repr(item) for item in target.components)
    if target.component_type in {"edge", "edge_loop"} and target.native_id:
        return repr(f"{target.native_id}.e[*]")
    if target.component_type == "face" and target.native_id:
        return repr(f"{target.native_id}.f[*]")
    return repr(target.native_id)


def _maya_route(command: AdaptiveSceneCommand, target: SceneCommandTarget, payload: dict[str, Any]) -> SceneCommandRoute:
    if command.key == "modeling.split_edge_loop":
        divisions = int(payload.get("divisions", 1) or 1)
        smoothing = float(payload.get("smoothing_angle", 30.0) or 30.0)
        selection_expr = _maya_component_expr(target)
        script = (
            "import maya.cmds as cmds\n"
            f"target = {target.native_id!r}\n"
            "if not cmds.objExists(target):\n"
            "    raise RuntimeError('Object does not exist: ' + target)\n"
            f"cmds.select([{selection_expr}], replace=True)\n"
            "try:\n"
            f"    result = cmds.polySplitRing(ch=False, splitType=1, divisions={divisions}, smoothingAngle={smoothing})\n"
            "except Exception:\n"
            f"    result = cmds.polyCut(ch=False, pc=(0, 0, 0), ro=(0, 0, 0))\n"
            "cmds.select(target, replace=True)\n"
            "print({'ok': True, 'command': 'modeling.split_edge_loop', 'result': result})\n"
        )
        return SceneCommandRoute(
            command=command.to_dict(),
            target=target.to_dict(),
            host="maya",
            execution_mode="bridge_script",
            status="routable",
            callable="MayaBridge.execute",
            script=script,
            required_payload={"divisions": divisions, "smoothing_angle": smoothing},
            validation=["Maya object exists", "host command returns without error", "scene snapshot updates topology"],
            fallback="Convert TC command to baked mesh edit if Maya topology command fails.",
        )
    if command.key.startswith("skinning."):
        mesh = target.native_id
        components = list(target.components)
        influence = str(payload.get("influence") or payload.get("joint") or "")
        influences = tuple(str(value) for value in payload.get("influences", ()) if str(value))
        max_influences = int(payload.get("max_influences", payload.get("maximum_influences", 4)) or 4)
        weight = float(payload.get("weight", payload.get("value", 1.0)) or 0.0)
        cluster = str(payload.get("cluster") or "")
        mode = str(payload.get("mode") or "replace")
        bind_method = str(payload.get("bind_method") or payload.get("method") or "heat").strip().lower().replace("-", "_").replace(" ", "_")
        maya_bind_methods = {
            "distance": 0,
            "closest_distance": 0,
            "heat": 2,
            "heat_map": 2,
            "heatmap": 2,
            "geodesic": 3,
            "geodesic_voxel": 3,
            "voxel": 3,
            "current": 4,
            "auto": 2,
        }
        maya_bind_method = int(payload.get("maya_bind_method", maya_bind_methods.get(bind_method, 2)) or 2)
        component_expr = components or ([f"{mesh}.vtx[*]"] if mesh else [])
        if command.key == "skinning.bind_skin":
            script = (
                "import maya.cmds as cmds\n"
                f"mesh = {mesh!r}\n"
                f"influences = {list(influences)!r}\n"
                "if not mesh or not cmds.objExists(mesh):\n"
                "    raise RuntimeError('Mesh does not exist: ' + str(mesh))\n"
                "missing = [name for name in influences if not cmds.objExists(name)]\n"
                "if missing:\n"
                "    raise RuntimeError('Missing skin influences: ' + ', '.join(missing))\n"
                f"cluster = cmds.skinCluster(influences, mesh, toSelectedBones=False, maximumInfluences={max_influences}, normalizeWeights=1, bindMethod={maya_bind_method})\n"
                "print({'ok': True, 'command': 'skinning.bind_skin', 'cluster': cluster[0] if cluster else ''})\n"
            )
            payload_out = {"influences": list(influences), "max_influences": max_influences, "bind_method": bind_method, "maya_bind_method": maya_bind_method}
        elif command.key == "skinning.auto_skin":
            script = (
                "import maya.cmds as cmds\n"
                f"mesh = {mesh!r}\n"
                f"influences = {list(influences)!r}\n"
                f"falloff = {float(payload.get('falloff', 4.0) or 4.0)!r}\n"
                "try:\n"
                "    from maya_tools.Rigging.auto_skinner import auto_skin\n"
                "    result = auto_skin(mesh, influence_joints=influences, falloff=falloff)\n"
                "except Exception:\n"
                "    if not mesh or not cmds.objExists(mesh):\n"
                "        raise RuntimeError('Mesh does not exist: ' + str(mesh))\n"
                "    missing = [name for name in influences if not cmds.objExists(name)]\n"
                "    if missing:\n"
                "        raise RuntimeError('Missing skin influences: ' + ', '.join(missing))\n"
                f"    result = cmds.skinCluster(influences, mesh, toSelectedBones=False, maximumInfluences={max_influences}, normalizeWeights=1, bindMethod={maya_bind_method})\n"
                "print({'ok': True, 'command': 'skinning.auto_skin', 'result': result})\n"
            )
            payload_out = {"influences": list(influences), "max_influences": max_influences, "bind_method": bind_method, "falloff": float(payload.get("falloff", 4.0) or 4.0)}
        elif command.key == "skinning.add_influence":
            script = (
                "import maya.cmds as cmds\n"
                f"mesh = {mesh!r}\n"
                f"influence = {influence!r}\n"
                f"cluster = {cluster!r}\n"
                "if not cluster:\n"
                "    history = cmds.listHistory(mesh) or []\n"
                "    clusters = cmds.ls(history, type='skinCluster') or []\n"
                "    cluster = clusters[0] if clusters else ''\n"
                "if not cluster:\n"
                "    raise RuntimeError('No skinCluster found for ' + str(mesh))\n"
                f"cmds.skinCluster(cluster, edit=True, addInfluence=influence, weight={weight})\n"
                "print({'ok': True, 'command': 'skinning.add_influence', 'cluster': cluster, 'influence': influence})\n"
            )
            payload_out = {"influence": influence, "weight": weight, "cluster": cluster}
        elif command.key == "skinning.remove_influence":
            script = (
                "import maya.cmds as cmds\n"
                f"mesh = {mesh!r}\n"
                f"influence = {influence!r}\n"
                f"cluster = {cluster!r}\n"
                "if not cluster:\n"
                "    history = cmds.listHistory(mesh) or []\n"
                "    clusters = cmds.ls(history, type='skinCluster') or []\n"
                "    cluster = clusters[0] if clusters else ''\n"
                "if not cluster:\n"
                "    raise RuntimeError('No skinCluster found for ' + str(mesh))\n"
                "cmds.skinCluster(cluster, edit=True, removeInfluence=influence)\n"
                "print({'ok': True, 'command': 'skinning.remove_influence', 'cluster': cluster, 'influence': influence})\n"
            )
            payload_out = {"influence": influence, "cluster": cluster}
        elif command.key in {"skinning.paint_weights", "skinning.normalize_weights", "skinning.prune_weights", "skinning.smooth_weights"}:
            script = (
                "import maya.cmds as cmds\n"
                f"mesh = {mesh!r}\n"
                f"cluster = {cluster!r}\n"
                f"components = {component_expr!r}\n"
                f"influence = {influence!r}\n"
                "if not cluster:\n"
                "    history = cmds.listHistory(mesh) or []\n"
                "    clusters = cmds.ls(history, type='skinCluster') or []\n"
                "    cluster = clusters[0] if clusters else ''\n"
                "if not cluster:\n"
                "    raise RuntimeError('No skinCluster found for ' + str(mesh))\n"
                "if influence:\n"
                f"    cmds.skinPercent(cluster, components, transformValue=[(influence, {weight})], normalize=True)\n"
                "else:\n"
                "    cmds.skinPercent(cluster, components, normalize=True)\n"
                "print({'ok': True, 'command': 'skinning.paint_weights', 'cluster': cluster, 'components': components})\n"
            )
            payload_out = {"components": component_expr, "influence": influence, "weight": weight, "mode": mode, "cluster": cluster}
        elif command.key in {"skinning.copy_weights", "skinning.transfer_weights"}:
            source_mesh = str(payload.get("source_mesh") or payload.get("source") or "")
            target_mesh = str(payload.get("target_mesh") or target.native_id or "")
            surface_association = str(payload.get("surface_association") or payload.get("strategy") or "closestPoint")
            influence_association = str(payload.get("influence_association") or "closestJoint")
            script = (
                "import maya.cmds as cmds\n"
                f"source_mesh = {source_mesh!r}\n"
                f"target_mesh = {target_mesh!r}\n"
                f"surface_association = {surface_association!r}\n"
                f"influence_association = {influence_association!r}\n"
                "def _skin_cluster_for(mesh):\n"
                "    history = cmds.listHistory(mesh) or []\n"
                "    clusters = cmds.ls(history, type='skinCluster') or []\n"
                "    if not clusters:\n"
                "        raise RuntimeError('No skinCluster found for ' + str(mesh))\n"
                "    return clusters[0]\n"
                "source_cluster = _skin_cluster_for(source_mesh)\n"
                "target_cluster = _skin_cluster_for(target_mesh)\n"
                "cmds.copySkinWeights(sourceSkin=source_cluster, destinationSkin=target_cluster, noMirror=True, surfaceAssociation=surface_association, influenceAssociation=[influence_association])\n"
                "print({'ok': True, 'command': 'skinning.transfer_weights', 'source': source_cluster, 'target': target_cluster})\n"
            )
            payload_out = {"source_mesh": source_mesh, "target_mesh": target_mesh, "surface_association": surface_association, "influence_association": influence_association}
        elif command.key in {"skinning.export_weights", "skinning.import_weights"}:
            path = str(payload.get("path") or payload.get("file_path") or "")
            deformer = str(payload.get("deformer") or cluster or "")
            method = "export" if command.key.endswith("export_weights") else "import"
            script = (
                "import os\n"
                "import maya.cmds as cmds\n"
                f"mesh = {mesh!r}\n"
                f"path = {path!r}\n"
                f"deformer = {deformer!r}\n"
                "if not path:\n"
                "    raise RuntimeError('A weight file path is required.')\n"
                "folder, filename = os.path.split(path)\n"
                "if not deformer:\n"
                "    history = cmds.listHistory(mesh) or []\n"
                "    clusters = cmds.ls(history, type='skinCluster') or []\n"
                "    deformer = clusters[0] if clusters else ''\n"
                "if not deformer:\n"
                "    raise RuntimeError('No skinCluster found for ' + str(mesh))\n"
                f"cmds.deformerWeights(filename, path=folder or '.', deformer=deformer, {method}=True)\n"
                f"print({{'ok': True, 'command': {command.key!r}, 'path': path, 'deformer': deformer}})\n"
            )
            payload_out = {"path": path, "deformer": deformer}
        else:
            return SceneCommandRoute(command.to_dict(), target.to_dict(), "maya", "bridge_script", "planned")
        return SceneCommandRoute(
            command=command.to_dict(),
            target=target.to_dict(),
            host="maya",
            execution_mode="bridge_script",
            status="routable",
            callable="MayaBridge.execute",
            script=script,
            required_payload=payload_out,
            validation=["Maya mesh exists", "skinCluster operation completes", "TC weight readback/parity metrics pass"],
            fallback="Convert TC skin cluster to engine-safe skeletal mesh weights or tcskin package.",
        )
    return SceneCommandRoute(command.to_dict(), target.to_dict(), "maya", "bridge_script", "planned")


def _blender_route(command: AdaptiveSceneCommand, target: SceneCommandTarget, payload: dict[str, Any]) -> SceneCommandRoute:
    if command.key == "modeling.split_edge_loop":
        cuts = int(payload.get("divisions", 1) or 1)
        script = (
            "import bpy\n"
            f"name = {target.native_id!r}\n"
            "obj = bpy.data.objects.get(name)\n"
            "if obj is None:\n"
            "    raise RuntimeError('Object does not exist: ' + name)\n"
            "bpy.ops.object.mode_set(mode='OBJECT')\n"
            "bpy.ops.object.select_all(action='DESELECT')\n"
            "obj.select_set(True)\n"
            "bpy.context.view_layer.objects.active = obj\n"
            "bpy.ops.object.mode_set(mode='EDIT')\n"
            f"bpy.ops.mesh.loopcut_slide(number_cuts={cuts})\n"
            "bpy.ops.object.mode_set(mode='OBJECT')\n"
            "print({'ok': True, 'command': 'modeling.split_edge_loop'})\n"
        )
        return SceneCommandRoute(
            command=command.to_dict(),
            target=target.to_dict(),
            host="blender",
            execution_mode="bridge_script",
            status="routable",
            callable="BlenderBridge.execute",
            script=script,
            required_payload={"divisions": cuts},
            validation=["Blender object exists", "loopcut operator completes", "scene snapshot updates topology"],
            fallback="Convert TC command to baked mesh edit if Blender loopcut cannot run non-interactively.",
        )
    return SceneCommandRoute(command.to_dict(), target.to_dict(), "blender", "bridge_script", "planned")


def _tc_route(command: AdaptiveSceneCommand, target: SceneCommandTarget, payload: dict[str, Any]) -> SceneCommandRoute:
    status = "routable" if command.tc_native_status == "implemented" else "planned"
    return SceneCommandRoute(
        command=command.to_dict(),
        target=target.to_dict(),
        host="tech_connector",
        execution_mode="tc_native",
        status=status,
        callable=f"tech_connector.viewer_cmds.{command.key.split('.', 1)[-1]}",
        required_payload=dict(payload or {}),
        validation=["TC local scene state updates", "undo chunk is recorded", "engine import/conversion path remains valid"],
        fallback="Route to selected bridge target or convert to engine-safe baked asset.",
        notes=["Native implementation status: " + command.tc_native_status],
    )


def resolve_adaptive_scene_command(
    command_key: str,
    target: SceneCommandTarget | dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> SceneCommandRoute:
    command = ADAPTIVE_SCENE_COMMANDS.get(str(command_key))
    if command is None:
        raise KeyError(f"Unknown adaptive scene command: {command_key}")
    target_obj = target if isinstance(target, SceneCommandTarget) else SceneCommandTarget(**dict(target or {}))
    payload = dict(payload or {})
    if command.key in {
        "scene.compose_usd",
        "scene.inspect_usd_composition",
        "scene.set_usd_variant",
        "scene.set_usd_payload",
        "scene.set_usd_override",
    }:
        return SceneCommandRoute(
            command=command.to_dict(),
            target=target_obj.to_dict(),
            host="tech_connector",
            execution_mode="tc_openusd_composition",
            status="routable",
            callable="tech_connector.game_engine.scene.usd_composition_command_service.apply_usd_composition_command",
            required_payload=payload,
            validation=[
                "composition contract validates",
                "isolated OpenUSD worker completes or cancels cleanly",
                "source fingerprints and result manifest persist in tcscene",
            ],
            fallback="Preserve the authored USD composition contract and retry on an available OpenUSD backend.",
            notes=["Composition commands are scene-wide and execute in Tech Connector regardless of the selected DCC object."],
        )
    host = target_obj.provider_base
    if command.key in {"scene.convert_to_tc", "scene.convert_selection_to_tc"}:
        return SceneCommandRoute(
            command=command.to_dict(),
            target=target_obj.to_dict(),
            host="tech_connector",
            execution_mode="tc_migration_pipeline",
            status="routable",
            callable="tech_connector.game_engine.scene.tc_scene_conversion_service.convert_to_tc",
            required_payload={
                **payload,
                "source_provider": target_obj.provider,
                "source_native_id": target_obj.native_id,
                "scope": "selection" if command.key.endswith("selection_to_tc") else "scene",
            },
            validation=[
                "source snapshot captured",
                "TC-native scene graph created",
                "meshes/materials/rigs/animation/shots converted or explicitly reported unsupported",
                "engine import/conversion paths preserved",
                "round-trip/source-link receipts recorded",
            ],
            fallback="Keep source-linked bridge representation and convert supported departments incrementally.",
            notes=[
                "Migration command should prefer TC-native data, but preserve source IDs for comparison, re-sync, and rollback.",
            ],
        )
    if host in {"tech_connector", "tc", "local"}:
        return _tc_route(command, target_obj, payload)
    if host == "maya":
        return _maya_route(command, target_obj, payload)
    if host == "blender":
        return _blender_route(command, target_obj, payload)
    if host == "unreal":
        return SceneCommandRoute(
            command=command.to_dict(),
            target=target_obj.to_dict(),
            host="unreal",
            execution_mode="engine_plugin_or_conversion",
            status="convertible",
            callable="Tech Connector Unreal plugin importer",
            required_payload=payload,
            validation=["convert/import through Tech Connector Unreal plugin", "asset registry readback passes"],
            fallback="Bake command result to engine-supported mesh/animation/cache asset.",
        )
    return SceneCommandRoute(
        command=command.to_dict(),
        target=target_obj.to_dict(),
        host=host,
        execution_mode="bridge_or_conversion",
        status="planned",
        required_payload=payload,
        validation=["resolve host bridge capability", "validate import/readback after command"],
        fallback="Convert TC-native result to an engine-safe asset.",
    )


def list_adaptive_scene_commands() -> list[dict[str, Any]]:
    return [command.to_dict() for command in ADAPTIVE_SCENE_COMMANDS.values()]

