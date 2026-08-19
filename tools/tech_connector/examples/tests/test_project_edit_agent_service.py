from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tech_connector.services.change_history_service import load_change_session, undo_change_session
from tech_connector.services.project_edit_agent_service import (
    apply_project_edit_agent_response,
    apply_project_edit_generated_symbol_repair,
    apply_project_edit_missing_symbol,
    apply_project_edit_syntax_repair,
    build_code_agent_adaptive_plan,
    build_project_edit_agent_request,
    build_project_edit_artifact_file_stages,
    build_project_edit_artifact_manifest_stage,
    build_project_edit_cross_file_failure_notes,
    build_project_edit_requirement_coverage,
    build_project_edit_function_repair_contract,
    build_project_edit_function_repair_plan_stage,
    build_project_edit_function_repair_stage,
    build_project_edit_leaf_candidate,
    build_project_edit_leaf_stage,
    build_project_edit_plan_from_leaf_work_units,
    build_project_edit_model_stages,
    build_project_edit_multi_file_candidate,
    build_project_edit_missing_symbol_stage,
    build_project_edit_repair_stage,
    build_project_edit_syntax_repair_stage,
    compile_project_edit_leaf_work_units,
    complete_project_edit_integration_contract_response,
    compose_project_edit_incremental_manifest_response,
    enforce_project_edit_explicit_cleanup,
    enforce_project_edit_requested_test_contracts,
    extract_project_edit_artifact_requirements,
    format_project_edit_generated_python,
    inspect_project_edit_structured_syntax,
    infer_project_edit_generated_dependencies,
    isolate_project_edit_generated_test_fixture,
    model_for_project_edit_stage,
    normalize_project_edit_async_test_lifecycle,
    parse_project_edit_leaf_source,
    parse_project_edit_artifact_manifest,
    parse_project_edit_generated_file,
    parse_project_edit_function_repair_plan,
    ProjectEditPlan,
    preview_project_edit_agent_response,
    project_edit_artifact_architecture_requires_coder,
    project_edit_file_worker_profile,
    project_edit_file_worker_model_override,
    project_edit_plan_fingerprint,
    project_edit_validation_failure_signature,
    project_edit_leaf_work_units_handoff,
    project_edit_has_core_contract_failure,
    project_edit_preview_error_score,
    render_code_agent_expert_context,
    render_code_agent_adaptive_plan,
    render_grounded_project_edit_handoff,
    render_project_edit_artifact_architecture,
    restore_project_edit_leaf_work_units,
    resolve_project_edit_cross_file_symbols,
    resolve_project_edit_failure_symbol,
    resolve_project_edit_standard_library_symbols,
    remove_project_edit_unused_imports,
    repair_project_edit_duplicate_dependency_symbols,
    select_code_agent_experts,
    ensure_project_edit_requested_docstrings,
    stabilize_project_edit_import_cycles,
    summarize_project_edit_generated_interface,
    validate_project_edit_generated_module_graph,
    validate_project_edit_integration_contract_response,
    render_project_edit_agent_report,
    validate_project_edit_plan_output,
    validate_project_edit_paths,
)
from tech_connector.services.project_service import discover_edit_targets, format_edit_target_context, build_project_edit_target_prompt


