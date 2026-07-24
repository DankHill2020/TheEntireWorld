from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tech_connector.services.unreal.unreal_capability_audit_service import (
    audit_unreal_capability_catalogs,
    format_unreal_capability_audit_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Unreal capability catalogs and plugin wrappers.")
    parser.add_argument("--json", action="store_true", help="Print the full audit as JSON.")
    args = parser.parse_args()

    audit = audit_unreal_capability_catalogs()
    if args.json:
        print(json.dumps(audit, indent=2, default=str))
    else:
        print(format_unreal_capability_audit_report(audit))
    return 0 if audit.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
