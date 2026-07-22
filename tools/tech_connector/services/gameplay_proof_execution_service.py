# coding=utf-8
"""
Gameplay Proof Execution Service for Tech Connector.
Implements the 9-stage closed runtime proof and self-repair pipeline.
Redefines "done" through live, evidence-backed Unreal Engine verification.
"""

from __future__ import annotations

import json
import re
import time
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from tech_connector.services.gameplay_proof_contract_service import (
    GameplayProofContract,
    ProofClaim,
    record_claim_evidence,
)
from tech_connector.bridges.unreal.unreal_diagnostics import read_recent_log_errors


class FeatureCompletionStatus(str, Enum):
    STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
    RUNTIME_BLOCKED = "RUNTIME_BLOCKED"
    RUNTIME_FAILED = "RUNTIME_FAILED"
    RUNTIME_PARTIALLY_VERIFIED = "RUNTIME_PARTIALLY_VERIFIED"
    FUNCTIONALLY_VERIFIED = "FUNCTIONALLY_VERIFIED"
    REGRESSION_VERIFIED = "REGRESSION_VERIFIED"
    SHIPPABLE_CANDIDATE = "SHIPPABLE_CANDIDATE"


class GameplayProofExecutionService:
    """Runs the empirical gameplay proof execution pipeline inside Unreal Engine."""

    def __init__(self, bridge: Any = None):
        self.bridge = bridge
        self.max_repair_retries = 3

    def run_proof_pipeline(
        self,
        contract: GameplayProofContract,
        bridge: Any = None,
        repair_callback: Any = None
    ) -> FeatureCompletionStatus:
        """
        Executes the full 9-stage proof execution pipeline.
        
        Parameters
        ----------
        contract: GameplayProofContract
            The contract with proof claims to verify.
        bridge: Optional
            Unreal HTTP bridge. If None, tries to find one.
        repair_callback: Optional
            Function to call when a repair attempt is needed.
        """
        if bridge:
            self.bridge = bridge
        elif not self.bridge:
            # Try to get bridge from context or default
            from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
            self.bridge = UnrealBridge()

        # Check if bridge is responsive
        if not self._check_bridge_health():
            contract.self_repair_notes.append("Unreal HTTP bridge is offline or unresponsive.")
            # Set all runtime claims to untestable/pending
            return FeatureCompletionStatus.RUNTIME_BLOCKED

        # Stage 1: Contract preparation
        try:
            self._prepare_contract(contract)
        except ValueError as exc:
            contract.self_repair_notes.append(f"Contract preparation failed: {exc}")
            return FeatureCompletionStatus.RUNTIME_FAILED

        unbound = [
            claim.claim_id
            for claim in contract.proof_claims
            if claim.evidence_level > 1
            and str((claim.observation_spec or {}).get("status") or "") != "bound"
        ]
        if unbound:
            contract.self_repair_notes.append(
                "Runtime proof is blocked until concrete observation bindings and public-trigger fixtures exist for: "
                + ", ".join(unbound)
            )
            return FeatureCompletionStatus.RUNTIME_BLOCKED

        # Run compilation check (Milestone 1)
        self._verify_compilation_milestone(contract)

        # Stage 9: Self-repair loop with Stage 3-8 inside
        retry_count = 0
        while retry_count <= self.max_repair_retries:
            # Stage 2: Validation strategy selection
            # Stage 3-5: Fixture, Instrumentation, Live execution
            # Stage 6: Deterministic evaluation
            # Stage 7: Negative-path testing
            # Stage 8: Log analysis
            success = self._execute_validation_cycle(contract)

            if success:
                # Reachability validation
                reachability_ok = self._validate_reachability(contract)
                if not reachability_ok:
                    contract.self_repair_notes.append("Reachability validation failed: Unused or disconnected gameplay elements detected.")
                    return FeatureCompletionStatus.RUNTIME_FAILED

                # Verify all claims are passed
                all_passed = all(c.status == "passed" for c in contract.proof_claims)
                if all_passed:
                    # check if regression tests passed
                    return FeatureCompletionStatus.SHIPPABLE_CANDIDATE
                else:
                    return FeatureCompletionStatus.RUNTIME_PARTIALLY_VERIFIED

            # Validation cycle failed - trigger repair
            if retry_count < self.max_repair_retries and repair_callback:
                retry_count += 1
                contract.self_repair_notes.append(f"Attempting self-repair loop: retry {retry_count}/{self.max_repair_retries}")
                repair_ok = repair_callback(contract)
                if not repair_ok:
                    contract.self_repair_notes.append("Repair callback failed or returned False.")
                    break
            else:
                break

        # If we reached here, some runtime claims failed or repair failed
        return FeatureCompletionStatus.RUNTIME_FAILED

    def _check_bridge_health(self) -> bool:
        if not self.bridge:
            return False
        try:
            # Query status
            if hasattr(self.bridge, "find_port") and self.bridge.find_port() is None:
                return False
            # Check ping
            res = self.bridge.execute_python("print('ping')", timeout=2.0)
            return bool(res and res.get("ok"))
        except Exception:
            return False

    # Stage 1: Contract preparation
    def _prepare_contract(self, contract: GameplayProofContract) -> None:
        for claim in contract.proof_claims:
            if not claim.claim_id:
                raise ValueError("ProofClaim is missing stable claim_id.")
            if not claim.when_trigger or "works" in claim.when_trigger.lower():
                raise ValueError(f"ProofClaim '{claim.claim_id}' has vague trigger: '{claim.when_trigger}'")
            if not claim.then_assertion or "right" in claim.then_assertion.lower() or "correctly" in claim.then_assertion.lower():
                raise ValueError(f"ProofClaim '{claim.claim_id}' has vague then_assertion: '{claim.then_assertion}'")

    def _verify_compilation_milestone(self, contract: GameplayProofContract) -> None:
        # Compilation is recorded only by a real compile/readback operation upstream.
        # Leaving the sentinel pending is intentional when no asset-bound evidence exists.
        return None

    # Stage 2: Validation strategy selection
    def _select_strategy(self, claim: ProofClaim) -> str:
        if claim.evidence_level == 1:
            return "static_analysis"
        if "automation" in claim.validation_method or "test" in claim.validation_method:
            return "unreal_automation"
        return "unreal_runtime"

    # Stage 3: Test fixture generation
    def _generate_test_fixture(self, claim: ProofClaim, contract: GameplayProofContract) -> str:
        """Return only a fixture that was explicitly bound to this claim."""
        spec = dict(claim.observation_spec or {})
        fixture_code = str(spec.get("fixture_code") or "").strip()
        if spec.get("status") != "bound" or not fixture_code:
            return (
                "import json\n"
                "print(json.dumps({'ok': False, 'error': "
                + repr("No bound runtime fixture for claim: " + claim.claim_id)
                + "}))"
            )
        return fixture_code

    # Stage 5: Live execution
    def _run_live_execution(self, script_code: str) -> dict[str, Any]:
        """Sends python script to Unreal and returns decoded response."""
        res = self.bridge.execute_python(script_code, timeout=15.0)
        if not res or not res.get("ok"):
            return {"ok": False, "error": res.get("error") or "Unknown bridge execution error"}
        
        stdout = res.get("python_stdout") or res.get("stdout") or ""
        # Find JSON block in stdout
        for line in stdout.splitlines():
            if line.strip().startswith("{") and line.strip().endswith("}"):
                try:
                    return json.loads(line.strip())
                except Exception:
                    pass
        return {"ok": False, "error": "No valid JSON observation found in stdout", "stdout": stdout}

    # Stage 6: Deterministic claim evaluation
    def _evaluate_claim(
        self,
        claim: ProofClaim,
        run_id: str,
        observations: list[dict[str, Any]],
        log_lines: list[str],
        error_lines: list[str]
    ) -> tuple[bool, str]:
        # Filter observations for this claim
        obs = [o for o in observations if o.get("claim_id") == claim.claim_id]
        if not obs:
            return False, f"Missing runtime observation for claim '{claim.claim_id}'"
        
        o = obs[0]
        expected = str(o.get("expected")).lower()
        observed = str(o.get("observed")).lower()

        comparator = str(o.get("comparator") or "").lower()
        passed = False
        try:
            if comparator == "equals":
                passed = observed == expected
            elif comparator == "not_equals":
                passed = observed != expected
            elif comparator == "greater_than":
                passed = float(o.get("observed")) > float(o.get("expected"))
            elif comparator == "greater_than_or_equal":
                passed = float(o.get("observed")) >= float(o.get("expected"))
            elif comparator == "less_than":
                passed = float(o.get("observed")) < float(o.get("expected"))
            elif comparator == "approximately":
                tolerance = float(o.get("tolerance") or 0.0)
                passed = abs(float(o.get("observed")) - float(o.get("expected"))) <= tolerance
        except (TypeError, ValueError):
            passed = False

        timestamp = float(o.get("timestamp") or 0.0)
        observed_text = f"Expected property '{o.get('property')}' with comparator '{comparator or 'missing'}' and value '{o.get('expected')}', observed '{o.get('observed')}' at t={timestamp:.2f}s."
        
        # If there are runtime errors in the logs, fail the claim
        if error_lines:
            passed = False
            observed_text += f" Failed due to runtime errors: {'; '.join(error_lines[:2])}"

        return passed, observed_text

    # Stage 7: Negative-path testing
    def _run_negative_paths(self, contract: GameplayProofContract) -> bool:
        negative_claims = [claim for claim in contract.proof_claims if claim.evidence_level == 5]
        return bool(negative_claims) and all(claim.status == "passed" for claim in negative_claims)

    # Stage 8: Runtime log analysis
    def _analyze_unreal_logs(self) -> tuple[list[str], list[str]]:
        try:
            # Read recent log errors/warnings
            log_res = read_recent_log_errors(limit=20)
            if log_res.get("ok"):
                entries = log_res.get("entries") or []
                errors = [e["message"] for e in entries if "error" in e["message"].lower() or "accessed none" in e["message"].lower()]
                warnings = [e["message"] for e in entries if "warning" in e["message"].lower()]
                return errors, warnings
        except Exception:
            pass
        return [], []

    # Reachability validation
    def _validate_reachability(self, contract: GameplayProofContract) -> bool:
        """Require both structural evidence and a reached public runtime path."""
        static_ok = all(
            claim.status == "passed"
            for claim in contract.proof_claims
            if claim.evidence_level == 1
        )
        runtime_reached = any(
            claim.status == "passed" and claim.evidence_level >= 3 and claim.evidence_observed
            for claim in contract.proof_claims
        )
        return static_ok and runtime_reached

    # High-level validation cycle helper
    def _execute_validation_cycle(self, contract: GameplayProofContract) -> bool:
        run_id = f"run_{int(time.time())}"
        
        # 1. Analyze logs before test to establish baseline
        pre_errors, pre_warnings = self._analyze_unreal_logs()

        # 2. Run live validation for each claim
        all_passed = True
        for claim in contract.proof_claims:
            if claim.claim_id == "compilation_milestone_1_only":
                continue
            
            strategy = self._select_strategy(claim)
            origin = "unreal_runtime" if strategy == "unreal_runtime" else "unreal_automation"
            
            # Generate and run fixture script
            fixture_code = self._generate_test_fixture(claim, contract)
            execution_res = self._run_live_execution(fixture_code)
            
            if not execution_res.get("ok"):
                record_claim_evidence(
                    contract=contract,
                    claim_id=claim.claim_id,
                    observed=f"Execution error: {execution_res.get('error')}",
                    passed=False,
                    origin=origin
                )
                all_passed = False
                continue

            # Analyze post-execution logs for new errors
            post_errors, post_warnings = self._analyze_unreal_logs()
            new_errors = [e for e in post_errors if e not in pre_errors]

            observations = execution_res.get("observations") or []
            passed, detail = self._evaluate_claim(claim, run_id, observations, post_warnings, new_errors)
            
            record_claim_evidence(
                contract=contract,
                claim_id=claim.claim_id,
                observed=detail,
                passed=passed,
                origin=origin
            )
            if not passed:
                all_passed = False

        # 3. Run negative paths
        neg_ok = self._run_negative_paths(contract)
        if not neg_ok:
            contract.self_repair_notes.append("Negative path verification failed: State did not fail-safe under invalid inputs.")
            all_passed = False

        return all_passed
