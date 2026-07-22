# Unreal Prompt System Reference Library

This document is the local implementation memory for prompt-built Unreal systems.
It exists so the generator compares a new request against known-good system
shapes before it creates or edits assets.

The standard is not "place plausible nodes." The standard is:

1. Resolve the target project assets and skeletons.
2. Select one or more documented recipes that match the prompt.
3. Expand those recipes into an executable plan with concrete assets, graph
   topology, variables, slots, and validation probes.
4. Stage the operation for review.
5. Apply only through first-party bridge operations.
6. Compile, save, rescan, and reject success if the graph or assets do not
   satisfy the recipe contracts.

## Competitive Capability Target

Ludus AI positions itself as an Unreal-native assistant that generates assets
inside the editor, works from project context, supports broad editor surfaces,
and applies changes through a staged approval flow. The engineering target for
this prompt system is the same class of behavior:

- Project-wide awareness: assets, Blueprints, C++, graph structure, naming
  conventions, plugins, skeletons, animation assets, maps, and selected actors.
- Direct editor mutation: generated assets should appear in Content Browser
  and changed graphs should be physically wired.
- Broad system coverage: Blueprint graphs, Animation Blueprints, Control Rig,
  IK Retargeter, Pose Search, Enhanced Input, GAS-style abilities, AI,
  Behavior Trees, UMG, Niagara, Materials, PCG, MetaSounds, Sequencer, level
  actors, save systems, inventory, puzzle state machines, and data assets.
- Staged operations: every multi-asset generation returns an approval-ready
  plan with affected assets, exact changes, validation probes, and rollback
  boundaries.
- No hallucinated success: compile, save, rescan graph pins, verify asset
  references, and report failures as failures.

Sources checked July 19, 2026:

- https://ludusengine.com/blog/generative-ai-unreal-engine
- https://ludusengine.com/blog/best-ai-for-unreal-engine-developers
- https://landing.ludusengine.com/

## Recipe Schema

Each recipe should define:

- `key`: stable identifier, for example `traversal.wall_contact_climb`.
- `family`: broad domain such as traversal, combat, animation, puzzle, AI, UI,
  VFX, audio, or world building.
- `trigger_phrases`: prompt phrases that select the recipe.
- `required_assets`: asset classes or exact assets that must exist or be
  generated.
- `graph_contract`: the graph topology that must be built.
- `validation_contract`: the objective proof required after mutation.
- `failure_modes`: common false-positive outcomes the system must reject.

## Core Generation Rules

- A prompt-built gameplay system must own real state, not just PrintString.
- A prompt-built animation system must verify the mesh uses the intended
  AnimBlueprint, the montage assets exist, the montage slots exist, and the
  slot nodes reach Output Pose.
- A prompt-built traversal system must prove traces use linked Start/End math,
  not default zero vectors.
- A prompt-built ability must verify activation, cooldown/resource state,
  animation or effect output, reset/cancel path, and input mapping.
- A prompt-built imported asset must land in a project folder such as
  `/Game/AIStudio/DownloadedAnimations`, `/Game/AIStudio/RetargetedAnimations`,
  `/Game/AIStudio/GeneratedAnims`, or another prompt-selected destination.
- A prompt-built retarget path must let the user select the destination
  skeleton or skeletal mesh before import/retarget when multiple candidates
  exist.
- A prompt-built motion matching system must verify Pose Search assets,
  compatible animation entries, schema/database wiring, and an AnimGraph node
  path to Output Pose.

## Animation Recipes

### Multi-Slot Montage Layering

Use when a prompt mentions montages, upper body, full body, additive layers,
aiming while moving, hit reactions, traversal montages, combat attacks, or any
system with multiple animation roles.

Required assets:

- AnimBlueprint
- Skeleton
- One AnimMontage per montage role
- Slot node per declared role slot

Graph contract:

- Every animation role declares an explicit slot name.
- Full-body actions use a full-body slot that reaches final pose.
- Upper-body actions use a slot blended per bone over locomotion.
- Additive reactions use additive pose handling before final output.
- Slot nodes are composed through the intended blend/layer path before Output
  Pose.

Validation:

- Every declared slot is present as a Slot node.
- Every declared Slot node has a connected Pose input.
- Every declared Slot node reaches Output Pose by graph traversal.
- Every PlayAnimMontage node has a non-empty AnimMontage asset pin.
- Every montage asset is saved and compatible with the selected skeleton.
- The character mesh uses the AnimBlueprint that contains the slot graph.

