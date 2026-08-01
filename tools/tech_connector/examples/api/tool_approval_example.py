"""Inspect runtime tool risk and perform a non-executing dry run."""

from __future__ import annotations

import json

from tech_connector.api import create_api


def main() -> None:
    api = create_api()
    tools_result = api.reasoning.tools()
    if not tools_result.ok:
        raise SystemExit(tools_result.error)

    tools = tools_result.result["tools"]
    for tool in tools:
        print(tool["name"], tool["mutability"], tool["risk"])

    mutable = next(
        (tool for tool in tools if tool["mutability"] != "read_only"),
        None,
    )
    if mutable is None:
        print("No mutating runtime tool is currently registered.")
        return

    preview = api.reasoning.execute_tool(
        mutable["name"],
        {},
        dry_run=True,
    )
    if not preview.ok:
        raise SystemExit(preview.error)
    print(json.dumps(preview.result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

