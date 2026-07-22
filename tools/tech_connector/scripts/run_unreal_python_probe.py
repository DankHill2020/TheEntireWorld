"""Run an Unreal Python probe through the live AI Studio bridge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--code")
    source.add_argument("--code-file", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    code = args.code if args.code is not None else args.code_file.read_text(encoding="utf-8")
    result = UnrealBridge().execute_python(code, timeout=args.timeout, reset_globals=True)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
