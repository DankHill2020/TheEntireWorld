"""Execute the selected-Skeleton handoff for externally acquired animation assets."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from tech_connector.services.asset_lineage_service import record_asset_lineage
from tech_connector.services.asset_provenance_ledger_service import register_external_asset
from tech_connector.services.unreal.animation_source_profile_service import (
    match_animation_source_profile,
)


def resolve_retarget_target_selection(
    prompt: str,
    prior_result_metadata: dict[str, Any] | None,
    clarification_binding: dict[str, Any] | None = None,
) -> str:
    prior = dict(prior_result_metadata or {})
    if prior.get("result_type") != "unreal_animation_retarget_target_selection":
        return ""
    binding = dict(clarification_binding or {})
    execution_request = dict(binding.get("execution_request") or {})
    values = dict(
        binding.get("values")
        or binding.get("resolved_slots")
        or binding.get("slot_values")
        or execution_request.get("keyword_args")
        or {}
    )
    return str(values.get("target_skeleton") or prompt or "").strip()


def selected_target_mesh(target_options: dict[str, Any], target_skeleton: str) -> str:
    for row in target_options.get("options") or []:
        if str(row.get("skeleton") or "") != str(target_skeleton or ""):
            continue
        meshes = [str(value) for value in row.get("skeletal_meshes") or [] if value]
        preferred = [value for value in meshes if "nogeo" in value.lower() or "simple" in value.lower()]
        return (preferred or meshes or [""])[0]
    return ""


def discover_mayapy(settings: dict[str, Any] | None = None) -> str:
    configured = str((settings or {}).get("mayapy_path") or os.environ.get("MAYAPY_PATH") or "")
    candidates = [Path(configured)] if configured else []
    autodesk = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Autodesk"
    if autodesk.is_dir():
        candidates.extend(sorted(autodesk.glob("Maya*/bin/mayapy.exe"), reverse=True))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return ""


def _marker_payload(output: str, marker: str) -> dict[str, Any]:
    prefix = marker + "="
    for line in reversed(str(output or "").splitlines()):
        if line.startswith(prefix):
            try:
                return dict(json.loads(line[len(prefix) :]))
            except (ValueError, TypeError):
                return {}
    return {}


def _run_maya_script(
    mayapy: str,
    script: Path,
    arguments: list[str],
    *,
    tools_root: Path,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(tools_root), environment.get("PYTHONPATH", "")) if value
    )
    return subprocess.run(
        [mayapy, str(script), *arguments],
        cwd=str(tools_root),
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def inspect_animation_fbx(
    source_fbx: str | Path,
    *,
    mayapy: str,
    tools_root: str | Path,
) -> dict[str, Any]:
    root = Path(tools_root).resolve()
    script = root / "tech_connector" / "scripts" / "maya_hik_asset_probe.py"
    process = _run_maya_script(mayapy, script, [str(Path(source_fbx).resolve())], tools_root=root)
    report = _marker_payload(process.stdout, "AI_STUDIO_MAYA_HIK_PROBE")
    report["process_returncode"] = process.returncode
    if not report:
        report = {
            "ok": False,
            "process_returncode": process.returncode,
            "errors": [process.stderr.strip() or process.stdout.strip() or "Maya FBX probe failed."],
        }
    return report


def _target_terms(target_mesh: str, target_skeleton: str) -> set[str]:
    values = " ".join([target_mesh, target_skeleton]).lower()
    return {
        value
        for value in re.findall(r"[a-z0-9]+", values)
        if len(value) > 2
        and value
        not in {
            "game", "characters", "mannequin", "mannequins", "meshes",
            "skeleton", "simple", "nogeo", "skm", "rig",
        }
    }


def discover_authored_target_rig(
    project_root: str | Path,
    *,
    target_mesh: str,
    target_skeleton: str,
) -> dict[str, Any]:
    project = Path(project_root).resolve()
    roots = [project / "ArtSource", project.parent / "ArtSource"]
    terms = _target_terms(target_mesh, target_skeleton)
    scored = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.fbx"):
            lower = str(path).lower()
            if not any(marker in lower for marker in ("retarget", "mocap_rig", "mocap\\rig")):
                continue
            name_terms = set(re.findall(r"[a-z0-9]+", path.stem.lower()))
            compact_name = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
            overlap = len(terms & name_terms) + sum(
                1 for term in terms if term not in name_terms and term in compact_name
            )
            score = overlap * 10 + (4 if "mocap_rig" in lower else 0) + (2 if "retarget" in lower else 0)
            if overlap > 0:
                scored.append((score, str(path.resolve())))
    scored.sort(key=lambda row: (-row[0], len(row[1]), row[1].lower()))
    return {
        "ok": bool(scored),
        "target_rig": scored[0][1] if scored else "",
        "candidates": [{"score": score, "path": path} for score, path in scored[:12]],
        "match_terms": sorted(terms),
    }


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return cleaned[:80] or "ExternalAnimation"


def _import_retargeted_animation(
    output_fbx: Path,
    target_skeleton: str,
    destination: str,
    destination_name: str,
) -> dict[str, Any]:
    from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

    source = "\n".join(
        [
            "import json",
            "import unreal",
            "from unreal_tools.animation_import_adapter import import_animation_verified",
            f"result = import_animation_verified({str(output_fbx)!r}, {target_skeleton!r}, {destination!r}, {destination_name!r}, replace_existing=True, save=True)",
            "details = []",
            "for object_path in result.get('verified_animation_paths', []):",
            "    asset_path = object_path.split('.')[0]",
            "    asset = unreal.EditorAssetLibrary.load_asset(asset_path)",
            "    skeleton = asset.get_editor_property('skeleton') if asset else None",
            "    frames = int(asset.get_editor_property('number_of_sampled_frames')) if asset else 0",
            "    duration = float(asset.get_play_length()) if asset else 0.0",
            "    details.append({'asset_path': asset_path, 'class': asset.get_class().get_name() if asset else '', 'skeleton': str(skeleton.get_path_name()).split('.')[0] if skeleton else '', 'sampled_frames': frames, 'duration': duration, 'saved': bool(unreal.EditorAssetLibrary.does_asset_exist(asset_path))})",
            "print(json.dumps({'import': result, 'details': details}))",
        ]
    )
    response = UnrealBridge().execute_python(source, timeout=300, reset_globals=True)
    if not response.get("ok"):
        return {"ok": False, "errors": [str(response.get("error") or "Unreal import failed.")]}
    data = response.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            data = {}
    result = dict(data or {})
    result["ok"] = bool((result.get("import") or {}).get("ok") and result.get("details"))
    return result


def _bridge_data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") if isinstance(response, dict) else {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            data = {}
    return dict(data or {}) if isinstance(data, dict) else {}


def choose_retarget_route(source_import: dict[str, Any]) -> str:
    """Choose the next retarget implementation from observed source assets."""

    if source_import.get("retarget_ready"):
        return "unreal_editor_ik_bake"
    return "external_dcc_retarget"


def _try_unreal_editor_ik_bake(
    source_fbx: Path,
    *,
    target_mesh: str,
    destination: str,
) -> dict[str, Any]:
    """Import a source rig and bake through a strictly matching project retargeter."""

    from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

    bridge = UnrealBridge()
    source_name = _safe_name(source_fbx.stem)
    source_destination = "/Game/AIStudio/ExternalAnimationSources/" + source_name
    source_response = bridge.safe_call(
        "unreal_tools.animation_source_import.import_animation_source",
        kwargs={
            "source_path": str(source_fbx),
            "destination_path": source_destination,
            "destination_name": "SRC_" + source_name,
            "replace_existing": False,
            "save": True,
        },
        timeout=300,
        retries=0,
        retry_safe=False,
        label="Import external animation source rig",
    )
    source_import = _bridge_data(source_response)
    report: dict[str, Any] = {
        "ok": False,
        "route": choose_retarget_route(source_import),
        "source_import": source_import,
        "source_bridge": {
            "ok": bool(source_response.get("ok")),
            "errors": list(source_response.get("errors") or []),
        },
        "retarget": {},
        "errors": [],
    }
    if not source_response.get("ok") or not source_import.get("retarget_ready"):
        report["errors"].extend(source_response.get("errors") or source_import.get("errors") or [])
        return report

    animation_paths = [str(value) for value in source_import.get("animation_paths") or [] if value]
    source_meshes = [str(value) for value in source_import.get("skeletal_mesh_paths") or [] if value]
    if not animation_paths or not source_meshes:
        report["errors"].append("Source import was marked ready without both an animation and SkeletalMesh.")
        return report
    bake_response = bridge.safe_call(
        "unreal_tools.retargeting.retarget_animation_with_matching_project_asset",
        kwargs={
            "animation_path": animation_paths[0],
            "source_skeletal_mesh_path": source_meshes[0],
            "target_skeletal_mesh_path": target_mesh,
            "destination_path": destination,
            "destination_suffix": "_Target",
            "save": True,
        },
        timeout=300,
        retries=0,
        retry_safe=False,
        label="Bake animation with matching Unreal IK Retargeter",
    )
    bake = _bridge_data(bake_response)
    report["retarget"] = bake
    report["retarget_bridge"] = {
        "ok": bool(bake_response.get("ok")),
        "errors": list(bake_response.get("errors") or []),
    }
    report["ok"] = bool(bake_response.get("ok") and bake.get("ok"))
    if not report["ok"]:
        report["errors"].extend(bake_response.get("errors") or bake.get("errors") or [])
    return report


def execute_animation_retarget_import_handoff(
    *,
    download_result: dict[str, Any],
    target_options: dict[str, Any],
    target_skeleton: str,
    project_root: str | Path,
    settings: dict[str, Any] | None = None,
    tools_root: str | Path | None = None,
) -> dict[str, Any]:
    """Prefer an Unreal editor bake, then use a verified DCC fallback."""

    project = Path(project_root).resolve()
    root = Path(tools_root).resolve() if tools_root else Path(__file__).resolve().parents[3]
    target_mesh = selected_target_mesh(target_options, target_skeleton)
    if not target_skeleton or not target_mesh:
        return {"ok": False, "status": "target_resolution_failed", "completion_allowed": False}

    rows = []
    mayapy = ""
    rig: dict[str, Any] = {}
    for role, role_row in (download_result.get("role_downloads") or {}).items():
        download = dict(role_row.get("download") or {})
        source_fbx = Path(str(download.get("local_path") or "")).resolve()
        row: dict[str, Any] = {"role": role, "source_fbx": str(source_fbx), "ok": False}
        if not source_fbx.is_file():
            row["errors"] = ["Downloaded source FBX is missing."]
            rows.append(row)
            continue
        destination = "/Game/AIStudio/GeneratedAnimations/Retargeted"
        unreal_bake = _try_unreal_editor_ik_bake(
            source_fbx,
            target_mesh=target_mesh,
            destination=destination,
        )
        row["unreal_editor_bake"] = unreal_bake
        if unreal_bake.get("ok"):
            retarget_result = dict(unreal_bake.get("retarget") or {}).get("retarget") or {}
            valid_outputs = list(retarget_result.get("valid_outputs") or [])
            ledger = register_external_asset(
                project,
                {
                    "local_path": str(source_fbx),
                    "sha256": (download.get("manifest") or {}).get("sha256", ""),
                    "provider": (download.get("manifest") or {}).get("provider", ""),
                    "source_url": (download.get("manifest") or {}).get("source_url", ""),
                    "target_skeleton": target_skeleton,
                    "generated_unreal_assets": [value.get("asset_path") for value in valid_outputs],
                    "retarget_route": "unreal_editor_ik_bake",
                    "retargeter": (unreal_bake.get("retarget") or {}).get("selected_retargeter", ""),
                    "semantic_role": role,
                    "license": (download.get("manifest") or {}).get("license", ""),
                },
            )
            row.update(
                {
                    "ok": True,
                    "retarget_route": "unreal_editor_ik_bake",
                    "unreal_assets": valid_outputs,
                    "asset_ledger": ledger,
                    "contextual_preview": {"required": True, "generated": False, "accepted": False},
                }
            )
            rows.append(row)
            continue

        if not mayapy:
            mayapy = discover_mayapy(settings)
        if not mayapy:
            row["errors"] = [
                "Unreal editor retarget baking was unavailable and no Maya fallback was installed.",
                *(unreal_bake.get("errors") or []),
            ]
            row["missing_capability"] = "source_skeletal_mesh_or_matching_ik_retargeter_or_mayapy"
            rows.append(row)
            continue
        if not rig:
            rig = discover_authored_target_rig(
                project,
                target_mesh=target_mesh,
                target_skeleton=target_skeleton,
            )
        if not rig.get("ok"):
            row["errors"] = [
                "Unreal editor retarget baking was unavailable and no authored DCC target rig matched.",
                *(unreal_bake.get("errors") or []),
            ]
            row["knowledge_suggestion"] = "Add or characterize a target rig or a reusable Unreal IK Retargeter for this source rig family."
            rows.append(row)
            continue
        probe = inspect_animation_fbx(source_fbx, mayapy=mayapy, tools_root=root)
        profile = match_animation_source_profile(probe)
        row.update({"source_probe": probe, "source_profile": profile})
        if not profile.get("ok"):
            row["errors"] = [str(profile.get("reason") or "No verified source profile matched.")]
            row["knowledge_suggestion"] = "Inspect and explicitly characterize this source hierarchy, then save a verified source profile."
            rows.append(row)
            continue

        target_label = _safe_name(Path(target_mesh).name)
        output_dir = project / "ArtSource" / "AIStudio" / "Animations" / "Retargeted" / target_label
        output_dir.mkdir(parents=True, exist_ok=True)
        output_fbx = output_dir / f"{_safe_name(source_fbx.stem)}_{target_label}_HIK.fbx"
        mapping_path = output_fbx.with_suffix(".source_mapping.json")
        mapping_path.write_text(
            json.dumps(
                {
                    "profile_id": profile.get("profile_id"),
                    "source_mapping": profile.get("source_mapping") or {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        process = _run_maya_script(
            mayapy,
            root / "tech_connector" / "scripts" / "maya_hik_retarget.py",
            [
                "--target-rig", str(rig["target_rig"]),
                "--source-fbx", str(source_fbx),
                "--output-fbx", str(output_fbx),
                "--source-mapping", str(mapping_path),
            ],
            tools_root=root,
        )
        retarget = _marker_payload(process.stdout, "AI_STUDIO_MAYA_HIK_RETARGET")
        row["retarget"] = {**retarget, "process_returncode": process.returncode}
        if process.returncode or not retarget.get("ok") or not output_fbx.is_file():
            row["errors"] = [process.stderr.strip() or "Maya HumanIK retarget failed."]
            rows.append(row)
            continue

        lineage = record_asset_lineage(
            output_fbx,
            sources=[
                {
                    "local_path": str(source_fbx),
                    "source_url": (download.get("manifest") or {}).get("source_url", ""),
                    "provider": (download.get("manifest") or {}).get("provider", ""),
                },
                {"local_path": str(rig["target_rig"]), "kind": "authored_target_rig"},
            ],
            transformations=[
                {
                    "operation": "animation.hik_retarget",
                    "profile_id": profile.get("profile_id"),
                    "result": "passed",
                    "target_response_samples": retarget.get("pre_bake_hips") or [],
                    "baked_joint_count": retarget.get("target_joint_count") or 0,
                }
            ],
            license_record=dict(download.get("manifest") or {}),
            semantic_contract={
                "role": role,
                "metadata_match": True,
                "visual_preview_required": True,
                "gameplay_use_accepted": False,
            },
            destination=target_skeleton,
        )
        unreal_import = _import_retargeted_animation(
            output_fbx,
            target_skeleton,
            destination,
            "A_" + _safe_name(source_fbx.stem) + "_" + target_label,
        )
        ledger = register_external_asset(
            project,
            {
                "local_path": str(output_fbx),
                "sha256": (lineage.get("output") or {}).get("sha256", ""),
                "provider": (download.get("manifest") or {}).get("provider", ""),
                "source_url": (download.get("manifest") or {}).get("source_url", ""),
                "derived_from": str(source_fbx),
                "target_skeleton": target_skeleton,
                "semantic_role": role,
                "license": (download.get("manifest") or {}).get("license", ""),
            },
        )
        row.update(
            {
                "ok": bool(unreal_import.get("ok")),
                "retarget_route": "maya_hik_bake_then_unreal_import",
                "output_fbx": str(output_fbx),
                "lineage": lineage,
                "unreal_import": unreal_import,
                "asset_ledger": ledger,
                "contextual_preview": {
                    "required": True,
                    "generated": False,
                    "accepted": False,
                },
            }
        )
        rows.append(row)

    imported = [row for row in rows if row.get("ok")]
    return {
        "ok": bool(imported) and len(imported) == len(rows),
        "status": "imported_pending_contextual_preview" if imported else "retarget_import_failed",
        "target_skeleton": target_skeleton,
        "target_mesh": target_mesh,
        "target_rig": rig.get("target_rig") if rig else "",
        "rows": rows,
        "completion_allowed": False,
        "next_gate": "contextual_clip_preview_and_segmentation" if imported else "repair_retarget_import",
    }


def render_animation_retarget_import_handoff(result: dict[str, Any]) -> str:
    lines = ["Animation retarget and import", "", f"Status: `{result.get('status')}`"]
    lines.append(f"Target Skeleton: `{result.get('target_skeleton') or 'unresolved'}`")
    lines.append(f"Target mesh: `{result.get('target_mesh') or 'unresolved'}`")
    for row in result.get("rows") or []:
        details = (row.get("unreal_import") or {}).get("details") or []
        asset = details[0].get("asset_path") if details else "not imported"
        lines.append(f"- `{row.get('role')}`: `{asset}`")
    if result.get("status") == "imported_pending_contextual_preview":
        lines.extend(
            [
                "",
                "Skeleton import passed. Gameplay use remains blocked until visual preview and clip segmentation confirm the requested role.",
            ]
        )
    return "\n".join(lines)
