# coding=utf-8
"""Run real-project project-edit previews and save generated code output."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time


from tech_connector.models.constants import TOOLS_ROOT, temp_output_path

ROOT = TOOLS_ROOT
OUT = temp_output_path("workspace", subdir="project_edit_real_preview")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_index() -> None:
    from tech_connector.knowledge.build_knowledge_index_v2 import main as build_index

    if os.environ.get("TECH_CONNECTOR_REAL_PREVIEW_SKIP_INDEX") == "1":
        return
    build_index(["--root", str(ROOT)])


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "case"


def _project_edit_cases() -> list[dict[str, str]]:
    create_rig = ROOT / "maya_tools" / "Rigging" / "create_rig.py"
    custom_widgets = ROOT / "custom_qt" / "custom_widgets.py"
    sequence_ui = ROOT / "maya_tools" / "Cinematics" / "SequenceUI" / "sequence_ui.py"
    return [
        {
            "name": "real_docstring_get_joint",
            "active": str(create_rig),
            "question": (
                "Improve only the _get_joint docstring in maya_tools/Rigging/create_rig.py. "
                "Keep behavior unchanged. Use the project docstring style with useful :param and :return entries."
            ),
            "plan": (
                "Intent:\nImprove the _get_joint docstring without changing runtime behavior.\n\n"
                f"Evidence-backed targets:\n{create_rig}\n\n"
                "Existing symbols to reuse:\n_get_joint\n\n"
                "Proposed changes:\nReplace _get_joint with the same implementation and a clearer docstring.\n\n"
                "Tests and verification:\nCompile maya_tools/Rigging/create_rig.py.\n\n"
                "Blockers:\nNone\n\n"
                "Plan self-check:\nOnly the docstring changes; behavior and imports remain unchanged.\n\n"
                "Approval scope:\nmaya_tools/Rigging/create_rig.py"
            ),
        },
        {
            "name": "real_pyside_custom_widgets_preview",
            "active": str(custom_widgets),
            "question": (
                "Convert custom_qt/custom_widgets.py to prefer PySide6. Do more than import replacement: "
                "handle common PySide6 API changes such as exec_ and moved QtGui classes. Generate a code preview."
            ),
            "plan": (
                "Intent:\nConvert the custom widgets module toward PySide6 while preserving fallback behavior.\n\n"
                f"Evidence-backed targets:\n{custom_widgets}\n\n"
                "Existing symbols to reuse:\nModelessContinueDialog\nBrowseDirectory\nListProgressBar\nLabeledSlider\n\n"
                "Proposed changes:\nUpdate legacy PySide/PyQt binding references and common Qt6 API patterns in this file only.\n\n"
                "Tests and verification:\nCompile custom_qt/custom_widgets.py.\n\n"
                "Blockers:\nNone\n\n"
                "Plan self-check:\nKeep public widget classes and behavior intact.\n\n"
                "Approval scope:\ncustom_qt/custom_widgets.py"
            ),
        },
        {
            "name": "real_pyside_sequence_ui_preview",
            "active": str(sequence_ui),
            "question": (
                "Convert maya_tools/Cinematics/SequenceUI/sequence_ui.py toward PySide6. "
                "Handle imports plus common API changes like exec_ calls. Keep behavior unchanged. Generate a code preview."
            ),
            "plan": (
                "Intent:\nConvert the sequence UI module toward PySide6 without changing feature behavior.\n\n"
                f"Evidence-backed targets:\n{sequence_ui}\n\n"
                "Existing symbols to reuse:\nSequence UI classes and functions in the file.\n\n"
                "Proposed changes:\nUpdate legacy PySide/PyQt binding references and common Qt6 API patterns in this file only.\n\n"
                "Tests and verification:\nCompile maya_tools/Cinematics/SequenceUI/sequence_ui.py.\n\n"
                "Blockers:\nNone\n\n"
                "Plan self-check:\nKeep public UI behavior intact and avoid broad refactors.\n\n"
                "Approval scope:\nmaya_tools/Cinematics/SequenceUI/sequence_ui.py"
            ),
        },
    ]


def _run_deterministic_pyside_case(path: Path) -> dict[str, object]:
    from tech_connector.services.pyside_conversion_service import convert_pyside_to_pyside6

    started = time.perf_counter()
    before = path.read_text(encoding="utf-8", errors="replace")
    result = convert_pyside_to_pyside6(before)
    elapsed = time.perf_counter() - started
    name = f"deterministic_pyside_{path.stem}"
    case_dir = OUT / name
    _write(case_dir / "new_content.py", result.source)
    _write(
        case_dir / "summary.json",
        json.dumps(
            {
                "case": name,
                "path": str(path),
                "changed": result.changed,
                "elapsed_seconds": round(elapsed, 3),
                "replacements": result.replacements,
                "warnings": result.warnings,
            },
            indent=2,
        ),
    )
    return {
        "case": name,
        "preview_ready": result.changed,
        "elapsed_seconds": round(elapsed, 3),
        "changed_files": [str(path)] if result.changed else [],
        "code_output": str(case_dir / "new_content.py"),
        "replacements": result.replacements,
        "warnings": result.warnings,
    }


def _run_project_edit_case(case: dict[str, str]) -> dict[str, object]:
    from tech_connector.app.main_window_editor import answer_project_index_request

    name = case["name"]
    case_dir = OUT / name
    statuses: list[dict[str, object]] = []
    started = time.perf_counter()

    def status(message: str) -> None:
        statuses.append({"at_seconds": round(time.perf_counter() - started, 3), "message": str(message)})
        print(f"[{name}] +{statuses[-1]['at_seconds']}s {message}")

    response, payload = answer_project_index_request(
        case["active"],
        case["question"],
        "project_edit",
        status_callback=status,
        approved_plan=case["plan"],
    )
    elapsed = time.perf_counter() - started
    _write(case_dir / "response.md", response or "")
    _write(case_dir / "payload.json", json.dumps(payload or {}, indent=2))
    changed_files: list[str] = []
    code_outputs: list[str] = []
    for index, change in enumerate((payload or {}).get("changes") or [], start=1):
        path = Path(str(change.get("path") or f"change_{index}.py"))
        changed_files.append(str(path))
        out_path = case_dir / f"{index:02d}_{path.name}"
        _write(out_path, str(change.get("new_content") or ""))
        code_outputs.append(str(out_path))
    return {
        "case": name,
        "preview_ready": bool(payload and payload.get("type") == "project_changes"),
        "elapsed_seconds": round(elapsed, 3),
        "changed_files": changed_files,
        "response": str(case_dir / "response.md"),
        "payload": str(case_dir / "payload.json"),
        "code_outputs": code_outputs,
        "timings": (payload or {}).get("timings") or {},
        "statuses": statuses,
    }


def main() -> int:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    OUT.mkdir(parents=True, exist_ok=True)
    _build_index()

    requested = {
        item.strip()
        for item in os.environ.get("TECH_CONNECTOR_REAL_CASES", "").split(",")
        if item.strip()
    }
    deterministic_paths = [
        ROOT / "custom_qt" / "custom_widgets.py",
        ROOT / "maya_tools" / "Cinematics" / "SequenceUI" / "sequence_ui.py",
    ]
    results: list[dict[str, object]] = []
    for path in deterministic_paths:
        name = f"deterministic_pyside_{path.stem}"
        if requested and name not in requested:
            continue
        results.append(_run_deterministic_pyside_case(path))

    for case in _project_edit_cases():
        if requested and case["name"] not in requested:
            continue
        results.append(_run_project_edit_case(case))

    summary = {"cases": len(results), "results": results}
    _write(OUT / "real_preview_results.json", json.dumps(summary, indent=2))
    lines = ["# Real Project Edit Preview Results", "", f"Cases run: {len(results)}", ""]
    lines.append("| Case | Ready | Time | Changed Files | Code Output |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    for item in results:
        outputs = item.get("code_outputs") or [item.get("code_output", "")]
        output_text = "<br>".join(str(output) for output in outputs if output)
        lines.append(
            f"| {item.get('case')} | {item.get('preview_ready')} | {item.get('elapsed_seconds')}s | "
            f"{len(item.get('changed_files') or [])} | {output_text} |"
        )
    _write(OUT / "real_preview_results.md", "\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {OUT / 'real_preview_results.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