Reject success when:

- Only `DefaultSlot` is checked for a multi-slot plan.
- A montage slot exists on the montage but not in the AnimGraph.
- The character mesh points to another AnimBlueprint.

### Motion Matching Locomotion

Use when a prompt mentions motion matching, Pose Search, motion-matched
locomotion, strafing locomotion databases, or high-quality locomotion.

Required assets:

- PoseSearchSchema
- PoseSearchDatabase
- Compatible locomotion AnimSequences
- AnimBlueprint with Motion Matching/Pose Search node path
- Optional Chooser assets for trajectory or mode selection

Graph contract:

- Resolve or create a PoseSearchSchema for the target skeleton.
- Resolve compatible animation clips or import and retarget them first.
- Create/update PoseSearchDatabase with saved compatible animation entries.
- Add Motion Matching/Pose Search node to the AnimGraph.
- Route locomotion state variables and trajectory data into the node.
- Ensure the node reaches Output Pose through the intended blend stack.

Validation:

- PoseSearch plugin/classes are discoverable.
- Schema asset exists.
- Database asset exists.
- Database references at least one compatible animation.
- AnimGraph contains a Motion Matching/Pose Search node.
- Motion matching node reaches Output Pose.
- Character mesh uses the updated AnimBlueprint.

Reject success when:

- A PoseSearchDatabase exists but has no compatible animation entries.
- Imported animations remain on a foreign skeleton.
- The AnimGraph compiles but the motion matching node is disconnected.

## Traversal Recipes

### Automatic Wall Contact Climb

Use when a prompt mentions wall climbing, ledge grab, hang, mantle, wall jump,
or climb traversal.

Graph contract:

- Event Tick runs a short forward capsule trace from actor location to actor
  location plus forward vector times climb probe distance.
- Trace hit enters a Branch and Do Once before state changes and montage play.
- Trace miss clears climb/hang variables, climb speed, vertical input, and
  resets Do Once.
- Wall jump input clears climb/hang state, plays wall-jump montage, launches
  away from the wall, then resets transient wall-jump state.
- Movement mode can change for prototype climb, but GravityScale-only climbing
  is not an animation system and must not count as success.

Validation:

- CapsuleTraceByChannel exists.
- Start and End pins are linked to location/vector math.
- ReturnValue links into Branch Condition.
- Branch true path reaches Do Once.
- Do Once completed path reaches PlayAnimMontage.
- False path resets climb state and Do Once.
- ABP update graph copies character climb variables every frame.
- Climb/hang montage role exists and is slotted into final pose.

Reject success when:

- Pressing a key only toggles gravity or movement mode.
- Tick restarts the montage every frame.
- The ABP never receives climb variables.

### Vault, Mantle, Slide

Use for vaulting waist-high obstacles, mantling ledges, sliding while sprinting,
and context-sensitive Space actions.

Graph contract:

- Input action or key routes through a movement-context branch.
- Vault/mantle uses forward and height traces to classify obstacle geometry.
- Slide checks grounded, sprinting, and speed thresholds.
- Chosen action sets a transient state, plays the correct montage, applies
  root motion or launch movement, and resets state.

Validation:

- Trace Start/End pins are linked.
- Classification Branch pins are wired.
- Correct montage role is played for selected action.
- State reset path exists.
- Collision capsule size changes, if any, are restored.

Reject success when:

- Space always launches without obstacle/sprint context.
- Slide changes capsule size without restoring it.

### Grappling Hook Zip

Use for grapples, pulls, zips, hook shots, or traversal tethers.

Graph contract:

- Input fires a forward trace or camera trace to max grapple distance.
- Hit result drives target location.
- Valid hit starts grapple state and montage.
- Movement uses LaunchCharacter, movement component interpolation, cable
  component, or custom movement according to prompt complexity.
- Invalid hit exits without changing grapple state.

Validation:

- Trace Start/End pins are linked.
- Trace hit condition gates launch/zip.
- Montage asset pin is populated.
- Launch or movement node has override/target pins set.
- Grapple state resets after travel or cancel.

Reject success when:

- Launch executes even when the trace misses.
- The trace uses default zero vector inputs.

## Combat Recipes

### Directional Dodge Roll

Graph contract:

