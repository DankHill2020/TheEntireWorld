"""Verified Unreal Sound Cue asset authoring operations."""

from __future__ import annotations

import json


def _asset_parts(asset_path):
    """
        Gets the package path and asset name.

    :param asset_path: Unreal content path
    :return: package path and asset name
    """
    value = str(asset_path or "").strip().rstrip("/")
    if not value.startswith("/Game/") or "/" not in value[1:]:
        raise ValueError("Sound Cue asset path must be below /Game: " + value)
    package_path, asset_name = value.rsplit("/", 1)
    if not asset_name:
        raise ValueError("Sound Cue asset name cannot be blank")
    return package_path, asset_name


def inspect_sound_cue(asset_path):
    """
        Inspects a Sound Cue's playable root and referenced Sound Wave.

    :param asset_path: Unreal Sound Cue content path
    :return: JSON Sound Cue structural readback receipt
    """
    import unreal

    cue = unreal.EditorAssetLibrary.load_asset(str(asset_path or ""))
    if cue is None or not isinstance(cue, unreal.SoundCue):
        return json.dumps({
            "ok": False,
            "status": "sound_cue_not_found",
            "asset_path": asset_path,
        }, indent=2)
    first_node = cue.get_editor_property("first_node")
    nodes = []
    visited = set()

    def visit(node, parent_name=""):
        """
            Reads one Sound Cue node and its child topology.

        :param node: Unreal SoundNode instance
        :param parent_name: parent SoundNode object name
        :return: None
        """
        if node is None:
            return
        object_path = str(node.get_path_name())
        if object_path in visited:
            return
        visited.add(object_path)
        node_row = {
            "name": str(node.get_name()),
            "class_path": str(node.get_class().get_path_name()),
            "parent": parent_name,
        }
        if isinstance(node, unreal.SoundNodeWavePlayer):
            try:
                node_row["looping"] = bool(node.get_editor_property("looping"))
            except Exception:
                node_row["looping"] = False
            try:
                wave = node.get_editor_property("sound_wave_asset_ptr")
                node_row["sound_wave"] = (
                    str(wave.get_path_name())
                    if wave and hasattr(wave, "get_path_name")
                    else str(wave or "")
                )
            except Exception:
                node_row["sound_wave"] = ""
        nodes.append(node_row)
        try:
            children = list(node.get_editor_property("child_nodes") or [])
        except Exception:
            children = []
        node_row["child_count"] = len([child for child in children if child is not None])
        for child in children:
            visit(child, node_row["name"])

    visit(first_node)
    row = {
        "ok": first_node is not None,
        "status": "inspected",
        "asset_path": asset_path,
        "class_path": str(cue.get_class().get_path_name()),
        "first_node_class": str(first_node.get_class().get_path_name()) if first_node else "",
        "first_node_name": str(first_node.get_name()) if first_node else "",
        "node_count": len(nodes),
        "nodes": nodes,
    }
    wave_nodes = [node for node in nodes if node["class_path"].endswith("SoundNodeWavePlayer")]
    if wave_nodes:
        row["sound_wave"] = wave_nodes[0].get("sound_wave", "")
        row["looping"] = bool(wave_nodes[0].get("looping"))
    return json.dumps(row, indent=2, default=str)


def create_from_wave(
    asset_path,
    sound_wave_path,
    looping=False,
    volume_multiplier=1.0,
    pitch_multiplier=1.0,
    overwrite=False,
    dry_run=False,
    cleanup_on_failure=True,
):
    """
        Creates a playable Sound Cue from a Sound Wave and verifies its root node.

    :param asset_path: destination Unreal Sound Cue content path
    :param sound_wave_path: source Unreal Sound Wave content path
    :param looping: whether the generated Wave Player loops
    :param volume_multiplier: Sound Cue base volume multiplier
    :param pitch_multiplier: Sound Cue base pitch multiplier
    :param overwrite: whether to replace the exact existing asset
    :param dry_run: whether to validate inputs without mutation
    :param cleanup_on_failure: whether to delete a newly created failed asset
    :return: JSON creation, save, and playable-root readback receipt
    """
    import unreal

    package_path, asset_name = _asset_parts(asset_path)
    volume = float(volume_multiplier)
    pitch = float(pitch_multiplier)
    if volume < 0.0:
        raise ValueError("volume_multiplier cannot be negative")
    if pitch < 0.0:
        raise ValueError("pitch_multiplier cannot be negative")
    wave = unreal.EditorAssetLibrary.load_asset(str(sound_wave_path or ""))
    if wave is None or not isinstance(wave, unreal.SoundWave):
        raise ValueError("Sound Wave asset not found: " + str(sound_wave_path or ""))
    exists_before = bool(unreal.EditorAssetLibrary.does_asset_exist(asset_path))
    if dry_run:
        return json.dumps({
            "ok": True,
            "status": "dry_run",
            "asset_path": asset_path,
            "sound_wave_path": sound_wave_path,
            "exists_before": exists_before,
            "would_overwrite": bool(exists_before and overwrite),
        }, indent=2)
    if exists_before and not overwrite:
        raise ValueError("Sound Cue already exists; set overwrite=True to replace it: " + asset_path)
    if exists_before and overwrite and not unreal.EditorAssetLibrary.delete_asset(asset_path):
        raise RuntimeError("Could not delete exact existing Sound Cue: " + asset_path)

    factory = unreal.SoundCueFactoryNew()
    factory.set_editor_property("initial_sound_waves", [wave])
    cue = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name,
        package_path,
        unreal.SoundCue,
        factory,
    )
    if cue is None:
        raise RuntimeError("Unreal failed to create Sound Cue: " + asset_path)
    try:
        cue.set_editor_property("volume_multiplier", volume)
        cue.set_editor_property("pitch_multiplier", pitch)
        first_node = cue.get_editor_property("first_node")
        if first_node is None or not isinstance(first_node, unreal.SoundNodeWavePlayer):
            raise RuntimeError("Sound Cue factory did not create a Wave Player root")
        first_node.set_editor_property("looping", bool(looping))
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(cue, False))
        inspection = json.loads(inspect_sound_cue(asset_path))
        verified = (
            saved
            and inspection.get("first_node_class") == "/Script/Engine.SoundNodeWavePlayer"
            and bool(inspection.get("looping")) == bool(looping)
        )
        if not verified:
            raise RuntimeError("Sound Cue save/playable-root readback failed")
        return json.dumps({
            "ok": True,
            "status": "sound_cue_created_and_saved",
            "asset_path": asset_path,
            "sound_wave_path": sound_wave_path,
            "saved": saved,
            "inspection": inspection,
            "postconditions": {
                "playable_wave_root": True,
                "looping_matches": True,
                "saved": True,
            },
        }, indent=2, default=str)
    except Exception:
        if cleanup_on_failure and unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            unreal.EditorAssetLibrary.delete_asset(asset_path)
        raise
