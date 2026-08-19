"""Aggregate and render code-agent benchmark results."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import statistics
from typing import Any

from .models import BenchmarkReport


def _percentile(values: list[float], percentile: float) -> float:
    """Return a linearly interpolated percentile.

    :param values: Numeric sample values.
    :param percentile: Percentile from zero through one.
    :return: Interpolated percentile value.
    """

    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def aggregate_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate scored runs by agent and model.

    :param runs: Combined run and score dictionaries.
    :return: Sorted aggregate rows.
    """

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in runs:
        grouped[(str(item["agent"]), str(item["model"]))].append(item)
    rows: list[dict[str, Any]] = []
    for (agent, model), items in sorted(grouped.items()):
        eligible_items = [
            item
            for item in items
            if bool(item.get("eligible", item.get("status") in {"ok", "preview_ok"}))
        ]
        scores = [
            float(item["score"]["total_points"]) for item in eligible_items
        ]
        latencies = [float(item["wall_seconds"]) for item in eligible_items]
        input_tokens = [int(item.get("input_tokens") or 0) for item in eligible_items]
        output_tokens = [int(item.get("output_tokens") or 0) for item in eligible_items]
        total_minutes = sum(latencies) / 60.0
        rows.append(
            {
                "agent": agent,
                "model": model,
                "attempts": len(items),
                "eligible_attempts": len(eligible_items),
                "ineligible_attempts": len(items) - len(eligible_items),
                "perfect_pass_rate": round(
                    sum(score >= 100.0 for score in scores) / len(scores), 4
                ) if scores else 0.0,
                "mean_quality": round(statistics.fmean(scores), 3) if scores else 0.0,
                "median_quality": round(statistics.median(scores), 3) if scores else 0.0,
                "median_wall_seconds": (
                    round(statistics.median(latencies), 3) if latencies else 0.0
                ),
                "p95_wall_seconds": round(_percentile(latencies, 0.95), 3),
                "mean_input_tokens": (
                    round(statistics.fmean(input_tokens), 1) if input_tokens else 0.0
                ),
                "mean_output_tokens": (
                    round(statistics.fmean(output_tokens), 1) if output_tokens else 0.0
                ),
                "quality_points_per_minute": round(
                    sum(scores) / total_minutes if total_minutes else 0.0, 3
                ),
                "mean_patch_lines": round(
                    statistics.fmean(
                        int(item["score"]["lines_added"])
                        + int(item["score"]["lines_removed"])
                        for item in eligible_items
                    ),
                    1,
                ) if eligible_items else 0.0,
            }
        )
    return rows


def write_report(report: BenchmarkReport, output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and concise Markdown benchmark reports.

    :param report: Completed benchmark report.
    :param output_dir: Report destination directory.
    :return: JSON and Markdown report paths.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Tech Connector vs Codex code-agent benchmark",
        "",
        f"Benchmark version: `{report.benchmark_version}`  ",
        f"Started: `{report.started_at}`  ",
        f"Finished: `{report.finished_at}`",
        "",
        "## Aggregate results",
        "",
        "| Agent | Model | Attempts | Eligible | Ineligible | Perfect | Mean quality | Median time | P95 time | Input tokens | Output tokens | Quality/min | Patch lines |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.summary:
        lines.append(
            f"| {row['agent']} | {row['model']} | {row['attempts']} | "
            f"{row['eligible_attempts']} | {row['ineligible_attempts']} | "
            f"{row['perfect_pass_rate'] * 100:.1f}% | {row['mean_quality']:.1f} | "
            f"{row['median_wall_seconds']:.2f}s | {row['p95_wall_seconds']:.2f}s | "
            f"{row['mean_input_tokens']:.0f} | {row['mean_output_tokens']:.0f} | "
            f"{row['quality_points_per_minute']:.1f} | {row['mean_patch_lines']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Attempts",
            "",
            "| Case | Agent | Model | Status | Eligible | Assertions | Score | Time | Files | Scope violations | Quality issues |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in report.runs:
        score = item["score"]
        lines.append(
            f"| {item['case_id']} | {item['agent']} | {item['model']} | "
            f"{item['status']} | {'yes' if item.get('eligible', True) else 'no'} | "
            f"{score['assertions_passed']}/{score['assertions_total']} | "
            f"{score['total_points']:.1f} | {item['wall_seconds']:.2f}s | "
            f"{len(score['changed_files'])} | {len(score['out_of_scope_files'])} | "
            f"{len(score.get('quality_issues') or [])} |"
        )
    lines.extend(
        [
            "",
            "## Scoring contract",
            "",
            "Each attempt receives up to 60 behavior points from a hidden evaluator, "
            "10 deterministic maintainability points, 10 syntax points, 10 "
            "scope-discipline points, and 10 completion points. Maintainability checks "
            "reject dead string literals, redundant lock nesting, generic public "
            "docstrings, missing public documentation, and lines over 120 characters. "
            "The evaluator is materialized only after the agent exits. Runtime and token "
            "metrics are reported independently from quality; zero tokens means the adapter "
            "did not expose token telemetry, not that inference was free. Infrastructure, "
            "timeout, and process failures keep their diagnostic scores in the attempt table "
            "but are excluded from aggregate quality and performance metrics.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path
