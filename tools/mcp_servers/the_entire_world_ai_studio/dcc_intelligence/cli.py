"""Command line entrypoint for local indexing and context building."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .daemon import DCCIntelligenceService


def main() -> int:
    parser = argparse.ArgumentParser(description="DCC local intelligence layer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Index a project")
    p_index.add_argument("root")
    p_index.add_argument("--dcc", default="generic")
    p_index.add_argument("--name")

    p_context = sub.add_parser("context", help="Build a model-ready context packet")
    p_context.add_argument("root")
    p_context.add_argument("project_id", type=int)
    p_context.add_argument("request")
    p_context.add_argument("--dcc")

    args = parser.parse_args()
    service = DCCIntelligenceService(Path(args.root))
    try:
        if args.command == "index":
            result = service.index_project(args.root, dcc=args.dcc, name=args.name)
        else:
            result = service.build_context(args.project_id, args.request, dcc=args.dcc)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
