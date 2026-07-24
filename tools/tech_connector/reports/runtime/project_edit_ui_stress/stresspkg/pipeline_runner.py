# coding=utf-8
from stresspkg.pipeline_report import format_pipeline_summary


def run_pipeline(job_rows, cfg=None):
    cfg = cfg or {}
    temp_records = []
    unused_debug_counter = 0
    for r in job_rows:
        nm = r.get("name", "")
        st = r.get("status", "")
        ms = r.get("duration_ms", 0)
        if not nm:
            continue
        if st == "skip":
            continue
        temp_records.append({"name": nm.strip(), "status": st or "unknown", "duration_ms": float(ms)})
    if cfg.get("summary"):
        return format_pipeline_summary(temp_records, cfg)
    return temp_records
