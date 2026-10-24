from __future__ import annotations

import argparse
import json
from pathlib import Path

from tech_connector.services.prompt.prompt_route_eval_service import (
    evaluate_prompt_route_cases,
    format_prompt_route_eval_detail,
    load_prompt_route_eval_cases,
)
from tech_connector.models.constants import TOOLS_ROOT


DEFAULT_FIXTURE = (
    Path(__file__).parents[1]
    / "examples"
    / "tests"
    / "fixtures"
    / "prompt_route_plan_eval_cases.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate deterministic prompt route accuracy and timing.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--project-root", action="append", default=[str(TOOLS_ROOT)])
    parser.add_argument("--case", action="append", default=[], help="Only run matching case id(s).")
    parser.add_argument("--category", action="append", default=[], help="Only run matching category/categories.")
    parser.add_argument("--json", action="store_true", help="Print full JSON rows instead of a compact summary.")
    parser.add_argument("--detail", action="store_true", help="Print a detailed per-prompt planning report.")
    parser.add_argument("--no-warmup", action="store_true", help="Include one-time lazy imports in the first case's latency.")
    args = parser.parse_args()
    cases = load_prompt_route_eval_cases(args.fixture)
    if args.case:
        selected = {str(item) for item in args.case}
        cases = [case for case in cases if case.id in selected]
    if args.category:
        selected = {str(item) for item in args.category}
        cases = [case for case in cases if case.category in selected]

    report = evaluate_prompt_route_cases(
        cases,
        project_roots=args.project_root,
        include_details=args.detail or args.json,
        warmup_classifier=not args.no_warmup,
    )
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    elif args.detail:
        print(format_prompt_route_eval_detail(report))
    else:
        print(
            f"Prompt route eval: {report.passed}/{report.total} passed, "
            f"accuracy={report.accuracy:.1%}, avg={report.average_ms:.1f}ms, max={report.max_ms:.1f}ms"
        )
        if not args.no_warmup and report.total:
            print(f"Cold startup/prewarm: {report.warmup_ms:.1f}ms (reported separately from steady-state cases)")
        for category, row in sorted(report.by_category.items()):
            print(
                f"- {category}: {row['passed']}/{row['total']} "
                f"accuracy={row['accuracy']:.1%}, avg={row['average_ms']:.1f}ms"
            )
        failures = [row for row in report.rows if not row.ok]
        if failures:
            print("\nFailures:")
            for row in failures:
                reasons = []
                if row.actual_route not in row.expected_routes:
                    reasons.append(f"route {row.actual_route!r} not in {row.expected_routes}")
                if row.expected_mutation_scope and row.mutation_scope != row.expected_mutation_scope:
                    reasons.append(f"mutation scope {row.mutation_scope!r} != {row.expected_mutation_scope!r}")
                if not row.timing_ok and not (args.detail or args.json):
                    reasons.append(f"latency {row.elapsed_ms:.1f}ms > {row.max_ms:.1f}ms")
                if not reasons:
                    reasons.append("provider, confirmation, or execution contract mismatch")
                print(f"- {row.id}: {'; '.join(reasons)}")
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
