# Federated DCC Viewport

## Purpose

Tech Connector can support Maya, Blender, MotionBuilder, Unreal, and other DCC
scenes in one production environment without forcing every application to become
fully interchangeable. The core model is a federated scene: each connected app
remains authoritative over its native data, while Tech Connector owns shared
identity, composition, validation, selection, interaction routing, and optional
USD-backed interchange layers.

This is not a one-way file converter. It is a shared control surface over live
applications and portable scene data.

## Architecture

```
Tech Connector Federated Scene
    App Providers
        Maya provider
        Blender provider
        MotionBuilder provider
        Unreal provider
    Shared Scene Model
        Stable Tech Connector object ids
        Source app and native object paths
        Shared transforms, visibility, bounds, metadata
        Cross-app relationships
        Validation state
    Scene Interchange Layer
        OpenUSD layers where available
        FBX, Alembic, glTF, OBJ, image, and cache imports
        Baked animation or geometry caches for non-portable procedural data
    Viewport Compositor
        Color, alpha, depth, and object-id buffers from app providers
        Shared camera, timeline, resolution, and clipping settings
    Interaction Router
        Selection, transform, property, command, and focus routing
```

The repo already contains the two practical halves of this system:

- `tech_connector.ui.dcc_driver_widget.DccDriverDialog` is the existing DCC
  driver / second-screen control surface. It knows about Maya, Blender,
  MotionBuilder, Unreal, Unity, Houdini, and Substance Painter hosts and routes
  quick actions or raw commands through the main-window bridge methods.
- `tech_connector.ui.three_d_mesh_painter_widget.ThreeDMeshPainterViewport` is
  the existing Mesh / FBX viewer and painter surface. It already owns a viewport
  canvas, orbit controls, transform modes, OBJ geometry loading, painting, camera
  helpers, material containers, and planned FBX, glTF, GLB, STL, and USD import
  entry points.

Those should not be replaced. The federated viewport should combine them: the
DCC Driver becomes the connected-app provider panel, and the Mesh / FBX Viewer
evolves into the shared compositor and interaction canvas.

OpenUSD is the preferred common scene layer for portable data such as hierarchy,
geometry, transforms, cameras, lights, materials, skeletons, animation, metadata,
references, and composition layers. Native procedural systems remain app-owned
unless there is a dependable adapter.

## Data Classes

Tech Connector should classify incoming scene data into three buckets:

| Class | Examples | Ownership |
| --- | --- | --- |
| Portable scene data | Meshes, transforms, cameras, lights, basic materials, skeletons, animation curves, metadata | Shared model or USD layer |
| Application-owned procedural data | Maya dependency nodes, Blender Geometry Nodes, Maya construction history, Blender modifiers, native rig controls, constraints, simulations, plugins | Source application |
| Baked interchange data | Geometry caches, animation caches, evaluated meshes, baked materials | Shared model, cache files, or USD layer |

The first version should be honest about this split. Tech Connector should
assemble and coordinate scenes before it attempts deep procedural translation.

## Render Packet Contract

Each live DCC provider should eventually be able to send synchronized frame
packets to the Tech Connector compositor:

```json
{
  "schema": "tech_connector.federated_viewport.frame.v1",
  "provider_id": "blender",
  "frame_id": 521,
  "camera_revision": 88,
  "timeline_time": 13.42,
  "resolution": [1920, 1080],
  "color_texture": "shared-handle-or-path",
  "alpha_texture": "shared-handle-or-path",
  "depth_texture": "shared-handle-or-path",
  "object_id_texture": "shared-handle-or-path",
  "near_clip": 0.1,
  "far_clip": 10000.0
}
```

Alpha-only compositing is useful for the first prototype, but depth-aware
compositing is required when assets from different applications overlap. The
object-id pass enables picking and maps clicked pixels back to native objects.

## Scene Element Isolation

Each provider must be able to render only the scene elements it owns for the
current federated view. The provider should remove the normal viewport
background, sky, grid, world environment, editor HUD, selection UI, manipulators,
safe-frame overlays, and other app chrome unless Tech Connector explicitly asks
for those overlays.

Minimum provider isolation controls:

- Include or exclude scene objects by native id, collection, display layer,
  namespace, take, level, selection set, or provider-defined filter.
- Render with transparent background and premultiplied alpha.
- Disable native viewport UI overlays by default.
- Optionally include provider-authored guides, bones, controls, cameras, lights,
  collision, locators, or grid as explicit render categories.
