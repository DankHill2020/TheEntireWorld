"""Code-generation policy for Tech Connector DCC adapters."""

from __future__ import annotations

from typing import Any

from reasoning_runtime import CodeGenerationPolicy, CodeIntelligenceAdapter


class DccCodePolicyAdapter(CodeIntelligenceAdapter):
    """Constrain generated code for host-safe DCC execution."""

    name = "tech_connector_code_policy"

    def get_generation_policy(self, context: dict[str, Any]) -> CodeGenerationPolicy:
        return CodeGenerationPolicy(
            import_rules=(
                "Import maya.cmds, unreal, bpy, and other host modules inside functions that run in that host.",
                "Normal Python processes should call DCC bridge adapters instead of importing host APIs directly.",
            ),
            patch_constraints=(
                "Keep DCC-specific code in tech_connector adapters, bridges, services/dcc, services/unreal, or tool packages.",
                "Do not introduce DCC imports into reasoning_runtime.",
            ),
            validation_commands=(
                "python -m py_compile for changed Python modules",
                "host bridge readback or compile validation for live DCC changes",
            ),
            forbidden_patterns=(
                "placeholder print-only implementation for requested host mutations",
                "runtime package importing tech_connector",
            ),
        )

    def select_tests_for_change(self, changed_files: list[str], context: dict[str, Any]) -> list[str]:
        tests = ["python -m py_compile " + " ".join(changed_files)] if changed_files else []
        if any("unreal" in path.lower() for path in changed_files):
            tests.append("run Unreal compile/readback validation when bridge is available")
        if any("maya" in path.lower() for path in changed_files):
            tests.append("run Maya import/readback validation when bridge is available")
        return tests
