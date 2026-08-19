from __future__ import annotations

"""DCC transferability analysis built on the existing operation contracts.

The operation/capability registries remain authoritative for what is callable.
This module answers a product-level question: if Tech Connector owns a native
feature, which host packages can receive, validate, round-trip, or bake it?
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from tech_connector.game_engine.integration.operation_contract_service import (
    HOSTS,
    OperationContract,
    operation_contracts,
)
from tech_connector.game_engine.scene.source_conversion_adapter_service import source_conversion_adapters
from tech_connector.game_engine.runtime.tc_runtime_authoring_service import runtime_authoring_contract


@dataclass(frozen=True)
class NativeDccFeature:
    key: str
    label: str
    department: str
    subjects: tuple[str, ...]
    preferred_formats: tuple[str, ...] = ()
    required_roles: tuple[str, ...] = ("export", "import")
    bake_fallbacks: tuple[str, ...] = ()
    benchmark_tools: tuple[str, ...] = ()
    top_line_requirements: tuple[str, ...] = ()
    engine_priority: str = "required"
    engine_paths: tuple[str, ...] = ()
    conversion_paths: tuple[str, ...] = ()
    custom_importer_targets: tuple[str, ...] = ()
    parity_policy: str = "native_plus_baked_engine_transfer"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HostTransferSupport:
    host: str
    supported: bool
    confidence: float
    roles: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    formats: list[str] = field(default_factory=list)
    bake_fallbacks: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeatureTransferReport:
    feature: dict[str, Any]
    hosts: dict[str, HostTransferSupport]
    engine_readiness: dict[str, Any]
    strongest_hosts: list[str]
    transfer_formats: list[str]
    critical_gaps: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "hosts": {host: support.to_dict() for host, support in self.hosts.items()},
            "engine_readiness": dict(self.engine_readiness),
            "strongest_hosts": list(self.strongest_hosts),
            "transfer_formats": list(self.transfer_formats),
            "critical_gaps": list(self.critical_gaps),
        }


NATIVE_DCC_FEATURES: dict[str, NativeDccFeature] = {
    "dcc_to_tc_migration": NativeDccFeature(
        key="dcc_to_tc_migration",
        label="Convert Other DCC To TC",
        department="pipeline",
        subjects=("asset", "animation", "static_mesh", "skeletal_mesh", "material", "textures"),
        preferred_formats=("usd", "fbx", "abc", "textures"),
        required_roles=("import", "process", "validate"),
        bake_fallbacks=("tcscene", "tcpackage", "source_link_manifest", "conversion_report"),
        benchmark_tools=("USD importers", "Blender import pipeline", "Maya references", "Unreal Interchange"),
        top_line_requirements=(
            "capture source scene via bridge/import",
            "convert supported meshes, rigs, materials, shots, animation, and constraints into TC-native data",
            "preserve source IDs, validation receipts, and engine import/conversion paths",
        ),
        engine_paths=("Tech Connector Unreal plugin: TCPackage importer", "Unity TCPackage importer", "USD/FBX fallback"),
        conversion_paths=("Maya/Blender/Mobu/Houdini/Unreal snapshot -> tcscene", "FBX/USD/Alembic -> TC-native package"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCPackage importer", "Unity TCPackage importer"),
        parity_policy="convert to TC-native where supported; keep source-linked bridge data for unsupported departments",
        notes="The migration path lets users adopt TC as a standalone DCC without losing source-DCC compatibility.",
    ),
    "scene_graph": NativeDccFeature(
        key="scene_graph",
        label="Scene Graph / Outliner",
        department="layout",
        subjects=("asset", "static_mesh", "skeletal_mesh"),
        preferred_formats=("usd", "fbx"),
        required_roles=("export", "import", "validate"),
        bake_fallbacks=("usd_path", "fbx_path", "transfer_path"),
        benchmark_tools=("Maya Outliner", "Blender Outliner", "Houdini Solaris", "Unreal World Outliner"),
        top_line_requirements=(
            "live federated source hierarchy",
            "tags, saved views, filters, references, and visibility layers",
            "source-aware property panels per DCC object",
        ),
        engine_paths=("Unreal World Outliner/Level Actors", "Unity Scene/GameObjects", "USD stage", "FBX hierarchy"),
        conversion_paths=("tcscene -> USD stage", "tcscene -> Unreal Level Actors", "tcscene -> Unity Scene"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCScene importer", "Unity TCScene importer"),
        parity_policy="preserve hierarchy natively; export engine-safe actors, folders, tags, and visibility",
        notes="Native hierarchy, visibility, tags, references, and source provenance.",
    ),
    "mesh_editing": NativeDccFeature(
        key="mesh_editing",
        label="Mesh Editing",
        department="modeling",
        subjects=("static_mesh", "skeletal_mesh", "asset"),
        preferred_formats=("usd", "fbx", "abc"),
        required_roles=("export", "import", "process", "validate"),
        bake_fallbacks=("fbx_path", "usd_path", "transfer_path"),
        benchmark_tools=("Blender Modeling", "Maya Modeling Toolkit", "Houdini SOPs", "ZBrush ZModeler"),
        top_line_requirements=(
            "component selection with stable IDs",
            "non-destructive edit stack",
            "bevel, extrude, weld, bridge, retopo, UV, LOD, and collision transfer",
        ),
        engine_paths=("Unreal StaticMesh/SkeletalMesh", "Unity Mesh", "FBX", "USD", "glTF", "collision/LOD assets"),
        conversion_paths=("tcmesh -> FBX", "tcmesh -> USD mesh", "tcmesh -> glTF", "tcmesh -> Unreal StaticMesh/SkeletalMesh"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCMesh importer", "Unity TCMesh importer"),
        parity_policy="edit natively; bake topology, UVs, normals, LODs, and collisions for engines",
        notes="Non-destructive edit stack should bake to mesh deltas or exported geometry.",
    ),
    "runtime_geometry_scalability": NativeDccFeature(
        key="runtime_geometry_scalability",
        label="LOD / Virtualized Mesh / Point Runtime",
        department="engine",
        subjects=("static_mesh", "skeletal_mesh", "material", "textures", "asset"),
        preferred_formats=("tcpackage", "usd", "gltf", "fbx", "textures"),
        required_roles=("process", "compile", "stream", "validate"),
        bake_fallbacks=("mesh_lod_chain", "clustered_mesh", "low_poly_collision", "pbr_texture_atlas"),
        benchmark_tools=("Unreal Nanite/LOD", "Unity LODGroup/Entities Graphics", "meshlet renderers", "surfel and point renderers"),
        top_line_requirements=(
            "authored and generated mesh LOD chains with stable material, UV, skin, collision, and source-ID mapping",
            "GPU-driven clustered mesh pages with hierarchical screen-space error, occlusion, and streaming",
            "optional oriented-point/surfel pages carrying PBR material data and atlas references",
            "per-view runtime selection based on measured GPU time, memory, bandwidth, overdraw, temporal stability, and quality",
            "mesh/SDF fallbacks for collision, navigation, ray queries, shadows, translucency, and deforming assets",
        ),
        engine_paths=(
            "TC Engine clustered mesh + surfel runtime",
            "Unreal StaticMesh/SkeletalMesh LOD or Nanite-ready mesh",
            "Unity Mesh LODGroup/Entities Graphics",
            "USD/glTF/FBX LOD plus baked PBR textures",
        ),
        conversion_paths=(
            "tcmesh -> validated mesh LOD chain",
            "tcmesh -> streamable meshlet hierarchy",
            "tcmesh + tcmaterial -> PBR surfel pages + source mapping",
            "surfel runtime -> mesh fallback package for external engines",
        ),
        custom_importer_targets=("Tech Connector runtime geometry compiler", "Tech Connector Unreal plugin runtime proxy"),
        parity_policy="hybrid and benchmark-gated: point data is optional and must never replace the authoritative mesh unless it wins quality/performance validation",
        notes="Point rendering can reduce geometry cost in some views but may lose to clustered meshes due to overdraw, sorting, holes, materials, or deformation.",
    ),
    "sculpting": NativeDccFeature(
        key="sculpting",
        label="Sculpting / High Density Detail",
        department="modeling",
        subjects=("static_mesh", "asset"),
        preferred_formats=("usd", "fbx", "abc", "textures"),
        required_roles=("process", "export", "validate"),
        bake_fallbacks=("normal_map", "displacement_map", "baked_mesh", "decimated_mesh"),
        benchmark_tools=("ZBrush", "Blender Sculpt", "Mudbox"),
        top_line_requirements=(
            "brush feel at high density",
            "subtools/layers",
            "retopo and displacement/normal bake handoff",
        ),
        engine_paths=("normal/displacement maps", "decimated mesh", "Nanite-ready mesh", "FBX/USD mesh"),
        conversion_paths=("tcsculpt -> decimated render mesh", "tcsculpt -> displacement/normal maps", "tcsculpt -> Nanite-ready mesh"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCSculpt/Detail importer",),
        parity_policy="high-density sculpt locally; engine path is decimated/render mesh plus baked maps",
        notes="TC should initially transfer sculpt intent through layers, masks, maps, and baked meshes.",
    ),
    "materials_textures": NativeDccFeature(
        key="materials_textures",
        label="Materials / Texture Layers",
        department="lookdev",
        subjects=("material", "textures", "asset"),
        preferred_formats=("textures", "usd", "fbx"),
        required_roles=("export", "import", "validate"),
        bake_fallbacks=("texture_paths", "material_slots", "flattened_maps"),
        benchmark_tools=("Substance 3D Painter", "Maya LookdevX", "Blender Shader Nodes", "Unreal Material Editor"),
        top_line_requirements=(
            "PBR/OpenPBR-aware material model",
            "layer stack, masks, smart materials, UDIMs, and rebake workflows",
            "shader graph export or baked texture fallback",
        ),
        engine_paths=("Unreal materials + texture sets", "Unity materials + texture sets", "USD Preview Surface", "MaterialX", "PBR maps"),
        conversion_paths=("tcmaterial -> MaterialX", "tcmaterial -> USD Preview Surface", "tcmaterial -> Unreal Material + textures", "tcmaterial -> Unity Material + textures"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCMaterial importer", "Unity TCMaterial importer"),
        parity_policy="preserve layered source; engine path is shader translation or baked PBR texture set",
        notes="Layered TC materials should export as texture sets plus host shader bindings.",
    ),
    "shader_graphs": NativeDccFeature(
        key="shader_graphs",
        label="Shader Graphs / Lookdev",
        department="lookdev",
        subjects=("material", "textures", "asset"),
        preferred_formats=("usd", "textures"),
        required_roles=("author", "export", "import", "validate"),
        bake_fallbacks=("baked_maps", "materialx", "usd_preview_surface", "host_shader_network"),
        benchmark_tools=("Unreal Material Editor", "Houdini VOPs/Karma", "Maya LookdevX", "Blender Shader Nodes"),
        top_line_requirements=(
            "node graph with host-compatible material dialects",
            "OpenPBR/MaterialX/USD Preview Surface mapping",
            "bake preview and readback validation",
        ),
        engine_paths=("Unreal Material graph", "Unity Shader Graph/HDRP material", "MaterialX", "USD Preview Surface", "baked maps"),
        conversion_paths=("tcshader -> MaterialX", "tcshader -> Unreal Material graph", "tcshader -> Unity Shader Graph", "unsupported nodes -> baked maps"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCShader importer", "Unity TCShader importer"),
        parity_policy="keep TC graph as source of truth; translate supported nodes and bake unsupported branches",
        notes="TC shaders should preserve intent where possible and bake when a target shader graph cannot represent it.",
    ),
    "animation_takes": NativeDccFeature(
        key="animation_takes",
        label="Animation Takes / Clips",
        department="animation",
        subjects=("animation", "skeletal_mesh"),
        preferred_formats=("fbx", "usd"),
        required_roles=("export", "import", "post_import", "validate"),
        bake_fallbacks=("baked_keys", "fbx_path", "animation_paths"),
        benchmark_tools=("MotionBuilder Takes/Story", "Maya Time Editor", "Unreal Sequencer", "Blender NLA"),
        top_line_requirements=(
            "responsive playback under heavy animated scenes",
            "takes, clips, layers, time warps, timecode, and story sequencing",
            "cross-DCC preview before commit",
        ),
        engine_paths=("Unreal AnimSequence/Level Sequence", "Unity AnimationClip/Timeline", "FBX animation", "USD animation"),
        conversion_paths=("tctake -> FBX animation", "tctake -> Unreal AnimSequence/Level Sequence", "tctake -> Unity AnimationClip/Timeline"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCTake importer", "Unity TCTake importer"),
        parity_policy="author rich takes locally; engine path is baked clips/sequences with timecode metadata",
        notes="Timecode, frame range, takes, curves, and baked playback should survive transfer.",
    ),
    "curve_editing": NativeDccFeature(
        key="curve_editing",
        label="Graph Editor / Curve Editing",
        department="animation",
        subjects=("animation",),
        preferred_formats=("fbx", "usd"),
        required_roles=("process", "export", "validate"),
        bake_fallbacks=("baked_keys", "animation_curves", "fbx_path"),
        benchmark_tools=("Maya Graph Editor", "MotionBuilder FCurve", "Blender Graph Editor"),
        top_line_requirements=(
            "fast key/curve selection and tangent editing",
            "cleanup, simplify, smooth, filter, overshoot detection",
            "AI-readable curve diagnostics",
        ),
        engine_paths=("Unreal AnimSequence curves", "Unity AnimationClip curves", "FBX baked curves"),
        conversion_paths=("tccurves -> FBX curves", "tccurves -> Unreal animation curves", "tccurves -> Unity AnimationClip curves"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCCurve importer",),
        parity_policy="preserve editable curves locally; engine path is baked animation curves with validation",
        notes="Curve operations should remain native TC data and bake to host animation curves.",
    ),
    "constraints": NativeDccFeature(
        key="constraints",
        label="Constraints",
        department="rigging",
        subjects=("animation", "skeletal_mesh"),
        preferred_formats=("fbx", "usd"),
        required_roles=("author", "process", "validate"),
        bake_fallbacks=("baked_keys", "control_rig_tracks", "animation_curves"),
        benchmark_tools=("Maya Constraints", "MotionBuilder Relation Constraints", "Unreal Control Rig", "Blender Constraints"),
        top_line_requirements=(
            "parent, point, rotate, scale, aim constraints",
            "axis masks, maintain offset, reversible driver/driven state",
            "live and baked cross-DCC modes",
        ),
        engine_paths=("Unreal Control Rig/Sequencer constraints", "Unity constraints/Animation Rigging", "baked transform keys"),
        conversion_paths=("tcconstraint -> Unreal Control Rig/Sequencer constraints", "tcconstraint -> Unity Animation Rigging", "tcconstraint -> baked keys"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCConstraint importer", "Unity TCConstraint importer"),
        parity_policy="preserve live constraints locally where possible; engine path must include baked-key fallback",
        notes="Parent, point, rotate, scale, aim, axis masks, offsets, and reversible drivers.",
    ),
    "rigging": NativeDccFeature(
        key="rigging",
        label="Rigging / Skinning",
        department="rigging",
        subjects=("skeletal_mesh", "animation"),
        preferred_formats=("fbx", "usd"),
        required_roles=("author", "export", "import", "validate"),
        bake_fallbacks=("fbx_path", "skin_weights", "joint_hierarchy", "control_rig"),
        benchmark_tools=("Maya Rigging", "MotionBuilder Character Solver", "Unreal Control Rig", "Blender Armatures"),
        top_line_requirements=(
            "skeleton, controls, constraints, skin weights, corrective shapes",
            "channel-box style editing with searchable rig properties",
            "deformer and skinning parity readback",
        ),
        engine_paths=("Unreal SkeletalMesh/Skeleton/Control Rig", "Unity SkinnedMeshRenderer/Avatar", "FBX skeleton+weights"),
        conversion_paths=("tcrig -> FBX skeleton/skin", "tcrig -> Unreal Control Rig", "tcrig -> Unity Avatar/Animation Rigging"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCRig importer", "Unity TCRig importer"),
        parity_policy="rich rig locally; engine path is skeleton, skin weights, corrective shapes, and optional control rig",
        notes="TC rigs should own semantic controls and export host-specific control rigs or baked skeletons.",
    ),
    "skinning_weights": NativeDccFeature(
        key="skinning_weights",
        label="Skinning / Weight Painting",
        department="skinning",
        subjects=("skeletal_mesh", "mesh", "animation"),
        preferred_formats=("fbx", "usd", "tcskin"),
        required_roles=("author", "process", "export", "import", "validate"),
        bake_fallbacks=("skin_weights", "joint_hierarchy", "fbx_skeletal_mesh", "tcskin_package"),
        benchmark_tools=("Maya Paint Skin Weights", "ngSkinTools", "Blender Weight Paint", "Unreal SkeletalMesh Skin Weights"),
        top_line_requirements=(
            "distance, heat-map, geodesic voxel, current/existing, and TC auto bind methods",
            "bind, add/remove influences, paint, smooth, prune, normalize, mirror, copy, transfer, import, and export",
            "per-vertex heatmap display, locked influences, component masking, undoable brush strokes",
            "Maya exported weights must import as TC-native skin clusters with engine-safe max influences, GPU parity, and readback",
        ),
        engine_paths=("Unreal SkeletalMesh skin weights", "Unity SkinnedMeshRenderer weights", "FBX skeleton+weights"),
        conversion_paths=("tcskin -> FBX skin weights", "tcskin -> Unreal SkeletalMesh LOD weights", "tcskin -> Unity SkinnedMeshRenderer"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCSkin importer", "Unity TCSkin importer"),
        parity_policy="own editable weights locally; engine path must clamp/prune to platform max influences and validate GPU deformation parity",
        notes="Skinning is promoted to its own lane so migration, bridge commands, and chat routing can reason about weight edits directly.",
    ),
    "retargeting": NativeDccFeature(
        key="retargeting",
        label="Retargeting",
        department="rigging",
        subjects=("animation", "skeletal_mesh"),
        preferred_formats=("fbx",),
        required_roles=("resolve", "post_import", "validate"),
        bake_fallbacks=("baked_target_skeleton_fbx", "animation_paths", "retarget_report"),
        benchmark_tools=("MotionBuilder Character Solver", "Maya HumanIK", "Unreal IK Retargeter", "MetaHuman RigLogic/DNA"),
        top_line_requirements=(
            "source/target skeleton characterization",
            "chain maps, root motion, scale compensation, floor contact, and validation clips",
            "route selection across TC, MotionBuilder, Maya HIK, and Unreal IK Retargeter",
        ),
        engine_paths=("Unreal IK Retargeter/retargeted AnimSequence", "Unity Humanoid Avatar retarget", "baked target FBX"),
        conversion_paths=("tcretarget -> Unreal IK Retargeter", "tcretarget -> Unity Avatar mapping", "tcretarget -> baked target FBX"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCRetarget importer", "Unity TCRetarget importer"),
        parity_policy="own retarget maps locally; engine path is verified retargeter asset or baked target animation",
        notes="TC should own source/target maps and bake through MotionBuilder, Maya HIK, or Unreal IK Retargeter.",
    ),
    "mocap_live_devices": NativeDccFeature(
        key="mocap_live_devices",
        label="Mocap / Live Devices",
        department="animation",
        subjects=("animation", "skeletal_mesh"),
        preferred_formats=("fbx", "usd"),
        required_roles=("import", "process", "validate"),
        bake_fallbacks=("baked_keys", "take_recording", "fbx_path"),
        benchmark_tools=("MotionBuilder Live Devices", "Unreal Live Link", "Rokoko", "Xsens", "Faceware"),
        top_line_requirements=(
            "live stream ingest and recording",
            "latency display, calibration, cleanup, and take management",
            "retarget preview during capture",
        ),
        engine_paths=("Unreal Live Link/recorded AnimSequence", "Unity Live Capture/AnimationClip", "baked FBX take"),
        conversion_paths=("tcrecording -> FBX take", "tcrecording -> Unreal recorded AnimSequence", "tcrecording -> Unity AnimationClip"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCLiveTake importer",),
        parity_policy="live capture locally; engine path is recorded take, Live Link route, or baked clip",
        notes="TC should become the neutral live-device hub and bake recorded takes to target hosts.",
    ),
    "shots_cameras": NativeDccFeature(
        key="shots_cameras",
        label="Shots / Cameras / Sequencer",
        department="layout",
        subjects=("animation", "asset"),
        preferred_formats=("fbx", "usd"),
        required_roles=("author", "export", "import", "validate"),
        bake_fallbacks=("camera_fbx", "level_sequence", "camera_cut_track"),
        benchmark_tools=("Unreal Sequencer", "MotionBuilder Story", "Maya Cameras", "Nuke multishot workflows"),
        top_line_requirements=(
            "shot profiles with camera, lens, projection, guide solve, frame range, and timecode",
            "camera cuts and sequence handoff",
            "projection-agnostic viewport and DCC camera baking",
        ),
        engine_paths=("Unreal Level Sequence/CineCameraActor", "Unity Timeline/Cinemachine camera", "FBX/USD camera"),
        conversion_paths=("tcshot -> Unreal Level Sequence", "tcshot -> Unity Timeline/Cinemachine", "tcshot -> FBX/USD camera"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCShot importer", "Unity TCShot importer"),
        parity_policy="support advanced projections locally; engine path is cine camera plus metadata or baked render/proxy",
        notes="Shot profiles should carry projection, lens, timecode, camera cuts, and guide-solve metadata.",
    ),
    "procedural_graph": NativeDccFeature(
        key="procedural_graph",
        label="Procedural Graph",
        department="procedural",
        subjects=("asset", "static_mesh"),
        preferred_formats=("usd", "abc", "fbx"),
        required_roles=("process", "export", "validate"),
        bake_fallbacks=("baked_mesh", "usd_path", "transfer_path"),
        benchmark_tools=("Houdini SOPs/PDG", "Blender Geometry Nodes", "Maya Bifrost", "Nuke node graphs"),
        top_line_requirements=(
            "attribute-first point and instance data model with stable IDs and deterministic seeds",
            "versioned node graph, incremental content-addressed cooking, diagnostics, and procedural/baked duality",
            "scatter, spline, transform, repeat, filter, weighted asset selection, instancing, and dependency validation",
        ),
        engine_paths=("Unreal PCG graph", "Unity TCProcedural asset", "Godot MultiMesh resource", "USD/FBX baked result", "instance manifest"),
        conversion_paths=("tcgraph -> Unreal PCG", "tcgraph -> Blender Geometry Nodes", "tcgraph -> Houdini SOPs", "tcgraph -> Unity/Godot procedural runtime", "tcgraph -> baked USD/FBX"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCGraph importer", "Unity TCGraph importer", "Godot TCGraph importer"),
        parity_policy="keep procedural graph locally; engine path must bake or translate to PCG/procedural asset",
        notes="TC-native graph nodes can remain procedural in TC and bake to mesh/assets for hosts.",
    ),
    "fx_simulation": NativeDccFeature(
        key="fx_simulation",
        label="FX / Simulation",
        department="fx",
        subjects=("asset", "static_mesh"),
        preferred_formats=("usd", "abc", "textures"),
        required_roles=("process", "export", "validate"),
        bake_fallbacks=("alembic_cache", "usd_cache", "vdb_cache", "baked_mesh_sequence"),
        benchmark_tools=("Houdini Solaris/Karma/Vellum/MPM", "Maya Bifrost", "Unreal Niagara"),
        top_line_requirements=(
            "TC-native real-time and baked solvers share one authored effects graph",
            "photoreal, toony, stylized, and retro/simple quality profiles preserve authored intent",
            "attribute preservation, interactive collider response, deterministic cache validation, and runtime LOD",
        ),
        engine_paths=("Unreal Niagara/Geometry Cache", "Unity VFX Graph/cache", "Alembic/USD/VDB cache"),
        conversion_paths=("tcfx -> Alembic/USD/VDB cache", "tcfx -> Unreal Niagara/Geometry Cache", "tcfx -> Unity VFX Graph/cache"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCFX importer",),
        parity_policy="simulate and render natively in TC; translate supported graphs and bake deterministic caches for other engines",
        notes="TC owns the effects graph and runtime; Houdini, Maya, Unreal, and Unity remain import, validation, and export targets.",
    ),
    "cloth_physics": NativeDccFeature(
        key="cloth_physics",
        label="Cloth / Soft Body Physics",
        department="simulation",
        subjects=("asset", "skeletal_mesh", "animation", "static_mesh"),
        preferred_formats=("usd", "abc", "fbx"),
        required_roles=("process", "export", "validate"),
        bake_fallbacks=("cloth_cache", "alembic_cache", "vertex_animation_texture", "baked_mesh_sequence"),
        benchmark_tools=("Havok Cloth", "Houdini Vellum", "Unreal Chaos Cloth", "Marvelous Designer", "Maya nCloth"),
        top_line_requirements=(
            "production-stable TC runtime cloth with photoreal, toony, and retro/simple profiles",
            "collision layers, pins, constraints, pressure, tear/weld, and material presets",
            "interactive collider response, volume-aware folds, shot cache validation, and deterministic runtime quality tiers",
        ),
        engine_paths=("Unreal Chaos Cloth", "Unity cloth/softbody package", "Alembic cloth cache", "vertex animation texture"),
        conversion_paths=("tccloth -> Unreal Chaos Cloth", "tccloth -> Alembic cloth cache", "tccloth -> vertex animation texture", "tccloth -> Unity cloth metadata/cache"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCCloth importer", "Unity TCCloth importer"),
        parity_policy="TC-native runtime cloth first; target engines receive a translated runtime setup or deterministic cache/VAT/skeletal fallback",
        notes="TC cloth targets production stability and direct TC Engine playback while retaining Alembic, VAT, and target-runtime fallbacks.",
    ),
    "destruction_fracture": NativeDccFeature(
        key="destruction_fracture",
        label="Destruction / Fracture",
        department="simulation",
        subjects=("asset", "static_mesh"),
        preferred_formats=("usd", "abc", "fbx"),
        required_roles=("process", "export", "validate"),
        bake_fallbacks=("fractured_meshes", "geometry_collection", "alembic_cache", "usd_cache"),
        benchmark_tools=("Houdini RBD", "Unreal Chaos Destruction", "Maya Bifrost", "RayFire"),
        top_line_requirements=(
            "fracture authoring with material-aware interior faces",
            "constraint networks, clustering, debris, dust hooks, and cache playback",
            "export to Unreal Geometry Collections or baked cache",
        ),
        engine_paths=("Unreal Geometry Collection/Chaos", "Unity destructible mesh package", "fractured FBX/USD", "Alembic cache"),
        conversion_paths=("tcdestruction -> Unreal Geometry Collection", "tcdestruction -> fractured FBX/USD", "tcdestruction -> Alembic cache", "tcdestruction -> Unity destructible package"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCDestruction importer", "Unity TCDestruction importer"),
        parity_policy="author fracture/destruction locally; engine path is geometry collection, fractured assets, or baked cache",
        notes="TC should own destructible intent and support procedural fracture plus baked or live-engine transfer.",
    ),
    "procedural_generation": NativeDccFeature(
        key="procedural_generation",
        label="Procedural Generation / World Building",
        department="procedural",
        subjects=("asset", "static_mesh", "material"),
        preferred_formats=("usd", "abc", "fbx", "textures"),
        required_roles=("process", "export", "validate"),
        bake_fallbacks=("baked_mesh", "instance_manifest", "usd_stage", "pcg_graph", "houdini_digital_asset"),
        benchmark_tools=("Houdini SOPs/PDG", "Unreal PCG", "Blender Geometry Nodes", "Maya Bifrost"),
        top_line_requirements=(
            "attribute-driven instancing, bounded and spline scattering, rules, masks, weighted assets, and deterministic seeds",
            "procedural graph stays editable in TC and recooks only invalidated dependencies",
            "node timing, value counts, warnings, fingerprints, and repeatable transfer validation",
            "translate to Unreal PCG, Blender Geometry Nodes, Houdini SOPs, Unity jobs, Godot MultiMesh, or deterministic baked results",
        ),
        engine_paths=("Unreal PCG graph/instancers", "Unity procedural generation data", "Godot MultiMeshInstance3D", "USD point instancers", "baked meshes"),
        conversion_paths=("tcprocedural -> Unreal PCG", "tcprocedural -> Blender Geometry Nodes", "tcprocedural -> Houdini SOPs/PDG", "tcprocedural -> Unity/Godot runtime data", "tcprocedural -> USD point instancers", "tcprocedural -> baked meshes"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCProcedural importer", "Unity TCProcedural importer", "Godot TCProcedural importer"),
        parity_policy="procedural rules stay native; engine path is PCG/instancing translation or baked deterministic result",
        notes="TC should let users build procedural mesh/world tools natively and export either graph intent or baked results.",
    ),
    "groom_cloth_crowds": NativeDccFeature(
        key="groom_cloth_crowds",
        label="Groom / Cloth / Crowds",
        department="character_fx",
        subjects=("asset", "skeletal_mesh", "animation"),
        preferred_formats=("usd", "abc", "fbx"),
        required_roles=("process", "export", "validate"),
        bake_fallbacks=("alembic_cache", "groom_cache", "cloth_cache", "crowd_agent_cache"),
        benchmark_tools=("Houdini Groom/Cloth/Crowds", "Maya XGen/Golaem", "Unreal Groom/Chaos", "MetaHuman Groom"),
        top_line_requirements=(
            "character-FX caches tied to shots/takes",
            "simulation provenance and scale/up-axis validation",
            "baked cache and live-DCC preview modes",
        ),
        engine_paths=("Unreal Groom/Chaos Cloth", "Unity hair/cloth package", "Alembic groom/cloth cache", "USD cache"),
        conversion_paths=("tcgroom -> Unreal Groom", "tccharacterfx -> Alembic/USD cache", "tccloth -> Chaos Cloth", "tccharacterfx -> Unity hair/cloth data"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCCharacterFX importer",),
        parity_policy="character FX may exceed engine features locally; saved assets require cache/runtime setup fallback",
        notes="TC should track character FX as shot-aware caches and source-linked procedural setups.",
    ),
    "lighting_rendering": NativeDccFeature(
        key="lighting_rendering",
        label="Lighting / Rendering",
        department="lighting",
        subjects=("asset", "material", "textures"),
        preferred_formats=("usd", "textures"),
        required_roles=("author", "export", "validate"),
        bake_fallbacks=("usd_lights", "render_settings", "lookdev_turntable", "preview_frames"),
        benchmark_tools=("Unreal Lumen/MegaLights", "Houdini Karma", "Arnold", "Blender Cycles/EEVEE"),
        top_line_requirements=(
            "portable light/camera/render intent",
            "renderer-specific overrides",
            "preview validation and render diagnostics",
        ),
        engine_paths=("Unreal lights/render settings", "Unity lights/URP/HDRP settings", "USD lights", "preview frames"),
        conversion_paths=("tclighting -> Unreal lights/settings", "tclighting -> Unity lights/settings", "tclighting -> USD lights"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCLighting importer", "Unity TCLighting importer"),
        parity_policy="preserve render intent locally; engine path maps supported lights/settings and records unsupported overrides",
        notes="TC should own render intent and dispatch host-specific lighting/render validation.",
    ),
    "compositing_review": NativeDccFeature(
        key="compositing_review",
        label="Compositing / Review",
        department="review",
        subjects=("asset", "animation", "textures"),
        preferred_formats=("textures", "usd"),
        required_roles=("process", "export", "validate"),
        bake_fallbacks=("review_movie", "annotated_frames", "nuke_script", "edl"),
        benchmark_tools=("Nuke", "SyncSketch", "Unreal Movie Render Queue", "Blender Compositor"),
        top_line_requirements=(
            "frame-accurate markups tied to shots/takes/timecode",
            "multi-shot variable-style review",
            "review notes that can target source DCC objects",
        ),
        engine_paths=("Unreal Movie Render Queue outputs", "Unity Recorder outputs", "review movie/EDL/annotation manifest"),
        conversion_paths=("tcreview -> annotation manifest", "tcreview -> Unreal Movie Render Queue job", "tcreview -> review movie/EDL"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCReview importer",),
        parity_policy="review data remains native; engine path is frame/movie output plus annotation manifest",
        notes="TC markups should be transferable to shots, frames, source assets, and downstream review/compositing tools.",
    ),
    "pipeline_asset_management": NativeDccFeature(
        key="pipeline_asset_management",
        label="Pipeline / Asset Management",
        department="pipeline",
        subjects=("asset", "animation", "static_mesh", "skeletal_mesh", "material", "textures"),
        preferred_formats=("usd", "fbx", "abc", "textures"),
        required_roles=("resolve", "export", "import", "validate"),
        bake_fallbacks=("manifest", "lineage_record", "dependency_report", "asset_package"),
        benchmark_tools=("USD", "ShotGrid", "Unreal Asset Registry", "Blender Asset Browser", "Houdini PDG"),
        top_line_requirements=(
            "lineage, licensing, activation, provenance, dependencies, and validation receipts",
            "project-aware asset browser",
            "repeatable transfer recipes and rollback",
        ),
        engine_paths=("Unreal Asset Registry", "Unity AssetDatabase", "asset manifest", "dependency report"),
        conversion_paths=("tcpackage -> Unreal project assets", "tcpackage -> Unity project assets", "tcpackage -> dependency manifest"),
        custom_importer_targets=("Tech Connector Unreal plugin: TCPackage importer", "Unity TCPackage importer"),
        parity_policy="TC provenance is canonical; engine path includes import receipts, dependency validation, and rollback recipe",
        notes="TC should be strongest here: full production awareness across departments and DCCs.",
    ),
}


def list_native_dcc_features() -> list[dict[str, Any]]:
    return [feature.to_dict() for feature in NATIVE_DCC_FEATURES.values()]


def _contract_matches_feature(contract: OperationContract, feature: NativeDccFeature) -> bool:
    if feature.subjects and not set(feature.subjects).intersection(contract.subjects):
        return False
    if feature.preferred_formats and contract.formats:
        if not set(feature.preferred_formats).intersection(contract.formats):
            return False
    return True


def _contracts_by_role_for_host(
    feature: NativeDccFeature,
    host: str,
    *,
    project_root: str | None = None,
) -> dict[str, list[OperationContract]]:
    contracts = operation_contracts(host=host, project_root=project_root)
    by_role: dict[str, list[OperationContract]] = {}
    for contract in contracts:
        if not _contract_matches_feature(contract, feature):
            continue
        by_role.setdefault(contract.role, []).append(contract)
    return by_role


def analyze_feature_transferability(
    feature_key: str,
    *,
    project_root: str | None = None,
) -> FeatureTransferReport:
    feature = NATIVE_DCC_FEATURES.get(str(feature_key))
    if feature is None:
        raise KeyError(f"Unknown native DCC feature: {feature_key}")

    host_reports: dict[str, HostTransferSupport] = {}
    all_formats: set[str] = set()
    critical_gaps: list[str] = []

    for host in HOSTS:
        by_role = _contracts_by_role_for_host(feature, host, project_root=project_root)
        matched_roles = set(by_role)
        required_roles = set(feature.required_roles)
        missing = sorted(required_roles - matched_roles)
        executable_count = sum(1 for rows in by_role.values() for contract in rows if contract.executable)
        total_count = sum(len(rows) for rows in by_role.values())
        role_score = len(required_roles & matched_roles) / max(1, len(required_roles))
        executable_score = min(1.0, executable_count / max(1, len(required_roles)))
        confidence = round((role_score * 0.7) + (executable_score * 0.3), 3)
        formats = sorted({
            fmt
            for rows in by_role.values()
            for contract in rows
            for fmt in contract.formats
        })
        all_formats.update(formats)
        support = HostTransferSupport(
            host=host,
            supported=confidence >= 0.5 and total_count > 0,
            confidence=confidence,
            roles={
                role: [contract.to_dict() for contract in sorted(rows, key=lambda item: item.key)[:8]]
                for role, rows in sorted(by_role.items())
            },
            formats=formats,
            bake_fallbacks=list(feature.bake_fallbacks),
            gaps=[f"missing role: {role}" for role in missing],
        )
        host_reports[host] = support
        if host in {"maya", "blender", "motionbuilder", "unreal"} and missing:
            critical_gaps.append(f"{host}: {', '.join(missing)}")

    strongest = sorted(
        (host for host, support in host_reports.items() if support.supported),
        key=lambda host: (-host_reports[host].confidence, host),
    )
    engine_hosts = {
        host: host_reports[host]
        for host in ("unreal", "unity")
        if host in host_reports
    }
    engine_supported_hosts = [
        host
        for host, support in engine_hosts.items()
        if support.supported or support.roles
    ]
    engine_formats = sorted(
        set(feature.preferred_formats)
        | {
            fmt
            for support in engine_hosts.values()
            for fmt in support.formats
        }
    )
    conversion_paths = list(feature.conversion_paths or feature.bake_fallbacks or feature.preferred_formats)
    custom_importers = list(feature.custom_importer_targets or ("Tech Connector Unreal plugin importer",))
    has_direct_or_convertible_path = bool(feature.engine_paths or conversion_paths or custom_importers)
    engine_ready = bool(engine_supported_hosts or has_direct_or_convertible_path)
    engine_readiness = {
        "priority": feature.engine_priority,
        "ready": engine_ready,
        "supported_hosts": engine_supported_hosts,
        "engine_paths": list(feature.engine_paths),
        "conversion_paths": conversion_paths,
        "custom_importer_targets": custom_importers,
        "formats": engine_formats,
        "bake_fallbacks": list(feature.bake_fallbacks),
        "policy": feature.parity_policy,
        "gates": [
            "must preserve TC-native authoring intent",
            "must provide direct engine import, deterministic conversion, or a Tech Connector engine plugin importer",
            "must validate engine import/readback before claiming completion",
        ],
    }
    if feature.engine_priority == "required" and not engine_ready:
        critical_gaps.append("engine: no direct import, conversion path, or custom importer target")
    return FeatureTransferReport(
        feature=feature.to_dict(),
        hosts=host_reports,
        engine_readiness=engine_readiness,
        strongest_hosts=strongest,
        transfer_formats=sorted(all_formats or set(feature.preferred_formats)),
        critical_gaps=critical_gaps,
    )


def build_dcc_transferability_matrix(
    *,
    project_root: str | None = None,
) -> dict[str, Any]:
    reports = {
        key: analyze_feature_transferability(key, project_root=project_root).to_dict()
        for key in NATIVE_DCC_FEATURES
    }
    return {
        "schema": "tech_connector.dcc_transferability_matrix.v1",
        "hosts": list(HOSTS),
        "source_conversion_adapters": source_conversion_adapters(),
        "tc_runtime_authoring": runtime_authoring_contract(),
        "feature_count": len(reports),
        "features": reports,
        "summary": {
            key: {
                "label": report["feature"]["label"],
                "department": report["feature"].get("department", ""),
                "strongest_hosts": report["strongest_hosts"],
                "transfer_formats": report["transfer_formats"],
                "critical_gaps": report["critical_gaps"],
                "benchmark_tools": report["feature"].get("benchmark_tools", []),
                "top_line_requirements": report["feature"].get("top_line_requirements", []),
                "engine_readiness": report.get("engine_readiness", {}),
            }
            for key, report in reports.items()
        },
    }


def infer_native_feature_keys(text: str) -> list[str]:
    q = str(text or "").lower()
    matches: list[str] = []
    rules = {
        "scene_graph": ("scene", "outliner", "hierarchy", "reference", "visibility", "source"),
        "mesh_editing": ("mesh", "model", "vertex", "edge", "face", "extrude", "bevel", "weld", "topology"),
        "sculpting": ("sculpt", "zbrush", "subtool", "displacement", "decimate", "retopo"),
        "materials_textures": ("material", "texture", "shader", "substance", "paint", "pbr", "roughness", "normal"),
        "shader_graphs": ("shader", "lookdev", "materialx", "openpbr", "node material", "lookdevx"),
        "animation_takes": ("animation", "anim", "take", "clip", "curve", "keyframe", "timeline", "timecode"),
        "curve_editing": ("graph editor", "fcurve", "tangent", "dope sheet", "curve cleanup"),
        "constraints": ("constraint", "parent", "point", "orient", "rotate", "scale", "aim", "driver", "driven"),
        "rigging": ("rig", "joint", "bone", "control rig", "deformer"),
        "skinning_weights": ("skin", "skinning", "weight", "weights", "bind skin", "paint weights", "influence", "skincluster"),
        "retargeting": ("retarget", "retargeter", "hik", "humanik", "skeleton", "mocap", "motionbuilder", "mobu"),
        "mocap_live_devices": ("live link", "device", "rokoko", "xsens", "faceware", "webcam", "capture"),
        "shots_cameras": ("shot", "camera", "sequencer", "sequence", "lens", "fov", "projection", "playblast"),
        "procedural_graph": ("procedural", "node", "graph", "houdini", "sop", "vop", "pdg", "modifier"),
        "fx_simulation": ("fx", "simulation", "sim", "vellum", "niagara", "bifrost", "fluid", "destruction", "vdb"),
        "cloth_physics": ("cloth", "soft body", "havok", "vellum", "chaos cloth", "marvelous", "ncloth", "pin"),
        "destruction_fracture": ("destruct", "destruction", "fracture", "rbd", "chaos destruction", "geometry collection", "debris"),
        "procedural_generation": ("procedural generation", "pcg", "scatter", "instance", "world building", "seed", "rules"),
        "groom_cloth_crowds": ("groom", "hair", "fur", "cloth", "crowd", "golaem", "chaos cloth"),
        "lighting_rendering": ("light", "lighting", "render", "lumen", "karma", "arnold", "cycles", "megalights"),
        "compositing_review": ("review", "markup", "syncsketch", "nuke", "composite", "compositing", "movie render"),
        "pipeline_asset_management": ("pipeline", "asset", "shotgrid", "provenance", "lineage", "license", "dependency"),
        "dcc_to_tc_migration": ("convert to tc", "migrate", "migration", "tc native", "convert from maya", "convert from blender"),
    }
    for key, tokens in rules.items():
        if any(token in q for token in tokens):
            matches.append(key)
    return matches or ["scene_graph"]


def build_cross_dcc_chat_context(
    prompt: str = "",
    *,
    project_root: str | None = None,
    max_hosts_per_feature: int = 4,
) -> str:
    """Return a compact routing hint for chat and pipeline planning prompts."""

    matrix = build_dcc_transferability_matrix(project_root=project_root)
    feature_keys = infer_native_feature_keys(prompt)
    lines = [
        "Cross-DCC transferability context:",
        "Use Tech Connector native intent first; choose host adapters from operation contracts; bake when no host supports the native concept directly.",
    ]
    if "dcc_to_tc_migration" in feature_keys:
        adapter_summary = []
        for provider, adapter in (matrix.get("source_conversion_adapters") or {}).items():
            adapter_summary.append(
                f"{provider}={adapter.get('implementation_state')}"
                f"/character:{'ready' if adapter.get('standalone_character_conversion_ready') else 'gap'}"
            )
        lines.append("- Source conversion adapters: " + ", ".join(adapter_summary) + ".")
    for key in feature_keys:
        row = (matrix.get("summary") or {}).get(key)
        if not row:
            continue
        hosts = ", ".join(row.get("strongest_hosts", [])[:max_hosts_per_feature]) or "no strong host yet"
        formats = ", ".join(row.get("transfer_formats", [])[:6]) or "host-native/baked"
        gaps = "; ".join(row.get("critical_gaps", [])[:4]) or "none"
        benchmarks = ", ".join(row.get("benchmark_tools", [])[:4]) or "department standards"
        requirements = "; ".join(row.get("top_line_requirements", [])[:3]) or "preserve native intent and bake when needed"
        engine = row.get("engine_readiness") or {}
        engine_paths = ", ".join(engine.get("engine_paths", [])[:4]) or "engine-safe bake/interchange required"
        conversion_paths = ", ".join(engine.get("conversion_paths", [])[:4]) or "none declared"
        importers = ", ".join(engine.get("custom_importer_targets", [])[:3]) or "none declared"
        lines.append(
            f"- {row.get('label')} [{row.get('department') or 'general'}]: "
            f"benchmarks: {benchmarks}; strongest hosts: {hosts}; formats: {formats}; "
            f"engine path: {engine_paths}; conversion: {conversion_paths}; importer: {importers}; "
            f"must preserve: {requirements}; gaps: {gaps}."
        )
    return "\n".join(lines)


def department_transfer_summary(
    department: str = "",
    *,
    project_root: str | None = None,
) -> dict[str, Any]:
    matrix = build_dcc_transferability_matrix(project_root=project_root)
    wanted = str(department or "").strip().lower()
    rows = {}
    for key, summary in (matrix.get("summary") or {}).items():
        if wanted and str(summary.get("department") or "").lower() != wanted:
            continue
        rows[key] = summary
    departments = sorted({
        str(summary.get("department") or "general")
        for summary in (matrix.get("summary") or {}).values()
    })
    return {
        "schema": "tech_connector.department_transfer_summary.v1",
        "department": wanted,
        "departments": departments,
        "feature_count": len(rows),
        "features": rows,
    }