- Report unsupported isolation categories instead of silently rendering them.

The compositor should treat each provider render as an element layer, not a
full screenshot of that application. This is what lets a Blender environment,
MotionBuilder character, and Maya prop appear inside one Tech Connector viewport
without each app bringing its own background along for the ride.

The initial isolation target can be conservative:

```json
{
  "schema": "tech_connector.federated_viewport.isolation.v1",
  "provider_id": "blender",
  "include": {
    "objects": ["blender://Scene/Environment/Door_Handle"],
    "collections": ["blender://Scene/Collection/Environment"]
  },
  "exclude_categories": ["background", "grid", "hud", "manipulators"],
  "include_categories": ["mesh", "curve", "camera", "light"],
  "transparent_background": true
}
```

## Shared Camera Contract

The Tech Connector camera can be authoritative, but the viewport should also let
users choose an existing camera from any connected application or a local camera
from the Mesh / FBX Viewer.

Supported camera authority modes:

| Mode | Behavior |
| --- | --- |
| `tc_master` | Tech Connector owns the camera. Every provider adapts to it. |
| `native_master` | A selected Maya, Blender, MotionBuilder, Unreal, or other native camera drives Tech Connector and the other providers. |
| `viewer_local` | The Mesh / FBX Viewer camera drives the composed view without writing back to native scenes until the user chooses to push it. |
| `provider_independent` | Providers keep their own cameras for diagnostic comparison, not final composition. |

For final compositing, only one camera authority should drive a frame set. The
UI can expose this as a camera dropdown:

```
Camera Source
    Tech Connector / Perspective
    Mesh Viewer / Orbit Camera
    Blender / Camera
    Blender / Shot010_Cam
    Maya / renderCam
    MotionBuilder / Producer Perspective
```

When a native camera is selected as the master, Tech Connector should query its
camera descriptor, normalize it into the shared camera schema, and push that
shared camera to every other visible provider. When the Tech Connector or Mesh
Viewer camera is selected, providers receive that shared camera as an override
for viewport rendering.

Camera synchronization must include:

- Position and rotation
- Projection mode
- Focal length or field of view
- Sensor or filmback dimensions
- Aspect ratio
- Lens shift
- Near and far clipping planes
- Viewport resolution
- World units
- Coordinate handedness

Small mismatches will make separately rendered layers slide against each other,
so camera revisions should be part of every frame packet.

Camera descriptors should be explicit:

```json
{
  "schema": "tech_connector.federated_viewport.camera.v1",
  "camera_id": "maya://Shot010/renderCam",
  "provider_id": "maya",
  "display_name": "renderCam",
  "authority": "native_master",
  "projection": "perspective",
  "transform": {
    "translation": [0.0, 145.0, 520.0],
    "rotation_euler": [-12.5, 0.0, 0.0],
    "rotation_order": "xyz"
  },
  "focal_length_mm": 35.0,
  "horizontal_aperture_mm": 36.0,
  "vertical_aperture_mm": 20.25,
  "field_of_view_degrees": 54.4,
  "near_clip": 0.1,
  "far_clip": 10000.0,
  "lens_shift": [0.0, 0.0],
  "resolution": [1920, 1080],
  "world_units": "centimeters",
  "up_axis": "y",
  "handedness": "right"
}
```

Providers should report which camera fields are lossy or unsupported. For
example, a provider may support FOV but not filmback, or may need a coordinate
conversion for up-axis differences.

## Object Identity

Every visible or selectable object needs a stable Tech Connector identity:

```json
{
  "tc_id": "tc://object/7f8a2a",
  "provider_id": "blender",
  "native_id": "blender://Scene/Environment/Door_Handle",
  "display_name": "Door_Handle",
  "object_type": "mesh",
  "parent_tc_id": "tc://object/2a09cd",
  "capabilities": {
    "select": true,
    "translate": true,
    "rotate": true,
    "scale": true,
    "visibility": true,
    "rename": true,
    "edit_mesh": true,
    "material_edit": true
  },
  "sync_state": "live"
}
```

Native ids are opaque to the core application. Only the owning provider should
parse or mutate them.

## Outliner

The outliner should support two complementary views.

Application view preserves ownership:

```
Shared Scene
    Blender
        Environment
        Buildings
        Props
    MotionBuilder
        Character_Hero
        Character_Enemy
        Takes
    Maya
        Hero_Rig
        Sword
        Cameras
    Tech Connector
        Shared Cameras
        Markers
        Annotations
        Cross-App Relationships
```

