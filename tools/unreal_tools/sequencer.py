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
        for track in sequence.get_tracks():
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
    for track in list(sequence.get_tracks()):
        if track.get_display_name().lower() == target:
            removed = bool(sequence.remove_track(track)) or removed
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


def create_float_track(
    sequence_path,
    track_name,
    keys,
    display_rate=30,
    replace_existing=True,
    save=True,
):
    """
        Creates a keyed master float track in a Level Sequence.
    :param sequence_path: Unreal Level Sequence content path
    :param track_name: display name for the float track
    :param keys: frame/value pairs
    :param display_rate: display frames per second
    :param replace_existing: whether to replace tracks with the same display name
    :param save: whether to save the sequence package
    :return: JSON authoring and key readback receipt
    """
    import unreal

    sequence = _load_sequence(unreal, sequence_path)
    rows = []
    for item in list(keys or []):
        if isinstance(item, dict):
            frame = int(item.get("frame", 0))
            value = float(item.get("value", 0.0))
        else:
            frame, value = int(item[0]), float(item[1])
        rows.append((frame, value))
    if not rows:
        raise ValueError("At least one Sequencer key is required")
    rows.sort(key=lambda item: item[0])
    if rows[0][0] < 0:
        raise ValueError("Sequencer key frames cannot be negative")

    target = str(track_name or "Float Track").strip() or "Float Track"
    existing = [
        track for track in list(sequence.get_tracks())
        if isinstance(track, unreal.MovieSceneFloatTrack)
        and str(track.get_display_name()).casefold() == target.casefold()
    ]
    if existing and not replace_existing:
        raise ValueError("Float track already exists: " + target)
    sequence.modify()
    for track in existing:
        sequence.remove_track(track)

    track = None
    try:
        rate = max(1, int(display_rate))
        end_frame = rows[-1][0]
        unreal.MovieSceneSequenceExtensions.set_display_rate(sequence, unreal.FrameRate(rate, 1))
        unreal.MovieSceneSequenceExtensions.set_playback_start(sequence, rows[0][0])
        unreal.MovieSceneSequenceExtensions.set_playback_end(sequence, end_frame + 1)
        track = sequence.add_track(unreal.MovieSceneFloatTrack)
        if track is None:
            raise RuntimeError("Unreal did not create a MovieSceneFloatTrack")
        track.set_display_name(target)
        section = track.add_section()
        if section is None:
            raise RuntimeError("Unreal did not create a float track section")
        unreal.MovieSceneSectionExtensions.set_range(section, rows[0][0], end_frame + 1)
        channels = list(unreal.MovieSceneSectionExtensions.get_all_channels(section))
        if len(channels) != 1 or not isinstance(channels[0], unreal.MovieSceneScriptingFloatChannel):
            raise RuntimeError("Float section did not expose exactly one scripting float channel")
        channel = channels[0]
        for frame, value in rows:
            channel.add_key(
                unreal.FrameNumber(frame),
                value,
                interpolation=unreal.MovieSceneKeyInterpolation.LINEAR,
            )
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)) if save else False
        key_rows = []
        for key in channel.get_keys():
            time = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
            key_rows.append({
                "frame": int(time.frame_number.value),
                "sub_frame": float(time.sub_frame),
                "value": float(key.get_value()),
                "interpolation": str(key.get_interpolation_mode()),
            })
        return _result(
            ok=bool(len(key_rows) == len(rows) and (saved or not save)),
            status="authored_and_saved" if saved else "authored",
            sequence_path=sequence_path,
            track_name=target,
            display_rate=rate,
            playback_range=[rows[0][0], end_frame + 1],
            key_count=len(key_rows),
            keys=key_rows,
            saved=saved,
        )
    except Exception:
        if track is not None:
            sequence.remove_track(track)
            if save:
                unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)
        raise


