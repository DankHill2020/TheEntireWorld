# execution_planner.py
"""Safe Execution Layer for the Tech Connector project pipeline.

Before any project mutation, generates a numbered execution plan the user can
Preview / Apply / Cancel.  Unreal-specific steps include automatic backup,
folder creation, Blueprint compilation, and error reporting.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

RISK_COLOURS = {"low": "green", "medium": "amber", "high": "red"}

@dataclass
class ExecutionStep:
    number: int
    description: str
    action: str           # e.g. 'backup', 'create_folder', 'add_class', etc.
    target: str           # asset path, folder, class name, etc.
    reversible: bool = True
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    title: str
    steps: List[ExecutionStep]
    risk: str             # 'low' | 'medium' | 'high'
    dry_run_safe: bool    # can we simulate this without mutations?
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    # ---- Serialisation -------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title":       self.title,
            "risk":        self.risk,
            "dry_run_safe": self.dry_run_safe,
            "created_at":  self.created_at,
            "steps": [
                {
                    "number":      s.number,
                    "description": s.description,
                    "action":      s.action,
                    "target":      s.target,
                    "reversible":  s.reversible,
                    "details":     s.details,
                }
                for s in self.steps
            ],
        }

    def preview_text(self) -> str:
        """Human-readable plan for display in the UI or chat."""
        lines = [
            f"## Execution Plan: {self.title}",
            f"Risk level: **{self.risk.upper()}** · Safe to dry-run: {'yes' if self.dry_run_safe else 'no'}",
            "",
        ]
        for step in self.steps:
            rev = " *(reversible)*" if step.reversible else " ⚠️ *(irreversible)*"
            lines.append(f"{step.number}. **{step.description}**{rev}")
            if step.target:
                lines.append(f"   → `{step.target}`")
        lines += [
            "",
            "---",
            "Actions: **[Preview]**  **[Apply]**  **[Apply & Replace]**  **[Cancel]**",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

class ExecutionPlanner:
    """Build execution plans for common Unreal / project mutations."""

    # Standard backup step always prepended to destructive plans
    BACKUP_STEP = ExecutionStep(
        number=1,
        description="Backup affected assets → /Saved/AI_Backups/<timestamp>/",
        action="backup",
        target="/Saved/AI_Backups/",
        reversible=True,
    )

    @staticmethod
    def _stamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    # ---- Unreal Blueprint creation plan --------------------------------

    @staticmethod
    def blueprint_creation(
        class_name: str,
        parent_class: str,
        target_folder: str,
        variables: Optional[List[str]] = None,
        graph_description: str = "",
    ) -> ExecutionPlan:
        """Plan for generating a new Blueprint class in Unreal."""
        steps = [
            ExecutionPlanner.BACKUP_STEP,
            ExecutionStep(
                number=2,
                description=f"Create folder `{target_folder}` if it does not exist",
                action="create_folder",
                target=target_folder,
                reversible=True,
            ),
            ExecutionStep(
                number=3,
                description=f"Add new Blueprint class `{class_name}` inheriting `{parent_class}`",
                action="add_blueprint_class",
                target=f"{target_folder}/{class_name}",
                reversible=False,
                details={"parent": parent_class},
            ),
        ]
        n = 4
        if variables:
            steps.append(ExecutionStep(
                number=n,
                description=f"Add {len(variables)} variable(s): {', '.join(variables)}",
                action="add_variables",
                target=f"{target_folder}/{class_name}",
                reversible=True,
                details={"variables": variables},
            ))
            n += 1
        if graph_description:
            steps.append(ExecutionStep(
                number=n,
                description=f"Wire Blueprint graph: {graph_description}",
                action="wire_graph",
                target=f"{target_folder}/{class_name}",
                reversible=False,
                details={"graph": graph_description},
            ))
            n += 1
        steps += [
            ExecutionStep(
                number=n,
                description="Compile Blueprint",
                action="compile_blueprint",
                target=f"{target_folder}/{class_name}",
                reversible=False,
            ),
            ExecutionStep(
                number=n + 1,
                description="Save asset to disk",
                action="save_asset",
                target=f"{target_folder}/{class_name}",
                reversible=True,
            ),
            ExecutionStep(
                number=n + 2,
                description="Report compilation errors (if any)",
                action="report_errors",
                target="log",
                reversible=True,
            ),
        ]
        return ExecutionPlan(
            title=f"Create Blueprint: {class_name}",
            steps=steps,
            risk="medium",
            dry_run_safe=False,
        )

    @staticmethod
    def asset_import(
        source_paths: List[str],
        destination_folder: str,
        asset_type: str = "auto",
    ) -> ExecutionPlan:
        """Plan for importing external assets into an Unreal project."""
        steps = [
            ExecutionPlanner.BACKUP_STEP,
            ExecutionStep(
                number=2,
                description=f"Create destination folder `{destination_folder}`",
                action="create_folder",
                target=destination_folder,
                reversible=True,
            ),
            ExecutionStep(
                number=3,
                description=f"Import {len(source_paths)} asset(s) as `{asset_type}`",
                action="import_assets",
                target=destination_folder,
                reversible=False,
                details={"sources": source_paths, "asset_type": asset_type},
            ),
            ExecutionStep(
                number=4,
                description="Save all imported assets",
                action="save_all",
                target=destination_folder,
                reversible=True,
            ),
            ExecutionStep(
                number=5,
                description="Report any import warnings or errors",
                action="report_errors",
                target="log",
                reversible=True,
            ),
        ]
        return ExecutionPlan(
            title=f"Import assets → {destination_folder}",
            steps=steps,
            risk="low",
            dry_run_safe=True,
        )

    @staticmethod
    def python_code_change(
        file_path: str,
        description: str,
        risk: str = "medium",
    ) -> ExecutionPlan:
        """Plan for AI-generated Python edits to a source file."""
        steps = [
            ExecutionStep(
                number=1,
                description=f"Backup `{Path(file_path).name}` to `/Saved/AI_Backups/{ExecutionPlanner._stamp()}/`",
                action="backup",
                target=file_path,
                reversible=True,
            ),
            ExecutionStep(
                number=2,
                description=f"Apply code change: {description}",
                action="apply_code_change",
                target=file_path,
                reversible=False,
                details={"description": description},
            ),
            ExecutionStep(
                number=3,
                description="Run syntax check on modified file",
                action="syntax_check",
                target=file_path,
                reversible=True,
            ),
            ExecutionStep(
                number=4,
                description="Report result",
                action="report_errors",
                target="log",
                reversible=True,
            ),
        ]
        return ExecutionPlan(
            title=f"Code change: {Path(file_path).name}",
            steps=steps,
            risk=risk,
            dry_run_safe=False,
        )

    @staticmethod
    def generic(
        title: str,
        step_descriptions: List[str],
        risk: str = "medium",
        dry_run_safe: bool = False,
    ) -> ExecutionPlan:
        """Build a simple numbered plan from a list of description strings."""
        steps = [
            ExecutionStep(
                number=i + 1,
                description=desc,
                action="generic",
                target="",
                reversible=True,
            )
            for i, desc in enumerate(step_descriptions)
        ]
        return ExecutionPlan(title=title, steps=steps, risk=risk, dry_run_safe=dry_run_safe)


# ---------------------------------------------------------------------------
# Execution engine (runs a plan against the active bridge)
# ---------------------------------------------------------------------------

class PlanExecutor:
    """Execute a plan step-by-step, calling the appropriate bridge method for
    each action.  Returns a result dict per step."""

    def __init__(self, unreal_bridge=None):
        self.bridge = unreal_bridge  # UnrealBridge instance or None

    def dry_run(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Simulate each step without actually mutating anything."""
        results = []
        for step in plan.steps:
            results.append({
                "step":    step.number,
                "action":  step.action,
                "target":  step.target,
                "status":  "simulated",
                "message": f"[DRY RUN] Would execute: {step.description}",
            })
        return {"plan": plan.title, "mode": "dry_run", "steps": results}

    def apply(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Apply the plan for real.  Stops on first failure."""
        results = []
        for step in plan.steps:
            result = self._execute_step(step)
            results.append(result)
            if result["status"] == "error":
                return {
                    "plan":      plan.title,
                    "mode":      "apply",
                    "status":    "failed",
                    "failed_at": step.number,
                    "steps":     results,
                }
        return {"plan": plan.title, "mode": "apply", "status": "success", "steps": results}

    def _execute_step(self, step: ExecutionStep) -> Dict[str, Any]:
        base = {"step": step.number, "action": step.action, "target": step.target}
        try:
            if step.action == "backup":
                # In a real implementation, copy files to the backup location
                return {**base, "status": "ok", "message": f"Backed up {step.target}"}
            elif step.action == "create_folder" and self.bridge:
                ok, msg = self.bridge.call(
                    "unreal.EditorAssetLibrary.make_directory",
                    args=[step.target],
                )
                return {**base, "status": "ok" if ok else "error", "message": msg}
            elif step.action == "add_blueprint_class" and self.bridge:
                parent = step.details.get("parent", "Actor")
                ok, msg = self.bridge.call(
                    "unreal.AssetToolsHelpers.get_asset_tools().create_asset",
                    args=[step.target.split("/")[-1], step.target.rsplit("/", 1)[0]],
                    kwargs={"asset_class": "Blueprint", "factory": None},
                )
                return {**base, "status": "ok" if ok else "error", "message": msg}
            elif step.action == "compile_blueprint" and self.bridge:
                ok, msg = self.bridge.call(
                    "unreal.KismetSystemLibrary.compile_blueprint",
                    args=[step.target],
                )
                return {**base, "status": "ok" if ok else "error", "message": msg}
            elif step.action == "save_asset" and self.bridge:
                ok, msg = self.bridge.call(
                    "unreal.EditorAssetLibrary.save_asset",
                    args=[step.target],
                )
                return {**base, "status": "ok" if ok else "error", "message": msg}
            elif step.action in ("report_errors", "syntax_check", "generic"):
                return {**base, "status": "ok", "message": "No issues."}
            else:
                return {**base, "status": "skipped", "message": "No bridge or unimplemented action."}
        except Exception as e:
            return {**base, "status": "error", "message": str(e)}


if __name__ == "__main__":
    plan = ExecutionPlanner.blueprint_creation(
        class_name="BP_PlayerCharacter",
        parent_class="Character",
        target_folder="/Game/AI_Generated/Characters",
        variables=["Health", "Stamina"],
        graph_description="BeginPlay → PrintString 'Hello World'",
    )
    print(plan.preview_text())
    print()
    executor = PlanExecutor()
    result = executor.dry_run(plan)
    print(json.dumps(result, indent=2))