Composed scene view organizes by production meaning:

```
Shot_010
    Environment
        Blender assets
    Characters
        MotionBuilder performance
        Maya production rig
    Cameras
    Shared relationships
```

Selecting an outliner item should:

- Highlight the object in the federated viewport
- Route native selection to the source application
- Populate shared and app-specific properties
- Show context commands based on object capabilities
- Display a Tech Connector transform manipulator when the transform is writable

## Attribute Editor And Channel Box

The editor should be descriptor-driven rather than hardcoded per application.
Adapters expose properties with display, validation, and routing metadata.

```json
{
  "id": "maya://Hero_R_Hand_CTRL.ik_fk",
  "label": "IK / FK",
  "group": "Custom Rig Attributes",
  "type": "float",
  "value": 1.0,
  "minimum": 0.0,
  "maximum": 1.0,
  "writable": true,
  "source": "maya",
  "edit_route": "native",
  "update_mode": "live"
}
```

Supported descriptor types should include:

- `bool`: checkbox
- `enum`: dropdown
- `int` and `float`: numeric field, optional slider
- `vector2`, `vector3`, `vector4`: component fields
- `color`: color picker
- `string`: text field
- `path`: file or folder picker
- `object_ref`: searchable object picker
- `action`: button
- `status`: read-only diagnostic row

Property groups should be divided into:

- Shared properties: name, transform, visibility, bounds, source app, native
  path, sync state, ownership, tags, metadata
- Application properties: Maya custom attributes, Blender modifiers,
  MotionBuilder takes, Unreal components, Houdini parameters
- Tech Connector properties: composition overrides, annotations, validation
  results, relationships, publish state, locks, sync policy

For multi-selection, the editor should show the shared editable intersection
first. Provider-specific sections can remain separate below it.

## Edit Routing

Every editable operation must declare where it executes:

| Route | Meaning |
| --- | --- |
| `native` | Send the mutation to the owning application bridge |
| `shared_override` | Store the mutation in a Tech Connector composition layer |
| `relationship` | Update a Tech Connector cross-app relationship |
| `read_only` | Display only |
| `requires_focus` | Focus or foreground the owning app before mutation |
| `transaction` | Group the mutation with undo, validation, and readback |

Examples:

- Maya rig control value changes route to Maya.
- Blender modifier edits route to Blender.
- Temporary placement offsets can route to a shared override.
- Review notes and annotations stay in Tech Connector.
- Cross-app constraints or preview targets update Tech Connector relationships
  and then send native marker or transform commands as needed.

## Prototype Phases

### Phase 1: Unified Scene Inspection

Read hierarchy, transforms, cameras, lights, meshes, materials, skeletons,
animation summaries, current selection, and file paths from Blender, Maya, and
MotionBuilder bridges. Build the first application-owned outliner.

### Phase 2: Alpha Composited Viewport

Synchronize camera, timeline, resolution, and clipping values across two app
providers. Render transparent color buffers and layer them in the Mesh Viewer.
Avoid overlap requirements in this phase.

This phase must include scene element isolation: each provider renders only its
selected or registered scene elements with transparent background and native
viewport UI overlays disabled.

### Phase 3: Depth-Aware Compositing

Add depth buffers to frame packets and perform per-pixel depth selection in the
Tech Connector compositor. This creates correct cross-application occlusion.

### Phase 4: Object-ID Picking

Add object-id buffers and an object registry. Map clicks back to source
application objects and route native selection through the relevant bridge.

### Phase 5: Shared Transform Tools

Let Tech Connector own the transform gizmo. Convert deltas into provider-native
coordinates, execute native transform commands, wait for readback, and refresh
the composed viewport.

### Phase 6: Validation And Cross-App Relationships

Add validators for units, scale, orientation, naming, missing textures, broken
references, unsupported nodes, skeletal mismatches, export state, and sync
latency. Add relationship records for align, snap, measure, reach target,
preview constraint, and marker workflows.

### Phase 7: Higher-Level Translation

Add dependable adapters for common rigs, material subsets, constraints,
modifiers, and procedural systems. Treat this as incremental coverage, not a
requirement for the federated viewport to be useful.

## Initial Integration Points

- `tech_connector.ui.dcc_driver_widget`: existing app-aware DCC Viewer / second
  screen. Extend its host model from quick commands into scene-provider status,
  scene-summary refresh, selection routing, camera sync status, and render stream
  health.
