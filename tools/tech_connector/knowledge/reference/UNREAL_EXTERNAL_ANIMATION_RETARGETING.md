# External Animation Retargeting

## Policy

Externally acquired character animation never uses a target path hardcoded in
the general pipeline. Target resolution order is:

1. explicit user-selected mesh or Skeleton
2. live selected character mesh or AnimBlueprint Skeleton
3. validated project knowledge profile
4. request target selection and block mutation

The current project may resolve UE5 Manny from live/project evidence, but Manny
is project knowledge rather than a product-wide code default.
- Once a target is resolved, unknown or partial source compatibility always
  chooses retargeting.
- Direct import is allowed only when hierarchy fingerprint, required bones,
  measured proportions, and reference pose all match the selected target.
- Import success is not compatibility proof.

The executable policy is
`tech_connector.services.unreal.external_animation_target_policy.decide_external_animation_target`.

## Capability Ladder

1. Inspect project knowledge and ArtSource rigs before searching externally.
2. Verify whether the source is already compatible with the selected target.
3. Free route: normalize axes, units, armature root, and motion root in Blender;
   then use Unreal IK Rig/IK Retargeter.
4. Optional accelerator: when Maya is installed and a characterized project rig
   exists, use `maya_tools.Rigging.mocap.hik_retarget.retarget_fbx_hik`.
5. Import the resulting animation through
   `unreal_tools.animation_import_adapter.import_animation_verified`.
6. Export the Unreal AnimSequence and inspect it independently before reuse.

The HumanIK callable requires an explicit `{label: {slot, bone}}` source map.
It must never guess characterization from similar names. Source maps are
knowledge profiles; the retarget function is an atomic technique.

## Verification Gates

A retarget action is reusable only when all applicable gates pass:

- source hierarchy and animation keys observed
- selected target and target Skeleton recorded
- source/target characterization or IK chains validated
- target motion observed before bake
- baked output exists and has nonzero animation duration
- independent round trip has plausible scale and upright orientation
- joint-connectivity contact sheet has coherent limbs and no catastrophic flips
- root/pelvis behavior is preserved according to the intended root-motion policy
- Unreal import creates an AnimSequence on the selected Skeleton
- Unreal export round trip preserves frame count, dimensions, and motion
- no new relevant import, compile, or runtime log errors

Gameplay use adds separate gates: contextual role, clip segmentation, montage or
AnimGraph integration, Blueprint compilation, and a matching PIE scenario. A
valid retarget does not prove that a mixed reference take is a usable climb,
vault, dodge, attack, or locomotion clip.

## Project Evidence

`semantic_project_index_service` indexes FBX, BVH, MA, and MB files found in
project-adjacent `ArtSource` folders. Probe evidence is enriched from:

`.ai_studio/intelligence/artsource_asset_evidence.json`

For this project, `C:/depot/ArtSource/Rigs/mocap_rigs/MannyRig_v01.fbx` is a
verified HumanIK retarget target for the tested CMU-to-Manny source profile. It
contains locked character `Character1` and a 160-bone Manny hierarchy. This is
an atomic retarget win, not proof that every source or gameplay system works.

## Repair History

The first direct Unreal route passed asset creation, exact chain mapping, and
target Skeleton checks but failed visual validation with extreme scale and axis
errors. Blender normalization fixed scale and orientation, but the resulting
motion still had invalid limb behavior due to reference-pose/proportion mismatch.
That route remains failed evidence.

The Maya HumanIK route used the authored Manny target rig, observed target hip
motion, baked 160 joints, exported FBX, passed independent visual inspection,
imported onto `SK_Mannequin`, and survived an Unreal export round trip. The full
CMU take remains contextual reference footage and must be segmented before use.

## Primary References

- Autodesk HumanIK: https://help.autodesk.com/cloudhelp/2023/ENU/Maya-CharacterAnimation/files/GUID-EDBDA3DB-4715-40EF-9ADF-412F78BFF98E.htm
- Autodesk retargeting: https://help.autodesk.com/cloudhelp/2023/ENU/Maya-CharacterAnimation/files/GUID-B2E9F8B9-F188-4E27-8820-BB0C8541701F.htm
- Autodesk bake retargeted animation: https://help.autodesk.com/cloudhelp/2022/ENU/Maya-CharacterAnimation/files/GUID-73463B4A-7B88-43F5-BA41-7908FD38E58A.htm
- Unreal IK Rig retargeting: https://dev.epicgames.com/documentation/en-us/unreal-engine/ik-rig-animation-retargeting-in-unreal-engine
- Unreal FBX skeletal import: https://dev.epicgames.com/documentation/unreal-engine/importing-skeletal-meshes-using-fbx-in-unreal-engine
