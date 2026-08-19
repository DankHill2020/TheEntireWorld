from __future__ import annotations

import unittest

from tech_connector.services.capability_implementation_provider import (
    ModelBackedCapabilityImplementationProvider,
)
from tech_connector.services.reasoning.semantic_execution_contract_service import (
    build_requirement_fulfillment_links,
    build_requirement_verification_chunks,
)
from tech_connector.services.prompt.prompt_plan_verification_service import (
    build_requirement_omission_cases,
)


class RequirementFulfillmentTests(unittest.TestCase):
    def test_existing_contracts_become_stable_domain_neutral_chunks(self) -> None:
        chunks = build_requirement_verification_chunks(
            "Create a retargeter, map the arm chains, save it, and verify the mapping.",
            semantic_contract={
                "goal": "Create a usable IK retargeter.",
                "expected_outputs": ["Saved IK Retargeter asset"],
                "evidence_required": ["Chain mapping readback"],
                "success_definition": "The saved mapping matches the requested source and target chains.",
            },
            behavior_contract={
                "required_parameter_names": ["SourceChain", "TargetChain"],
                "required_result_evidence": ["Compile/save result", "Chain mapping readback"],
            },
            candidate_steps=[
                "Create and save the IK Retargeter asset.",
                "Map SourceChain to TargetChain and return chain mapping readback.",
            ],
        )

        self.assertGreaterEqual(len(chunks), 5)
        self.assertEqual(len({row["id"] for row in chunks}), len(chunks))
        self.assertTrue(any(row["source"].endswith("evidence_required") for row in chunks))
        self.assertTrue(any("SourceChain" in row["requirement"] for row in chunks))
        self.assertTrue(any(row["evidence_score"] > 0 for row in chunks))

    def test_fulfillment_links_preserve_requirement_to_proof_chain(self) -> None:
        chunks = [{
            "id": "mapping_1234",
            "requirement": "Return chain mapping readback.",
            "source": "requested_behavior_contract.required_result_evidence",
            "evidence": "Map both chains and return chain mapping readback.",
        }]
        links = build_requirement_fulfillment_links(
            chunks,
            operation="retarget.set_chain_mapping",
            artifacts=["unreal_tools/retarget.py", "AIStudioBridgeLibrary.cpp"],
            validation_evidence=[{"ok": True, "mapping": "Arm_L -> LeftArm"}],
        )

        self.assertEqual("validated", links[0]["status"])
        self.assertEqual("retarget.set_chain_mapping", links[0]["operation"])
        self.assertEqual(2, len(links[0]["implementation_artifacts"]))
        self.assertEqual(True, links[0]["validation_evidence"][0]["ok"])

    def test_artifact_diagnostics_select_only_the_owning_group(self) -> None:
        changes = [
            {"path": "plugins/AIStudioBridge/Source/AIStudioBridge/Private/AIStudioBridgeLibrary.cpp"},
            {"path": "plugins/AIStudioBridge/Source/AIStudioBridge/Public/AIStudioBridgeLibrary.h"},
            {"path": "unreal_tools/retarget.py"},
            {"path": "tech_connector/examples/tests/test_unreal_execution_pipeline.py"},
        ]

        selected = ModelBackedCapabilityImplementationProvider._affected_artifact_paths(
            changes,
            ["C++ compiler failed in AIStudioBridgeLibrary.cpp"],
        )

        self.assertEqual(
            {"plugins/AIStudioBridge/Source/AIStudioBridge/Private/AIStudioBridgeLibrary.cpp"},
            selected,
        )

    def test_negative_cases_remove_exactly_one_requirement_commitment(self) -> None:
        steps = [
            "Create and save the retargeter.",
            "Map the arm chains.",
            "Read back the resulting chain mapping.",
        ]
        chunks = [
            {"id": "create", "requirement": "Create it.", "evidence": steps[0]},
            {"id": "map", "requirement": "Map chains.", "evidence": steps[1]},
            {"id": "proof", "requirement": "Read back mapping.", "evidence": steps[2]},
        ]

        cases = build_requirement_omission_cases(chunks, steps)

        self.assertEqual(3, len(cases))
        for case in cases:
            self.assertEqual(2, len(case["candidate_steps"]))
            self.assertNotIn(case["removed_evidence"], case["candidate_steps"])


if __name__ == "__main__":
    unittest.main()
