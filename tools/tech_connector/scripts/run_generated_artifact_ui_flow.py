"""Exercise generated-artifact planning and repair through the official UI service."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_PROMPT = (
    "Create a complete multi-file Python artifact for Tech Connector that incrementally "
    "snapshots very large directory trees and computes deterministic Merkle-style diffs "
    "between snapshots. It must stream file hashing with bounded parallelism, preserve "
    "stable ordering across platforms, detect renamed files by content identity, honor "
    "gitignore-style include and exclude rules, avoid symlink and junction loops, report "
    "permission and disappearing-file errors without aborting the whole scan, support "
    "cancellation and pause/resume from an atomic manifest checkpoint, and emit observer "
    "events separately from hashing work. The result must expose a typed API for added, "
    "removed, modified, and renamed paths, avoid loading all file contents into memory, "
    "and recover cleanly from a truncated journal or interrupted atomic replace. Generate "
    "focused modules plus comprehensive unittest coverage using only temporary directories "
    "and standard-library dependencies. Do not modify live project files; materialize and "
    "execute only in a disposable workspace. Return all generated code, syntax/import/test "
    "command output, per-stage timings, and proof for every requirement."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--project-root", default="C:/depot/tools")
    parser.add_argument(
        "--report",
        default="C:/depot/tools/tech_connector/reports/runtime/"
        "random_merkle_snapshot_official_ui_flow_v5.json",
    )
    args = parser.parse_args()

    from tech_connector.app.main_window_editor import answer_project_index_request

    started = time.perf_counter()
    updates: list[dict[str, object]] = []

    def status(message: str) -> None:
        entry = {
            "seconds": round(time.perf_counter() - started, 3),
            "message": str(message),
        }
        updates.append(entry)
        print(f"+{entry['seconds']}s {message}", flush=True)

    plan_started = time.perf_counter()
    plan_text, plan_payload = answer_project_index_request(
        args.project_root,
        args.prompt,
        "project_edit",
        status_callback=status,
    )
    plan_elapsed = round(time.perf_counter() - plan_started, 3)
    if not isinstance(plan_payload, dict) or plan_payload.get("type") != "project_edit_plan":
        raise RuntimeError("Official UI flow did not return an approval plan.")

    result_text, result_payload = answer_project_index_request(
        args.project_root,
        args.prompt,
        "project_edit",
        status_callback=status,
        approved_plan=plan_payload,
    )
    report = {
        "prompt": args.prompt,
        "plan_elapsed_seconds": plan_elapsed,
        "total_seconds": round(time.perf_counter() - started, 3),
        "updates": updates,
        "plan_text": plan_text,
        "plan_payload": plan_payload,
        "result": {
            "text": result_text,
            "payload": result_payload,
        },
    }
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
