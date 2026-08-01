"""Reasoning guidance for Tech Connector's DCC/game-development domain."""

from __future__ import annotations

from typing import Any

from reasoning_runtime import ReasoningAdapter


class DccReasoningAdapter(ReasoningAdapter):
    """Provide DCC vocabulary, prompt overlays, and knowledge-gap policy."""

    name = "tech_connector_reasoning"

    def get_system_instructions(self) -> str:
        return (
            "Tech Connector focuses on safe DCC and game-development automation. "
            "Resolve project context, prefer registered tools, validate host-side "
            "effects, and preserve evidence for each action."
        )

    def get_domain_vocabulary(self) -> dict[str, Any]:
        return {
            "hosts": [
                "maya",
                "unreal",
                "blender",
                "motionbuilder",
                "substance_painter",
                "unity",
                "houdini",
            ],
            "tool_packages": [
                "maya_tools",
                "unreal_tools",
                "blender_tools",
                "motionbuilder_tools",
                "substance_painter_tools",
                "unity_tools",
            ],
            "artifact_types": [
                "fbx",
                "uasset",
                "blueprint",
                "skeletal_mesh",
                "static_mesh",
                "material",
                "animation_sequence",
            ],
        }

    def get_gap_policies(self) -> list[dict[str, Any]]:
        return [
            {
                "gap": "unknown_host_api",
                "strategy": "search project index, registered operation catalogs, and host reflection before code generation",
            },
            {
                "gap": "missing_live_validation",
                "strategy": "prefer bridge readback, compile logs, asset existence checks, and disposable fixtures",
            },
        ]

    def get_code_generation_rules(self) -> list[str]:
        return [
            "DCC host APIs should be imported at execution time inside host-safe functions.",
            "Generated tools must call real host APIs or registered adapters, not placeholder print loops.",
            "Unreal mutations require compile/save/readback validation where available.",
            "Maya and Blender mutations require scene readback or explicit user-verifiable output.",
        ]

    def get_patch_constraints(self) -> list[str]:
        return [
            "Keep runtime-agnostic logic out of DCC adapters.",
            "Keep DCC-specific imports out of reasoning_runtime.",
            "Route live host execution through Tech Connector bridges.",
        ]
