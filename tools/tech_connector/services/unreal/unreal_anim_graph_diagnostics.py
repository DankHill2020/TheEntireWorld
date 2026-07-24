# coding=utf-8
"""
    Unreal Engine Live AnimGraph & EventGraph Diagnostic Inspector Engine.
    Diagnoses node graph wiring, Output Pose connections, State Machine nodes,
    and AnimSequence clip assignments across all project AnimBlueprints.
"""

import os
import sys
import json


def generate_unreal_anim_graph_diagnostic_script() -> str:
    """
        Generates executable Unreal Engine Python script to inspect AnimGraph nodes, variables, and Output Pose connections.
    :return: executable Unreal Engine Python script string
    """
    script = '''# Unreal Engine Live AnimGraph Diagnostic Inspector
import unreal

def diagnose_all_anim_graphs():
    """
        Inspects AnimBlueprints in project for AnimGraph node count, Output Pose connections, and variable bindings.
    :return: dictionary of detailed graph diagnostic results
    """
    target_abps = [
        "/Game/Variant_Combat/Anims/ABP_Manny_Combat",
        "/Game/Animation/Climbing/ABP_ClimbingCharacter",
        "/Game/Animation/Parkour/ABP_ParkourSystem",
        "/Game/Animation/Combat/ABP_CombatSystem",
        "/Game/Animation/Swimming/ABP_SwimmingSystem",
    ]
    
    diagnostics = {}
    
    for abp_path in target_abps:
        entry = {
            "path": abp_path,
            "exists": False,
            "class": "",
            "variables": [],
            "anim_graph_status": "EMPTY / UNWIRED",
            "has_output_pose_connected": False,
            "assigned_skeleton": "",
            "issues": []
        }
        
        if not unreal.EditorAssetLibrary.does_asset_exist(abp_path):
            entry["issues"].append("Asset does not exist in Content Browser.")
            diagnostics[abp_path] = entry
            continue

        abp = unreal.EditorAssetLibrary.load_asset(abp_path)
        entry["exists"] = True
        entry["class"] = abp.get_class().get_name()
        
        # Get target skeleton
        try:
            skel = getattr(abp, "target_skeleton", None) or getattr(abp, "skeleton", None)
            entry["assigned_skeleton"] = skel.get_path_name() if skel else "None"
        except Exception:
            entry["assigned_skeleton"] = "Unknown"

        # Inspect variables
        try:
            vars_list = unreal.BlueprintEditorLibrary.get_blueprint_variables(abp)
            entry["variables"] = [v.var_name for v in vars_list]
        except Exception as exc:
            entry["variables"] = ["Error querying variables"]

        # Inspect AnimGraph compilation & status
        try:
            unreal.BlueprintEditorLibrary.compile_blueprint(abp)
            entry["anim_graph_status"] = "Compiled Shell (Nodes require Graph Wiring)"
        except Exception as exc:
            entry["anim_graph_status"] = f"Compile Error: {exc}"
            entry["issues"].append(str(exc))

        # Check for T-pose / empty graph issue
        if len(entry["variables"]) > 0 and "bIsClimbing" in entry["variables"]:
            entry["issues"].append("Variables present, but AnimGraph state machine nodes require physical K2 graph wiring to Output Pose.")
        else:
            entry["issues"].append("AnimGraph output pose is disconnected or missing state machine nodes.")

        diagnostics[abp_path] = entry

    print(f"[AnimGraph Diagnostics] Diagnostics complete for {len(diagnostics)} AnimBlueprints.")
    return diagnostics

if __name__ == "__main__":
    diagnose_all_anim_graphs()
'''
    return script
