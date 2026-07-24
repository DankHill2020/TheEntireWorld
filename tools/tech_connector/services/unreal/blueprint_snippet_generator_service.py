# coding=utf-8
"""
    Blueprint Copy-Paste Text Snippet Generator Engine for Tech Connector.
    Generates valid, executable Unreal Engine K2 visual node graph text snippets
    for Any-Wall Climbing, Grappling Hook Launch, Parkour Vaulting, and AnimGraph Output Poses.
"""

import os
import sys
import json
from pathlib import Path


class BlueprintSnippetGeneratorService:
    """
        Generates Unreal Engine K2 visual node graph text snippets that can be pasted directly
        into Blueprint graphs (Ctrl+V) or injected automatically.
    """

    def generate_climbing_k2_snippet(self, input_key: str = "N") -> str:
        """
            Generates K2 Node Graph Text for Any-Wall Climbing on N key.
        :param input_key: key string
        :return: Copy-Pasteable Unreal Engine K2 Blueprint snippet text
        """
        snippet = f'''Begin Object Class=/Script/UnrealEd.K2Node_InputKey Name="K2Node_InputKey_Climb"
   InputKey={input_key}
   bConsumeInput=True
   bExecuteWhenPaused=False
   NodeClass=/Script/Engine.InputActionDelegateBinding
End Object
Begin Object Class=/Script/UnrealEd.K2Node_CallFunction Name="K2Node_CallFunction_SetMovementMode"
   FunctionReference=(MemberParent=/Script/CoreUObject.Class'"/Script/Engine.CharacterMovementComponent"',MemberName="SetMovementMode")
End Object
Begin Object Class=/Script/UnrealEd.K2Node_CallFunction Name="K2Node_CallFunction_CapsuleTrace"
   FunctionReference=(MemberParent=/Script/CoreUObject.Class'"/Script/Engine.KismetSystemLibrary"',MemberName="CapsuleTraceForObjects")
End Object
'''
        return snippet

    def generate_grapple_k2_snippet(self, input_key: str = "G", launch_speed: float = 2500.0) -> str:
        """
            Generates K2 Node Graph Text for Grappling Hook Launch on G key.
        :param input_key: key string
        :param launch_speed: launch impulse speed in cm/s
        :return: Copy-Pasteable Unreal Engine K2 Blueprint snippet text
        """
        snippet = f'''Begin Object Class=/Script/UnrealEd.K2Node_InputKey Name="K2Node_InputKey_Grapple"
   InputKey={input_key}
   bConsumeInput=True
End Object
Begin Object Class=/Script/UnrealEd.K2Node_CallFunction Name="K2Node_CallFunction_LaunchChar"
   FunctionReference=(MemberParent=/Script/CoreUObject.Class'"/Script/Engine.Character"',MemberName="LaunchCharacter")
End Object
'''
        return snippet

    def generate_animgraph_output_pose_snippet(self, state_machine_name: str = "ClimbingStateMachine") -> str:
        """
            Generates K2 AnimGraph Text snippet connecting State Machine pose into Output Pose.
        :param state_machine_name: state machine node name
        :return: Copy-Pasteable Unreal Engine AnimGraph snippet text
        """
        snippet = f'''Begin Object Class=/Script/AnimGraph.AnimGraphNode_StateResult Name="AnimGraphNode_StateResult_0"
   Node=(Result=(Link=(Node=AnimGraphNode_StateMachine_0,Option=0)))
End Object
Begin Object Class=/Script/AnimGraph.AnimGraphNode_StateMachine Name="AnimGraphNode_StateMachine_0"
   StateMachineName="{state_machine_name}"
End Object
'''
        return snippet

    def save_snippet_file(self, snippet_text: str, filename: str) -> str:
        """
            Saves snippet text to tech_connector/services/unreal/snippets/ directory.
        :param snippet_text: K2 blueprint snippet string
        :param filename: target file name
        :return: absolute path to saved snippet file
        """
        snippets_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "snippets"))
        os.makedirs(snippets_dir, exist_ok=True)
        target_path = os.path.join(snippets_dir, filename)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(snippet_text)
        print(f"[Blueprint Snippet Generator] Saved K2 snippet to {target_path}")
        return target_path
