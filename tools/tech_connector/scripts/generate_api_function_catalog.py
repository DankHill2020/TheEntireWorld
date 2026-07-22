"""Generate docs/API_FUNCTION_CATALOG.md from DCC tool source."""

from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from tech_connector.api import DCC_API_ALIASES
    from tech_connector.services.api_catalog_service import (
        discover_dcc_api_catalog,
        render_api_function_catalog_markdown,
    )

    catalog = discover_dcc_api_catalog(aliases=DCC_API_ALIASES)
    output_path = root / "tech_connector" / "docs" / "API_FUNCTION_CATALOG.md"
    output_path.write_text(render_api_function_catalog_markdown(catalog), encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