class TestProjectEditAgentService(unittest.TestCase):
    ACTIVE_UI_FILE = "C:/depot/tools/custom_qt/custom_widgets.py"

    def test_generated_artifact_manifest_is_validated_and_dependency_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            response = json.dumps({
                "files": [
                    {
                        "path": "tech_connector/examples/tests/test_scheduler.py",
                        "purpose": "Prove scheduling and recovery.",
                        "requirements": ["cycle rejection", "journal replay"],
                        "public_symbols": [],
                        "depends_on": ["tech_connector/services/execution/scheduler.py"],
                        "is_test": True,
                    },
                    {
                        "path": "tech_connector/services/execution/scheduler.py",
                        "purpose": "Execute dependency graphs.",
                        "requirements": ["deterministic topological scheduling"],
                        "public_symbols": ["DependencyScheduler"],
                        "depends_on": [],
                        "is_test": False,
                    },
                ]
            })

            manifest, errors = parse_project_edit_artifact_manifest(
                response,
                project_root=root,
            )

        self.assertEqual([], errors)
        self.assertEqual(
            [
                "tech_connector/services/execution/scheduler.py",
                "tech_connector/examples/tests/test_scheduler.py",
            ],
            [item["path"] for item in manifest],
        )

    def test_generated_artifact_manifest_rejects_unsafe_paths_and_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            unsafe, unsafe_errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "files": [
                        {
                            "path": ".cache/runtime.py",
                            "purpose": "Unsafe.",
                            "requirements": ["bad path"],
                            "public_symbols": [],
                            "depends_on": [],
                            "is_test": False,
                        },
                        {
                            "path": "tests/test_runtime.py",
                            "purpose": "Test.",
                            "requirements": ["proof"],
                            "public_symbols": [],
                            "depends_on": [],
                            "is_test": True,
                        },
                    ]
                }),
                project_root=root,
            )
            cyclic, cyclic_errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "files": [
                        {
                            "path": "pkg/a.py",
                            "purpose": "A.",
                            "requirements": ["A"],
                            "public_symbols": ["A"],
                            "depends_on": ["pkg/b.py"],
                            "is_test": False,
                        },
                        {
                            "path": "pkg/b.py",
                            "purpose": "B.",
                            "requirements": ["B"],
                            "public_symbols": ["B"],
                            "depends_on": ["pkg/a.py"],
                            "is_test": False,
                        },
                        {
                            "path": "tests/test_b.py",
                            "purpose": "Proof.",
                            "requirements": ["test B"],
                            "public_symbols": [],
                            "depends_on": ["pkg/b.py"],
                            "is_test": True,
                        },
                    ]
                }),
                project_root=root,
            )

        self.assertEqual([], unsafe)
        self.assertTrue(any("unsafe" in error.lower() for error in unsafe_errors))
        self.assertEqual([], cyclic)
        self.assertTrue(any("cycle" in error.lower() for error in cyclic_errors))

    def test_generated_artifact_manifest_normalizes_declared_test_path(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "integration_contracts": [
                        "Runtime.commit() and Runtime.recover() share one atomic journal format."
                    ],
                    "files": [
                        {
                            "path": "pkg/runtime.py",
                            "purpose": "Runtime.",
                            "requirements": ["execute"],
                            "public_symbols": ["Runtime"],
                            "depends_on": [],
                            "is_test": False,
                        },
                        {
                            "path": "runtime_tests.py",
                            "purpose": "Proof.",
                            "requirements": ["test execution"],
                            "public_symbols": [],
                            "depends_on": ["pkg/runtime.py"],
                            "is_test": True,
                        },
                    ]
                }),
                project_root=root,
            )

        self.assertEqual([], errors)
        self.assertEqual(
            "tech_connector/examples/tests/test_runtime_tests.py",
            manifest[1]["path"],
        )

    def test_generated_artifact_manifest_matches_existing_src_and_test_layout(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "tech_connector").mkdir()
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "files": [
                        {
                            "path": "src/tech_connector/runtime.py",
                            "purpose": "Runtime.",
                            "requirements": ["execute"],
                            "public_symbols": ["Runtime"],
                            "depends_on": ["hashlib", "pathlib"],
                            "is_test": False,
                        },
                        {
                            "path": "tests/test_runtime.py",
                            "purpose": "Unittest proof.",
                            "requirements": ["prove execution"],
                            "public_symbols": [],
                            "depends_on": ["src/tech_connector/runtime.py"],
                            "is_test": True,
                        },
                    ]
                }),
                project_root=root,
            )

        self.assertEqual([], errors)
        self.assertEqual("tech_connector/runtime.py", manifest[0]["path"])
        self.assertEqual([], manifest[0]["depends_on"])
        self.assertEqual(
            "tech_connector/examples/tests/test_runtime.py",
            manifest[1]["path"],
        )

    def test_generated_artifact_requirement_ledger_preserves_compound_request(self) -> None:
        ledger = extract_project_edit_artifact_requirements(
            "Build a scheduler. It must provide cycle detection, bounded concurrency, "
            "and crash recovery. Return tests. Do not touch live files."
        )

        self.assertEqual(["R1", "R2", "R3", "R4", "R5", "R6"], [item["id"] for item in ledger])
        self.assertTrue(any("bounded concurrency" in item["text"] for item in ledger))
        safety = next(item for item in ledger if "Do not touch live files" in item["text"])
        self.assertEqual("workflow", safety["scope"])
        tests = next(item for item in ledger if item["text"] == "Return tests")
        self.assertEqual("artifact", tests["scope"])

    def test_delivery_requirements_are_not_assigned_to_generated_files(self) -> None:
        ledger = extract_project_edit_artifact_requirements(
            "Build an incremental decoder. Include cancellation. "
            "Do not modify live project files; execute in a disposable workspace. "
            "Return all generated code, repair logs, per-stage timings, and a requirement coverage matrix."
        )
        artifact_ids = [
            item["id"] for item in ledger if item["scope"] == "artifact"
        ]
        workflow_ids = [
            item["id"] for item in ledger if item["scope"] == "workflow"
        ]
        files = [
            {
                "path": "pkg/decoder.py",
                "purpose": "Own incremental decoding and cancellation.",
                "requirements": [],
                "requirement_ids": artifact_ids,
                "public_symbols": ["Decoder.feed", "Decoder.cancel"],
                "contracts": ["feed is incremental and cancel is idempotent"],
                "algorithm_steps": ["buffer bounded chunks", "observe cancellation"],
                "validation_steps": ["assert chunks decode", "assert cancellation stops work"],
                "depends_on": [],
                "is_test": False,
            },
            {
                "path": "tech_connector/examples/tests/test_decoder.py",
                "purpose": "Prove decoding and cancellation.",
                "requirements": [],
                "requirement_ids": artifact_ids,
                "public_symbols": [],
                "contracts": ["call Decoder public methods"],
                "algorithm_steps": ["feed chunks", "cancel between chunks"],
                "validation_steps": ["assert decoded events", "assert bounded stop"],
                "depends_on": ["pkg/decoder.py"],
                "is_test": True,
            },
        ]
        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "integration_contracts": [
                        "Decoder owns feed(bytes) and cancel(); cancellation is idempotent "
                        "and tests call those exact methods."
                    ],
                    "files": files,
                }),
                project_root=root,
                requirement_ledger=ledger,
                strict_architecture=True,
            )

        self.assertEqual([], errors)
        assigned_ids = {
            requirement_id
            for item in manifest
            for requirement_id in item["requirement_ids"]
        }
        self.assertTrue(set(artifact_ids).issubset(assigned_ids))
        self.assertTrue(set(workflow_ids).isdisjoint(assigned_ids))
        coverage = build_project_edit_requirement_coverage(manifest, ledger)
        workflow_rows = [item for item in coverage if item["scope"] == "workflow"]
        self.assertTrue(all(item["system_owners"] == ["project_edit_flow"] for item in workflow_rows))
        self.assertTrue(all(not item["production_owners"] for item in workflow_rows))

    def test_complex_artifact_architecture_starts_with_coder_capacity(self) -> None:
        small = [
            {"id": "R1", "text": "Add one typed helper.", "scope": "artifact"},
            {"id": "R2", "text": "Return per-stage timings.", "scope": "workflow"},
        ]
        complex_ledger = [
            {
                "id": f"R{index}",
                "text": f"Implement independent behavior {index} with failure recovery.",
                "scope": "artifact",
            }
            for index in range(1, 9)
        ]

        self.assertFalse(project_edit_artifact_architecture_requires_coder(small))
        self.assertTrue(project_edit_artifact_architecture_requires_coder(complex_ledger))
        self.assertEqual("standard", project_edit_file_worker_profile(1))
        self.assertEqual("standard", project_edit_file_worker_profile(2))
        self.assertEqual("standard", project_edit_file_worker_profile(3))
        self.assertEqual("", project_edit_file_worker_model_override(2, {}))
        self.assertEqual(
            "",
            project_edit_file_worker_model_override(
                3,
                {"code_model": "ollama:qwen2.5-coder:7b"},
            ),
        )
        self.assertEqual(
            "",
            project_edit_file_worker_model_override(
                3,
                {"semantic_alignment_model": "ollama:custom:8b"},
            ),
        )

    def test_shared_undefined_contract_is_returned_to_architecture(self) -> None:
        generated = [
            (
                "C:/tmp/pkg/reader.py",
                "",
                "class Record:\n    pass\n",
            ),
            (
                "C:/tmp/pkg/writer.py",
                "",
                "class Record:\n    pass\n",
            ),
            (
                "C:/tmp/tests/test_contract.py",
                "",
                "def test_one():\n    Record()\n\ndef test_two():\n    Record()\n",
            ),
        ]
        notes = build_project_edit_cross_file_failure_notes(
            generated,
            [
                "Generated callables reference undefined names in "
                "test_one, test_two: Record"
            ],
        )

        self.assertEqual(1, len(notes))
        self.assertIn("multiple modules", notes[0])
        self.assertIn("canonical production owner", notes[0])

    def test_disposable_failure_signature_ignores_temp_paths_and_line_numbers(self) -> None:
        first = project_edit_validation_failure_signature([
            "Disposable generated-patch validation failed:\n"
            "  File \"C:/Temp/tech_connector_patch_validation_alpha/pkg/runtime.py\", line 18\n"
            "TypeError: Runtime.__init__() missing 1 required positional argument: 'limit'"
        ])
        second = project_edit_validation_failure_signature([
            "Disposable generated-patch validation failed:\n"
            "  File \"C:/Temp/tech_connector_patch_validation_beta/pkg/runtime.py\", line 27\n"
            "TypeError: Runtime.__init__() missing 1 required positional argument: 'limit'"
        ])

        self.assertEqual(first, second)
        self.assertTrue(first)

    def test_generated_artifact_manifest_assigns_missing_ledger_ids(self) -> None:
        ledger = [
            {"id": "R1", "text": "Build runtime."},
            {"id": "R2", "text": "Prove recovery."},
        ]
        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "integration_contracts": [
                        "Runtime.commit() and Runtime.recover() share one atomic journal format."
                    ],
                    "files": [
                        {
                            "path": "runtime.py",
                            "purpose": "Runtime.",
                            "requirements": ["Build runtime."],
                            "requirement_ids": ["1"],
                            "public_symbols": ["Runtime"],
                            "depends_on": [],
                            "is_test": False,
                        },
                        {
                            "path": "runtime_tests.py",
                            "purpose": "Proof.",
                            "requirements": ["Test runtime."],
                            "requirement_ids": ["1"],
                            "public_symbols": [],
                            "depends_on": ["runtime.py"],
                            "is_test": True,
                        },
                    ]
                }),
                project_root=root,
                requirement_ledger=ledger,
            )

        self.assertEqual([], errors)
        self.assertEqual({"R1", "R2"}, {
            requirement_id
            for item in manifest
            for requirement_id in item["requirement_ids"]
        })
        test_file = next(item for item in manifest if item["is_test"])
        self.assertIn("R2", test_file["requirement_ids"])

    def test_strict_artifact_architecture_requires_implementation_and_test_ownership(self) -> None:
        ledger = [
            {"id": "R1", "text": "Persist state atomically."},
            {"id": "R2", "text": "Recover an interrupted operation."},
        ]
        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "integration_contracts": [
                        "Runtime.commit() and Runtime.recover() share one atomic journal format."
                    ],
                    "files": [
                        {
                            "path": "pkg/runtime.py",
                            "purpose": "Own atomic persistence and recovery.",
                            "requirements": [item["text"] for item in ledger],
                            "requirement_ids": ["R1", "R2"],
                            "public_symbols": ["Runtime.commit", "Runtime.recover"],
                            "contracts": ["commit is atomic", "recover is idempotent"],
                            "algorithm_steps": ["write journal", "replace snapshot", "replay tail"],
                            "validation_steps": ["round-trip state"],
                            "depends_on": [],
                            "is_test": False,
                        },
                        {
                            "path": "tech_connector/examples/tests/test_runtime.py",
                            "purpose": "Prove normal and interrupted behavior.",
                            "requirements": [item["text"] for item in ledger],
                            "requirement_ids": ["R1", "R2"],
                            "public_symbols": [],
                            "contracts": ["call Runtime public API"],
                            "algorithm_steps": ["arrange temporary state", "interrupt", "recover"],
                            "validation_steps": ["assert committed state", "assert replay is idempotent"],
                            "depends_on": ["pkg/runtime.py"],
                            "is_test": True,
                        },
                    ]
                }),
                project_root=root,
                requirement_ledger=ledger,
                strict_architecture=True,
            )

        self.assertEqual([], errors)
        self.assertEqual(2, len(manifest))
        coverage = build_project_edit_requirement_coverage(manifest, ledger)
        self.assertTrue(all(item["status"] == "verified" for item in coverage))
        self.assertTrue(all(item["production_owners"] for item in coverage))
        self.assertTrue(all(item["test_owners"] for item in coverage))

    def test_strict_artifact_architecture_rejects_silent_ownership_and_duplicate_tests(self) -> None:
        ledger = [{"id": "R1", "text": "Decode bounded frames."}]
        files = [
            {
                "path": "pkg/decoder.py",
                "purpose": "Decode frames.",
                "requirements": ["Decode bounded frames."],
                "requirement_ids": ["R1"],
                "public_symbols": ["Decoder.feed"],
                "contracts": ["feed accepts chunks and returns immutable events"],
                "algorithm_steps": ["scan once"],
                "validation_steps": ["bounded-buffer assertion"],
                "depends_on": [],
                "is_test": False,
            },
            *[
                {
                    "path": f"tech_connector/examples/tests/test_decoder_{suffix}.py",
                    "purpose": "Prove decoding.",
                    "requirements": ["Decode bounded frames."],
                    "requirement_ids": ["R1"],
                    "public_symbols": [],
                    "contracts": ["call Decoder.feed"],
                    "algorithm_steps": ["feed hostile chunks"],
                    "validation_steps": ["assert bounded memory"],
                    "depends_on": ["pkg/decoder.py"],
                    "is_test": True,
                }
                for suffix in ("a", "b")
            ],
        ]
        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "integration_contracts": [
                        "Decoder.feed(data: bytes) is the sole boundary and consumes the shared frame field order."
                    ],
                    "files": files,
                }),
                project_root=root,
                requirement_ledger=ledger,
                strict_architecture=True,
            )

        self.assertEqual([], manifest)
        self.assertTrue(any("duplicates test responsibility" in error for error in errors))

    def test_strict_artifact_architecture_merges_partial_rows_for_one_file(self) -> None:
        ledger = [
            {"id": "R1", "text": "Decode bounded frames."},
            {"id": "R2", "text": "Recover after malformed input."},
        ]
        production_row = {
            "path": "pkg/decoder.py",
            "purpose": "Own bounded decoding.",
            "requirements": ["Decode bounded frames."],
            "requirement_ids": ["R1"],
            "public_symbols": ["Decoder.feed"],
            "contracts": ["feed returns immutable events"],
            "algorithm_steps": ["scan each byte once"],
            "validation_steps": ["assert bounded buffering"],
            "depends_on": [],
            "is_test": False,
        }
        recovery_row = {
            **production_row,
            "purpose": "Own malformed-input recovery.",
            "requirements": ["Recover after malformed input."],
            "requirement_ids": ["R2"],
            "public_symbols": ["Decoder.reset"],
            "contracts": ["reset discards only the invalid frame"],
            "algorithm_steps": ["resume at the next sync marker"],
            "validation_steps": ["assert later frames still decode"],
        }
        test_row = {
            "path": "tech_connector/examples/tests/test_decoder.py",
            "purpose": "Prove decoding and recovery.",
            "requirements": [item["text"] for item in ledger],
            "requirement_ids": ["R1", "R2"],
            "public_symbols": [],
            "contracts": ["call only Decoder public methods"],
            "algorithm_steps": ["feed valid and malformed chunks"],
            "validation_steps": ["assert events and recovery"],
            "depends_on": ["pkg/decoder.py"],
            "is_test": True,
        }

        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "integration_contracts": [
                        "Decoder.feed(data: bytes) and Decoder.reset() use the shared frame field order; tests reuse the same instance."
                    ],
                    "files": [production_row, recovery_row, test_row],
                }),
                project_root=root,
                requirement_ledger=ledger,
                strict_architecture=True,
            )

        self.assertEqual([], errors)
        self.assertEqual(2, len(manifest))
        production = next(item for item in manifest if not item["is_test"])
        self.assertEqual(["R1", "R2"], production["requirement_ids"])
        self.assertEqual(["Decoder.feed", "Decoder.reset"], production["public_symbols"])
        self.assertIn("malformed-input recovery", production["purpose"])

    def test_artifact_dependency_reconciles_an_unambiguous_file_name(self) -> None:
        ledger = [{"id": "R1", "text": "Resolve configuration before decoding."}]
        files = [
            {
                "path": "pkg/config.py",
                "purpose": "Own decoder configuration.",
                "requirements": ["Resolve configuration before decoding."],
                "requirement_ids": ["R1"],
                "public_symbols": ["DecoderConfig"],
                "contracts": ["configuration is immutable"],
                "algorithm_steps": ["validate bounds once"],
                "validation_steps": ["assert invalid bounds fail"],
                "depends_on": [],
                "is_test": False,
            },
            {
                "path": "pkg/decoder.py",
                "purpose": "Consume validated configuration.",
                "requirements": ["Resolve configuration before decoding."],
                "requirement_ids": ["R1"],
                "public_symbols": ["Decoder"],
                "contracts": ["Decoder requires DecoderConfig"],
                "algorithm_steps": ["store validated configuration"],
                "validation_steps": ["assert configuration is retained"],
                "depends_on": ["config.py"],
                "is_test": False,
            },
            {
                "path": "tech_connector/examples/tests/test_decoder.py",
                "purpose": "Prove configuration integration.",
                "requirements": ["Resolve configuration before decoding."],
                "requirement_ids": ["R1"],
                "public_symbols": [],
                "contracts": ["construct Decoder from DecoderConfig"],
                "algorithm_steps": ["construct and inspect decoder"],
                "validation_steps": ["assert public behavior"],
                "depends_on": ["decoder.py"],
                "is_test": True,
            },
        ]

        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "integration_contracts": [
                        "DecoderConfig is immutable, owned by pkg/config.py, and required by Decoder(config)."
                    ],
                    "files": files,
                }),
                project_root=root,
                requirement_ledger=ledger,
                strict_architecture=True,
            )

        self.assertEqual([], errors)
        decoder = next(item for item in manifest if item["path"] == "pkg/decoder.py")
        proof = next(item for item in manifest if item["is_test"])
        self.assertEqual(["pkg/config.py"], decoder["depends_on"])
        self.assertIn("pkg/decoder.py", proof["depends_on"])

    def test_strict_architecture_rejects_paths_as_integration_contracts(self) -> None:
        ledger = [{"id": "R1", "text": "Share one immutable record."}]
        files = [
            {
                "path": "pkg/model.py",
                "purpose": "Own the record.",
                "requirements": ["Share one immutable record."],
                "requirement_ids": ["R1"],
                "public_symbols": ["Record"],
                "contracts": ["Record is immutable"],
                "algorithm_steps": ["store validated fields"],
                "validation_steps": ["assert mutation fails"],
                "depends_on": [],
                "is_test": False,
            },
            {
                "path": "tech_connector/examples/tests/test_model.py",
                "purpose": "Prove the record contract.",
                "requirements": ["Share one immutable record."],
                "requirement_ids": ["R1"],
                "public_symbols": [],
                "contracts": ["construct Record"],
                "algorithm_steps": ["construct and attempt mutation"],
                "validation_steps": ["assert mutation fails"],
                "depends_on": ["pkg/model.py"],
                "is_test": True,
            },
        ]
        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "integration_contracts": ["C:/tmp/contracts.py"],
                    "files": files,
                }),
                project_root=root,
                requirement_ledger=ledger,
                strict_architecture=True,
            )

        self.assertEqual([], manifest)
        self.assertTrue(any("file paths" in error for error in errors))
        self.assertTrue(any("callable signature" in error for error in errors))

    def test_incremental_architecture_composes_local_file_work_packets(self) -> None:
        ledger = [
            {"id": "R1", "text": "Decode records.", "scope": "artifact"},
            {"id": "R2", "text": "Return timing details.", "scope": "workflow"},
        ]
        contract_response = json.dumps({
            "integration_contracts": {
                "canonical_owners": ["Record is owned by pkg/model.py"],
                "signatures": ["decode(data: bytes, limit: int = 8) -> Record"],
                "shared_invariants": ["retained bytes never exceed limit"],
                "data_layout": ["field order is marker then payload length then payload"],
                "errors": ["invalid input raises ValueError"],
            },
        })
        file_map_response = json.dumps({
            "files": [
                {
                    "path": "pkg/decoder.py",
                    "purpose": "Decode records.",
                    "requirement_ids": ["R1"],
                    "public_symbols": ["decode"],
                    "depends_on": [],
                    "is_test": False,
                },
                {
                    "path": "tech_connector/examples/tests/test_decoder.py",
                    "purpose": "Prove decoding.",
                    "requirement_ids": ["R1"],
                    "public_symbols": [],
                    "depends_on": ["pkg/decoder.py"],
                    "is_test": True,
                },
            ],
        })

        response, errors = compose_project_edit_incremental_manifest_response(
            contract_response,
            file_map_response,
            ledger,
        )
        payload = json.loads(response)

        self.assertEqual([], errors)
        self.assertEqual(2, len(payload["files"]))
        self.assertIn("Implement Decode records.", payload["files"][0]["algorithm_steps"])
        self.assertIn("Prove Decode records.", payload["files"][1]["algorithm_steps"])
        self.assertNotIn("R2", payload["files"][0]["requirement_ids"])

    def test_generated_file_removes_import_time_execution(self) -> None:
        source, errors = parse_project_edit_generated_file(
            "class Runtime:\n    pass\n\nruntime = Runtime()\nruntime.start()\n",
            path="pkg/runtime.py",
            expected_public_symbols=["Runtime"],
        )

        self.assertEqual([], errors)
        self.assertIn("class Runtime", source)
        self.assertNotIn("Runtime()", source)
        self.assertNotIn("runtime.start()", source)

    def test_generated_file_removes_redundant_no_op_constructor(self) -> None:
        source, errors = parse_project_edit_generated_file(
            "class Encoder:\n"
            "    def __init__(self):\n"
            "        pass\n\n"
            "    def encode(self, value):\n"
            "        return bytes(value)\n",
            path="pkg/encoder.py",
            expected_public_symbols=["Encoder", "Encoder.encode"],
        )

        self.assertEqual([], errors)
        self.assertNotIn("def __init__", source)
        self.assertIn("def encode", source)

    def test_generated_module_graph_rejects_undeclared_or_missing_local_modules(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / "pkg" / "decoder.py")
            errors = validate_project_edit_generated_module_graph(
                "from .config import Config\n\nclass Decoder:\n    pass\n",
                path=path,
                project_root=root,
                generated_files=[],
                declared_dependencies=[],
            )

        self.assertTrue(any("could not be resolved" in error for error in errors))

    def test_generated_consumer_must_reuse_dependency_owned_public_types(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            model_path = str(Path(root) / "pkg" / "model.py")
            consumer_path = str(Path(root) / "pkg" / "consumer.py")
            errors = validate_project_edit_generated_module_graph(
                "class Record:\n    pass\n\nclass Consumer:\n    pass\n",
                path=consumer_path,
                project_root=root,
                generated_files=[
                    (model_path, "", "class Record:\n    pass\n"),
                ],
                declared_dependencies=["pkg/model.py"],
            )

        self.assertTrue(any("duplicates dependency-owned public type" in error for error in errors))
        self.assertTrue(any("Record" in error for error in errors))

    def test_generated_interface_readback_carries_real_defaults_and_constants(self) -> None:
        readback = summarize_project_edit_generated_interface(
            "pkg/runtime.py",
            "LIMIT = 8\n\n"
            "class Runtime:\n"
            "    def __init__(self, limit=LIMIT):\n"
            "        self.limit = limit\n\n"
            "    def run(self, value, *, strict=True):\n"
            "        return value\n",
        )

        self.assertIn("LIMIT=8", readback)
        self.assertIn("Runtime(limit=LIMIT)", readback)
        self.assertIn("Runtime.run(value, *, strict=True)", readback)

    def test_structural_import_failure_does_not_select_a_test_leaf_for_repair(self) -> None:
        generated = [
            ("C:/tmp/pkg/runtime.py", "", "def run():\n    return 1\n"),
            (
                "C:/tmp/tech_connector/examples/tests/test_runtime.py",
                "",
                "def test_run():\n    assert True\n",
            ),
        ]
        target = resolve_project_edit_failure_symbol(
            generated,
            [
                "New import could not be resolved or accounted for: .missing.Config.",
                "ERROR: test_run",
            ],
        )

        self.assertEqual({}, target)

    def test_disposable_artifact_contract_builds_one_worker_per_manifest_file(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            plan = ProjectEditPlan(
                prompt=(
                    "Create complete multi-file implementation code and tests. "
                    "Do not modify live project files; materialize only in a disposable workspace."
                ),
                discovery={"project_roots": [root]},
                discovery_context="",
                model_prompt="",
            )
            manifest = [
                {
                    "path": "pkg/runtime.py",
                    "absolute_path": str(Path(root) / "pkg" / "runtime.py"),
                    "purpose": "Runtime.",
                    "requirements": ["execute work"],
                    "public_symbols": ["Runtime"],
                    "depends_on": [],
                    "is_test": False,
                },
                {
                    "path": "tests/test_runtime.py",
                    "absolute_path": str(Path(root) / "tests" / "test_runtime.py"),
                    "purpose": "Proof.",
                    "requirements": ["prove execution"],
                    "public_symbols": [],
                    "depends_on": ["pkg/runtime.py"],
                    "is_test": True,
                },
            ]

            manifest_stage = build_project_edit_artifact_manifest_stage(plan)
            file_stages = build_project_edit_artifact_file_stages(plan, manifest)

        self.assertIsNotNone(manifest_stage)
        self.assertEqual(2, len(file_stages))
        self.assertIn("Return raw Python only", file_stages[0][2].user_prompt)
        self.assertIn("substantive unittest coverage", file_stages[1][2].user_prompt)
        self.assertTrue(all(stage.num_predict == -1 for _path, _source, stage in file_stages))

    def test_multi_file_candidate_creates_new_files_and_modifies_existing_files(self) -> None:
        payload = json.loads(build_project_edit_multi_file_candidate([
            ("C:/project/pkg/new_file.py", "", "VALUE = 1\n"),
            ("C:/project/pkg/existing.py", "VALUE = 1\n", "VALUE = 2\n"),
        ]))

        self.assertEqual("create", payload["changes"][0]["action"])
        self.assertEqual("modify", payload["changes"][1]["action"])

    def test_explicit_active_edit_reuses_index_snapshot_without_deep_intelligence(self) -> None:
        active = str(Path(__file__).parents[1] / "services" / "project_edit_agent_service.py")
        snapshot = {
            "path": active,
            "root": str(Path(active).parents[1]),
            "sha1": "a" * 40,
            "symbols": [{
                "kind": "function",
                "name": "preview_project_edit_agent_response",
                "qualname": "preview_project_edit_agent_response",
                "start_line": 100,
                "end_line": 120,
                "source": "def preview_project_edit_agent_response():\n    return None",
            }],
        }
        with patch(
            "tech_connector.services.file_index_service.file_index_service.get_file_snapshot",
            return_value=snapshot,
        ), patch(
            "tech_connector.services.project_edit_agent_service._build_project_edit_intelligence_packet"
        ) as deep_intelligence:
            plan = build_project_edit_agent_request(
                "In project_edit_agent_service.py, update the preview function and add focused tests.",
                active_path=active,
            )

        deep_intelligence.assert_not_called()
        self.assertEqual("explicit_index_snapshot", plan.discovery["evidence_mode"])
        self.assertEqual("reuse_target_discovery", plan.intelligence_packet["mode"])
        self.assertEqual("a" * 40, plan.discovery["index_revision"])

    def test_build_project_edit_agent_request_includes_adaptive_success_contract(self) -> None:
        plan = build_project_edit_agent_request(
            "Add missing docstrings to rig helper functions",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )

        self.assertIn("adaptive_planning", [stage["key"] for stage in plan.stages])
        self.assertIn("code_intelligence", [stage["key"] for stage in plan.stages])
        self.assertIn("expert_selection", [stage["key"] for stage in plan.stages])
        self.assertEqual("adaptive_code_agent_v1", plan.adaptive_plan["framework"])
        self.assertTrue(plan.intelligence_packet)
        self.assertTrue(plan.domain_experts)
        self.assertTrue(plan.success_contract)
        self.assertIn("Adaptive code agent execution plan:", plan.model_prompt)
        self.assertIn("Code intelligence packet:", plan.model_prompt)
        self.assertIn("Deterministic IDE-agent steps before model synthesis:", plan.model_prompt)
        self.assertIn("Code/domain expert advisory context:", plan.model_prompt)
        self.assertIn("Reuse existing project functions, classes, services, and helpers", plan.model_prompt)
        self.assertIn("validate, repair, and report", plan.model_prompt)

    def test_project_edit_model_stages_split_plan_and_patch_generation(self) -> None:
        plan = build_project_edit_agent_request(
            "Find a Maya rigging function and build a UI around it.",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )

        stages = build_project_edit_model_stages(plan)

        self.assertEqual(["target_selection_plan", "patch_generation"], [stage.key for stage in stages])
        self.assertIn("Do not emit XML patches", stages[0].user_prompt)
        self.assertIn("approval-ready implementation plan", stages[0].user_prompt)
        self.assertIn('"changes": [', stages[1].user_prompt)
        self.assertEqual("object", stages[1].response_format["type"])
        self.assertIn("new_content", stages[1].response_format["properties"]["changes"]["items"]["required"])
        self.assertIn("replace_symbol", stages[1].response_format["properties"]["changes"]["items"]["properties"]["action"]["enum"])
        self.assertIn("insert_after_symbol", stages[1].response_format["properties"]["changes"]["items"]["properties"]["action"]["enum"])
        self.assertLessEqual(len(stages[0].user_prompt), 7000)
        self.assertLessEqual(len(stages[1].user_prompt), 12000)
        self.assertEqual("local_model_serial", stages[0].resource_lane)
        self.assertEqual(4096, stages[0].num_ctx)
        self.assertEqual("local_plan", stages[0].model_tier)
        self.assertFalse(stages[0].prefer_coder)
        self.assertEqual("local_code", stages[1].model_tier)
        self.assertTrue(stages[1].prefer_coder)
        self.assertEqual("micro", stages[1].coder_preference)

    def test_project_edit_model_stages_skip_patch_for_plan_only_request(self) -> None:
        plan = build_project_edit_agent_request(
            "Find a Maya rigging function and explain how you would build a UI around it. Do not edit anything.",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )

        stages = build_project_edit_model_stages(plan)

        self.assertEqual(["target_selection_plan"], [stage.key for stage in stages])
        self.assertNotIn("<modify_file path=", stages[0].user_prompt)

    def test_plan_only_new_artifact_keeps_disposable_architecture_scope(self) -> None:
        prompt = (
            "Build a multi-file Python task scheduler with dependency-cycle detection, "
            "bounded parallel workers, cancellation, and atomic checkpoints. "
            "Plan only and do not edit live project files."
        )

        plan = build_project_edit_agent_request(
            prompt,
            active_path="C:/depot/tools",
        )

        self.assertEqual(
            "generated_artifact_scope",
            plan.discovery["evidence_mode"],
        )
        self.assertEqual("C:\\depot\\tools", plan.discovery["best_target"]["path"])
        self.assertIsNotNone(build_project_edit_artifact_manifest_stage(plan))
        self.assertEqual(
            ["target_selection_plan", "patch_generation"],
            [stage.key for stage in build_project_edit_model_stages(plan)],
        )
        requirements = extract_project_edit_artifact_requirements(prompt)
        self.assertEqual("workflow", requirements[-1]["scope"])

    def test_incremental_file_map_repairs_missing_behavioral_test_owner(self) -> None:
        contract = json.dumps(
            {
                "integration_contracts": {
                    "canonical_owners": ["Scheduler"],
                    "signatures": ["schedule(task_id: str) -> None"],
                    "shared_invariants": ["Task IDs are unique."],
                    "data_layout": ["checkpoint JSON contains version and tasks"],
                    "errors": ["Duplicate task IDs raise ValueError."],
                }
            }
        )
        file_map = json.dumps(
            {
                "files": [
                    {
                        "path": "tech_connector/examples/scheduler.py",
                        "purpose": "Scheduler runtime.",
                        "requirement_ids": ["R1"],
                        "public_symbols": ["Scheduler"],
                        "depends_on": [],
                        "is_test": False,
                    }
                ]
            }
        )
        ledger = [{"id": "R1", "text": "Build the scheduler", "scope": "artifact"}]

        combined, errors = compose_project_edit_incremental_manifest_response(
            contract,
            file_map,
            ledger,
        )
        payload = json.loads(combined)

        self.assertEqual([], errors)
        self.assertTrue(payload["deterministic_repairs"])
        self.assertEqual(2, len(payload["files"]))
        self.assertTrue(payload["files"][-1]["is_test"])
        self.assertEqual(
            ["tech_connector/examples/scheduler.py"],
            payload["files"][-1]["depends_on"],
        )

    def test_strict_manifest_does_not_extract_sync_from_async(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            payload = {
                "integration_contracts": [
                    "signatures: reload_async(name: str) -> bool",
                    "data_layout: generation record field order is name then version",
                    "errors: reload failures return False",
                ],
                "files": [
                    {
                        "path": "tech_connector/examples/reloader.py",
                        "purpose": "Async reloader.",
                        "requirements": ["Create an async plugin reloader"],
                        "requirement_ids": ["R1"],
                        "public_symbols": ["reload_async"],
                        "contracts": ["reload_async(name: str) -> bool"],
                        "algorithm_steps": ["Drain calls and swap generations."],
                        "validation_steps": ["Import and inspect reload_async."],
                        "depends_on": [],
                        "is_test": False,
                    },
                    {
                        "path": "tech_connector/examples/tests/test_reloader.py",
                        "purpose": "Reloader proof.",
                        "requirements": ["Create an async plugin reloader"],
                        "requirement_ids": ["R1"],
                        "public_symbols": [],
                        "contracts": ["Call reload_async."],
                        "algorithm_steps": ["Prove generation swaps."],
                        "validation_steps": ["Run unittest."],
                        "depends_on": ["tech_connector/examples/reloader.py"],
                        "is_test": True,
                    },
                ],
            }
            _manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps(payload),
                project_root=root,
                requirement_ledger=[
                    {
                        "id": "R1",
                        "text": "Create an async plugin reloader",
                        "scope": "artifact",
                    }
                ],
                strict_architecture=True,
            )

        self.assertFalse(any("protocol terms: sync" in error for error in errors))

    def test_integration_contract_gate_requires_explicit_crc(self) -> None:
        response = json.dumps(
            {
                "integration_contracts": {
                    "canonical_owners": ["EventLog"],
                    "signatures": ["append(data: bytes) -> int"],
                    "shared_invariants": ["Sequence IDs increase."],
                    "data_layout": ["frame field order is length then payload"],
                    "errors": ["Corruption raises ValueError."],
                }
            }
        )
        errors = validate_project_edit_integration_contract_response(
            response,
            [
                {
                    "id": "R1",
                    "text": "Build CRC-framed binary event records",
                    "scope": "artifact",
                }
            ],
        )

        self.assertTrue(any("protocol terms: crc" in error for error in errors))

    def test_integration_contract_gate_requires_async_observer_and_drain_mechanism(self) -> None:
        response = json.dumps({
            "integration_contracts": {
                "canonical_owners": ["CallDrainer"],
                "signatures": ["drain_in_flight_calls(module_path)"],
                "shared_invariants": ["in_flight_calls reaches zero before swap"],
                "data_layout": ["ModuleState stores in_flight_calls as int"],
                "errors": ["Drain failures raise RuntimeError"],
            }
        })

        errors = validate_project_edit_integration_contract_response(
            response,
            [{
                "id": "R1",
                "text": (
                    "Build an async reloader that drains in-flight calls and emits "
                    "observer events."
                ),
                "scope": "artifact",
            }],
        )

        self.assertTrue(any("async, observer" in error for error in errors))
        self.assertTrue(any("wait/wake" in error for error in errors))
        self.assertTrue(any("observer registration" in error for error in errors))

        completed, fixes = complete_project_edit_integration_contract_response(
            response,
            [{
                "id": "R1",
                "text": (
                    "Build an async reloader that drains in-flight calls and emits "
                    "observer events."
                ),
                "scope": "artifact",
            }],
        )
        self.assertEqual(
            [],
            validate_project_edit_integration_contract_response(
                completed,
                [{
                    "id": "R1",
                    "text": (
                        "Build an async reloader that drains in-flight calls and emits "
                        "observer events."
                    ),
                    "scope": "artifact",
                }],
            ),
        )
        self.assertEqual(2, len(fixes))

    def test_production_manifest_drops_misdeclared_test_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            payload = {
                "integration_contracts": [
                    "signatures: append_record(data: bytes) -> int",
                    "data_layout: frame field order is length then payload",
                    "errors: invalid frames raise ValueError",
                ],
                "files": [
                    {
                        "path": "tech_connector/examples/event_log.py",
                        "purpose": "Event log.",
                        "requirements": ["Build an event log"],
                        "requirement_ids": ["R1"],
                        "public_symbols": ["append_record"],
                        "contracts": ["append_record(data: bytes) -> int"],
                        "algorithm_steps": ["Append one framed record."],
                        "validation_steps": ["Import and inspect append_record."],
                        "depends_on": ["temp_directory_tests.py"],
                        "is_test": False,
                    },
                    {
                        "path": "tech_connector/examples/tests/test_event_log.py",
                        "purpose": "Event log proof.",
                        "requirements": ["Build an event log"],
                        "requirement_ids": ["R1"],
                        "public_symbols": [],
                        "contracts": ["Call append_record."],
                        "algorithm_steps": ["Prove append and recovery."],
                        "validation_steps": ["Run unittest."],
                        "depends_on": ["tech_connector/examples/event_log.py"],
                        "is_test": True,
                    },
                ],
            }
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps(payload),
                project_root=root,
                requirement_ledger=[
                    {"id": "R1", "text": "Build an event log", "scope": "artifact"}
                ],
                strict_architecture=True,
            )

        self.assertEqual([], errors)
        production = next(item for item in manifest if not item["is_test"])
        self.assertEqual([], production["depends_on"])

    def test_strict_manifest_collapses_absent_dependency_into_owner(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            payload = {
                "integration_contracts": [
                    "signatures: reload(name: str) -> bool",
                    "data_layout: generation record field order is name then version",
                    "errors: reload failure triggers rollback and returns False",
                ],
                "files": [
                    {
                        "path": "tech_connector/hot_reloader.py",
                        "purpose": "Hot reload runtime.",
                        "requirements": ["Build hot reload with rollback"],
                        "requirement_ids": ["R1"],
                        "public_symbols": ["reload"],
                        "contracts": ["reload(name: str) -> bool"],
                        "algorithm_steps": ["Drain, swap, and roll back."],
                        "validation_steps": ["Import and inspect reload."],
                        "depends_on": ["src/tech_connector/rollback_handler.py"],
                        "is_test": False,
                    },
                    {
                        "path": "tech_connector/examples/tests/test_hot_reloader.py",
                        "purpose": "Hot reload proof.",
                        "requirements": ["Build hot reload with rollback"],
                        "requirement_ids": ["R1"],
                        "public_symbols": [],
                        "contracts": ["Call reload."],
                        "algorithm_steps": ["Prove rollback."],
                        "validation_steps": ["Run unittest."],
                        "depends_on": ["tech_connector/hot_reloader.py"],
                        "is_test": True,
                    },
                ],
            }
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps(payload),
                project_root=root,
                requirement_ledger=[
                    {
                        "id": "R1",
                        "text": "Build hot reload with rollback",
                        "scope": "artifact",
                    }
                ],
                strict_architecture=True,
            )

        self.assertEqual([], errors)
        production = next(item for item in manifest if not item["is_test"])
        self.assertEqual([], production["depends_on"])
        self.assertIn(
            "rollback_handler.py",
            production["dependency_repairs"][0],
        )

    def test_project_edit_stage_models_reuse_existing_router_settings(self) -> None:
        plan = build_project_edit_agent_request(
            "Find a Maya rigging function and build a UI around it.",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )
        stages = build_project_edit_model_stages(plan)
        settings = {
            "router_local_plan": "qwen3:8b",
            "router_local_code_micro": "qwen2.5-coder:1.5b",
            "model": "ollama:qwen3:14b",
        }

        self.assertEqual("qwen3:8b", model_for_project_edit_stage(stages[0], settings))
        self.assertEqual("qwen2.5-coder:1.5b", model_for_project_edit_stage(stages[1], settings))

    def test_project_edit_plan_output_requires_target_and_verification_evidence(self) -> None:
        plan = build_project_edit_agent_request(
            "Add a helper and focused tests in the project edit service (project_edit_agent_service.py).",
            active_path=str(Path(__file__).parents[1] / "services" / "project_edit_agent_service.py"),
        )
        valid = """Intent: implement the requested helper.
Best target: project_edit_agent_service.py based on the active file and indexed service symbols.
Reuse preview_project_edit_agent_response and the existing validation helpers rather than duplicating them.
Generate a focused patch, then compile the module, verify imports, and run focused unittest tests.
Block if the target signature or required call site cannot be established from project evidence.
Plan self-check: target, test scope, and verification all match the objective.
"""

        self.assertEqual([], validate_project_edit_plan_output(plan, valid))

    def test_project_edit_plan_output_rejects_detached_code_and_renders_grounded_fallback(self) -> None:
        plan = build_project_edit_agent_request(
            "Add a helper and focused tests in the project edit service (project_edit_agent_service.py).",
            active_path=str(Path(__file__).parents[1] / "services" / "project_edit_agent_service.py"),
        )
        detached = """Here is the implementation:
```python
class ReplacementEditor:
    def run(self):
        return True
```
This should solve the request without any other changes or tests.
"""

        errors = validate_project_edit_plan_output(plan, detached)
        fallback = render_grounded_project_edit_handoff(plan, rejected_plan_errors=errors)

        self.assertTrue(any("implementation code" in error for error in errors))
        self.assertTrue(any("target file" in error for error in errors))
        self.assertTrue(any("indexed existing symbol" in error for error in errors))
        self.assertIn("project_edit_agent_service.py", fallback)
        self.assertIn("Completion gates:", fallback)

    def test_project_edit_patch_stage_includes_exact_source_and_preview_contract(self) -> None:
        plan = build_project_edit_agent_request(
            "In project_edit_agent_service.py, add summarize_validation_failures and reuse it for validation errors. Preview only; do not apply changes.",
            active_path=str(Path(__file__).parents[1] / "services" / "project_edit_agent_service.py"),
        )

        patch_stage = build_project_edit_model_stages(plan)[1]

        self.assertIn("Focused exact source excerpts:", patch_stage.user_prompt)
        self.assertIn("def render_project_edit_agent_report", patch_stage.user_prompt)
        self.assertIn("A preview still requires a complete structured change payload", patch_stage.user_prompt)
        self.assertLessEqual(len(patch_stage.user_prompt), 13000)

    def test_project_edit_repairs_refine_context_and_escalate_one_tier_at_a_time(self) -> None:
        plan = build_project_edit_agent_request(
            "In project_edit_agent_service.py, add summarize_validation_failures and focused tests.",
            active_path=str(Path(__file__).parents[1] / "services" / "project_edit_agent_service.py"),
        )
        candidate = "<modify_file path=\"service.py\">\ninvalid candidate\n</modify_file>"
        stages = [
            build_project_edit_repair_stage(
                plan,
                candidate,
                ["Generated Python did not parse."],
                attempt=attempt,
                approved_plan="Approved plan: update the service and focused tests.",
            )
            for attempt in (1, 2, 3, 4, 5)
        ]

        self.assertEqual(["small", "standard", "standard", "standard", "standard"], [stage.coder_preference for stage in stages])
        self.assertEqual([105, 135, 135, 135, 135], [stage.timeout for stage in stages])
        self.assertTrue(all("Focus only on the listed failures" in stage.user_prompt for stage in stages))
        self.assertTrue(all("Current exact source excerpts:" in stage.user_prompt for stage in stages))
        self.assertTrue(all("Approved plan: update the service" in stage.user_prompt for stage in stages))
        self.assertTrue(all("Syntax reset:" in stage.user_prompt for stage in stages))
        self.assertTrue(all(stage.timeout < 300 for stage in stages))

        implementation_reset = build_project_edit_repair_stage(
            plan,
            candidate,
            ["Candidate did not implement requested public symbols: summarize_validation_failures"],
            attempt=1,
            approved_plan="Approved plan: define and reuse the helper with tests.",
        )
        self.assertIn("Implementation reset:", implementation_reset.user_prompt)
        self.assertIn("Never import", implementation_reset.user_prompt)
        self.assertNotIn("invalid candidate", implementation_reset.user_prompt)

        completion_focus = build_project_edit_repair_stage(
            plan,
            candidate,
            ["New public callables need useful docstrings: summarize_validation_failures"],
            attempt=3,
            approved_plan="Approved plan: define and reuse the helper with tests.",
        )
        self.assertIn("Completion focus:", completion_focus.user_prompt)

    def test_project_edit_candidate_scoring_prefers_missing_docs_and_tests_over_invalid_code(self) -> None:
        nearly_complete = project_edit_preview_error_score(
            [
                "New public callables need useful docstrings: summarize_validation_failures",
                "Behavior-changing tool work must add or update a focused test file before preview approval.",
            ]
        )
        malformed = project_edit_preview_error_score(
            ["Structured change JSON did not parse: Unterminated string starting at line 8."]
        )

        self.assertLess(nearly_complete, malformed)

    def test_project_edit_core_failure_recognizes_new_symbol_used_as_replace_target(self) -> None:
        prompt = "Add a function named summarize_validation_failures with focused tests."

        self.assertTrue(project_edit_has_core_contract_failure(
            ["Indexed Python symbol was not found: summarize_validation_failures in service.py"],
            prompt,
        ))
        self.assertFalse(project_edit_has_core_contract_failure(
            ["Indexed Python symbol was not found: unrelated_existing_helper in service.py"],
            prompt,
        ))

    def test_project_edit_preview_accepts_structured_json_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "values.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            response = json.dumps(
                {
                    "changes": [
                        {
                            "action": "modify",
                            "path": str(source),
                            "original_content": "VALUE = 1\n",
                            "new_content": "VALUE = 2\n",
                        }
                    ],
                    "report": {"changed": ["VALUE"], "verification": ["compile"]},
                    "blocked_reason": "",
                }
            )

            preview = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertTrue(preview.ok)
            self.assertEqual("VALUE = 2\n", preview.changes[0]["after"])
            self.assertEqual("VALUE = 1\n", source.read_text(encoding="utf-8"))

    def test_project_edit_preview_resolves_nested_symbol_replacement_with_ast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.py"
            source.write_text(
                "class Example:\n"
                "    def value(self) -> int:\n"
                "        return 1\n",
                encoding="utf-8",
            )
            response = json.dumps(
                {
                    "changes": [
                        {
                            "action": "replace_symbol",
                            "path": str(source),
                            "target_symbol": "value",
                            "original_content": "",
                            "new_content": "def value(self) -> int:\n    return 2",
                        }
                    ],
                    "report": {"changed": ["Example.value"], "reused": [], "verification": ["compile"], "remaining_gaps": []},
                    "blocked_reason": "",
                }
            )

            preview = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertTrue(preview.ok)
            self.assertIn("    def value(self) -> int:", preview.changes[0]["after"])
            self.assertIn("        return 2", preview.changes[0]["after"])

    def test_project_edit_preview_composes_symbol_operations_on_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.py"
            source.write_text(
                "def value() -> int:\n"
                "    return 1\n",
                encoding="utf-8",
            )
            response = json.dumps(
                {
                    "changes": [
                        {
                            "action": "insert_before_symbol",
                            "path": str(source),
                            "target_symbol": "value",
                            "original_content": "",
                            "new_content": "def helper() -> int:\n    \"\"\"Return the replacement value.\n\n    :return: Replacement integer value.\n    \"\"\"\n    return 2",
                        },
                        {
                            "action": "replace_symbol",
                            "path": str(source),
                            "target_symbol": "value",
                            "original_content": "",
                            "new_content": "def value() -> int:\n    return helper()",
                        },
                    ],
                    "report": {"changed": ["helper", "value"], "reused": [], "verification": ["compile"], "remaining_gaps": []},
                    "blocked_reason": "",
                }
            )

            preview = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertTrue(preview.ok, preview.errors)
            self.assertEqual(1, len(preview.changes))
            self.assertIn("def helper() -> int:", preview.changes[0]["after"])
            self.assertIn(":return: Replacement integer value.", preview.changes[0]["after"])
            self.assertIn("def value() -> int:", preview.changes[0]["after"])
            self.assertIn("    return helper()", preview.changes[0]["after"])

    def test_project_edit_leaf_workers_compile_evidence_and_compose_valid_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "service.py"
            tests_dir = root / "tests"
            tests_dir.mkdir()
            test_path = tests_dir / "test_service.py"
            target_before = (
                "def render_errors(results: list[dict[str, object]]) -> list[str]:\n"
                "    \"\"\"Render validation errors.\n\n"
                "    :param results: Validation result dictionaries.\n"
                "    :return: Failure message strings.\n"
                "    \"\"\"\n"
                "    return [str(item.get('message', '')) for item in results if not item.get('ok')]\n"
            )
            test_before = (
                "import unittest\n\n"
                "from service import render_errors\n\n\n"
                "class TestService(unittest.TestCase):\n"
                "    def test_render_errors(self):\n"
                "        self.assertEqual(['bad'], render_errors([{'ok': False, 'message': 'bad'}]))\n"
            )
            target.write_text(target_before, encoding="utf-8")
            test_path.write_text(test_before, encoding="utf-8")
            objective = (
                "In service.py, add a reusable function named summarize_validation_failures that accepts "
                "validation result dictionaries and returns concise failure lines. Reuse it in render_errors "
                "and add focused unittest coverage."
            )
            plan = ProjectEditPlan(
                prompt=objective,
                discovery={
                    "best_target": {"path": str(target)},
                    "project_roots": [str(root)],
                },
                discovery_context="",
                model_prompt="",
                active_path=str(target),
            )
            approved = (
                "Implement summarize_validation_failures in service.py and integrate it into the selected renderer. "
                "Extend TestService.test_render_errors in tests/test_service.py. Verify imports and unittest."
            )

            snapshots = {
                str(target.resolve()).lower(): {
                    "path": str(target.resolve()),
                    "root": str(root.resolve()),
                    "sha1": hashlib.sha1(target.read_bytes()).hexdigest(),
                    "symbols": [{
                        "kind": "function",
                        "name": "render_errors",
                        "qualname": "render_errors",
                        "source": target_before,
                    }],
                },
                str(test_path.resolve()).lower(): {
                    "path": str(test_path.resolve()),
                    "root": str(root.resolve()),
                    "sha1": hashlib.sha1(test_path.read_bytes()).hexdigest(),
                    "symbols": [{
                        "kind": "method",
                        "name": "test_render_errors",
                        "qualname": "TestService.test_render_errors",
                        "source": (
                            "def test_render_errors(self):\n"
                            "    self.assertEqual(['bad'], render_errors([{'ok': False, 'message': 'bad'}]))"
                        ),
                    }],
                },
            }
            with patch(
                "tech_connector.services.file_index_service.file_index_service.get_file_snapshot",
                side_effect=lambda value, **_kwargs: snapshots.get(str(Path(value).resolve()).lower()),
            ):
                work_units = compile_project_edit_leaf_work_units(plan, approved)

            self.assertIsNotNone(work_units)
            assert work_units is not None
            self.assertEqual("render_errors", work_units.integration_symbol)
            self.assertEqual("TestService.test_render_errors", work_units.test_anchor_symbol)
            self.assertEqual("service", work_units.owner_module)
            self.assertEqual("micro", build_project_edit_leaf_stage(
                work_units,
                kind="define",
                attempt=1,
                objective=objective,
                approved_plan=approved,
            ).coder_preference)
            self.assertEqual("small", build_project_edit_leaf_stage(
                work_units,
                kind="integrate",
                attempt=1,
                objective=objective,
                approved_plan=approved,
            ).coder_preference)

            helper_source, helper_errors = parse_project_edit_leaf_source(
                json.dumps({
                    "source": (
                        "def summarize_validation_failures(results: list[dict[str, object]]) -> list[str]:\n"
                        "    \"\"\"Return messages from failed validation results.\n\n"
                        "    :param results: Validation result dictionaries.\n"
                        "    :return: Failure message strings.\n"
                        "    \"\"\"\n"
                        "    return [str(item.get('message', 'Validation failed.')) for item in results "
                        "if not item.get('ok')]"
                    )
                }),
                kind="define",
                expected_symbol="summarize_validation_failures",
                objective=objective,
            )
            integration_source, integration_errors = parse_project_edit_leaf_source(
                json.dumps({
                    "source": (
                        "def render_errors(results: list[dict[str, object]]) -> list[str]:\n"
                        "    \"\"\"Render validation errors.\n\n"
                        "    :param results: Validation result dictionaries.\n"
                        "    :return: Failure message strings.\n"
                        "    \"\"\"\n"
                        "    return summarize_validation_failures(results)"
                    )
                }),
                kind="integrate",
                expected_symbol="render_errors",
                required_reference="summarize_validation_failures",
                objective=objective,
            )
            test_source, test_errors = parse_project_edit_leaf_source(
                json.dumps({
                    "source": (
                        "def test_summarize_validation_failures(self):\n"
                        "    results = [{'ok': True, 'message': 'skip'}, {'ok': False, 'message': 'bad'}]\n"
                        "    self.assertEqual(['bad'], summarize_validation_failures(results))"
                    )
                }),
                kind="test",
                expected_symbol="test_summarize_validation_failures",
                required_reference="summarize_validation_failures",
                objective=objective,
            )
            self.assertEqual([], helper_errors + integration_errors + test_errors)
            candidate = build_project_edit_leaf_candidate(
                work_units,
                helper_source=helper_source,
                integration_source=integration_source,
                test_source=test_source,
            )

            preview = preview_project_edit_agent_response(
                candidate,
                project_root=str(root),
                request_prompt=objective,
            )

            self.assertTrue(preview.ok, preview.errors)
            self.assertEqual(2, len(preview.changes))
            target_after = next(
                item["after"]
                for item in preview.changes
                if Path(item["path"]).resolve() == target.resolve()
            )
            test_after = next(
                item["after"]
                for item in preview.changes
                if Path(item["path"]).resolve() == test_path.resolve()
            )
            self.assertIn("def summarize_validation_failures", target_after)
            self.assertIn("from service import summarize_validation_failures", test_after)
            self.assertEqual(target_before, target.read_text(encoding="utf-8"))
            self.assertEqual(test_before, test_path.read_text(encoding="utf-8"))

            handoff = project_edit_leaf_work_units_handoff(work_units)
            restored, restore_errors = restore_project_edit_leaf_work_units(handoff, objective)
            self.assertEqual([], restore_errors)
            self.assertEqual(work_units.integration_symbol, restored.integration_symbol)
            restored_plan = build_project_edit_plan_from_leaf_work_units(objective, restored)
            self.assertEqual("approved_index_handoff", restored_plan.discovery["evidence_mode"])

            test_path.write_text(test_before + "\n# changed\n", encoding="utf-8")
            stale_units, stale_errors = restore_project_edit_leaf_work_units(handoff, objective)
            self.assertIsNone(stale_units)
            self.assertTrue(any("test file changed" in error for error in stale_errors))

    def test_project_edit_leaf_validation_rejects_unbounded_or_detached_source(self) -> None:
        source, errors = parse_project_edit_leaf_source(
            json.dumps({"source": "import os\n\ndef helper():\n    return 1"}),
            kind="define",
            expected_symbol="helper",
        )
        detached, detached_errors = parse_project_edit_leaf_source(
            json.dumps({"source": "def render(values):\n    return list(values)"}),
            kind="integrate",
            expected_symbol="render",
            required_reference="summarize_validation_failures",
        )

        self.assertEqual("", source)
        self.assertTrue(any("exactly one function" in error for error in errors))
        self.assertEqual("", detached)
        self.assertTrue(any("required symbol" in error for error in detached_errors))

        wrong_contract, contract_errors = parse_project_edit_leaf_source(
            (
                "def summarize_validation_failures(result: ProjectEditApplyResult) -> str:\n"
                "    \"\"\"Return one joined validation report.\"\"\"\n"
                "    return '\\n'.join(item['message'] for item in result.validation)"
            ),
            kind="define",
            expected_symbol="summarize_validation_failures",
            objective=(
                "Add a helper that accepts validation result dictionaries and returns human-readable failure lines."
            ),
        )
        self.assertEqual("", wrong_contract)
        self.assertTrue(any("dictionaries" in error or "individual failure lines" in error for error in contract_errors))

        unfiltered, unfiltered_errors = parse_project_edit_leaf_source(
            (
                "def summarize_validation_failures(results: list[dict[str, object]]) -> list[str]:\n"
                "    \"\"\"Return a line for every validation result.\"\"\"\n"
                "    return [str(item.get('message')) for item in results]"
            ),
            kind="define",
            expected_symbol="summarize_validation_failures",
            objective=(
                "Add a helper that accepts validation result dictionaries and returns human-readable failure lines."
            ),
        )
        self.assertEqual("", unfiltered)
        self.assertTrue(any("ok value is true" in error for error in unfiltered_errors))

    def test_project_edit_leaf_test_normalizes_single_class_wrapper(self) -> None:
        source, errors = parse_project_edit_leaf_source(
            (
                "import unittest\n"
                "from service import summarize_validation_failures\n\n"
                "class TestService(unittest.TestCase):\n"
                "    def test_summarize_validation_failures(self):\n"
                "        self.assertEqual([], summarize_validation_failures([]))\n"
            ),
            kind="test",
            expected_symbol="test_generated_behavior",
            required_reference="summarize_validation_failures",
        )

        self.assertEqual([], errors)
        self.assertTrue(source.startswith("def test_summarize_validation_failures"))
        self.assertNotIn("class TestService", source)
        self.assertNotIn("import unittest", source)

    def test_project_edit_leaf_test_extracts_only_method_using_required_helper(self) -> None:
        source, errors = parse_project_edit_leaf_source(
            (
                "import unittest\n\n"
                "class TestService(unittest.TestCase):\n"
                "    def test_existing_behavior(self):\n"
                "        self.assertTrue(True)\n\n"
                "    def test_summarize_validation_failures(self):\n"
                "        self.assertEqual([], summarize_validation_failures([]))\n"
            ),
            kind="test",
            expected_symbol="test_generated_behavior",
            required_reference="summarize_validation_failures",
        )

        self.assertEqual([], errors)
        self.assertTrue(source.startswith("def test_summarize_validation_failures"))
        self.assertNotIn("test_existing_behavior", source)

    def test_project_edit_preview_resolves_unique_bare_filename_within_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_dir = Path(tmp) / "services"
            service_dir.mkdir()
            source = service_dir / "sample.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            response = json.dumps(
                {
                    "changes": [
                        {
                            "action": "modify",
                            "path": "sample.py",
                            "target_symbol": "",
                            "original_content": "VALUE = 1\n",
                            "new_content": "VALUE = 2\n",
                        }
                    ],
                    "report": {"changed": ["VALUE"], "reused": [], "verification": ["compile"], "remaining_gaps": []},
                    "blocked_reason": "",
                }
            )

            preview = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertTrue(preview.ok, preview.errors)
            self.assertEqual(source.resolve(), Path(preview.changes[0]["path"]).resolve())

    def test_project_edit_preview_supports_exact_text_edits_for_cpp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Bridge.cpp"
            source.write_text("#include \"Core.h\"\n\nvoid Existing() {}\n", encoding="utf-8")
            response = json.dumps({
                "changes": [
                    {
                        "action": "insert_after_text",
                        "path": str(source),
                        "target_symbol": "#include \"Core.h\"\n",
                        "original_content": "",
                        "new_content": "#include \"NiagaraSystem.h\"\n",
                    },
                    {
                        "action": "insert_after_text",
                        "path": str(source),
                        "target_symbol": "void Existing() {}\n",
                        "original_content": "",
                        "new_content": "\nvoid Added() {}\n",
                    },
                ],
                "report": {"changed": [], "reused": [], "verification": [], "remaining_gaps": []},
                "blocked_reason": "",
            })

            preview = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertTrue(preview.ok, preview.errors)
            after = preview.changes[0]["after"]
            self.assertIn('#include "Core.h"\n#include "NiagaraSystem.h"', after)
            self.assertIn("void Existing() {}\n\nvoid Added() {}", after)

    def test_project_edit_preview_rejects_ambiguous_text_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Bridge.cpp"
            source.write_text("anchor\nanchor\n", encoding="utf-8")
            response = json.dumps({
                "changes": [{
                    "action": "insert_after_text",
                    "path": str(source),
                    "target_symbol": "anchor",
                    "original_content": "",
                    "new_content": "new",
                }],
                "report": {"changed": [], "reused": [], "verification": [], "remaining_gaps": []},
                "blocked_reason": "",
            })

            preview = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertFalse(preview.ok)
            self.assertTrue(any("found 2" in error for error in preview.errors))

    def test_project_edit_syntax_subagent_repairs_one_structured_change(self) -> None:
        candidate = json.dumps(
            {
                "changes": [
                    {
                        "action": "modify",
                        "path": "service.py",
                        "target_symbol": "render_report",
                        "original_content": "old source",
                        "new_content": "def summarize(item):\n    return f'{item.get(\"message\")'",
                    }
                ],
                "report": {"changed": [], "reused": [], "verification": [], "remaining_gaps": []},
                "blocked_reason": "",
            }
        )

        issues = inspect_project_edit_structured_syntax(candidate)
        small_stage = build_project_edit_syntax_repair_stage(issues[0], attempt=1)
        standard_stage = build_project_edit_syntax_repair_stage(issues[0], attempt=2)
        repaired = apply_project_edit_syntax_repair(
            candidate,
            change_index=0,
            repair_response=json.dumps(
                {"corrected_source": "def summarize(item):\n    return str(item.get('message'))"}
            ),
        )

        self.assertEqual(1, len(issues))
        self.assertEqual("small", small_stage.coder_preference)
        self.assertEqual("standard", standard_stage.coder_preference)
        self.assertEqual([], inspect_project_edit_structured_syntax(repaired))

    def test_project_edit_preview_rejects_self_import_missing_symbol_and_missing_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "service.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            response = json.dumps(
                {
                    "changes": [
                        {
                            "action": "modify",
                            "path": str(source),
                            "target_symbol": "",
                            "original_content": "VALUE = 1\n",
                            "new_content": "from service import requested_helper\n\nVALUE = 1\n",
                        }
                    ],
                    "report": {"changed": [], "reused": [], "verification": [], "remaining_gaps": []},
                    "blocked_reason": "",
                }
            )

            preview = preview_project_edit_agent_response(
                response,
                project_root=tmp,
                request_prompt="Add a function named requested_helper and focused unittest coverage.",
            )

            self.assertFalse(preview.ok)
            self.assertTrue(any("cannot import" in error.lower() for error in preview.errors))
            self.assertTrue(any("requested_helper" in error for error in preview.errors))
            self.assertTrue(any("focused test file" in error for error in preview.errors))

    def test_project_edit_plan_fingerprint_detects_stale_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            plan = ProjectEditPlan(
                prompt="Update VALUE.",
                discovery={"best_target": {"path": str(target)}},
                discovery_context="",
                model_prompt="",
                active_path=str(target),
            )

            before = project_edit_plan_fingerprint(plan)
            target.write_text("VALUE = 2\n", encoding="utf-8")

            self.assertNotEqual(before, project_edit_plan_fingerprint(plan))

    def test_code_agent_selects_existing_domain_experts(self) -> None:
        maya_experts = select_code_agent_experts(
            "Create a Maya UI for an existing rigging function.",
            discovery={
                "best_target": {"path": "C:/depot/tools/maya_tools/Rigging/create_rig.py"},
                "project_roots": ["C:/depot/tools"],
            },
        )
        maya_domains = {expert["domain"] for expert in maya_experts}
        self.assertIn("maya.rigging", maya_domains)
        self.assertIn("python.code", maya_domains)
        self.assertIn("Code/domain expert advisory context:", render_code_agent_expert_context(maya_experts))

    def test_code_agent_selects_ui_and_validation_experts_for_maya_ui_work(self) -> None:
        experts = select_code_agent_experts(
            "Create a Maya Qt UI for an existing rigging function, validate inputs, add tests, and compile modified files.",
            discovery={
                "best_target": {"path": "C:/depot/tools/maya_tools/Rigging/create_rig.py"},
                "project_roots": ["C:/depot/tools"],
            },
            limit=8,
        )

        domains = {expert["domain"] for expert in experts}
        self.assertIn("maya.rigging", domains)
        self.assertIn("python.ui_integration", domains)
        self.assertIn("python.testing_validation", domains)

    def test_code_agent_selects_unreal_graph_expert_for_graph_code_request(self) -> None:
        experts = select_code_agent_experts(
            "Improve Unreal Blueprint graph planning code and validation.",
            discovery={
                "best_target": {
                    "path": "C:/depot/tools/tech_connector/services/unreal/semantic_graph_service.py"
                },
                "project_roots": ["C:/depot/tools/tech_connector"],
            },
        )
        domains = {expert["domain"] for expert in experts}
        self.assertIn("unreal.blueprint_graph", domains)
        self.assertIn("python.code", domains)

    def test_code_agent_selects_responsiveness_and_index_experts_for_freeze_work(self) -> None:
        experts = select_code_agent_experts(
            "Fix the UI freeze while project indexing and long prompts stream; keep chat updates responsive.",
            discovery={
                "best_target": {
                    "path": "C:/depot/tools/tech_connector/app/main_window_editor.py"
                },
                "project_roots": ["C:/depot/tools/tech_connector"],
            },
            limit=8,
        )

        domains = {expert["domain"] for expert in experts}
        self.assertIn("python.async_responsiveness", domains)
        self.assertIn("python.index_search", domains)
        self.assertIn("python.ui_integration", domains)

    def test_adaptive_plan_requires_successful_output_and_fallbacks(self) -> None:
        plan = build_code_agent_adaptive_plan(
            "Implement a reusable stamina system and connect it to sprinting",
            discovery={
                "confidence": "low",
                "best_target": {},
            },
        )
        text = render_code_agent_adaptive_plan(plan)

        self.assertTrue(plan["requires_confirmation"])
        self.assertIn("successful output", text)
        self.assertIn("repo map, symbol lookup, references, usages", text)
        self.assertIn("build_code_intelligence_packet", text)
        self.assertIn("Do not fabricate missing APIs or paths.", text)
        self.assertIn("Capability gaps", text)

    def test_preview_resolves_modify_file_with_existing_resilient_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "tool.py"
            source.write_text("def run() -> str:\n    return 'old'\n", encoding="utf-8")
            response = f"""<modify_file path="{source}">
<<<< ORIGINAL
def run() -> str:
    return 'old'
====
def run() -> str:
    return 'new'
>>>>
</modify_file>"""

            result = preview_project_edit_agent_response(response, project_root=str(root))

            self.assertTrue(result.ok)
            self.assertEqual("preview_ready", result.status)
            self.assertEqual(1, len(result.changes))
            self.assertIn("return 'new'", result.changes[0]["after"])
            self.assertEqual("def run() -> str:\n    return 'old'\n", source.read_text(encoding="utf-8"))

    def test_apply_writes_change_validates_python_and_creates_undo_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "tool.py"
            source.write_text("def run() -> str:\n    return 'old'\n", encoding="utf-8")
            response = f"""<modify_file path="{source}">
<<<< ORIGINAL
def run() -> str:
    return 'old'
====
def run() -> str:
    return 'new'
>>>>
</modify_file>"""

            result = apply_project_edit_agent_response(response, project_root=str(root))

            self.assertTrue(result.ok)
            self.assertEqual("applied", result.status)
            self.assertIn("return 'new'", source.read_text(encoding="utf-8"))
            self.assertTrue(result.change_session_path)
            self.assertTrue(any(item.get("ok") for item in result.validation))

            session = load_change_session(result.change_session_path)
            ok, _message, changed = undo_change_session(session)
            self.assertTrue(ok)
            self.assertIn(str(source.resolve()), changed)
            self.assertIn("return 'old'", source.read_text(encoding="utf-8"))

    def test_apply_reports_validation_failure_for_invalid_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.py"
            source.write_text("def run():\n    return 'old'\n", encoding="utf-8")
            response = f"""<modify_file path="{source}">
<<<< ORIGINAL
def run():
    return 'old'
====
def run(
    return 'new'
>>>>
</modify_file>"""

            result = apply_project_edit_agent_response(response, project_root=str(root))
            report = render_project_edit_agent_report(result)

            self.assertFalse(result.ok)
            self.assertEqual("preview_failed", result.status)
            self.assertIn("failed: candidate:syntax", report)
            self.assertIn("Warnings / Errors:", report)
            self.assertIn("return 'old'", source.read_text(encoding="utf-8"))

    def test_create_file_is_supported_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            response = '''<create_file path="new_tool.py">
def created() -> bool:
    \"\"\"Return whether the generated tool was created successfully.

    :return: True when the tool was created.
    \"\"\"
    return True
</create_file>'''

            result = apply_project_edit_agent_response(response, project_root=str(root))
            report = render_project_edit_agent_report(result)

            self.assertTrue(result.ok)
            self.assertTrue((root / "new_tool.py").exists())
            self.assertIn("create", report)
            self.assertIn("py_compile new_tool.py", report)

    def test_preview_rejects_unresolved_new_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = """<create_file path="broken_import_tool.py">
import package_that_does_not_exist_tech_connector

def build_report():
    \"\"\"Build the report.\"\"\"
    return package_that_does_not_exist_tech_connector.report()
</create_file>"""

            result = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertFalse(result.ok)
            self.assertTrue(any("could not be resolved" in error for error in result.errors))

    def test_preview_rejects_new_public_callable_without_docstring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = """<create_file path="undocumented_tool.py">
def normalize_records(records):
    return list(records)
</create_file>"""

            result = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertFalse(result.ok)
            self.assertTrue(any("docstrings" in error for error in result.errors))

    def test_whole_tool_preview_requires_and_accepts_focused_behavior_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response_without_test = '''<create_file path="record_tool.py">
def normalize_records(records: list[str]) -> list[str]:
    \"\"\"Normalize records by trimming whitespace and removing empty values.

    :param records: Record values to normalize.
    :return: Normalized non-empty record values.
    \"\"\"
    return [value.strip() for value in records if value.strip()]
</create_file>'''
            prompt = "Create a reusable record normalization tool with working behavior."

            rejected = preview_project_edit_agent_response(
                response_without_test,
                project_root=tmp,
                request_prompt=prompt,
            )

            self.assertFalse(rejected.ok)
            self.assertTrue(any("focused test file" in error for error in rejected.errors))

            response_with_test = response_without_test + """
<create_file path="test_record_tool.py">
import unittest

from record_tool import normalize_records


class RecordToolTests(unittest.TestCase):
    def test_normalize_records_trims_and_drops_empty_values(self):
        self.assertEqual(["alpha", "beta"], normalize_records([" alpha ", "", "beta"]))


if __name__ == "__main__":
    unittest.main()
</create_file>"""
            accepted = preview_project_edit_agent_response(
                response_with_test,
                project_root=tmp,
                request_prompt=prompt,
            )

            self.assertTrue(accepted.ok, accepted.errors)
            self.assertTrue(all(item.get("ok") for item in accepted.validation))

            applied = apply_project_edit_agent_response(
                response_with_test,
                project_root=tmp,
                request_prompt=prompt,
            )
            self.assertTrue(applied.ok, applied.errors)
            self.assertTrue(any("Focused behavior tests passed" in item.get("message", "") for item in applied.validation))

    def test_preview_rejects_placeholder_test_that_discovers_zero_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = '''<create_file path="record_tool.py">
def normalize_records(records: list[str]) -> list[str]:
    \"\"\"Normalize records by trimming whitespace and removing empty values.

    :param records: Record values to normalize.
    :return: Normalized non-empty record values.
    \"\"\"
    return [value.strip() for value in records if value.strip()]
</create_file>
<create_file path="test_record_tool.py">
import unittest


class RecordToolTests(unittest.TestCase):
    pass
</create_file>'''

            result = preview_project_edit_agent_response(
                response,
                project_root=tmp,
                request_prompt="Create a reusable record normalization tool with working behavior and tests.",
            )

            self.assertFalse(result.ok)
            self.assertTrue(any("generated-patch validation failed" in error for error in result.errors))

    def test_preview_rejects_cross_file_import_failure_in_disposable_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = '''<create_file path="cycle_a.py">
from cycle_b import read_b


def read_a() -> object:
    """Read the A value.

    :return: Value read from the B module.
    """
    return read_b()
</create_file>
<create_file path="cycle_b.py">
from cycle_a import read_a


def read_b() -> object:
    """Read the B value.

    :return: Value read from the A module.
    """
    return read_a()
</create_file>
<create_file path="test_cycle.py">
import unittest

from cycle_a import read_a


class CycleTests(unittest.TestCase):
    def test_cycle_imports(self):
        self.assertTrue(callable(read_a))
</create_file>'''

            result = preview_project_edit_agent_response(
                response,
                project_root=tmp,
                request_prompt="Create a working multi-file cycle tool with behavior tests.",
            )

            self.assertFalse(result.ok)
            self.assertTrue(any("ImportError" in error for error in result.errors))

    def test_stabilize_generated_import_cycles_moves_import_to_function_use_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "sample"
            records = [
                (
                    str(package / "alpha.py"),
                    "",
                    "from sample.beta import read_beta\n\n\ndef read_alpha():\n    return read_beta()\n",
                ),
                (
                    str(package / "beta.py"),
                    "",
                    "from sample.alpha import read_alpha\n\n\ndef read_beta():\n    return 'beta'\n",
                ),
            ]

            stabilized, fixes = stabilize_project_edit_import_cycles(
                records,
                project_root=str(root),
            )

            alpha = stabilized[0][2]
            beta = stabilized[1][2]
            self.assertNotEqual([], fixes)
            self.assertNotIn("from sample.beta import read_beta\n\n\ndef", alpha)
            self.assertIn("    from sample.beta import read_beta", alpha)
            self.assertNotIn("from sample.alpha import read_alpha", beta)
            compile(alpha, "alpha.py", "exec")
            compile(beta, "beta.py", "exec")

    def test_traceback_repair_targets_and_replaces_only_failing_test_method(self) -> None:
        records = [(
            "C:/tmp/tests/test_tool.py",
            "",
            "import unittest\n\nclass ToolTests(unittest.TestCase):\n"
            "    def test_first(self):\n        self.assertTrue(True)\n\n"
            "    def test_second(self):\n        self.assertTrue(False)\n",
        )]
        target = resolve_project_edit_failure_symbol(
            records,
            ["FAIL: test_second (test_tool.ToolTests.test_second)\nAssertionError"],
        )

        repaired, errors = apply_project_edit_generated_symbol_repair(
            records,
            path=target["path"],
            symbol=target["symbol"],
            replacement_response=(
                "def test_second(self):\n"
                "    self.assertTrue(True)\n"
            ),
        )

        self.assertEqual([], errors)
        self.assertEqual("ToolTests.test_second", target["symbol"])
        self.assertIn("def test_first", repaired[0][2])
        self.assertIn("def test_second", repaired[0][2])
        self.assertNotIn("assertTrue(False)", repaired[0][2])

        wrapped_repair, wrapped_errors = apply_project_edit_generated_symbol_repair(
            records,
            path=target["path"],
            symbol=target["symbol"],
            replacement_response=(
                "class ToolTests:\n"
                "    def test_second(self):\n"
                "        self.assertEqual(2, 1 + 1)\n"
            ),
        )
        self.assertEqual([], wrapped_errors)
        self.assertIn("self.assertEqual(2, 1 + 1)", wrapped_repair[0][2])

    def test_function_repair_contract_is_scoped_to_callable_and_owned_requirements(self) -> None:
        records = [(
            "C:/tmp/snapshot.py",
            "",
            "import hashlib\n\n"
            "def compute_diff(before, after, *, detect_renames=True):\n"
            "    return directory_path\n\n"
            "def hash_file(path):\n"
            "    return hashlib.sha256(path.read_bytes()).hexdigest()\n",
        ), (
            "C:/tmp/test_snapshot.py",
            "",
            "def test_compute_diff():\n"
            "    with fixture() as temp_dir:\n"
            "        before = {'old.txt': 'abc'}\n"
            "        after = {'new.txt': 'abc'}\n"
            "        added, removed, modified, renamed = compute_diff(before, after)\n"
            "        assert renamed == {'old.txt': 'new.txt'}\n",
        )]
        target = resolve_project_edit_failure_symbol(
            records,
            [
                'File "C:/tmp/snapshot.py", line 4, in compute_diff\n'
                "NameError: name 'directory_path' is not defined"
            ],
        )

        contract, errors = build_project_edit_function_repair_contract(
            records,
            target=target,
            validation_errors=[
                "NameError: name 'directory_path' is not defined in compute_diff"
            ],
            objective="Compute deterministic Merkle diffs with rename detection.",
            requirements=["deterministic ordering", "rename detection"],
        )
        stage = build_project_edit_function_repair_stage(contract)
        diagnosis_stage = build_project_edit_function_repair_plan_stage(contract)

        self.assertEqual([], errors)
        self.assertEqual("compute_diff", contract["symbol"])
        self.assertIn("detect_renames=True", contract["signature"])
        self.assertEqual(["deterministic ordering", "rename detection"], contract["requirements"])
        self.assertIn("hash_file", contract["sibling_symbols"])
        self.assertIn("directory_path", contract["forbidden_names"])
        self.assertTrue(any("renamed ==" in value for value in contract["callsite_excerpts"]))
        self.assertFalse(any("temp_dir" in value for value in contract["callsite_excerpts"]))
        self.assertIn("Exact required signature", stage.user_prompt)
        self.assertNotIn("return hashlib.sha256", stage.user_prompt)
        self.assertIn("Do not write Python", diagnosis_stage.system_prompt)

    def test_function_repair_micro_plan_requires_algorithm_and_postconditions(self) -> None:
        plan, errors = parse_project_edit_function_repair_plan(json.dumps({
            "root_cause": "The function reads a nonexistent directory_path global.",
            "algorithm_steps": [
                "Build reverse digest indexes from old_snapshot and new_snapshot.",
                "Pair removed and added paths whose digest values match.",
            ],
            "preserve": ["the exact signature"],
            "postconditions": ["renames maps old paths to new paths deterministically"],
        }))
        _invalid, invalid_errors = parse_project_edit_function_repair_plan(json.dumps({
            "root_cause": "",
            "algorithm_steps": [],
            "preserve": [],
            "postconditions": [],
        }))
        _drift, drift_errors = parse_project_edit_function_repair_plan(
            json.dumps({
                "root_cause": "directory_path is undefined",
                "algorithm_steps": ["Add a directory_path parameter to the signature."],
                "preserve": ["return type"],
                "postconditions": ["the call succeeds"],
            }),
            contract={"forbidden_names": ["directory_path"]},
        )
        _shallow, shallow_errors = parse_project_edit_function_repair_plan(
            json.dumps({
                "root_cause": "Rename logic reads an unavailable path.",
                "algorithm_steps": ["Remove directory_path and return four collections."],
                "preserve": ["signature"],
                "postconditions": ["renames is deterministic"],
            }),
            contract={
                "forbidden_names": ["directory_path"],
                "objective": "Detect renamed files between snapshots.",
            },
        )

        self.assertEqual([], errors)
        self.assertIn("digest", " ".join(plan["algorithm_steps"]))
        self.assertGreaterEqual(len(invalid_errors), 3)
        self.assertTrue(any("signature" in error for error in drift_errors))
        self.assertTrue(any("snapshot digest" in error for error in shallow_errors))

    def test_callable_repair_rejects_signature_drift_and_new_undefined_globals(self) -> None:
        records = [(
            "C:/tmp/snapshot.py",
            "",
            "def compute_diff(before, after, *, detect_renames=True):\n"
            "    return []\n\n"
            "def preserved():\n"
            "    return 42\n",
        )]

        _repaired, signature_errors = apply_project_edit_generated_symbol_repair(
            records,
            path=records[0][0],
            symbol="compute_diff",
            replacement_response=(
                "def compute_diff(before, after):\n"
                "    return []\n"
            ),
        )
        _repaired, name_errors = apply_project_edit_generated_symbol_repair(
            records,
            path=records[0][0],
            symbol="compute_diff",
            replacement_response=(
                "def compute_diff(before, after, *, detect_renames=True):\n"
                "    return missing_index.build(before, after)\n"
            ),
        )
        _repaired, no_progress_errors = apply_project_edit_generated_symbol_repair(
            records,
            path=records[0][0],
            symbol="compute_diff",
            replacement_response=(
                "def compute_diff(before, after, *, detect_renames=True):\n"
                "    return directory_path\n"
            ),
            forbidden_names=["directory_path"],
        )
        exception_repaired, exception_errors = apply_project_edit_generated_symbol_repair(
            records,
            path=records[0][0],
            symbol="compute_diff",
            replacement_response=(
                "def compute_diff(before, after, *, detect_renames=True):\n"
                "    raise InventedSwapError('swap failed')\n"
            ),
        )
        stdlib_repaired, stdlib_errors = apply_project_edit_generated_symbol_repair(
            records,
            path=records[0][0],
            symbol="compute_diff",
            replacement_response=(
                "def compute_diff(before, after, *, detect_renames=True):\n"
                "    return sys.version_info[:2] if importlib.util else []\n"
            ),
        )

        self.assertTrue(any("signature" in error.lower() for error in signature_errors))
        self.assertTrue(any("undefined names" in error.lower() for error in name_errors))
        self.assertTrue(any("proven-invalid" in error for error in no_progress_errors))
        self.assertEqual([], exception_errors)
        self.assertIn("raise RuntimeError('swap failed')", exception_repaired[0][2])
        self.assertEqual([], stdlib_errors)
        self.assertIn("import importlib", stdlib_repaired[0][2])
        self.assertIn("import sys", stdlib_repaired[0][2])

    def test_production_placeholder_repairs_advance_across_callables(self) -> None:
        records = [(
            "C:/tmp/snapshot.py",
            "",
            "def scan_tree(root):\n"
            "    pass\n\n"
            "def compute_diff(before, after):\n"
            "    pass\n",
        )]
        errors = [
            "Generated production callables are placeholders: scan_tree, compute_diff"
        ]

        first = resolve_project_edit_failure_symbol(records, errors)
        second = resolve_project_edit_failure_symbol(
            records,
            errors,
            deprioritized_symbols={first["symbol"]},
        )

        self.assertEqual("scan_tree", first["symbol"])
        self.assertEqual("compute_diff", second["symbol"])

    def test_undefined_name_ownership_does_not_blame_innocent_callables(self) -> None:
        records = [(
            "C:/tmp/snapshot.py",
            "",
            "def snapshot_directory(directory_path):\n"
            "    return directory_path\n\n"
            "def compute_diff(before, after):\n"
            "    return directory_path\n\n"
            "def main():\n"
            "    directory_path = 'fixture'\n"
            "    return snapshot_directory(directory_path)\n",
        )]
        candidate = build_project_edit_multi_file_candidate(records)

        preview = preview_project_edit_agent_response(
            candidate,
            project_root="C:/tmp",
            request_prompt="Create a disposable snapshot utility.",
        )
        undefined_errors = [
            error
            for error in preview.errors
            if "undefined names" in error
        ]

        self.assertTrue(undefined_errors)
        self.assertIn("compute_diff", undefined_errors[0])
        self.assertNotIn("snapshot_directory, main", undefined_errors[0])

    def test_placeholder_repairs_advance_before_undefined_name_repairs(self) -> None:
        records = [(
            "C:/tmp/tests/test_tool.py",
            "",
            "import unittest\n\nclass ToolTests(unittest.TestCase):\n"
            "    def test_dynamic(self):\n        missing_helper()\n\n"
            "    def test_invalid_json(self):\n        pass\n",
        )]

        target = resolve_project_edit_failure_symbol(
            records,
            [
                "Generated test methods are placeholders: ToolTests.test_invalid_json",
                "Generated callables reference undefined names in ToolTests.test_dynamic: missing_helper",
            ],
        )

        self.assertEqual("ToolTests.test_invalid_json", target["symbol"])

    def test_shared_setup_traceback_repairs_setup_before_individual_tests(self) -> None:
        records = [(
            "C:/tmp/tests/test_tool.py",
            "",
            "import unittest\n\nclass ToolTests(unittest.TestCase):\n"
            "    def setUp(self):\n        self.path = 'missing/folder/data.jsonl'\n\n"
            "    def test_first(self):\n        self.assertTrue(self.path)\n\n"
            "    def test_second(self):\n        self.assertTrue(self.path)\n",
        )]

        target = resolve_project_edit_failure_symbol(
            records,
            [
                "ERROR: test_first (test_tool.ToolTests.test_first)\n"
                'File "test_tool.py", line 5, in setUp\nFileNotFoundError',
                "Generated test methods are placeholders: ToolTests.test_second",
            ],
        )

        self.assertEqual("ToolTests.setUp", target["symbol"])

    def test_runtime_traceback_repairs_production_before_the_asserting_test(self) -> None:
        records = [
            (
                "C:/tmp/snapshot.py",
                "",
                "def compute_diff(before, after):\n"
                "    return {'wrong'}\n",
            ),
            (
                "C:/tmp/tests/test_snapshot.py",
                "",
                "import unittest\n\n"
                "class SnapshotTests(unittest.TestCase):\n"
                "    def test_compute_diff(self):\n"
                "        self.assertEqual(compute_diff({}, {}), set())\n",
            ),
        ]

        target = resolve_project_edit_failure_symbol(
            records,
            [
                "FAIL: test_compute_diff (test_snapshot.SnapshotTests.test_compute_diff)\n"
                'File "C:/tmp/tests/test_snapshot.py", line 5, in test_compute_diff\n'
                "AssertionError"
            ],
        )

        self.assertEqual("compute_diff", target["symbol"])
        self.assertEqual("C:/tmp/snapshot.py", target["path"])

    def test_standard_library_symbol_repair_uses_runtime_inventory(self) -> None:
        repaired, fixes = resolve_project_edit_standard_library_symbols([(
            "C:/tmp/worker.py",
            "",
            "def wait_for_retry(delay):\n"
            "    \"\"\"Wait before retrying.\"\"\"\n"
            "    time.sleep(delay)\n",
        )])

        self.assertIn("import time", repaired[0][2])
        self.assertTrue(any("import time" in fix for fix in fixes))

    def test_many_placeholder_tests_request_file_level_repair(self) -> None:
        records = [(
            "C:/tmp/tests/test_tool.py",
            "",
            "import unittest\n\nclass ToolTests(unittest.TestCase):\n"
            "    def test_a(self):\n        pass\n"
            "    def test_b(self):\n        pass\n"
            "    def test_c(self):\n        pass\n"
            "    def test_d(self):\n        pass\n",
        )]

        target = resolve_project_edit_failure_symbol(
            records,
            ["Generated test methods are placeholders: "
             "ToolTests.test_a, ToolTests.test_b, ToolTests.test_c, ToolTests.test_d"],
        )

        self.assertEqual({}, target)

    def test_generated_file_gate_requires_manifest_symbols_and_real_bodies(self) -> None:
        _source, missing_errors = parse_project_edit_generated_file(
            "class Runtime:\n    \"\"\"Runtime.\"\"\"\n",
            path="C:/tmp/runtime.py",
            expected_public_symbols=["Runtime", "Task"],
        )
        placeholder_source, placeholder_errors = parse_project_edit_generated_file(
            "class Runtime:\n"
            "    \"\"\"Runtime.\"\"\"\n"
            "    def cancel(self):\n"
            "        \"\"\"Cancel work.\"\"\"\n"
            "        pass\n",
            path="C:/tmp/runtime.py",
            expected_public_symbols=["Runtime"],
        )

        self.assertTrue(any("Task" in error for error in missing_errors))
        self.assertTrue(any("placeholder" in error.lower() for error in placeholder_errors))
        self.assertTrue(any("Runtime.cancel" in error for error in placeholder_errors))
        self.assertIn("def cancel", placeholder_source)

        dataclass_source, dataclass_errors = parse_project_edit_generated_file(
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class Diff:\n"
            "    \"\"\"Describe changed paths.\"\"\"\n"
            "    additions: tuple[str, ...]\n"
            "    removals: tuple[str, ...]\n",
            path="C:/tmp/diff.py",
            expected_public_symbols=["Diff", "additions", "removals"],
        )
        self.assertEqual([], dataclass_errors)
        self.assertIn("class Diff", dataclass_source)

        inserted, insertion_errors = apply_project_edit_missing_symbol(
            "def existing():\n    return 1\n",
            path="C:/tmp/runtime.py",
            symbol="Runtime",
            response=(
                "class Runtime:\n"
                "    def cancel(self):\n"
                "        return True\n"
            ),
        )
        self.assertEqual([], insertion_errors)
        self.assertIn("class Runtime", inserted)
        method_inserted, method_errors = apply_project_edit_missing_symbol(
            "class ObserverSystem:\n"
            "    def __init__(self):\n"
            "        self.observers = []\n",
            path="C:/tmp/observer_system.py",
            symbol="emit_observer_event",
            response=(
                "class ObserverSystem:\n"
                "    async def emit_observer_event(self, event):\n"
                "        for observer in tuple(self.observers):\n"
                "            await observer(event)\n"
            ),
        )
        self.assertEqual([], method_errors)
        self.assertIn("async def emit_observer_event", method_inserted)
        stage = build_project_edit_missing_symbol_stage(
            path="C:/tmp/runtime.py",
            symbol="Runtime",
            source=inserted,
            objective="Create a runtime.",
        )
        self.assertIn("exactly one complete", stage.system_prompt)

        await_source, await_errors = parse_project_edit_generated_file(
            "async def run():\n"
            "    return 1\n\n"
            "if __name__ == '__main__':\n"
            "    result = await run()\n",
            path="C:/tmp/runtime.py",
            expected_public_symbols=["run"],
        )
        self.assertEqual([], await_errors)
        self.assertIn("async def run", await_source)
        self.assertNotIn("await run()", await_source)

        call_source, call_errors = parse_project_edit_generated_file(
            "def configure():\n"
            "    return True\n\n"
            "configure()\n",
            path="C:/tmp/configure.py",
            expected_public_symbols=["configure"],
        )
        self.assertEqual([], call_errors)
        self.assertEqual(1, call_source.count("configure()"))

        lifecycle_files, lifecycle_fixes = normalize_project_edit_async_test_lifecycle([
            (
                "C:/tmp/test_runtime.py",
                "",
                "import unittest\n\n"
                "class TestRuntime(unittest.IsolatedAsyncioTestCase):\n"
                "    async def setUp(self):\n"
                "        self.runtime = object()\n\n"
                "    async def test_runtime(self):\n"
                "        self.assertIsNotNone(self.runtime)\n",
            )
        ])
        self.assertIn("async def asyncSetUp", lifecycle_files[0][2])
        self.assertEqual(1, len(lifecycle_fixes))

    def test_identifier_contract_failure_targets_only_owning_method(self) -> None:
        records = [(
            "C:/tmp/task_tool.py",
            "",
            "class TaskTool:\n"
            "    def add_task(self, t):\n        return t\n\n"
            "    def list_tasks(self):\n        return []\n",
        )]

        target = resolve_project_edit_failure_symbol(
            records,
            ["Requested renamed identifiers remain: t"],
        )

        self.assertEqual("TaskTool.add_task", target["symbol"])

    def test_explicit_cleanup_is_scoped_and_source_preserving(self) -> None:
        original = (
            "class TaskTool:\n"
            "    def add_task(self, t):\n"
            "        self.debug_cache_unused = []\n"
            "        return t\n\n"
            "    def list_tasks(self):\n"
            "        return []\n"
        )
        generated = original + (
            "\n    def unrelated_helper(self):\n"
            "        \"\"\"Return unrelated state.\"\"\"\n"
            "        return True\n"
        )

        cleaned, fixes = enforce_project_edit_explicit_cleanup(
            [("C:/tmp/task_tool.py", original, generated)],
            request_prompt=(
                "Build out TaskTool. Rename t to task. "
                "Remove debug_cache_unused. Add useful docstrings."
            ),
        )

        source = cleaned[0][2]
        self.assertNotEqual([], fixes)
        self.assertIn("def add_task(self, task)", source)
        self.assertNotIn("debug_cache_unused", source)
        self.assertNotIn("unrelated_helper", source)
        self.assertIn("def list_tasks", source)
        compile(source, "task_tool.py", "exec")

    def test_known_standard_library_symbol_is_imported_without_rewriting_method(self) -> None:
        source = (
            "import unittest\n\n"
            "class ToolTests(unittest.TestCase):\n"
            "    def test_temp(self):\n"
            "        with NamedTemporaryFile() as handle:\n"
            "            self.assertTrue(handle.name)\n"
        )

        resolved, fixes = resolve_project_edit_standard_library_symbols(
            [("C:/tmp/test_tool.py", "", source)]
        )

        self.assertNotEqual([], fixes)
        self.assertIn("from tempfile import NamedTemporaryFile", resolved[0][2])
        self.assertIn("with NamedTemporaryFile() as handle:", resolved[0][2])

    def test_unused_generated_imports_are_removed_at_module_and_function_scope(self) -> None:
        source = (
            "import os\n\n"
            "def save_rows(rows):\n"
            "    from sample.report import summarize\n"
            "    return list(rows)\n"
        )

        resolved, fixes = remove_project_edit_unused_imports(
            [("C:/tmp/store.py", "", source)]
        )

        self.assertEqual(2, len(fixes))
        self.assertNotIn("import os", resolved[0][2])
        self.assertNotIn("import summarize", resolved[0][2])
        self.assertIn("return list(rows)", resolved[0][2])

    def test_preview_rejects_dynamic_path_test_that_never_checks_expanduser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = """<create_file path="task_tool.py">
import os


class TaskTool:
    \"\"\"Track tasks.\"\"\"

    def __init__(self, path=None):
        self.path = path or os.path.expanduser("~/tasks.json")
</create_file>
<create_file path="test_task_tool.py">
import unittest

from task_tool import TaskTool


class TaskToolTests(unittest.TestCase):
    def test_dynamic_default_path(self):
        tool = TaskTool("explicit.json")
        self.assertTrue(tool.path)
</create_file>"""

            result = preview_project_edit_agent_response(
                response,
                project_root=tmp,
                request_prompt=(
                    "Create TaskTool and add unittest coverage for dynamic default path."
                ),
            )

            self.assertFalse(result.ok)
            self.assertTrue(any("stronger behavioral proof" in error for error in result.errors))

    def test_explicit_path_test_contracts_use_the_disposable_fixture(self) -> None:
        source = (
            "import os\nimport unittest\n"
            "from sample.task_tool import TaskTool\n\n"
            "class TaskToolTests(unittest.TestCase):\n"
            "    def test_invalid_json(self):\n"
            "        from sample.task_store import load_tasks\n"
            "        self.assertEqual(load_tasks('home.json'), [])\n\n"
            "    def test_dynamic_default_path(self):\n"
            "        self.assertTrue(TaskTool().path)\n"
        )

        resolved, fixes = enforce_project_edit_requested_test_contracts(
            [("C:/tmp/test_task_tool.py", "", source)],
            request_prompt=(
                "Use os.path.expanduser('~/tasks.json') and add tests for invalid JSON "
                "and dynamic default path."
            ),
        )

        result = resolved[0][2]
        self.assertEqual(2, len(fixes))
        self.assertIn("open(self.tool.path", result)
        self.assertIn("os.path.expanduser('~/tasks.json')", result)
        self.assertNotIn("load_tasks('home.json')", result)
        compile(result, "test_task_tool.py", "exec")

    def test_generated_python_formatter_normalizes_repaired_method_indentation(self) -> None:
        source = (
            "# coding=utf-8\n\n\nclass ToolTests:\n"
            "    def test_value(self):\n"
            "            value = 1\n"
            "            assert value == 1\n"
        )

        formatted, fixes = format_project_edit_generated_python(
            [("C:/tmp/test_tool.py", "", source)]
        )

        self.assertNotEqual([], fixes)
        self.assertIn("        value = 1", formatted[0][2])
        self.assertNotIn("            value = 1", formatted[0][2])
        compile(formatted[0][2], "test_tool.py", "exec")

    def test_preview_enforces_explicit_identifier_cleanup_and_public_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "task_tool.py"
            source.write_text(
                'def process_task(t):\n    """Process one task."""\n    return t\n',
                encoding="utf-8",
            )
            response = f"""<modify_file path="{source}">
<<<< ORIGINAL
def process_task(t):
    \"\"\"Process one task.\"\"\"
    return t
====
def process_task(t):
    \"\"\"Process one task.\"\"\"
    debug_cache_unused = []
    return t


def unrelated_helper():
    \"\"\"Return an unrelated value.\"\"\"
    return True
>>>>
</modify_file>"""

            result = preview_project_edit_agent_response(
                response,
                project_root=tmp,
                request_prompt=(
                    "Create process_task. Rename t to task. "
                    "Remove debug_cache_unused. Add useful docstrings."
                ),
            )

            self.assertFalse(result.ok)
            self.assertTrue(any("removed identifiers remain" in error for error in result.errors))
            self.assertTrue(any("renamed identifiers remain" in error for error in result.errors))
            self.assertTrue(any("Unrequested public callables" in error for error in result.errors))

    def test_generated_cross_file_symbols_and_requested_docstrings_are_wired(self) -> None:
        records = [
            ("C:/tmp/sample/report.py", "", "def summarize(rows):\n    return len(rows)\n"),
            (
                "C:/tmp/sample/tool.py",
                "",
                "class TaskTool:\n"
                "    def count(self, rows):\n"
                "        return summarize(rows)\n",
            ),
        ]

        wired, symbol_fixes = resolve_project_edit_cross_file_symbols(
            records,
            project_root="C:/tmp",
        )
        documented, docstring_fixes = ensure_project_edit_requested_docstrings(
            wired,
            request_prompt="Add useful docstrings.",
        )

        self.assertNotEqual([], symbol_fixes)
        self.assertNotEqual([], docstring_fixes)
        self.assertIn("from sample.report import summarize", documented[1][2])
        self.assertIn('"""Provide task tool behavior."""', documented[1][2])
        compile(documented[1][2], "tool.py", "exec")

    def test_generated_test_fixture_isolated_without_rewriting_test_methods(self) -> None:
        records = [
            (
                "C:/tmp/sample/tool.py",
                "",
                "class Tool:\n    def __init__(self, path=None):\n        self.path = path\n",
            ),
            (
                "C:/tmp/tests/test_tool.py",
                "",
                "import unittest\n\nclass ToolTests(unittest.TestCase):\n"
                "    def setUp(self):\n        self.tool = Tool()\n\n"
                "    def test_value(self):\n        self.assertIsNotNone(self.tool)\n",
            ),
        ]

        isolated, fixes = isolate_project_edit_generated_test_fixture(records)

        self.assertNotEqual([], fixes)
        self.assertIn("TemporaryDirectory", isolated[1][2])
        self.assertIn("generated_test_data.json", isolated[1][2])
        self.assertIn("def test_value", isolated[1][2])
        compile(isolated[1][2], "test_tool.py", "exec")

    def test_apply_withholds_completion_when_generated_behavior_test_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = '''<create_file path="calculator_tool.py">
def add_values(left: int, right: int) -> int:
    """Return the sum of two integer values.

    :param left: Left integer value.
    :param right: Right integer value.
    :return: Sum of both values.
    """
    return left - right
</create_file>
<create_file path="test_calculator_tool.py">
import unittest

from calculator_tool import add_values


class CalculatorToolTests(unittest.TestCase):
    def test_add_values_returns_sum(self):
        self.assertEqual(5, add_values(2, 3))


if __name__ == "__main__":
    unittest.main()
</create_file>'''

            result = apply_project_edit_agent_response(
                response,
                project_root=tmp,
                request_prompt="Create a reusable calculator tool with working behavior.",
            )

            self.assertFalse(result.ok)
            self.assertEqual("preview_failed", result.status)
            self.assertTrue(any("FAILED" in error or "failed" in error.lower() for error in result.errors))

    def test_validate_project_edit_paths_reuses_python_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "checked.py"
            source.write_text("def checked():\n    return True\n", encoding="utf-8")

            result = validate_project_edit_paths([str(source)])

            self.assertEqual(1, len(result))
            self.assertTrue(result[0]["ok"])
            self.assertIn("py_compile checked.py", result[0]["command"])

    def test_target_discovery_uses_subsystem_paths_over_active_file_for_indexing(self) -> None:
        discovery = discover_edit_targets(
            "Indexing says ready while still running; find that progress bug and fix it.",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(any("knowledge_background_service.py" in path or "main_window_core.py" in path for path in paths))
        self.assertFalse(str((discovery["best_target"] or {}).get("path") or "").endswith("custom_widgets.py"))

    def test_target_discovery_uses_prompt_thread_paths_for_freeze_work(self) -> None:
        discovery = discover_edit_targets(
            "Troubleshoot why the app freezes during long prompts and patch the likely main-thread issue.",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(
            any(
                marker in path
                for path in paths
                for marker in (
                    "main_window_chat_runtime.py",
                    "prompt_dispatch_service.py",
                    "prompt_progress_service.py",
                )
            )
        )
        self.assertFalse(str((discovery["best_target"] or {}).get("path") or "").endswith("custom_widgets.py"))

    def test_target_discovery_uses_parser_paths_for_xml_patch_work(self) -> None:
        discovery = discover_edit_targets(
            "Find the parser for XML patches and make errors more actionable.",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(any("project_edit_agent_service.py" in path or "knowledge/search.py" in path for path in paths))
        self.assertFalse(str((discovery["best_target"] or {}).get("path") or "").replace("\\", "/").startswith("tests/"))

    def test_target_discovery_uses_pipeline_paths_for_node_graph_work(self) -> None:
        discovery = discover_edit_targets(
            "When I right click in pipeline node view the filter is slow. Find the code path and improve it.",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(any("pipeline_node_view.py" in path or "node_search_dialog.py" in path for path in paths))
        self.assertFalse(str((discovery["best_target"] or {}).get("path") or "").endswith("custom_widgets.py"))

    def test_target_discovery_uses_code_agent_paths_for_adaptive_planning(self) -> None:
        discovery = discover_edit_targets(
            "Which service should own adaptive code-agent planning?",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(any("project_edit_agent_service.py" in path or "code_intelligence_service.py" in path for path in paths))

    def test_target_discovery_uses_maya_rigging_paths_for_docstring_work(self) -> None:
        discovery = discover_edit_targets(
            "Add missing docstrings and missing param entries to existing Maya rigging functions, but inspect the project first.",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(any("maya_tools/Rigging/create_rig.py" in path for path in paths))
        self.assertFalse(str((discovery["best_target"] or {}).get("path") or "").endswith("custom_widgets.py"))

    def test_project_edit_contract_requires_create_plan_for_missing_targets(self) -> None:
        context = format_edit_target_context(
            {
                "question": "Create missing function launch_rig_mapping_wizard in the Maya UI layer.",
                "project_roots": ["C:/depot/tools"],
                "active_path": self.ACTIVE_UI_FILE,
                "terms": ["launch", "rig", "mapping", "wizard"],
                "scope": None,
                "confidence": "none",
                "best_target": None,
                "candidates": [],
            }
        )
        prompt = build_project_edit_target_prompt(
            "Create missing function launch_rig_mapping_wizard in the Maya UI layer.",
            context,
            active_path=self.ACTIVE_UI_FILE,
        )

        self.assertIn("verify that the target exists", prompt)
        self.assertIn("how to create it", prompt)
        self.assertIn("how it would be implemented", prompt)
        self.assertIn("ask for approval before emitting a create-file or create-symbol patch", prompt)
        self.assertIn("creation plan and implementation plan", prompt)

    def test_artifact_manifest_rejects_test_redeclaration_of_production_api(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "files": [
                        {
                            "path": "tech_connector/services/generated/worker.py",
                            "purpose": "Own production behavior.",
                            "requirements": ["reload plugins"],
                            "public_symbols": ["HotReloader(module_path)"],
                            "depends_on": [],
                            "is_test": False,
                        },
                        {
                            "path": "tech_connector/examples/tests/test_worker.py",
                            "purpose": "Prove production behavior.",
                            "requirements": ["reload plugins"],
                            "public_symbols": [
                                "HotReloader(module_path)",
                                "TestHotReloader.test_reload()",
                            ],
                            "depends_on": [
                                "tech_connector/services/generated/worker.py"
                            ],
                            "is_test": True,
                        },
                    ]
                }),
                project_root=root,
            )

        self.assertEqual([], manifest)
        self.assertTrue(any("import production APIs" in error for error in errors))

    def test_standard_library_resolution_covers_test_class_bases_and_mock(self) -> None:
        source = (
            "class TestWorker(unittest.IsolatedAsyncioTestCase):\n"
            "    async def test_swap(self):\n"
            "        value = Mock()\n"
            "        self.assertIsNotNone(value)\n"
        )

        resolved, fixes = resolve_project_edit_standard_library_symbols([
            ("C:/tmp/test_worker.py", "", source)
        ])

        self.assertIn("import unittest", resolved[0][2])
        self.assertIn("from unittest.mock import Mock", resolved[0][2])
        self.assertEqual(2, len(fixes))

    def test_function_repair_forbidden_names_are_scoped_to_target_callable(self) -> None:
        source = (
            "import unittest\n\n"
            "class TestWorker(unittest.TestCase):\n"
            "    def test_first(self):\n"
            "        self.assertTrue(Mock())\n\n"
            "    def test_second(self):\n"
            "        self.assertTrue(other_missing)\n"
        )
        generated = [("C:/tmp/test_worker.py", "", source)]

        contract, errors = build_project_edit_function_repair_contract(
            generated,
            target={
                "path": "C:/tmp/test_worker.py",
                "symbol": "TestWorker.test_first",
            },
            validation_errors=[
                "Generated callables reference undefined names in "
                "TestWorker.test_first: Mock",
                "Generated callables reference undefined names in "
                "TestWorker.test_second: other_missing",
            ],
            objective="Repair the failing test.",
        )

        self.assertEqual([], errors)
        self.assertEqual(["Mock"], contract["forbidden_names"])

    def test_duplicate_dependency_symbols_are_replaced_with_canonical_imports(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            owner_path = root_path / "package" / "owner.py"
            consumer_path = root_path / "package" / "consumer.py"
            owner_source = "class Worker:\n    def run(self):\n        return 1\n"
            consumer_source = (
                "class Worker:\n"
                "    def run(self):\n"
                "        return 2\n\n"
                "class Consumer:\n"
                "    def __init__(self):\n"
                "        self.worker = Worker()\n"
            )

            repaired, fixes = repair_project_edit_duplicate_dependency_symbols(
                consumer_source,
                path=str(consumer_path),
                project_root=root,
                generated_files=[(str(owner_path), "", owner_source)],
            )

        self.assertIn("from package.owner import Worker", repaired)
        self.assertEqual(0, repaired.count("class Worker"))
        self.assertNotIn("class Worker", repaired)
        self.assertTrue(any("removed echoed Worker" in fix for fix in fixes))
        dependencies = infer_project_edit_generated_dependencies(
            repaired,
            path=str(consumer_path),
            project_root=str(root_path),
            generated_files=[(str(owner_path), "", owner_source)],
        )
        self.assertEqual(["package/owner.py"], dependencies)

    def test_strict_artifact_manifest_compacts_six_files_without_losing_contracts(self) -> None:
        files = []
        for index in range(5):
            files.append({
                "path": f"tech_connector/services/generated/part_{index}.py",
                "purpose": f"Own behavior {index}.",
                "requirements": [f"behavior {index}"],
                "public_symbols": [f"run_{index}(value)"],
                "contracts": [f"run_{index}(value) returns value"],
                "algorithm_steps": [f"process behavior {index}"],
                "validation_steps": [f"verify behavior {index}"],
                "depends_on": [],
                "is_test": False,
            })
        files.append({
            "path": "tech_connector/examples/tests/test_parts.py",
            "purpose": "Prove all behavior.",
            "requirements": ["all behavior"],
            "public_symbols": ["TestParts.test_all()"],
            "contracts": ["TestParts.test_all() returns None"],
            "algorithm_steps": ["exercise all public APIs"],
            "validation_steps": ["run focused unittest"],
            "depends_on": [item["path"] for item in files],
            "is_test": True,
        })
        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "integration_contracts": [
                        "run_0(value) returns value using stable ownership"
                    ],
                    "files": files,
                }),
                project_root=root,
                strict_architecture=True,
            )

        self.assertEqual([], errors)
        self.assertEqual(5, len(manifest))
        self.assertEqual(5, len({
            symbol.split("(", 1)[0]
            for item in manifest
            if not item["is_test"]
            for symbol in item["public_symbols"]
        }))
        self.assertTrue(any(item["dependency_repairs"] for item in manifest))

    def test_manifest_splits_accidentally_joined_quoted_public_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "files": [
                        {
                            "path": "tech_connector/services/generated/worker.py",
                            "purpose": "Own worker behavior.",
                            "requirements": ["worker behavior"],
                            "public_symbols": [
                                "register_observer', 'emit_observer_event"
                            ],
                            "depends_on": [],
                            "is_test": False,
                        },
                        {
                            "path": "tech_connector/examples/tests/test_worker.py",
                            "purpose": "Prove worker behavior.",
                            "requirements": ["worker behavior"],
                            "public_symbols": [],
                            "depends_on": [
                                "tech_connector/services/generated/worker.py"
                            ],
                            "is_test": True,
                        },
                    ]
                }),
                project_root=root,
            )

        self.assertEqual([], errors)
        self.assertEqual(
            ["register_observer", "emit_observer_event"],
            manifest[0]["public_symbols"],
        )

    def test_strict_manifest_rejects_duplicate_production_api_owners(self) -> None:
        files = []
        for name in ("first", "second"):
            files.append({
                "path": f"tech_connector/services/generated/{name}.py",
                "purpose": f"Own {name} behavior.",
                "requirements": ["observer behavior"],
                "public_symbols": ["ObserverDispatchError"],
                "contracts": ["ObserverDispatchError reports callback failures"],
                "algorithm_steps": ["notify observer snapshot"],
                "validation_steps": ["inspect emitted event"],
                "depends_on": [],
                "is_test": False,
            })
        files.append({
            "path": "tech_connector/examples/tests/test_observer.py",
            "purpose": "Prove observer behavior.",
            "requirements": ["observer behavior"],
            "public_symbols": ["TestObserver.test_emit()"],
            "contracts": ["TestObserver.test_emit() returns None"],
            "algorithm_steps": ["register and assert callback"],
            "validation_steps": ["run unittest"],
            "depends_on": [item["path"] for item in files],
            "is_test": True,
        })
        with tempfile.TemporaryDirectory() as root:
            manifest, errors = parse_project_edit_artifact_manifest(
                json.dumps({
                    "integration_contracts": [
                        "signatures: emit_observer_event(event) returns None",
                        "errors: ObserverDispatchError reports callback failures",
                    ],
                    "files": files,
                }),
                project_root=root,
                strict_architecture=True,
            )

        self.assertEqual([], manifest)
        self.assertTrue(any("multiple owners" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
