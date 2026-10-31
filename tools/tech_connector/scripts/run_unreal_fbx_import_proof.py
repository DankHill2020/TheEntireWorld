"""Safely import an animation-only FBX into Unreal and save proof JSON.

Uses a hidden full-editor Python session. On UE 5.7 the faster Python
commandlet can crash inside Slate after Interchange has saved the asset.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editor", type=Path, required=True,
                        help="Absolute path to UnrealEditor-Cmd.exe")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--animation-fbx", type=Path, required=True)
    parser.add_argument("--skeleton-asset-path", required=True)
    parser.add_argument("--destination-path", required=True)
    parser.add_argument("--asset-name", required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--required-bone", action="append", default=[])
    parser.add_argument("--moving-bone", action="append", default=[],
                        help="Require sampled nonconstant motion on this saved AnimSequence bone")
    parser.add_argument("--minimum-motion-translation", type=float, default=0.1)
    parser.add_argument("--minimum-motion-rotation-degrees", type=float, default=1.0)
    parser.add_argument("--minimum-track-count", type=int, default=1)
    parser.add_argument("--minimum-frame-count", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--reopen-commandlet-timeout", type=int, default=45,
                        help="Seconds before using the full-editor reopen fallback")
    return parser


def _config(args: argparse.Namespace) -> dict:
    for name in ("editor", "project", "animation_fbx"):
        path = getattr(args, name).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"{name} does not exist: {path}")
    if args.animation_fbx.suffix.lower() != ".fbx":
        raise ValueError("Animation source must be .fbx")
    if args.project.suffix.lower() != ".uproject":
        raise ValueError("Unreal project must be .uproject")
    if not args.destination_path.startswith("/Game/") or ".." in args.destination_path:
        raise ValueError("Destination must be a /Game path without '..'")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.asset_name):
        raise ValueError("Asset name must be an Unreal-safe identifier")
    if not args.skeleton_asset_path.startswith("/Game/"):
        raise ValueError("Skeleton must be a project asset")
    report = args.report_json.expanduser().resolve()
    if report in {args.editor.resolve(), args.project.resolve(), args.animation_fbx.resolve()}:
        raise ValueError("Report path aliases an input")
    if report.exists():
        raise FileExistsError(f"Refusing to overwrite proof report: {report}")
    if (args.minimum_track_count < 1 or args.minimum_frame_count < 1
            or args.timeout < 1 or args.reopen_commandlet_timeout < 1
            or args.minimum_motion_translation <= 0
            or args.minimum_motion_rotation_degrees <= 0):
        raise ValueError("Minimum counts and timeout must be positive")
    return {
        "animation_fbx": str(args.animation_fbx.resolve()),
        "skeleton_asset_path": args.skeleton_asset_path,
        "destination_path": args.destination_path.rstrip("/"),
        "asset_name": args.asset_name,
        "report_json": str(report),
        "required_bones": sorted(set(args.required_bone)),
        "motion_bones": sorted(set(args.moving_bone)),
        "minimum_motion_translation": args.minimum_motion_translation,
        "minimum_motion_rotation_degrees": args.minimum_motion_rotation_degrees,
        "minimum_track_count": args.minimum_track_count,
        "minimum_frame_count": args.minimum_frame_count,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = _config(args)
    script = Path(__file__).with_name("unreal_import_animation_in_editor.py").resolve()
    cache = args.cache_dir.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    report_path = Path(config["report_json"])
    receipt_prefix = f"unreal_animation_{uuid4().hex}"
    import_receipt = cache / f"{receipt_prefix}_import.json"
    reopen_receipt = cache / f"{receipt_prefix}_reopen.json"
    config["report_json"] = str(import_receipt)
    command = [
        str(args.editor.resolve()), str(args.project.resolve()),
        f"-ExecutePythonScript={script}",
        "-unattended", "-nop4", "-nosplash", "-nullrhi", "-RenderOffscreen",
        "-ddc=InstalledNoZenLocalFallback",
        f"-LocalDataCachePath={cache / 'DDC'}",
        f"-ZenDataPath={cache / 'Zen'}",
    ]
    environment = os.environ.copy()
    environment["TC_UNREAL_IMPORT_CONFIG_JSON"] = json.dumps(config)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        command, env=environment, cwd=str(args.project.resolve().parent),
        capture_output=True, text=True, timeout=args.timeout, creationflags=flags,
        check=False,
    )
    if completed.returncode != 0 or not import_receipt.is_file():
        tail = "\n".join((completed.stdout + "\n" + completed.stderr).splitlines()[-20:])
        raise RuntimeError(
            f"Unreal import was not verified (exit {completed.returncode}, "
            f"report present={import_receipt.is_file()}).\n{tail}"
        )
    import_proof = json.loads(import_receipt.read_text(encoding="utf-8"))
    asset_package = config["destination_path"] + "/" + config["asset_name"]
    expected_asset = asset_package + "." + config["asset_name"]
    expected_skeleton = config["skeleton_asset_path"]
    skeleton_matches = import_proof.get("skeleton") in {
        expected_skeleton, expected_skeleton + "." + expected_skeleton.rsplit("/", 1)[-1]
    }
    if (import_proof.get("ok") is not True
            or import_proof.get("anim_sequence") != expected_asset
            or not skeleton_matches):
        raise RuntimeError("Unreal proof report did not record success")
    reopen_config = {
        "anim_sequence": asset_package,
        "skeleton_asset_path": config["skeleton_asset_path"],
        "required_bones": config["required_bones"],
        "motion_bones": config["motion_bones"],
        "minimum_motion_translation": config["minimum_motion_translation"],
        "minimum_motion_rotation_degrees": config["minimum_motion_rotation_degrees"],
        "minimum_track_count": config["minimum_track_count"],
        "minimum_frame_count": config["minimum_frame_count"],
        "report_json": str(reopen_receipt),
    }
    reopen_script = Path(__file__).with_name("unreal_verify_animation_reopen.py").resolve()
    # The Python commandlet is safe for read-only verification on UE 5.7 and
    # avoids a second full-editor startup. Keep import in the full editor:
    # Interchange can crash in the commandlet after writing an asset.
    reopen_command = list(command)
    reopen_command[2:3] = ["-run=pythonscript", f"-script={reopen_script}"]
    reopen_environment = os.environ.copy()
    reopen_environment["TC_UNREAL_REOPEN_CONFIG_JSON"] = json.dumps(reopen_config)
    try:
        reopened = subprocess.run(
            reopen_command, env=reopen_environment, cwd=str(args.project.resolve().parent),
            capture_output=True, text=True,
            timeout=min(args.timeout, args.reopen_commandlet_timeout),
            creationflags=flags, check=False,
        )
    except subprocess.TimeoutExpired:
        reopened = None
    reopen_mode = "read_only_commandlet"
    if reopened is None or reopened.returncode != 0 or not reopen_receipt.is_file():
        # A read-only UE commandlet can finish its script yet stall during DDC
        # maintenance on exit. Never accept its partial receipt as final proof.
        # Run a fresh full-editor verification with a distinct receipt instead.
        reopen_mode = "full_editor_fallback"
        reopen_receipt = cache / f"{receipt_prefix}_reopen_fallback.json"
        reopen_config["report_json"] = str(reopen_receipt)
        reopen_environment["TC_UNREAL_REOPEN_CONFIG_JSON"] = json.dumps(reopen_config)
        fallback_command = list(command)
        fallback_command[2] = f"-ExecutePythonScript={reopen_script}"
        reopened = subprocess.run(
            fallback_command, env=reopen_environment,
            cwd=str(args.project.resolve().parent), capture_output=True,
            text=True, timeout=args.timeout, creationflags=flags, check=False,
        )
    if reopened.returncode != 0 or not reopen_receipt.is_file():
        tail = "\n".join((reopened.stdout + "\n" + reopened.stderr).splitlines()[-20:])
        raise RuntimeError(
            f"Unreal independent reopen failed (exit {reopened.returncode}, "
            f"report present={reopen_receipt.is_file()}).\n{tail}"
        )
    reopen_proof = json.loads(reopen_receipt.read_text(encoding="utf-8"))
    if (reopen_proof.get("ok") is not True
            or reopen_proof.get("anim_sequence") != expected_asset
            or reopen_proof.get("skeleton") != import_proof.get("skeleton")
            or reopen_proof.get("track_count") != import_proof.get("track_count")
            or reopen_proof.get("frame_count") != import_proof.get("frame_count")):
        raise RuntimeError("Independent reopen did not match import receipt")
    if config["motion_bones"]:
        samples = {str(row.get("bone")): row for row in reopen_proof.get("motion_samples") or []}
        if set(samples) != set(config["motion_bones"]):
            raise RuntimeError("Independent reopen omitted required motion samples")
        for sample in samples.values():
            if (float(sample.get("maximum_translation_delta") or 0) < config["minimum_motion_translation"]
                    and float(sample.get("maximum_rotation_delta_degrees") or 0) < config["minimum_motion_rotation_degrees"]):
                raise RuntimeError("Independent reopen did not prove required bone motion")
    proof = dict(import_proof)
    proof["independent_reopen"] = reopen_proof
    proof["independent_reopen_mode"] = reopen_mode
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print("TC_UNREAL_IMPORT_PROOF=" + json.dumps(proof))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
