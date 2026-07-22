# coding=utf-8
"""
    System Impact and QA Testing Reporter Engine for Tech Connector.
    Provides comprehensive reporting for ANY system modification detailing affected assets,
    changes made, step-by-step testing instructions, and potential impact/regression lists.
"""

import os
import sys
import json
from pathlib import Path


class SystemImpactQAReporter:
    """
        Generates standardized, evidence-backed System Impact & QA Testing Reports.
    """

    def __init__(self, system_name: str, task_description: str):
        """
            Initializes the QA reporter for a given system operation.
        :param system_name: name of the system or tool modified
        :param task_description: description of the task executed
        """
        self.system_name = system_name
        self.task_description = task_description
        self.affected_assets = []
        self.modifications_detail = []
        self.testing_instructions = []
        self.potential_impacts = []

    def add_affected_asset(self, asset_path: str, asset_type: str, action: str = "Modified"):
        """
            Registers an affected asset or source file.
        :param asset_path: file path or Unreal package path
        :param asset_type: asset type string (e.g. Blueprint, AnimBlueprint, PythonModule, Widget)
        :param action: action performed (Created, Modified, Injected, Compiled)
        :return: None
        """
        self.affected_assets.append({
            "asset_path": asset_path,
            "asset_type": asset_type,
            "action": action
        })

    def add_modification_detail(self, category: str, details: str):
        """
            Adds specific details of what was touched on an asset.
        :param category: category (e.g. Variables, Functions, Settings, Nodes, Pipeline)
        :param details: detailed description of modification
        :return: None
        """
        self.modifications_detail.append({
            "category": category,
            "details": details
        })

    def add_test_step(self, step_number: int, input_trigger: str, expected_behavior: str):
        """
            Adds a step-by-step testing instruction.
        :param step_number: numeric order of test step
        :param input_trigger: key press or user action required
        :param expected_behavior: expected result in-game or in-editor
        :return: None
        """
        self.testing_instructions.append({
            "step": step_number,
            "trigger": input_trigger,
            "expected_behavior": expected_behavior
        })

    def add_potential_impact(self, component_name: str, risk_description: str, recommended_check: str):
        """
            Adds a potential downstream impact or regression test recommendation.
        :param component_name: impacted component or system name
        :param risk_description: potential risk or side-effect
        :param recommended_check: recommended verification step
        :return: None
        """
        self.potential_impacts.append({
            "component": component_name,
            "risk": risk_description,
            "recommended_check": recommended_check
        })

    def generate_report_markdown(self) -> str:
        """
            Renders the complete System Impact & QA Testing Report in Github Markdown.
        :return: formatted report string
        """
        lines = []
        lines.append(f"# System Impact & QA Testing Report: {self.system_name}")
        lines.append(f"**Task Description**: {self.task_description}\n")

        # Section 1: Affected Assets & Files
        lines.append("## 1. Affected Assets & Code Files")
        if self.affected_assets:
            lines.append("| Asset / File Path | Asset Type | Action |")
            lines.append("| :--- | :--- | :--- |")
            for item in self.affected_assets:
                lines.append(f"| `{item['asset_path']}` | {item['asset_type']} | **{item['action']}** |")
        else:
            lines.append("No specific assets recorded.")
        lines.append("")

        # Section 2: What Was Touched / Changed
        lines.append("## 2. Modifications Detail (What Was Touched)")
        if self.modifications_detail:
            for item in self.modifications_detail:
                lines.append(f"- **[{item['category']}]**: {item['details']}")
        else:
            lines.append("No modifications detailed.")
        lines.append("")

        # Section 3: How to Test in Game / Editor
        lines.append("## 3. Step-by-Step Test Instructions (Zero Manual Setup Required)")
        if self.testing_instructions:
            lines.append("| Step | Input / Action Trigger | Expected In-Game / Editor Result |")
            lines.append("| :---: | :--- | :--- |")
            for item in self.testing_instructions:
                lines.append(f"| {item['step']} | **`{item['trigger']}`** | {item['expected_behavior']} |")
        else:
            lines.append("No test steps specified.")
        lines.append("")

        # Section 4: Potential Impacts & Regression Verification
        lines.append("## 4. Potential Downstream Impacts & Recommended Checks")
        if self.potential_impacts:
            for item in self.potential_impacts:
                lines.append(f"- **Component**: `{item['component']}`")
                lines.append(f"  - *Potential Risk*: {item['risk']}")
                lines.append(f"  - *Recommended Check*: {item['recommended_check']}")
        else:
            lines.append("No downstream impact risks identified.")
        lines.append("")

        lines.append("---")
        lines.append("> **Zero-Manual-Steps Policy**: All targets resolved, assets modified, and code compiled automatically. The system is ready for testing.")

        return "\n".join(lines)

    def generate_report_dict(self) -> dict:
        """
            Generates dictionary representation of the report.
        :return: report dictionary
        """
        return {
            "system_name": self.system_name,
            "task_description": self.task_description,
            "affected_assets": self.affected_assets,
            "modifications_detail": self.modifications_detail,
            "testing_instructions": self.testing_instructions,
            "potential_impacts": self.potential_impacts,
            "markdown_report": self.generate_report_markdown(),
        }
