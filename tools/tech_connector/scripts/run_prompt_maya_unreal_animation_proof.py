"""Compile and replay one explicit Maya HIK-control-FBX -> Unreal prompt.

This bounded, headless proof runner uses the same typed compiler as Pipeline
View and the independently audited host importers. It does not claim to run
the live UI/HTTP bridge graph. Outputs must be explicit and never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from tech_connector.game_engine.integration.dynamic_pipeline_compiler_service import (
    compile_dynamic_pipeline,
)


_OPERATIONS = (
    "animation.fbx_to_engine",
    "unreal_tools.asset_transfer_adapter.import_fbx_verified",
    "unreal_tools.asset_transfer_adapter.registry_readback",
)
PROOF_SCHEMA = "tech_connector.maya_unreal_animation_prompt_proof.v2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _unreal_asset_file(project: Path, object_path: str) -> Path:
    package = str(object_path).split(".", 1)[0]
    if not package.startswith("/Game/") or any(
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) is None
        for part in package.split("/")[2:]
    ):
        raise ValueError("Unreal proof returned an invalid /Game asset path")
    return project.parent / "Content" / (package[len("/Game/"):] + ".uasset")


def compile_proof_plan(prompt: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Accept only a complete, unambiguous Maya-to-Unreal animation plan."""
    plan = compile_dynamic_pipeline(prompt)
    stages = list(plan.get("stages") or [])
    if (not plan.get("success") or not plan.get("execution_ready")
            or plan.get("gaps") or plan.get("required_inputs")
            or tuple(stage.get("operation") for stage in stages) != _OPERATIONS
            or [stage.get("host") for stage in stages] != ["maya", "unreal", "unreal"]):
        raise ValueError("Prompt did not compile to a complete Maya HIK-to-Unreal animation handoff")
    maya, unreal, readback = stages
    maya_params = maya["params"]
    unreal_params = unreal["params"]
    if any(not maya_params.get(key) for key in
           ("animation_fbx", "rig_scene", "target_hik_fbx", "output_scene", "output_fbx")):
        raise ValueError("Prompt must label the source FBX, rig, target HIK, scene and engine FBX")
    if unreal_params.get("source_file") != {
        "from_action": maya["id"], "result_path": "fbx_path",
    } or readback["params"].get("imported_paths") != {
        "from_action": unreal["id"], "result_path": "imported_paths",
    }:
        raise ValueError("Compiled handoff did not bind the selected FBX and imported assets")
    destination = str(unreal_params.get("destination_path") or "")
    skeleton = str(unreal_params.get("skeleton_path") or "")
    if not destination.startswith("/Game/") or not skeleton.startswith("/Game/"):
        raise ValueError("Prompt must name an explicit Unreal /Game destination and Skeleton")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", Path(maya_params["output_fbx"]).stem):
        raise ValueError("Engine FBX basename must be an Unreal-safe asset name")
    return plan, maya_params, unreal_params


