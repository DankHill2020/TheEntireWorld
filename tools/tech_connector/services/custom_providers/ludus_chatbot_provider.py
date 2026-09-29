"""Mock Ludus Chatbot/Reasoning Provider streaming realistic context-sensitive Ludus sessions."""

from __future__ import annotations

import time
from typing import Callable, List


def generate_chat_response(prompt: str, history: List[dict], on_chunk: Callable[[str], None]) -> str:
    """Simulate a real, project-aware Ludus session based on keywords in the prompt."""
    
    normalized_prompt = str(prompt or "").lower()
    
    # 1. Crawling animation system in ABP Combat
    if "crawl" in normalized_prompt or "abp combat" in normalized_prompt:
        chunks = [
            "\nASSISTANT [Ludus AI]:\n",
            "\nThought for 1 second\n"
            "I'll start by exploring the project to understand what's available. "
            "Let me find the ABP Combat blueprint and any relevant animation assets.\n",
            
            "\nSearched for assets\n/Game\n",
            "\nListed project tree\n/Game\n",
            
            "\nThought for 3 seconds\n"
            "Good, I found two combat ABPs. Let me read both to determine which is the main one, "
            "and simultaneously check the Animation/Combat folder for existing assets.\n",
            
            "\nLoaded blueprint\nABP_Manny_Combat\n",
            "\nLoaded blueprint\nABP_CombatSystem\n",
            "\nSearched for assets\n/Game\n",
            
            "\nThought for 5 seconds\n"
            "ABP_Manny_Combat is clearly the main one. Let me read it in detail and check the skeleton it uses.\n",
            
            "\nLoaded blueprint\nABP_Manny_Combat\n",
            
            "\nThought for 45 seconds\n"
            "Excellent - I have a thorough picture of the ABP. Let me now check what character blueprints "
            "exist to understand the full picture before planning.\n",
            
            "\nSearched for assets\n/Game\n",
            
            "\nThought for 0 seconds\n"
            "Found BP_CombatCharacter. Let me check its overview quickly.\n",
            
            "\nLoaded blueprint\nBP_CombatCharacter\n",
            
            "\nRunning Agent Task\n",
            "\nThought process\n",
            
            "\nThought for 1 second\n"
            "Loaded blueprint\n"
            "BP_CombatCharacter\n",
            
            "\nRunning Agent Task\n",
            "\nThought process\n",
            
            "\nThought for 1 second\n"
            "Loaded blueprint\n"
            "BP_CombatCharacter\n",
            
            "\nRunning Agent Task\n",
            "\nThought for 0 seconds\n",
            
            "\nThought for 17 seconds\n"
            "I now have a complete picture of the system. Here's the full plan before I execute anything:\n\n"
            "[Plan] Crawling Animation System - Proposed Plan\n\n"
            "### What I found\n"
            "- **Target ABP:** `ABP_Manny_Combat` - has a Locomotion state machine (Idle <-> Walk/Run) and a Main States machine (Locomotion, Jump, Fall Loop, Land)\n"
            "- **Character BP:** `BP_CombatCharacter` - no `bIsCrawling` variable yet\n"
            "- **Crawl animations:** None exist in the project - will use `MM_Idle` and `BS_Idle_Walk_Run` as placeholders (you can swap them for real crawl anims later)\n\n"
            "### What will be built\n"
            "* **Step 1 - Add bIsCrawling to BP_CombatCharacter**\n"
            "  Add a `bIsCrawling` bool variable so the ABP can read it. You can toggle this from any input/gameplay logic.\n\n"
            "* **Step 2 - Add bIsCrawling variable to ABP_Manny_Combat**\n"
            "  New bool variable that gets synced from the character each frame.\n\n"
            "* **Step 3 - Wire ABP EventGraph**\n"
            "  In the Update Animation event, cast the stored Character to `BP_CombatCharacter` and read `bIsCrawling` into the ABP variable.\n\n"
            "* **Step 4 - Add Crawl states to the Locomotion SM**\n"
            "  Two new states inside the existing Locomotion state machine:\n"
            "  - **Crawl Idle** - plays `MM_Idle` looping (placeholder)\n"
            "  - **Crawl Move** - plays `BS_Idle_Walk_Run` driven by Direction/GroundSpeed (placeholder)\n\n"
            "* **Step 5 - Wire all transitions**\n\n"
            "| From | To | Condition |\n"
            "| :--- | :--- | :--- |\n"
            "| Idle | Crawl Idle | `bIsCrawling == true` |\n"
            "| Walk/Run | Crawl Move | `bIsCrawling == true` |\n"
            "| Crawl Idle | Idle | `bIsCrawling == false` |\n"
            "| Crawl Move | Walk/Run | `bIsCrawling == false` |\n"
            "| Crawl Idle | Crawl Move | `ShouldMove == true` |\n"
            "| Crawl Move | Crawl Idle | `ShouldMove == false` |\n\n"
            "> [Warning] **Note:** The crawl animation placeholders (`MM_Idle` / `BS_Idle_Walk_Run`) will visually work identically to the standing versions until you replace them with real crawling sequences. The system structure will be fully ready.\n\n"
            "> [Manual Step] **Manual step required:** After execution, you'll need to set `bIsCrawling = true` on `BP_CombatCharacter` from your input/gameplay code (e.g., a crouch key or ability trigger) to activate the crawl state.\n\n"
            "Shall I proceed with this plan? Or would you like to adjust anything (e.g., keep crawling entirely within the ABP driven by a crouching flag instead)?\n"
        ]
        
    # 2. Default: Animation rewind bug resolution
    else:
        chunks = [
            "\nASSISTANT [Ludus AI]:\n",
            "\n[Thought Process]\n"
            "The user wants to resolve the enemy animation rewind issue where Ability 3 does not "
            "properly rewind the animation snapshots of enemies. I need to explore the project "
            "and find the relevant rewind and enemy blueprints.\n",
            
            "\n[Action] Took a screenshot of the viewport scene.\n",
            "[Action] Listed project tree under /Game.\n",
            
            "\n[Thought Process]\n"
            "I see this is the 'Time_Fighters' project. The relevant assets appear to be:\n"
            " - BP_AbilityTargetRewind (Ability 3)\n"
            " - BP_TestEnemy / BP_CombatEnemy\n"
            " - BPI_AnimRewindable (Interface for animation rewinding)\n"
            " - BP_TimeAffectedComponent (Handles rewind logic on enemies)\n"
            "Let me load these blueprints to inspect their implementation.\n",
            
            "\n[Action] Loaded blueprint: BP_TimeTargetComponent\n",
            "[Action] Loaded blueprint: BP_AbilityTargetRewind\n",
            "[Action] Loaded blueprint: BPI_AnimRewindable\n",
            
            "\n[Thought Process]\n"
            "The ability triggers the rewind, but we need to see how the enemy component captures "
            "and applies the animation snapshots. Let's load BP_TimeAffectedComponent and the combat enemy.\n",
            
            "\n[Action] Loaded blueprint: BP_TimeAffectedComponent\n",
            "[Action] Loaded blueprint: BP_CombatEnemy\n",
            "[Action] Loaded blueprint: ABP_Manny_Combat\n",
            
            "\n[Thought Process]\n"
            "I have diagnosed the root causes of the animation snapshot failure:\n\n"
            "1. Bug 1 (Invalid Snapshots): In BP_TimeAffectedComponent, the PoseSnapshot is added to the "
            "PoseHistory array, and then updated by-ref. However, modifying a Get(a ref) array element "
            "in Blueprints does not reliably write back into the array, so bIsValid remains false for all frames.\n"
            "2. Bug 2 (Hardcoded Cast): The component cast-pushes to ABP_Manny_Combat. If any other ABP is "
            "used, it fails. We should use the BPI_AnimRewindable interface instead.\n"
            "3. Bug 3 (Event Name Mismatch): ABP_Manny_Combat implements TickAnimRewind_1 instead of the "
            "clean TickAnimRewind name, causing the message call to drop.\n\n"
            "I will apply the fixes: update array storage to use a SnapshotBuffer staging variable, "
            "replace the casts with interface message dispatches, and correct the event names in the ABP.\n",
            
            "\n[Action] Editing Blueprint: BP_TimeAffectedComponent...\n",
            "[Action] Linked nodes: linked SnapshotBuffer variable -> Array Add -> TickAnimRewind message.\n",
            "[Action] Editing Animation Blueprint: ABP_Manny_Combat...\n",
            "[Action] Renamed custom events TickAnimRewind_1 and EndAnimRewind_1 to match interface.\n",
            
            "\n[Action] Compiled BP_TimeAffectedComponent successfully.\n",
            "[Action] Compiled ABP_Manny_Combat successfully.\n",
            
            "\n[Ludus AI] Implementation complete. The animation snapshot history will now record correctly "
            "via the SnapshotBuffer and push frames synchronously to the ABP during rewind without race conditions. "
            "You can now play in editor and test Ability 3 on the target dummy!"
        ]

    full_response = ""
    for chunk in chunks:
        on_chunk(chunk)
        full_response += chunk
        time.sleep(0.3)  # Slightly faster stream for testing

    return full_response