def _camera_key_rows(camera_spec):
    """
        Normalizes one camera's transform keys.

    :param camera_spec: camera specification containing transform keys
    :return: sorted camera transform key rows
    """
    rows = []
    for item in list(camera_spec.get("keys") or []):
        if not isinstance(item, dict):
            raise ValueError("Camera keys must be objects")
        location = list(item.get("location") or (0.0, 0.0, 0.0))
        rotation = list(item.get("rotation") or (0.0, 0.0, 0.0))
        if len(location) != 3 or len(rotation) != 3:
            raise ValueError("Camera key location and rotation must contain three values")
        rows.append({
            "frame": int(item.get("frame", camera_spec.get("start_frame", 0))),
            "location": [float(value) for value in location],
            "rotation": [float(value) for value in rotation],
        })
    if not rows:
        rows.append({
            "frame": int(camera_spec.get("start_frame", 0)),
            "location": [float(value) for value in list(camera_spec.get("location") or (0.0, 0.0, 100.0))],
            "rotation": [float(value) for value in list(camera_spec.get("rotation") or (0.0, 0.0, 0.0))],
        })
    rows.sort(key=lambda row: row["frame"])
    if rows[0]["frame"] < 0:
        raise ValueError("Camera key frames cannot be negative")
    return rows


def author_camera_cuts(
    sequence_path,
    cameras,
    display_rate=30,
    replace_existing=False,
    save=True,
):
    """
        Authors spawnable cinematic cameras, transform keys, and camera cuts.

    :param sequence_path: Unreal Level Sequence content path
    :param cameras: ordered camera specifications with names, ranges, and transform keys
    :param display_rate: display frames per second
    :param replace_existing: whether to replace existing camera cuts and same-named bindings
    :param save: whether to save the sequence package
    :return: JSON authoring and structural readback receipt
    """
    import unreal

    specs = []
    names = set()
    for index, raw_spec in enumerate(list(cameras or [])):
        if not isinstance(raw_spec, dict):
            raise ValueError("Camera specifications must be objects")
        spec = dict(raw_spec)
        name = str(spec.get("name") or f"Camera_{index + 1:02d}").strip()
        if not name:
            raise ValueError("Camera names cannot be blank")
        folded_name = name.casefold()
        if folded_name in names:
            raise ValueError("Camera names must be unique: " + name)
        names.add(folded_name)
        keys = _camera_key_rows(spec)
        start_frame = int(spec.get("start_frame", keys[0]["frame"]))
        end_frame = int(spec.get("end_frame", keys[-1]["frame"] + 1))
        if start_frame < 0 or end_frame <= start_frame:
            raise ValueError(f"Invalid camera range for {name}: [{start_frame}, {end_frame})")
        if keys[0]["frame"] < start_frame or keys[-1]["frame"] >= end_frame:
            raise ValueError(f"Camera keys for {name} must fall inside its cut range")
        specs.append({
            "name": name,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "keys": keys,
        })
    if not specs:
        raise ValueError("At least one camera specification is required")
    specs.sort(key=lambda row: (row["start_frame"], row["end_frame"]))
    for previous, current in zip(specs, specs[1:]):
        if current["start_frame"] < previous["end_frame"]:
            raise ValueError(
                f"Camera cut ranges overlap: {previous['name']} and {current['name']}"
            )

    sequence = _load_sequence(unreal, sequence_path)
    existing_cut_tracks = [
        track for track in list(sequence.get_tracks())
        if isinstance(track, unreal.MovieSceneCameraCutTrack)
    ]
    existing_bindings = [
        binding for binding in list(sequence.get_bindings())
        if str(binding.get_display_name()).casefold() in names
    ]
    if (existing_cut_tracks or existing_bindings) and not replace_existing:
        raise ValueError(
            "Sequence already contains camera cuts or same-named bindings; "
            "set replace_existing=True to replace them"
        )

    sequence.modify()
    if replace_existing:
        for track in existing_cut_tracks:
            sequence.remove_track(track)
        for binding in existing_bindings:
            binding.remove()

    created_bindings = []
    cut_track = None
    try:
        rate = max(1, int(display_rate))
        playback_start = specs[0]["start_frame"]
        playback_end = max(spec["end_frame"] for spec in specs)
        unreal.MovieSceneSequenceExtensions.set_display_rate(
            sequence, unreal.FrameRate(rate, 1)
        )
        unreal.MovieSceneSequenceExtensions.set_playback_start(sequence, playback_start)
        unreal.MovieSceneSequenceExtensions.set_playback_end(sequence, playback_end)

        cut_track = sequence.add_track(unreal.MovieSceneCameraCutTrack)
        if cut_track is None:
            raise RuntimeError("Unreal did not create a camera cut track")

        camera_receipts = []
        for spec in specs:
            binding = sequence.add_spawnable_from_class(unreal.CineCameraActor)
            if binding is None:
                raise RuntimeError("Unreal did not create CineCameraActor spawnable: " + spec["name"])
            created_bindings.append(binding)
            binding.set_display_name(spec["name"])

            transform_track = binding.add_track(unreal.MovieScene3DTransformTrack)
            if transform_track is None:
                raise RuntimeError("Unreal did not create camera transform track")
            transform_track.set_display_name("Transform")
            transform_section = transform_track.add_section()
            if transform_section is None:
                raise RuntimeError("Unreal did not create camera transform section")
            unreal.MovieSceneSectionExtensions.set_range(
                transform_section, spec["start_frame"], spec["end_frame"]
            )
            channels = list(
                unreal.MovieSceneSectionExtensions.get_all_channels(transform_section)
            )
            channel_map = {
                str(channel.get_name()).split("_", 1)[0]: channel
                for channel in channels
            }
            required_channels = (
                "Location.X", "Location.Y", "Location.Z",
                "Rotation.X", "Rotation.Y", "Rotation.Z",
            )
            missing_channels = [name for name in required_channels if name not in channel_map]
            if missing_channels:
                raise RuntimeError(
                    "Transform section is missing channels: " + ", ".join(missing_channels)
                )
            for key in spec["keys"]:
                frame = unreal.FrameNumber(key["frame"])
                values = key["location"] + key["rotation"]
                for channel_name, value in zip(required_channels, values):
                    channel_map[channel_name].add_key(
                        frame,
                        value,
                        interpolation=unreal.MovieSceneKeyInterpolation.LINEAR,
                    )

            cut_section = cut_track.add_section()
            if cut_section is None:
                raise RuntimeError("Unreal did not create camera cut section")
            unreal.MovieSceneSectionExtensions.set_range(
                cut_section, spec["start_frame"], spec["end_frame"]
            )
            cut_section.set_camera_binding_id(sequence.get_binding_id(binding))
            camera_receipts.append({
                "name": spec["name"],
                "binding_id": str(binding.get_id()),
                "cut_range": [spec["start_frame"], spec["end_frame"]],
                "transform_key_count": len(spec["keys"]),
                "channel_key_counts": {
                    name: int(channel_map[name].get_num_keys())
                    for name in required_channels
                },
            })

        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)) if save else False
        cut_sections = list(cut_track.get_sections())
        verified = (
            len(camera_receipts) == len(specs)
            and len(cut_sections) == len(specs)
            and all(
                all(count == receipt["transform_key_count"] for count in receipt["channel_key_counts"].values())
                for receipt in camera_receipts
            )
            and (saved or not save)
        )
        if not verified:
            raise RuntimeError("Camera-cut graph failed structural save/readback verification")
        return _result(
            ok=True,
            status="camera_cuts_authored_and_saved" if saved else "camera_cuts_authored",
            sequence_path=sequence_path,
            display_rate=rate,
            playback_range=[playback_start, playback_end],
            camera_count=len(camera_receipts),
            cut_count=len(cut_sections),
            cameras=camera_receipts,
            saved=saved,
        )
    except Exception:
        if cut_track is not None:
            sequence.remove_track(cut_track)
        for binding in created_bindings:
            binding.remove()
        if save:
            unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)
        raise
