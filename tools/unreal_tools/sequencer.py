"""Level Sequence helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def _result(**payload):
    return json.dumps(payload, indent=2, default=str)


def _load_sequence(unreal, sequence_path):
    asset = unreal.EditorAssetLibrary.load_asset(sequence_path)
    if not asset:
        raise ValueError(f"Level Sequence not found: {sequence_path}")
    return asset


def get_tracks(sequence_path):
    import unreal

    sequence = _load_sequence(unreal, sequence_path)
    tracks = []
    try:
        for binding in sequence.get_bindings():
            for track in binding.get_tracks():
                tracks.append({
                    "binding": binding.get_display_name(),
                    "track_name": track.get_display_name(),
                    "track_class": track.get_class().get_name(),
                })
        for track in sequence.get_master_tracks():
            tracks.append({"binding": "", "track_name": track.get_display_name(), "track_class": track.get_class().get_name()})
    except Exception as exc:
        return _result(ok=False, error=str(exc), sequence_path=sequence_path)
    return _result(ok=True, sequence_path=sequence_path, tracks=tracks, count=len(tracks))


def delete_track(sequence_path, track_name, save=True):
    import unreal

    sequence = _load_sequence(unreal, sequence_path)
    target = str(track_name).lower()
    removed = False
    for binding in sequence.get_bindings():
        for track in list(binding.get_tracks()):
            if track.get_display_name().lower() == target:
                removed = bool(binding.remove_track(track)) or removed
    for track in list(sequence.get_master_tracks()):
        if track.get_display_name().lower() == target:
            removed = bool(sequence.remove_master_track(track)) or removed
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)
    return _result(ok=removed, sequence_path=sequence_path, track_name=track_name, removed=removed, saved=bool(save))


def validate_playback(sequence_path="", expected_assets=None, open_sequence=False):
    """Read back a Level Sequence enough to prove it can be validated."""
    import unreal

    expected_assets = list(expected_assets or [])
    if not sequence_path:
        return _result(ok=False, status="sequence_path_required", expected_assets=expected_assets)
    sequence = _load_sequence(unreal, sequence_path)
    tracks = json.loads(get_tracks(sequence_path))
    warnings = []
    if open_sequence:
        try:
            unreal.get_editor_subsystem(unreal.AssetEditorSubsystem).open_editor_for_assets([sequence])
        except Exception as exc:
            warnings.append(f"open_sequence warning: {exc}")
    found_assets = []
    for asset_path in expected_assets:
        try:
            asset = unreal.EditorAssetLibrary.load_asset(str(asset_path))
            found_assets.append({"asset_path": str(asset_path), "exists": bool(asset)})
        except Exception as exc:
            found_assets.append({"asset_path": str(asset_path), "exists": False, "error": str(exc)})
    missing = [item["asset_path"] for item in found_assets if not item.get("exists")]
    return _result(
        ok=bool(tracks.get("ok")) and not missing,
        status="sequence_readback_complete" if not missing else "expected_assets_missing",
        sequence_path=sequence_path,
        tracks=tracks.get("tracks", []),
        track_count=tracks.get("count", 0),
        expected_assets=found_assets,
        warnings=warnings,
    )