def _run(command: list[str], *, timeout: int, label: str, temp_dir: Path) -> None:
    environment = os.environ.copy()
    root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = root + os.pathsep + environment.get("PYTHONPATH", "")
    environment["TEMP"] = str(temp_dir)
    environment["TMP"] = str(temp_dir)
    completed = subprocess.run(
        command, env=environment, capture_output=True, text=True, timeout=timeout, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode:
        tail = "\n".join((completed.stdout + "\n" + completed.stderr).splitlines()[-20:])
        raise RuntimeError(f"{label} failed (exit {completed.returncode}):\n{tail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--mayapy", type=Path, required=True)
    parser.add_argument("--editor", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--required-bone", action="append", default=[])
    parser.add_argument("--moving-bone", action="append", default=[])
    parser.add_argument("--minimum-motion-translation", type=float, default=0.1)
    parser.add_argument("--minimum-motion-rotation-degrees", type=float, default=1.0)
    parser.add_argument("--minimum-track-count", type=int, default=1)
    parser.add_argument("--minimum-frame-count", type=int, default=1)
    args = parser.parse_args(argv)

    if not args.moving_bone:
        raise ValueError("Animation proof requires at least one moving bone for fresh Unreal readback")

    for label in ("prompt_file", "mayapy", "editor", "project"):
        if not getattr(args, label).is_file():
            raise FileNotFoundError(f"{label} not found: {getattr(args, label)}")
    report = args.report_json.expanduser().resolve()
    if report.exists():
        raise FileExistsError(f"Refusing to overwrite final proof: {report}")
    prompt = args.prompt_file.read_text(encoding="utf-8")
    plan, maya_params, unreal_params = compile_proof_plan(prompt)
    cache_dir = args.cache_dir.expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    maya_report = report.with_name(report.stem + ".maya.json")
    unreal_report = report.with_name(report.stem + ".unreal.json")
    outputs = {report, maya_report, unreal_report}
    inputs = {Path(value).expanduser().resolve() for value in (
        args.prompt_file, args.mayapy, args.editor, args.project,
        maya_params["animation_fbx"], maya_params["rig_scene"],
        maya_params["target_hik_fbx"], maya_params.get("source_hik_fbx"),
        maya_params["output_scene"], maya_params["output_fbx"],
    ) if value}
    if outputs & inputs or len(outputs) != 3:
        raise ValueError("Proof report paths must not alias selected inputs or outputs")
    if any(path.exists() for path in (maya_report, unreal_report)):
        raise FileExistsError("Refusing to overwrite an existing partial proof report")
    selected_inputs = {
        role: Path(maya_params[role]).expanduser().resolve()
        for role in ("animation_fbx", "rig_scene", "target_hik_fbx", "source_hik_fbx")
        if maya_params.get(role)
    }
    selected_inputs["project"] = args.project.resolve()
    scene_path = Path(maya_params["output_scene"]).expanduser().resolve()
    output_fbx = Path(maya_params["output_fbx"]).expanduser().resolve()
    destination = str(unreal_params["destination_path"]).rstrip("/")
    asset_path = _unreal_asset_file(
        args.project.resolve(),
        f"{destination}/{output_fbx.stem}.{output_fbx.stem}",
    ).resolve()
    output_artifacts = {scene_path, output_fbx, asset_path}
    if len(output_artifacts) != 3 or output_artifacts & set(selected_inputs.values()):
        raise ValueError("Proof output artifacts must be distinct from selected inputs")
    for path in output_artifacts:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite an existing proof artifact: {path}")
    input_sha256 = {role: _sha256(path) for role, path in selected_inputs.items()}

    maya_command = [
        str(args.mayapy.resolve()),
        str(Path(__file__).with_name("maya_fbx_to_engine.py").resolve()),
        "--animation-fbx", str(maya_params["animation_fbx"]),
        "--rig-scene", str(maya_params["rig_scene"]),
        "--target-hik-fbx", str(maya_params["target_hik_fbx"]),
        "--output-scene", str(maya_params["output_scene"]),
        "--output-fbx", str(maya_params["output_fbx"]),
        "--report-json", str(maya_report),
    ]
    if maya_params.get("source_hik_fbx"):
        maya_command.extend(["--source-hik-fbx", str(maya_params["source_hik_fbx"])])
    _run(maya_command, timeout=420, label="Maya HIK/control/FBX stage", temp_dir=cache_dir)
    if not maya_report.is_file():
        raise RuntimeError("Maya exited without a proof report")
    maya_proof = json.loads(maya_report.read_text(encoding="utf-8"))
    if (maya_proof.get("ok") is not True or not output_fbx.is_file()
            or Path(maya_proof.get("fbx_path") or "").resolve() != output_fbx
            or not maya_proof.get("clean_export", {}).get("ok")):
        raise RuntimeError("Maya stage did not prove the requested clean FBX")

    unreal_command = [
        sys.executable,
        str(Path(__file__).with_name("run_unreal_fbx_import_proof.py").resolve()),
        "--editor", str(args.editor.resolve()),
        "--project", str(args.project.resolve()),
        "--animation-fbx", str(output_fbx),
        "--skeleton-asset-path", str(unreal_params["skeleton_path"]),
        "--destination-path", str(unreal_params["destination_path"]),
        "--asset-name", output_fbx.stem,
        "--report-json", str(unreal_report),
        "--cache-dir", str(cache_dir),
        "--minimum-track-count", str(args.minimum_track_count),
        "--minimum-frame-count", str(args.minimum_frame_count),
        "--minimum-motion-translation", str(args.minimum_motion_translation),
        "--minimum-motion-rotation-degrees", str(args.minimum_motion_rotation_degrees),
    ]
    for bone in args.required_bone:
        unreal_command.extend(["--required-bone", bone])
    for bone in args.moving_bone:
        unreal_command.extend(["--moving-bone", bone])
    _run(unreal_command, timeout=750, label="Unreal import and independent reopen", temp_dir=cache_dir)
    if not unreal_report.is_file():
        raise RuntimeError("Unreal exited without independent reopen proof")
    unreal_proof = json.loads(unreal_report.read_text(encoding="utf-8"))
    if (unreal_proof.get("ok") is not True
            or Path(unreal_proof.get("animation_fbx") or "").resolve() != output_fbx
            or not unreal_proof.get("independent_reopen", {}).get("ok")):
        raise RuntimeError("Unreal proof does not match the compiled Maya FBX")

    for role, path in selected_inputs.items():
        if _sha256(path) != input_sha256[role]:
            raise RuntimeError(f"Selected {role} changed during cross-host proof")
    if not scene_path.is_file():
        raise RuntimeError("Maya scene disappeared before proof receipt")
    if _unreal_asset_file(args.project.resolve(), unreal_proof["anim_sequence"]).resolve() != asset_path:
        raise RuntimeError("Saved Unreal asset does not match the selected output name and destination")
    if not asset_path.is_file():
        raise RuntimeError(f"Saved Unreal AnimSequence is missing: {asset_path}")
    output_files = {"maya_scene": scene_path, "fbx_path": output_fbx,
                    "unreal_asset": asset_path, "maya_report": maya_report,
                    "unreal_report": unreal_report}

    proof = {
        "ok": True,
        "schema": PROOF_SCHEMA,
        "prompt": prompt,
        "project": str(args.project.resolve()),
        "selected_inputs": {role: str(path) for role, path in selected_inputs.items()},
        "input_sha256": input_sha256,
        "motion_gate": {
            "moving_bones": sorted(set(args.moving_bone)),
            "minimum_translation": args.minimum_motion_translation,
            "minimum_rotation_degrees": args.minimum_motion_rotation_degrees,
        },
        "output_files": {role: str(path) for role, path in output_files.items()},
        "output_bytes": {role: path.stat().st_size for role, path in output_files.items()},
        "output_sha256": {role: _sha256(path) for role, path in output_files.items()},
        "compiled_operations": [stage["operation"] for stage in plan["stages"]],
        "maya": maya_proof,
        "unreal": unreal_proof,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print("TC_PROMPT_MAYA_UNREAL_PROOF=" + json.dumps({
        "ok": True, "report_json": str(report),
        "fbx_path": str(output_fbx),
        "anim_sequence": unreal_proof["anim_sequence"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
