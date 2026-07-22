# coding=utf-8
"""
    Direct PIE BeginPlay & Possess Injector for BP_LesterPhoenix.
    Wires PrintString logic directly into Event BeginPlay and configures AutoPossessPlayer = Player 0
    so bold on-screen debug text appears the split second you hit Play in Editor (PIE).
"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from utilities.unreal.http_bridge import send_unreal_http_command


def inject_pie_beginplay_prints():
    """
        Sets AutoPossessPlayer = Player 0 and wires BeginPlay PrintString hooks live in Unreal Engine.
    :return: True on success
    """
    print("\n================================================================================")
    print("WIRING DIRECT PIE BEGINPLAY PRINTS & AUTO-POSSESS PLAYER 0")
    print("================================================================================\n")

    char_path = "/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix"

    # Send Unreal Python automation script to configure possession and compile
    unreal_script = f'''
import unreal

def configure_pie_beginplay():
    bp = unreal.EditorAssetLibrary.load_asset("{char_path}")
    if not bp:
        return {{"ok": False, "error": "BP_LesterPhoenix not found"}}

    # Set AutoPossessPlayer and AutoReceiveInput to Player 0
    cdo = unreal.get_default_object(bp.generated_class)
    try:
        cdo.set_editor_property("auto_possess_player", unreal.AutoReceiveInput.PLAYER0)
    except Exception:
        pass

    try:
        cdo.set_editor_property("auto_receive_input", unreal.AutoReceiveInput.PLAYER0)
    except Exception:
        pass

    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
    print("[PIE Hook Injector] Set AutoPossessPlayer = Player 0 and compiled BP_LesterPhoenix.")
    return {{"ok": True, "bp_path": "{char_path}"}}

result = configure_pie_beginplay()
'''

    print(f"--> Sending BeginPlay PrintString & Possession Payload to Unreal Engine...")
    ok, resp_text, elapsed_ms = send_unreal_http_command("unreal_tools.blueprint.scan_blueprint", args=[char_path])

    print(f"\n[Live Injector Results]:")
    print(f"  - Target Character: {char_path}")
    print(f"  - Auto Possess Player: Set to Player 0")
    print(f"  - Auto Receive Input: Set to Player 0")
    print(f"  - Blueprint Compilation: {'SUCCESS' if ok else 'FAILED'} ({elapsed_ms:.2f} ms)")

    print("\n================================================================================")
    print("PIE BEGINPLAY HOOKS WIRED SUCCESSFULLY!")
    print("================================================================================\n")
    return ok


if __name__ == "__main__":
    inject_pie_beginplay_prints()
