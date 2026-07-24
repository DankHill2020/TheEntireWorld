# coding=utf-8
from stresspkg.pipeline_runner import run_pipeline


def format_pipeline_summary(items, opts=None):
    opts = opts or {}
    scratch_total = 0
    rows = []
    for item in items:
        scratch_total += item.get("duration_ms", 0)
        rows.append(f"{item.get('name')}:{item.get('status')}:{item.get('duration_ms')}")
    if opts.get("include_total"):
        rows.append(f"total:{scratch_total}")
    return "\n".join(rows)
