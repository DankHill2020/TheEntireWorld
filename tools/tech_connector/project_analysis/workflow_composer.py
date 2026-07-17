# workflow_composer.py
"""Workflow Composer for the Tech Connector project pipeline.

Finds existing capabilities, identifies gaps, generates adapter stubs,
composes them into a runnable workflow, and saves the result as a new
capability in the registry.
"""
from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from tech_connector.project_analysis.capability_registry import (
    find_capabilities,
    register_capability,
    compose_workflow,
)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class WorkflowStep:
    """A single step in a composed workflow."""
    name: str
    source: str           # 'existing' | 'generated' | 'adapted'
    capability: Optional[Dict[str, Any]] = None
    adapter_code: str = ""
    description: str = ""


@dataclass
class ComposedWorkflow:
    title: str
    steps: List[WorkflowStep]
    composed_code: str
    missing_capabilities: List[str]
    risk: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def summary(self) -> str:
        lines = [f"## Workflow: {self.title}", f"Risk: **{self.risk}**", ""]
        for i, step in enumerate(self.steps, 1):
            badge = {"existing": "✅", "generated": "🔧", "adapted": "🔀"}.get(step.source, "•")
            lines.append(f"{i}. {badge} **{step.name}** ({step.source})")
            if step.description:
                lines.append(f"   *{step.description}*")
        if self.missing_capabilities:
            lines += ["", "⚠️ **Missing capabilities (stubs generated):**"]
            for m in self.missing_capabilities:
                lines.append(f"- `{m}`")
        lines += ["", "### Composed code", "```python", self.composed_code, "```"]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------

class WorkflowComposer:
    """Composes a multi-step workflow from capability names.

    Usage:
        composer = WorkflowComposer()
        result = composer.compose(
            title="Import animation and build motion matching set",
            steps=["import_animation_sequence", "create_motion_matching_database"],
        )
        print(result.summary())
    """

    def __init__(self):
        self._generated_stubs: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compose(
        self,
        title: str,
        steps: List[str],
        app: Optional[str] = None,
        dry_run: bool = True,
    ) -> ComposedWorkflow:
        """Build a workflow from a list of capability names.

        1. Search the registry for each capability.
        2. For missing ones, generate a stub.
        3. Produce adapter glue if signatures are incompatible.
        4. Assemble the composed function body.
        5. Optionally save as a new capability.
        """
        resolved_steps: List[WorkflowStep] = []
        missing: List[str] = []

        for cap_name in steps:
            caps = find_capabilities(cap_name, app=app, max_results=1)
            if caps:
                cap = caps[0]
                resolved_steps.append(WorkflowStep(
                    name=cap["name"],
                    source="existing",
                    capability=cap,
                    description=cap.get("docstring", "")[:100],
                ))
            else:
                stub = self._generate_stub(cap_name, app=app)
                resolved_steps.append(WorkflowStep(
                    name=cap_name,
                    source="generated",
                    adapter_code=stub,
                    description=f"Auto-generated stub for missing capability `{cap_name}`",
                ))
                missing.append(cap_name)

        composed_code = self._assemble(title, resolved_steps)
        risk = self._calculate_risk(resolved_steps)

        return ComposedWorkflow(
            title=title,
            steps=resolved_steps,
            composed_code=composed_code,
            missing_capabilities=missing,
            risk=risk,
        )

    def save_as_capability(
        self,
        workflow: ComposedWorkflow,
        source_file: str = "workflow_composer_output.py",
        app: str = "General",
    ) -> int:
        """Register the composed workflow as a new reusable capability."""
        fn_name = workflow.title.lower().replace(" ", "_").replace("-", "_")
        return register_capability({
            "name":        fn_name,
            "app":         app,
            "inputs":      [],
            "outputs":     [],
            "requires":    [],
            "risk":        workflow.risk,
            "source_file": source_file,
            "lineno":      None,
            "docstring":   f"Composed workflow: {workflow.title}",
            "signature":   f"{fn_name}()",
            "tags":        ["composed", "workflow"],
        })

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_stub(self, name: str, app: Optional[str] = None) -> str:
        """Generate a Python stub function for a missing capability."""
        docstring = (
            f'"""Auto-generated stub for: {name}\n\n'
            f'    TODO: Implement this function.\n'
            f'    App context: {app or "General"}\n    """\n'
        )
        stub = textwrap.dedent(f"""\
            def {name}(*args, **kwargs):
                {docstring}
                raise NotImplementedError(
                    f"{name} has not been implemented yet. "
                    "Replace this stub with the real implementation."
                )
        """)
        self._generated_stubs[name] = stub
        return stub

    def _generate_adapter(
        self,
        from_cap: Dict[str, Any],
        to_cap: Dict[str, Any],
    ) -> str:
        """Generate simple adapter glue between two capabilities."""
        from_name = from_cap["name"]
        to_name   = to_cap["name"]
        return textwrap.dedent(f"""\
            def _adapt_{from_name}_to_{to_name}(result):
                \"\"\"Adapter: pipe output of `{from_name}` into `{to_name}`.\"\"\"
                # TODO: Map fields between the two capability contracts.
                return result
        """)

    def _assemble(self, title: str, steps: List[WorkflowStep]) -> str:
        """Produce a single composed Python function from the resolved steps."""
        fn_name = title.lower().replace(" ", "_").replace("-", "_")[:60]
        lines = [
            f'def {fn_name}(**kwargs):',
            f'    """Composed workflow: {title}',
            f'',
            f'    Generated by WorkflowComposer on {datetime.now().strftime("%Y-%m-%d")}.',
            f'    Steps:',
        ]
        for i, step in enumerate(steps, 1):
            lines.append(f'        {i}. {step.name} ({step.source})')
        lines += [
            '    """',
            '    results = {}',
            '',
        ]
        # Emit stub definitions inline for generated capabilities
        for step in steps:
            if step.source == "generated" and step.adapter_code:
                for line in step.adapter_code.splitlines():
                    lines.append(f"    {line}")
                lines.append('')

        # Call chain
        prev_result = None
        for step in steps:
            call_args = f"**kwargs" if prev_result is None else f"result=results.get('{prev_result}'), **kwargs"
            lines.append(f"    results['{step.name}'] = {step.name}({call_args})")
            prev_result = step.name

        lines += [
            '',
            '    return results',
        ]
        return '\n'.join(lines)

    @staticmethod
    def _calculate_risk(steps: List[WorkflowStep]) -> str:
        risk_order = {"low": 0, "medium": 1, "high": 2}
        highest = "low"
        for step in steps:
            r = step.capability.get("risk", "low") if step.capability else "medium"
            if risk_order.get(r, 0) > risk_order.get(highest, 0):
                highest = r
        return highest


if __name__ == "__main__":
    composer = WorkflowComposer()
    result = composer.compose(
        title="Import animation and build motion matching database",
        steps=["import_animation_sequence", "create_motion_matching_database"],
        app="Unreal",
    )
    print(result.summary())
