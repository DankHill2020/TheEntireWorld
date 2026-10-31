# Production Joint Placement Pipeline

## Goal

Create a repeatable animation skeleton whose joints are anatomically plausible,
inside the character volume, compatible with the existing HumanIK map, and
explicitly marked for artist review when the input cannot support a reliable
automatic decision.

Automatic placement is not considered successful merely because joints were
created. Success means that topology, volume containment, hierarchy, pose, and
confidence checks all pass.

## Pipeline

1. **Mesh preflight**
   - Resolve the visible, non-intermediate mesh shape.
   - Record vertex/face/shell counts.
   - Detect boundary edges, non-manifold edges, and lamina faces.
   - Treat open, non-manifold, or multi-shell input as review-required.

2. **Canonical proposal**
   - Read core joint world positions from the existing studio Maya template at
     `rig_template.DEFAULT_BIPED_RIG_TEMPLATE`.
   - Use the authored `.bps` bind-pose matrices directly from the Maya ASCII
     asset, without importing or referencing it into the working scene.
   - Scale that HIK-compatible template into the target mesh bounds.
   - Permit an ML landmark provider to override known joint proposals.
   - Ignore unknown provider outputs and never let inference create arbitrary
     Maya nodes directly.

3. **Geometry refinement**
   - Intersect accelerated rays with the real world-space mesh.
   - Pair ordered surface crossings into solid intervals.
   - Recenter each proposal in cross-sections perpendicular to its expected
     bone direction: X/Z for vertical torso and leg chains, Y/Z for horizontal
     arm chains, and X/Y for forward-facing toe chains.
   - Alternate both section axes to converge toward the local medial region.
   - Project arms onto exact XY planes and legs/spine onto exact YZ planes.
   - Preserve or introduce a small elbow/knee prebend so two-bone IK never
     starts from a singular, perfectly straight chain.

4. **Independent containment**
   - Test each point using odd/even ray parity on X, Y, and Z.
   - Require a two-of-three majority to avoid vertex/edge grazing ambiguity.
   - If a proposal is outside, find the closest surface and test inward offsets
     along both normal directions and toward the character center.

5. **Skeleton construction**
   - Run `preview_biped_joint_placement` or
     `preview_selected_mesh_joint_placement` first for a non-destructive review.
   - Load or reuse the high-resolution Maya studio template, with 280 joints
     beneath `origin`.
   - Fit the solved anchors onto the authored hierarchy.
   - Uniformly scale secondary finger, face, and twist offsets before fitting
     the primary anchors, preserving authored orientations and hierarchy.
   - Treat the 12 separately rooted reverse-foot joints as high-resolution rig
     helpers and report them separately from the 280-joint skeleton count.
   - Record the applied template scale so repeated fitting is idempotent.
   - Store one preferred local bend axis on elbows, knees, spine joints, and
     every finger knuckle. Keep rotate channels unlocked for constraints,
     retargeting, and FK; preferred axes guide IK without damaging the bind rig.
   - Project each thumb and finger chain onto its strongest authored plane
     before assigning knuckle bend axes.
   - Generate HIK maps from the fitted studio root.

6. **QA result**
   - Return per-joint confidence, pose classification, planar deviation,
     topology facts, local clearance, anatomical-order issues, unverified joint
     names, and a `requires_review` flag.
   - `require_interior=True` converts unverified containment into a hard failure.
   - Approval locators are green for verified/high confidence, yellow for low
     confidence, and red when containment cannot be verified.

## ML contract

ML is a proposal provider, not the final authority. A provider returns a mapping
of established joint names to world-space XYZ positions. The deterministic mesh
solver performs the final embedding and validation. This allows RigNet-style or
studio-trained inference to be added later without coupling model dependencies
to Maya or weakening deterministic fallback behavior.

## Acceptance criteria

- Closed production meshes have no unverified joints.
- Open/non-manifold input is visibly marked for review.
- Repeated runs on unchanged geometry produce the same points.
- The output fills the required HumanIK slots.
- Production commits retain all 280 joints below `origin`; the 12 RFL helpers
  remain separately counted.
- Spine/neck/head order, hip/knee/ankle order, side assignment, lateral limb
  order, and minimum bone lengths pass anatomical validation.
- Arm, leg, and spine plane deviation is effectively zero; elbows and knees
  retain a nonzero prebend and explicit preferred bend-axis metadata.
- Existing public entry points and the proportional legacy solver remain usable.
- The hard-coded proportional table is an emergency fallback only; the studio
  skeleton asset is the normal source of anatomical proportions.