- Input reads current movement vector or last movement input.
- Set dodge and invulnerability state.
- Play dodge montage in the declared slot.
- Apply LaunchCharacter or root motion displacement.
- Delay/timer resets dodge and invulnerability state.

Validation:

- Input path reaches PlayAnimMontage and movement displacement.
- Montage slot reaches Output Pose.
- Invulnerability has a reset path.

Reject success when:

- Dodge is only a LaunchCharacter impulse.
- Invulnerability never resets.

### Melee Combo

Graph contract:

- Input opens a combo window, increments combo index, and plays the current
  attack montage section.
- Montage notify or timer opens/closes combo input buffering.
- Hit trace or collision window is gated by montage notify/state.
- Damage output references a damage interface/component.

Validation:

- Combo index is bounded and reset.
- Montage sections exist or notifies are present.
- Hit detection only runs during active frames.
- Damage target path is valid.

Reject success when:

- All attack inputs play the same montage without combo state.
- Damage applies without hit validation.

### Block, Parry, Counter

Graph contract:

- Hold input enters block state.
- Timed parry window exists at activation.
- Incoming hit checks attacker direction and parry/block timing.
- Successful parry plays counter/stun montage and opens counter state.

Validation:

- Block state has press and release paths.
- Parry window is timer bounded.
- Incoming damage path branches on block/parry state.
- Counter montage and reset path exist.

Reject success when:

- Parry is a permanent bool.
- Incoming damage is never connected to defense state.

## Ability Recipes

### Cooldown Resource Ability

Graph contract:

- Input checks cooldown, resource, and activation tags/state.
- Activation spends resource and sets active/cooldown state.
- Ability emits movement, damage, effect, spawned actor, or animation output.
- Timer/delay clears active and cooldown state.

Validation:

- Cooldown gate exists before activation.
- Resource subtraction is bounded.
- Output effect is real, not only PrintString.
- Reset/cancel path exists.

Reject success when:

- The ability can fire during cooldown.
- Resource can go negative unless explicitly allowed.

### Gameplay Ability System Style Ability

Graph contract:

- Ability class or component owns activation logic.
- Gameplay Tags describe activation, cooldown, block/cancel, and state.
- Gameplay Effects handle cooldown/resource/damage when GAS is available.
- Character grants ability and binds input.

Validation:

- GAS classes/plugins are available or the plan chooses a non-GAS fallback.
- Ability asset/class exists.
- Input reaches ability activation.
- Cooldown/effect assets are referenced.

Reject success when:

- The plan claims GAS but only creates character bools.

## Puzzle Recipes

### Interactable State Machine

Graph contract:

- Interaction detection finds a target actor/component.
- Puzzle actor owns solved/progress/reset state.
- Inputs transition puzzle state, not just character variables.
- Completion triggers a visible level or gameplay result.

Validation:

- Interact binding stays preserved unless prompt asks otherwise.
- Puzzle actor compiles.
- State transitions and reset path are wired.
- Referenced actors/components exist or are spawned.

Reject success when:

- A PrintString-only interaction is treated as a puzzle.

### Sequence Puzzle

Graph contract:

- Ordered inputs append to a sequence buffer.
- Correct sequence triggers solved state.
- Incorrect sequence clears or penalizes according to prompt.
- Visual/audio feedback is emitted for progress, failure, and solve.

Validation:

- Sequence buffer exists and is bounded.
- Correct and incorrect branches exist.
- Solved output references a real actor/component/event.

Reject success when:

- Any input solves the puzzle.

## AI Recipes

### Patrol, Chase, Attack

Required assets:

- AIController
- BehaviorTree or StateTree
- Blackboard, if BehaviorTree
- Perception component or sensing trace
- Pawn/Character Blueprint

Graph contract:

- AI owns perception and target selection.
- Patrol state moves among waypoints.
- Chase state follows visible target.
- Attack state gates range, cooldown, and animation.
- Lost target path returns to search/patrol.

Validation:

- Controller is assigned to pawn.
- BehaviorTree/StateTree asset exists and is referenced.
- Blackboard keys exist.
- Perception component exists.
- Attack montage/effect path is valid.

Reject success when:

- AI logic is placed only on Level Blueprint.
- Attack fires without range/cooldown checks.

## UI Recipes

### HUD Widget Binding

Graph contract:

- Widget Blueprint exists.
- Character/controller creates and adds widget to viewport.
- Widget receives data through binding, event dispatch, or view model.
- Input mode/focus behavior matches prompt.

