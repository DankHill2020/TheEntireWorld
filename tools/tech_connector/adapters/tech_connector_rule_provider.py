"""Tech Connector domain rules supplied as data to the runtime."""

from __future__ import annotations

from reasoning_runtime import ReasoningRule, RuleProvider, RuleSet


class TechConnectorRuleProvider(RuleProvider):
    """Provide DCC/game-development rules without embedding them in the runtime."""

    name = "tech_connector_rules"

    def get_rule_sets(self, context: dict) -> list[RuleSet]:
        return [
            RuleSet(
                name="tech_connector_dcc_boundaries",
                rules=(
                    ReasoningRule(
                        key="runtime_no_dcc_imports",
                        description="reasoning_runtime must not import Tech Connector, DCC bridges, or host API modules.",
                        severity="error",
                        applies_to=("architecture", "code_generation"),
                    ),
                    ReasoningRule(
                        key="host_execution_through_bridges",
                        description="Maya, Unreal, Blender, and other host operations must execute through Tech Connector bridge/capability adapters.",
                        severity="error",
                        applies_to=("execution", "code_generation"),
                    ),
                    ReasoningRule(
                        key="validate_live_side_effects",
                        description="DCC mutations require proof such as compile logs, scene readback, asset existence, or saved-state checks.",
                        severity="warning",
                        applies_to=("validation",),
                    ),
                ),
            )
        ]
