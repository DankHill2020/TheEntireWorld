"""Run an Unreal Python probe through the live AI Studio bridge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "tech_connector").is_dir()
)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

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