Validation:

- Widget class reference is populated.
- CreateWidget reaches AddToViewport.
- Bound data variables exist and update.

Reject success when:

- Widget is created but never added to viewport.

## VFX, Audio, Materials, PCG, Sequencer

The prompt system should maintain recipes for each editor surface it can mutate:

- Niagara: emitters, systems, user parameters, spawn/update scripts, renderer,
  bounds, preview validation.
- Materials: texture parameters, scalar/vector params, usage flags, compile
  status, assigned mesh/material slots.
- MetaSounds and SoundCues: input params, wave players, attenuation,
  concurrency, references from gameplay graph.
- PCG: graph asset, input data, generation bounds, spawned output validation.
- Sequencer: level sequence, possessed/spawned bindings, camera cuts, tracks,
  section ranges, playback trigger.
- Control Rig: rig hierarchy, controls, constraints, graph compile, skeletal
  mesh compatibility.

Each recipe must end with the same proof: asset exists, graph compiles, required
references are populated, generated output is connected to gameplay or level
state, and the user has repeatable test steps.

## Semantic Project Index And Reasoning Loop

The prompt system must reason from live project facts, not from a mechanic name.
Recipes are comparison material and validation contracts; they are never a
license to emit a fixed graph without inspecting the project.

The semantic index stores:

- Unreal asset catalog rows, class, tags, fingerprints, and dependency edges.
- Blueprint parent/generated classes, components, variables, functions, graphs,
  nodes, pins, pin values, directions, and physical links.
- Animation skeleton, duration, samples, root-motion facts, and provenance.
- Reflected C++ classes/functions and include relationships from project and
  active bridge-plugin source.
- Task-specific PIE observations with assertions and evidence.
- Explicit exclusions for retired, misleading, or context-invalid assets.

Refresh behavior:

1. Refresh the asset/dependency catalog when Unreal connects and at a bounded
   interval while connected.
2. Compare fingerprints and deep-index changed Blueprint/animation assets.
3. Deep-index exact assets named by the prompt even when unchanged.
4. Replace an asset's prior graph topology atomically so stale pins and links
   cannot survive a reread.
5. Reload the Unreal-side collector module before refresh so editor Python does
   not execute stale tool code.
6. Remove index rows for deleted assets. Preserve explicit exclusions even if
   Unreal still has an asset loaded or its package remains on disk.

Prompt-visible operations:

- `unreal_semantic_index_refresh`
- `unreal_semantic_index_query`
- `unreal_project_visibility`
- `unreal_semantic_index_exclude`
- `unreal_record_runtime_observation`

Task reasoning loop:

`goal -> task-scoped visibility -> project retrieval -> evidence contract ->
capability resolution -> staged mutation -> compile -> graph readback -> asset
validation -> PIE scenario -> failed invariant diagnosis -> bounded repair`

The loop is limited to three repair attempts per failed invariant. Each retry
must cite a new observation or acquired source; repeating the same mutation is
not a repair. A verified recipe is learned only after capabilities, assets,
compile, graph postconditions, runtime scenarios, and log gates all pass.

### Partial Sight And Add Knowledge

Coverage is task-specific. The system does not need every Blueprint in a large
project deeply indexed when the prompt names two exact targets, but it does need
deep topology for those targets and metadata for every selected animation.

When any required domain is incomplete, the plan must present:

- `add_knowledge_first` (recommended): deepen relevant assets, inspect live
  reflection, retrieve accepted technical sources, or run the missing PIE
  scenario before mutation.
- `run_with_current_knowledge`: create only isolated/removable prototype assets
  and prohibit completion claims until all missing gates pass.

The first 6,000 characters of prompt context must contain visibility, gaps, and
this choice because app prompt paths may truncate later context.

### Evidence Acquisition, Not Hardcoded Mechanics

`AutonomousKnowledgeRetrievalEngine` searches the semantic project index and
local knowledge index using terms derived from the request and failed
assertions. It emits research queries and source acceptance rules. It must not
invent an expert strategy.

A new C++ wrapper is justified only when all are true:

- Live Python reflection cannot expose the required observation or mutation.
- No registered first-party operation satisfies the contract.
- The proposed wrapper can return structured evidence and has a self-test.