## Maya UI

The Full Rig Actions section exposes two separate operations:

- **Preview Joint Placement** creates guides and diagnostics only.
- **Fit Mapped Skeleton / Default Template** fits the hierarchy already defined
  by the active HumanIK Rig Mapping. Joint names, mapped spine count, parent
  relationships, fingers, and authored detail branches are preserved. When no
  usable mapping exists, it commits the default 280-joint hierarchy instead.
- **Capture Approved Baseline** stores the selected approved character in
  translation- and uniform-scale-invariant normalized coordinates.
- **Validate Selected Placement** compares a non-destructive proposal with one
  approved baseline.
- **Run Placement Regression Suite** launches mayapy asynchronously so every
  manifest scene is tested without modifying the artist's open scene.

## Regression acceptance

Golden cases live under `joint_placement_regression_cases/` and reference their mesh
scenes from `manifest.json`. Reports include mean/maximum normalized anchor
error, mean/maximum bone-length ratio error, chain-plane deviation, containment,
anatomical validation, and the 280+12 hierarchy counts. New solvers—including
ML landmark providers—must pass the same corpus before becoming the default.

## Approved studio reference atlas

`joint_placement_reference_atlas/` contains normalized full-hierarchy samples
captured from approved studio `_rig.ma` files. When the target has an exact
vertex/face topology match, the production solver selects the closest approved
body proportion and transfers every joint through a local affine fit of the 32
nearest corresponding vertices. This preserves anatomical depth, hands, feet,
twist chains, facial branches, and correctives instead of inferring them from a
front-view silhouette. For unrelated topology, the solver falls back to the
normalized reference ranking and mesh-volume heuristics. Core chains still pass
through containment, plane, hierarchy, and anatomical validation in both modes.

Run `joint_placement_reference_builder.py` with Maya's `mayapy` to regenerate
the atlas from approved source rigs. Source scenes are opened read-only; the
runtime solver uses only the checked-in normalized JSON data and does not need
the production drive mounted.

## Corrective and MetaHuman-style hierarchies

Mapped placement derives the character side/up/depth axes from the Hips, Head,
Left Hand, and Right Hand mappings. This supports characters whose physical
up-axis differs from Maya's scene preference, including the local MetaHuman
sample whose body is physically Z-up in a Y-up scene.

For a detected MetaHuman-style bind hierarchy:

- twist joints retain their authored fraction along the newly fitted core bone;
- `*_correctiveRoot_*` joints are colocated with their driver joint;
- `*_twistCor_*` joints are colocated with their authored twist parent;
- named body and finger surface correctives are projected to the selected body
  mesh surface;
- joint names, hierarchy, and joint orientation values are not changed;
- `FACIAL_*` DNA joints and `_drv` duplicates are protected;
- locked or driven corrective translations are reported and skipped. Disable or
  remove RigLogic/RBF systems in neutral-pose editing mode before rerunning when
  those joints must be repositioned.

Mapped fitting performs this editability check before changing any joint. If a
body corrective or twist is still driven, the fit is rejected with the affected
joint names so an assembled MetaHuman cannot be left partially updated.

Every detected corrective is audited after dependency-graph evaluation. The
placement report stored on the skeleton root records detected and verified
totals, custom/unclassified corrective nodes, driven nodes that could not be
verified, and exact relationship errors. Editable surface correctives are
projected exactly; driven RBF correctives are accepted only when their evaluated
neutral positions remain inside a small character-scale surface envelope.
Authored twist fractions are audited separately so a driven twist that failed to
follow a resized limb cannot be mistaken for a corrective-placement failure.

This follows Epic's separation between automatically placed surface joints,
volume joints that require inspection, and protected DNA/body connection joints.
Facial neutral-joint updates must continue through the DNA/MetaHuman for Maya
workflow rather than body-mesh projection.

## References

- Baran and Popovic, *Automatic Rigging and Animation of 3D Characters*, ACM
  Transactions on Graphics 26(3), 2007.
- Xu et al., *RigNet: Neural Rigging for Articulated Characters*, ACM
  Transactions on Graphics 39(4), 2020.
- Autodesk Maya Python API 2.0, `MFnMesh.allIntersections` and cached mesh
  intersection accelerators.
- Epic Games, *MetaHuman DNA, Rig Definition, and Rig Operation*.
- Epic Games, *MetaHuman Stylized Character - Body Rig Editing*.
