from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tech_connector.game_engine.integration.developer_prompt_demo_qualification_service import (
    DEVELOPER_PROMPT_CASES,
    qualify_developer_demo_prompts,
)
from tech_connector.models.constants import temp_output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Qualify developer AI prompts and on-demand pipeline generation for a demo.",
    )
    parser.add_argument(
        "--project-root",
        default=str(APP_ROOT),
        help="Project root used by project-aware prompt routing.",
    )
    parser.add_argument(
        "--output",
        default=str(temp_output_path("developer_prompt_demo_qualification.json", subdir="reports")),
        help="JSON evidence report path.",
    )
    parser.add_argument(
        "--pipelines-only",
        action="store_true",
        help="Run only pipeline generation, materialization, preflight, and safe-failure cases.",
    )
    parser.add_argument(
        "--require-end-to-end",
        action="store_true",
        help="Return a failing exit code while any case lacks end-to-end evidence.",
    )
    parser.add_argument(
        "--runtime-evidence",
        action="append",
        default=[],
        help="Artifact-backed live runtime report; may be supplied more than once.",
    )
    args = parser.parse_args()

    cases = (
        tuple(case for case in DEVELOPER_PROMPT_CASES if case.pipeline)
        if args.pipelines_only
        else DEVELOPER_PROMPT_CASES
    )
    report = qualify_developer_demo_prompts(
        args.project_root,
        output_path=args.output,
        cases=cases,
        runtime_evidence_paths=tuple(args.runtime_evidence),
    )
    print(json.dumps({
        "ready_for_demo": report["ready_for_demo"],
        "planning_ready": report["planning_ready"],
        "ready_for_end_to_end_demo": report["ready_for_end_to_end_demo"],
        "summary": report["summary"],
        "failed_case_ids": report["failed_case_ids"],
        "end_to_end_unproven_case_ids": report["end_to_end_unproven_case_ids"],
        "report_path": report.get("report_path", args.output),
    }, indent=2))
    ready = (
        report["ready_for_end_to_end_demo"]
        if args.require_end_to_end
        else report["ready_for_demo"]
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