Otherwise the tool continues with existing Python/Blueprint capabilities or
adds knowledge. This keeps the reasoning system generic across traversal,
combat, animation, abilities, puzzles, AI, UI, VFX, audio, and future systems.

### Retired Asset Policy

An invalid or obsolete asset is deleted when Unreal confirms post-delete
absence. If Unreal reports contradictory delete state or keeps a package loaded,
the path is explicitly excluded from semantic retrieval with the user's reason.
Transport-valid but context-invalid animation clips are also excluded. A later
full index refresh cannot silently reintroduce excluded paths.

Current project exclusions include the rolled-back empty climbing AnimBlueprint
placeholders and the mislabeled generated climb clip/montages. They are not
evidence for the replacement system.

### Context-Aware Download And Retarget Gate

Before download, each animation role declares motion terms, excluded motions,
posture, direction, loop expectation, root-motion policy, source URL, license,
and target skeleton. HTTPS success alone is only a transport probe.

After download:

1. Store the original file and provenance in the external cache.
2. Import into a user-selected `/Game` destination folder.
3. Let the user select the destination skeleton or skeletal mesh when more than
   one valid target exists.
4. Attempt Unreal import/IK retarget first. If the source cannot be represented
   with enough hierarchy information, use an approved DCC retarget path and
   reimport the result.
5. Verify skeleton compatibility, duration, sample count/rate, root-motion
   policy, montage slot, AnimGraph reachability, compile state, and PIE playback.
6. Reject and exclude the candidate when the observed motion does not satisfy
   its semantic role, even if import and retarget succeeded.

## Runtime QA Report Template

Every executed prompt-built system should report:

1. Affected Assets & Files
2. Modifications Detail
3. Step-by-Step Test Instructions
4. Downstream Impacts

The report must include failed validations plainly. A system is not done until
the graph compiles, the required pins are connected, the assets exist, and the
feature can be tested in the editor with visible behavior.

## C++ To Python Capability Workflow

Use this workflow when Unreal Python cannot expose the runtime/editor behavior
needed for honest validation. Examples include PIE input injection, runtime
montage playback proof, low-level graph mutation not reflected in Python, or
engine subsystems hidden behind C++ APIs.

Required process:

1. Detect the capability gap and mark the prompt plan as capability-pending.
2. Generate a small reflected C++ plugin wrapper with `UFUNCTION(BlueprintCallable,
   CallInEditor)` methods.
3. Write the plugin under either `PROJECT/Plugins/AIStudioBridge` or the selected
   engine's `Engine/Plugins/AIStudioBridge`. Never keep both copies active.
4. Build the source plugin while it is still disabled in the `.uproject`.
5. Confirm the expected module DLL exists in the built/package output.
6. Only then enable the plugin in the `.uproject` descriptor.
7. If the `.uproject` is read-only, clear the read-only attribute before editing
   and preserve the existing plugin entries.
8. Compile the plugin/project with the matching Unreal Engine toolchain.
9. Verify required build prerequisites before claiming compilation can happen.
10. Restart or reload Unreal if required.
11. In Unreal Python, verify the reflected class exists, for example
   `hasattr(unreal, "AIStudioBridgeLibrary")`.
12. Call the reflected function from Python and parse its JSON result.
13. Register the capability so future prompt plans call the wrapper directly.

The descriptor update is transactional: if build, module discovery, or Python
reflection fails, leave the plugin disabled so the editor remains bootable.
Generated `.uplugin` files must set `EnabledByDefault` to `false`, especially at
engine scope; otherwise Unreal can attempt to load a missing module even when
the project descriptor has no plugin entry.

Observed UE 5.8 build prerequisite note:

- On July 19, 2026, this machine's UE 5.8 `UnrealBuildTool.exe` required
  `.NET Microsoft.NETCore.App 10.0.0`.
- Installed runtimes were 3.1.16, 6.0.36, 8.0.15, and 9.0.4.
- Result: UBT could not compile the generated plugin until .NET 10 is installed
  or the editor/engine supplies a compatible build path.
- Use UE's bundled .NET executable when present:
  `Engine/Binaries/ThirdParty/DotNet/10.0/win-x64/dotnet.exe` with
  `Engine/Binaries/DotNET/AutomationTool/AutomationTool.dll`.
- This machine's plugin-only build proved bundled .NET 10 was usable, but MSVC
  14.38 failed while compiling UE's shared editor PCH at
  `ContainerAllocationPolicies.h(843)` with `C7539`.