- `tech_connector.ui.three_d_mesh_painter_widget`: existing Mesh / FBX Viewer.
  Promote its canvas into a federated viewport compositor that can draw local
  mesh assets plus live DCC color/depth/object-id layers.
- `tech_connector.bridges.*`: provider execution, scene inspection, selection,
  transform, property, and render packet commands.
- `tech_connector.ui.pipeline_attribute_editor`: existing descriptor-driven UI
  pattern for a future object property editor.
- `tech_connector.app.main_window_dcc`: direct DCC command routing and bridge
  discovery.
- `tech_connector.data.capability_registry.json`: capability discovery surface
  for provider-specific commands.

## Provider Snapshot Coverage

The first shared bridge contract is `get_scene_snapshot(...)`. A snapshot returns
provider id, scene path/name, units, up axis, visible scene elements, cameras,
active camera where available, and isolation settings. Scene elements can carry
true mesh geometry or a bounds fallback.

Apps do not need this on day one. A newly added 3D app can start as only
launchable and docs-aware if the user supplies an executable path and API docs.
Scene snapshots, camera sync, geometry extraction, render packets, and smart
menus are optional provider upgrades.

| Provider | Current Snapshot Support | Notes |
| --- | --- | --- |
| Maya | True mesh vertices/faces, cameras, visible element bounds | Uses world-space mesh extraction through `maya.cmds`; non-mesh elements use bounds fallback. |
| Blender | True evaluated mesh vertices/faces, cameras, visible element bounds | Uses `bpy` evaluated depsgraph so modifiers can be represented as evaluated mesh output. |
| MotionBuilder | Object bounds and cameras | Mesh extraction remains a follow-up; useful now for characters, cameras, markers, and app-colored placement. |
| Houdini | True geometry points/faces where nodes expose geometry, cameras, bounds fallback | SOP geometry can be imported as true mesh; procedural networks remain Houdini-owned. |
| Unreal | Actor bounds and camera actors | True static/skeletal mesh extraction requires a separate editor mesh-data path and project settings. |
| Unity | Explicitly unsupported by current bridge | Needs a C# bridge endpoint that emits structured GameObject, Renderer bounds, MeshFilter geometry, and Camera data. |
| 3ds Max | No registered bridge in this checkout | Needs a MaxScript/Python bridge before it can participate. |

## Combination Strategy

The first combined UI can be built as a new wrapper dialog instead of deeply
rewiring both existing widgets immediately:

```
FederatedDccViewportDialog
    Left: provider/outliner panel
        Connected apps from DccDriverDialog.HOSTS
        Per-app scene summary
        Application-owned object tree
    Center: ThreeDMeshPainterViewport canvas
        Local mesh/FBX/OBJ/USD assets
        Live app render layers
        Shared camera controls
        Selection and transform gizmo
    Right: descriptor-driven attribute/channel panel
        Shared properties
        Provider-specific properties
        Tech Connector relationship properties
    Bottom: sync/status strip
        Frame ids
        Camera revision
        Timeline
        Provider latency
        Validation alerts
```

This lets the current DCC Driver and Mesh / FBX Viewer continue to work as
standalone tools while the federated viewport grows beside them.

## Existing Viewer Responsibilities

The DCC Driver should keep responsibility for:

- Host discovery and reachability
- Launch and bridge setup actions
- Raw command execution
- Quick app-specific actions
- Bridge status and command logging

The Mesh / FBX Viewer should keep responsibility for:

- Camera navigation
- Local mesh display
- Transform mode state
- Viewport painting and overlays
- Import/export-adjacent asset inspection

The federated layer should add:

- A shared camera contract above both
- A stable object registry across app providers
- True scene geometry import for supported object types
- Bounds or icon fallback for unsupported object types
- A render packet compositor
- Depth-aware occlusion
- Object-id picking
- Provider-aware selection and edit routing
- Descriptor-driven property panels

## First Thin Slice

The smallest useful implementation should be:

1. Create a `FederatedDccViewportDialog` that embeds or mirrors the current DCC
   host list beside the existing Mesh / FBX Viewer canvas.
2. Add provider scene-snapshot commands that return real mesh geometry when
   available, plus bounds fallback data for non-mesh or oversized elements.
3. Assign each provider a stable viewport fill and outline color.
4. Build a federated object registry from those summaries.
5. Display an application-owned outliner.
6. Route outliner selection back to each native application.
7. Show shared transform, visibility, source app, native path, and sync status in
   a descriptor-driven property panel.

That proves the control model before the rendering work gets expensive.
