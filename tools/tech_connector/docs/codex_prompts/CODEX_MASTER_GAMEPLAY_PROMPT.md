# Standalone Codex System Generation Prompt

This request is governed by
[`UNREAL_GAMEPLAY_PROOF_AND_KNOWLEDGE_POLICY.md`](UNREAL_GAMEPLAY_PROOF_AND_KNOWLEDGE_POLICY.md).
The requirements below are requested behavior, not evidence of a valid
architecture. Resolve them against the live project, compare known techniques
with current evidence, and never report the system complete until the policy's
Level 1-6 proof and reusable-system gates pass.

```text
Build a 100% playable Master Traversal and Combat System for Unreal Engine 5 satisfying the following requirements:

1. Target Assets & Skeleton:
   - Character Blueprint: `/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix`
   - AnimBlueprint: `/Game/Variant_Combat/Anims/ABP_Manny_Combat`
   - Target Skeleton: UE5 Manny Skeleton (`/Game/Characters/Mannequins/Meshes/SKM_Manny`)

2. Conflict-Free Keybindings:
   - Any-Wall Climbing: Bind to `N` key (Preserve `E` key for Interact). Perform capsule trace across WorldStatic, WorldDynamic, PhysicsBody. Set MovementMode = MOVE_Flying, GravityScale = 0.0.
   - Grappling Hook Zip: Bind to `G` key (Preserve `F` key for Viewport Focus). Fire 2,500 cm forward trace and execute LaunchCharacter(LaunchVelocity, bXYOverride=True, bZOverride=True).
   - Parkour Vault & Slide: Bind to `Space` key. Vault over waist-high obstacles; execute ground slide while sprinting.
   - Combat Dodge Roll: Bind to `C` key. Perform directional Dodge Roll with invulnerability frames.

3. Visual K2 Graph Pin Wiring (No Manual Steps):
   - Use `unreal.AssetEditorSubsystem` to open `BP_LesterPhoenix` in Unreal Editor memory.
   - Use `unreal.BlueprintGraphEditor.create_node_from_name` to place Event BeginPlay, InputKey N, InputKey G, InputKey Space, InputKey C, and PrintString nodes.
   - Execute `src_pin.make_link_to(dst_pin)` to physically draw execution wires between events, PrintString, and LaunchCharacter.
   - Set AutoPossessPlayer = Player 0 and AutoReceiveInput = Player 0.
   - Save modified assets to disk using `unreal.EditorAssetLibrary.save_loaded_asset`.

4. AnimGraph Output Pose Wiring & FBX Animation Ingestion:
   - Connect State Machine pose pins into AnimGraph `Output Pose` in `ABP_Manny_Combat`.
   - Wire `BlueprintUpdateAnimation` to update bIsClimbing, bIsVaulting, bIsGrappling, bIsDodgeRolling every frame.
   - Audit clips against UE5 Manny Skeleton (`SKM_Manny`). Stream-download reference `.fbx` skeletal animation clips over HTTPS on the fly if missing.

5. System Impact & QA Report Output:
   - Return a 4-section report detailing: 1) Affected Assets & Files, 2) Modifications Detail, 3) Step-by-Step Test Instructions, and 4) Downstream Impacts.
```