- UE 5.8 rejects MSVC 14.40 through 14.43 and reports 14.50.35717 as preferred.
  Epic's UE 5.8 setup guide requires Visual Studio 2022 17.14+ or Visual Studio
  2026 for general development; this machine had VS 2022 17.13.6.
- MSVC 14.50 ships with Visual Studio 2026. The official component id is
  `Microsoft.VisualStudio.Component.VC.14.50.18.0.x86.x64`.
- Validate the Microsoft Authenticode signature of any downloaded Visual Studio
  bootstrapper before execution. A short/corrupt bootstrapper is a hard stop;
  use the fixed-version Build Tools link from Microsoft's release-history page.

Machine-readable lifecycle required in the tool:

`source_generated -> prerequisites_verified -> built -> binary_verified -> enabled -> reflected -> self_tested`

`set_unreal_plugin_enabled_transactionally` must refuse enablement until
`diagnose_unreal_cpp_build_environment` reports a single plugin install, bundled
.NET, a supported non-banned compiler, and an existing module DLL. Disabling is
always allowed as a recovery action.

Validation gates:

- Plugin files exist in the project.
- `.uproject` includes `{"Name": "AIStudioBridge", "Enabled": true}`.
- Build tool exists for the project's `EngineAssociation`.
- Required .NET/runtime/compiler prerequisites are installed.
- Build succeeds.
- The expected `UnrealEditor-AIStudioBridge.dll` exists before enablement.
- Unreal Python exposes `unreal.AIStudioBridgeLibrary`.
- Expected wrapper method exists.
- Runtime wrapper returns `ok: true` for the observed system.

Reject success when:

- Plugin source was generated but not enabled.
- Plugin is enabled but not compiled or loaded.
- The wrapper exists but returns only static data for a runtime claim.
- Build prerequisites are missing and the report still says runtime validation
  passed.

### Smart Runtime Inspection Wrappers

The bridge should expose facts Unreal Python cannot reliably observe:

- `InspectAnimationSequence`: skeleton, duration, sample rate, sampled keys, and
  root-motion presence for imported or retargeted clips.
- `InspectCharacterInPIE`: live actor location/velocity, movement mode, gravity
  scale, AnimInstance class, active montage and position, plus explicitly named
  reflected character/AnimInstance properties.
- `InspectAnimBlueprintGraph`: graph/node/pin/link topology.
- `ValidateCharacterMontagesInPIE`: actual `Montage_Play` result and active state.

Future wrappers may add controlled input/action invocation, collision-query
capture, notify receipt, pose-search query state, and network-role snapshots.
Each must return structured evidence and pass its own self-test before the
capability registry advertises it to prompt planning.

## Context-Aware Online Animation Selection

An animation import is not gameplay proof. Every gameplay role must declare a
semantic contract before search or download: required motion terms, useful
supporting terms, excluded motions, loop expectation, root-motion policy, and
expected posture. Candidate title/description/tags must satisfy that contract.

The download pipeline has two distinct modes:

- `probe_only`: proves HTTPS download, provenance, import, and retarget plumbing;
  the clip cannot be assigned to a gameplay role.
- gameplay: requires semantic acceptance before download, then skeleton,
  duration, root-motion, retarget, montage-slot, graph, compile, and PIE checks.

For example, `Samba Dancing.fbx` is a valid transport probe but is rejected for
climb, vault, grapple, slide, and dodge roles even if it imports and retargets.

### Runtime Montage Validation Wrapper

Use this wrapper when static graph validation says montages are wired but the
system still needs proof that the runtime character can play them.

Generated function:

- `UAIStudioBridgeLibrary::ValidateCharacterMontagesInPIE`

Expected Python call after plugin compile/load:

```python
unreal.AIStudioBridgeLibrary.validate_character_montages_in_pie(
    character_class,
    montages,
    "ABP_Manny_Combat",
)
```

Required observations:

- Active PIE world exists.
- Runtime actor of the requested class exists.
- At least one skeletal mesh component has an AnimInstance whose class contains
  the expected AnimBlueprint marker.
- Each montage asset is non-null.
- Each `Montage_Play` call returns a positive duration.
- Each montage is active or playing immediately after play.

This wrapper complements, but does not replace, graph validation. A shippable
animation feature needs both: graph paths from inputs to montage nodes, and
runtime proof that the live AnimInstance can play the required montages.
