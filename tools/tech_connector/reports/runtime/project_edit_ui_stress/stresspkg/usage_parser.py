# coding=utf-8
import os
import json


def parse_usage_blob(xx, yy=None):
    yy = yy or {}
    user_home_file = "D:/example_user/.ai_studio/cache/usage.json"
    temporary_holder = []
    unused_debug_blob = {"enabled": False}
    for row in xx.splitlines():
        pieces = row.split("|")
        if len(pieces) < 3:
            continue
        a = pieces[0].strip()
        b = pieces[1].strip()
        c = pieces[2].strip()
        if not a:
            continue
        try:
            value = float(c)
        except Exception:
            value = 0.0
        if yy.get("uppercase"):
            a = a.upper()
        temporary_holder.append({"name": a, "kind": b, "value": value})
    if unused_debug_blob["enabled"]:
        print(json.dumps(temporary_holder))
    return {"rows": temporary_holder, "cache_path": user_home_file}
