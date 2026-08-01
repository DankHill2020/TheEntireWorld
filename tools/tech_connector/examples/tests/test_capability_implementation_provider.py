from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tech_connector.services.capability_acquisition_coordinator import (
    CapabilityAcquisitionCoordinator,
)
from tech_connector.services.capability_implementation_provider import (
    ModelBackedCapabilityImplementationProvider,
)
from tech_connector.services.project_edit_agent_service import (
    ProjectEditPlan,
    ProjectEditPromptStage,
)


class CapabilityImplementationProviderTests(unittest.TestCase):
    def test_missing_public_docstring_is_repaired_without_model_call(self) -> None:
        provider = ModelBackedCapabilityImplementationProvider(".")
        output = json.dumps({
            "changes": [{
                "action": "insert_after_symbol",
                "path": "unreal_tools/niagara.py",
                "target_symbol": "attach_editable_character_fx",
                "original_content": "",
                "new_content": "\ndef synthesize_source_strategy_stack(source_strategy, parameters):\n    return parameters",
            }],
            "report": {"changed": [], "reused": [], "verification": [], "remaining_gaps": []},
            "blocked_reason": "",
        })
        repaired, actions = provider._mechanically_repair_output(
            output,
            ["New public callables need useful docstrings: synthesize_source_strategy_stack"],
            SimpleNamespace(plan={}),
        )

        code = json.loads(repaired)["changes"][0]["new_content"]
        tree = ast.parse(code)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
        self.assertIsNotNone(ast.get_docstring(function))
        self.assertEqual(actions, ["inserted_missing_public_docstring"])

    def test_behavior_contract_rejects_metadata_only_domain_strategy(self) -> None:
        provider = ModelBackedCapabilityImplementationProvider(".")
        preview = SimpleNamespace(changes=[
            {
                "path": "unreal_tools/niagara.py",
                "after": (
                    "def synthesize_source_strategy_stack(source_strategy, parameters):\n"
                    "    return {'source_strategy': 'camera_facing_character_outline'}\n"
                ),
            },
            {
                "path": "tech_connector/examples/tests/test_niagara.py",
                "after": (
                    "def test_stack():\n"
                    "    mock = object()\n"
                    "    synthesize_source_strategy_stack('camera_facing_character_outline', {})\n"
                ),
            },
        ])
        job = SimpleNamespace(plan={
            "requested_operation": "niagara.synthesize_source_strategy_stack",
            "requested_behavior_contract": {
                "source_strategy": "camera_facing_character_outline",
                "required_implementation_evidence": [
                    {
                        "label": "host mutation readback",
                        "any_of": ["stack_readback", "module_readback", "renderer_readback"],
                    },
                ],
            },
        })

        errors = provider._behavior_contract_errors(preview, job)

        self.assertTrue(any("host mutation readback" in error for error in errors))

    def test_cpp_required_contract_rejects_python_only_adapter(self) -> None:
        provider = ModelBackedCapabilityImplementationProvider(".")
        preview = SimpleNamespace(changes=[{
            "path": "unreal_tools/niagara.py",
            "after": (
                "def synthesize_source_strategy_stack(system_path, source_strategy, parameters, save=True):\n"
                "    return unreal.AIStudioBridgeLibrary.synthesize_niagara_source_strategy_stack()\n"
            ),
        }])
        job = SimpleNamespace(plan={
            "requested_operation": "niagara.synthesize_source_strategy_stack",
            "requested_behavior_contract": {
                "source_strategy": "camera_facing_character_outline",
                "required_implementation_layer": "reflected_cpp_bridge",
                "required_cpp_method": "SynthesizeNiagaraSourceStrategyStack",
                "required_python_bridge_call": "unreal.AIStudioBridgeLibrary.synthesize_niagara_source_strategy_stack",
                "required_unreal_modules": ["Niagara", "NiagaraEditor"],
            },
        })

        errors = provider._behavior_contract_errors(preview, job)

        self.assertTrue(any("C++ body is missing" in error for error in errors))
        self.assertTrue(any("C++ declaration is missing" in error for error in errors))
        self.assertTrue(any("Build.cs is missing" in error for error in errors))

    def test_missing_test_symbol_is_reanchored_to_indexed_method(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            test_path = root / "examples" / "tech_connector" / "tests" / "test_unreal_execution_pipeline.py"
            test_path.parent.mkdir(parents=True)
            test_path.write_text(
                "import unittest\n\n"
                "class TestUnrealExecutionPipeline(unittest.TestCase):\n"
                "    def test_existing_niagara(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            provider = ModelBackedCapabilityImplementationProvider(root)
            output = json.dumps({
                "changes": [{
                    "action": "insert_after_symbol",
                    "path": str(test_path),
                    "target_symbol": "test_unreal_execution_pipeline",
                    "original_content": "",
                    "new_content": "def test_new_niagara(self):\n    self.assertTrue(True)",
                }],
                "report": {"changed": [], "reused": [], "verification": [], "remaining_gaps": []},
                "blocked_reason": "",
            })
            job = SimpleNamespace(plan={
                "host": "unreal",
                "requested_operation": "niagara.synthesize_source_strategy_stack",
            })

            repaired, actions = provider._mechanically_repair_output(
                output,
                [f"Indexed Python symbol was not found: test_unreal_execution_pipeline in {test_path}"],
                job,
            )

            change = json.loads(repaired)["changes"][0]
            self.assertEqual(
                change["target_symbol"],
                "TestUnrealExecutionPipeline.test_existing_niagara",
            )
            self.assertTrue(change["new_content"].startswith("    def"))
            self.assertTrue(any(action.startswith("reanchored_test_change") for action in actions))

    def test_unresolved_niagara_test_import_is_normalized_without_model(self) -> None:
        provider = ModelBackedCapabilityImplementationProvider(".")
        output = json.dumps({
            "changes": [{
                "action": "insert_after_symbol",
                "path": "tech_connector/examples/tests/test_niagara.py",
                "target_symbol": "TestNiagara.test_existing",
                "original_content": "",
                "new_content": (
                    "    def test_new(self):\n"
                    "        from niagara import synthesize_source_strategy_stack\n"
                    "        self.assertTrue(synthesize_source_strategy_stack)\n"
                ),
            }],
            "report": {"changed": [], "reused": [], "verification": [], "remaining_gaps": []},
            "blocked_reason": "",
        })
        job = SimpleNamespace(plan={"requested_operation": "niagara.synthesize_source_strategy_stack"})

        repaired, actions = provider._mechanically_repair_output(
            output,
            ["New import could not be resolved or accounted for: niagara.synthesize_source_strategy_stack."],
            job,
        )

        code = json.loads(repaired)["changes"][0]["new_content"]
        self.assertIn("from unreal_tools.niagara import synthesize_source_strategy_stack", code)
        self.assertIn("normalized_focused_test_import", actions)

    def test_behavior_contract_uses_small_alignment_critic_without_rerouting(self) -> None:
        captured = {}

        def verifier(prompt, candidate):
            captured["prompt"] = prompt
            captured["candidate"] = candidate
            return {
                "matches_request": False,
                "missing": [{"request_fragment": "camera silhouette readback"}],
                "elapsed_ms": 3.5,
            }

        provider = ModelBackedCapabilityImplementationProvider(".", alignment_verifier=verifier)
        job = SimpleNamespace(
            original_request="Create camera silhouette Niagara FX.",
            plan={
                "requested_operation": "niagara.synthesize_source_strategy_stack",
                "requested_behavior_contract": {
                    "source_strategy": "camera_facing_character_outline",
                    "acceptance": ["Prove stack readback."],
                },
                "steps": [{"objective": "Implement the missing stack operation."}],
            },
        )

        verdict = provider._verify_design_alignment(job)

        self.assertFalse(verdict["matches_request"])
        self.assertEqual(captured["prompt"], job.original_request)
        self.assertEqual(
            captured["candidate"]["operation_plan"]["operation"],
            "niagara.synthesize_source_strategy_stack",
        )

    def test_disposable_failure_is_repaired_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "adapter.py"
            source.write_text("def existing():\n    return False\n", encoding="utf-8")
            plan = ProjectEditPlan(
                prompt="Implement sample.operation",
                discovery={
                    "project_roots": [str(root)],
                    "best_target": {"path": str(source), "symbols": [{"name": "existing"}]},
                    "candidates": [],
                },
                discovery_context=f"Target: {source}\nSymbol: existing",
                model_prompt="",
                active_path=str(source),
            )
            stage = ProjectEditPromptStage(
                key="patch_generation",
                label="Patch",
                system_prompt="patch",
                user_prompt="patch",
                model_tier="local_code",
                response_format="json",
            )
            model_calls: list[str] = []
            validation_calls = 0
            apply_calls = 0

            def model_query(stage_arg, _model, _prompt=None):
                model_calls.append(stage_arg.key)
                return "candidate-one" if len(model_calls) == 1 else "candidate-two"

            def previewer(output, **_kwargs):
                return SimpleNamespace(
                    ok=True,
                    errors=[],
                    changes=[{"path": str(source), "after": f"# {output}\n"}],
                )

            def validator(**_kwargs):
                nonlocal validation_calls
                validation_calls += 1
                if validation_calls == 1:
                    return {
                        "ok": False,
                        "errors": ["focused test failed"],
                        "commands": [{"exit_code": 1, "command": ["python", "-m", "unittest"], "stderr": "assertion failed"}],
                    }
                return {"ok": True, "temp_workspace": str(root / "temp"), "commands": []}

            def applier(_output, **_kwargs):
                nonlocal apply_calls
                apply_calls += 1
                return SimpleNamespace(ok=True, errors=[], changes=[], change_session_path="")

            provider = ModelBackedCapabilityImplementationProvider(
                root,
                model_query=model_query,
                plan_builder=lambda *_args, **_kwargs: plan,
                stage_builder=lambda _plan: [stage],
                previewer=previewer,
                temp_validator=validator,
                applier=applier,
            )
            provider._state.update({"edit_plan": plan, "context_revision": 0, "approved_plan": "approved"})
            from tech_connector.services.capability_acquisition_coordinator import AcquisitionJob

            job = AcquisitionJob(
                plan={"host": "unreal", "requested_operation": "sample.operation"},
                original_request="Implement it.",
            )
            result = provider._implement(job)

            self.assertTrue(result["ok"], result)
            self.assertEqual(validation_calls, 2)
            self.assertEqual(apply_calls, 1)
            self.assertEqual(model_calls, ["patch_generation", "quality_repair_1"])

    def test_post_apply_missing_callable_automatically_reenters_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            available = False
            provider = ModelBackedCapabilityImplementationProvider(
                directory,
                operation_validator=lambda operation: {
                    "operation": operation,
                    "callable_found": available,
                    "reason": "missing" if not available else "available",
                },
                live_operation_validator=lambda _status: {"ok": True},
            )
            provider._state["applied"] = SimpleNamespace(changes=[])
            repair_contexts: list[list[str]] = []

            def repair(_job):
                nonlocal available
                repair_contexts.append(list(provider._state.get("repair_context") or []))
                available = True
                provider._state["applied"] = SimpleNamespace(changes=[])
                return {"ok": True}

            provider._implement = repair
            from tech_connector.services.capability_acquisition_coordinator import AcquisitionJob

            job = AcquisitionJob(
                plan={"host": "unreal", "requested_operation": "sample.operation"},
                original_request="Implement it.",
            )
            result = provider._validate(job)

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["repair_attempts"], 1)
            self.assertEqual(len(repair_contexts), 1)
            self.assertIn("still not an importable callable", repair_contexts[0][0])

    def test_disposable_validator_expands_workspace_placeholders(self) -> None:
        from tech_connector.services.code_operation_service import validate_patch_in_temp_workspace

        with tempfile.TemporaryDirectory() as directory:
            result = validate_patch_in_temp_workspace(
                source_root=directory,
                patch_files=[{"path": "sample.py", "content": "VALUE = 1\n"}],
                validation_commands=[
                    [
                        "python",
                        "-c",
                        "import pathlib,sys; assert pathlib.Path(sys.argv[1]).is_dir()",
                        "{workspace}",
                    ]
                ],
                keep_workspace=False,
            )

            self.assertTrue(result["ok"], result)
            self.assertNotIn("{workspace}", result["commands"][0]["command"][-1])

    def test_disposable_copy_excludes_all_dot_prefixed_directories(self) -> None:
        from tech_connector.services.code_operation_service import validate_patch_in_temp_workspace

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "tech_connector"
            hidden = package / ".pytest_cache"
            hidden.mkdir(parents=True)
            (hidden / "blocked.txt").write_text("local cache", encoding="utf-8")
            (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

            result = validate_patch_in_temp_workspace(
                source_root=root,
                copy_paths=["tech_connector"],
                validation_commands=[],
                keep_workspace=True,
            )

            self.assertTrue(result["ok"], result)
            copied_root = Path(result["temp_workspace"]) / "tech_connector"
            self.assertTrue((copied_root / "module.py").exists())
            self.assertFalse((copied_root / ".pytest_cache").exists())

    def test_cpp_patch_requests_disposable_unreal_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugins" / "AIStudioBridge"
            source = plugin / "Source" / "AIStudioBridge" / "Private" / "AIStudioBridgeLibrary.cpp"
            source.parent.mkdir(parents=True)
            source.write_text("void Existing() {}\n", encoding="utf-8")
            (plugin / "AIStudioBridge.uplugin").write_text("{}", encoding="utf-8")
            engine = root / "UE_5.8"
            run_uat = engine / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
            run_uat.parent.mkdir(parents=True)
            run_uat.write_text("@echo off\n", encoding="utf-8")
            captured = {}

            def validator(**kwargs):
                captured.update(kwargs)
                return {"ok": True, "temp_workspace": str(root / "temp"), "commands": []}

            provider = ModelBackedCapabilityImplementationProvider(
                root,
                settings={"unreal_engine_root": str(engine)},
                temp_validator=validator,
            )
            preview = SimpleNamespace(
                changes=[
                    {
                        "path": str(source),
                        "after": "void Existing() {}\nvoid Acquired() {}\n",
                    }
                ]
            )
            result = provider._validate_in_temp(preview)

            self.assertTrue(result["ok"])
            self.assertEqual(captured["timeout_seconds"], 900)
            self.assertIn("plugins/AIStudioBridge", captured["copy_paths"])
            build_command = captured["validation_commands"][0]
            self.assertIn("BuildPlugin", build_command)
            self.assertTrue(any("{workspace}" in item for item in build_command))

    def test_python_patch_runs_changed_focused_tests_in_disposable_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tech_connector" / "sample.py"
            test = root / "examples" / "tech_connector" / "tests" / "test_sample.py"
            source.parent.mkdir(parents=True)
            test.parent.mkdir(parents=True)
            source.write_text("VALUE = 1\n", encoding="utf-8")
            test.write_text("import unittest\n", encoding="utf-8")
            captured = {}

            def validator(**kwargs):
                captured.update(kwargs)
                return {"ok": True, "temp_workspace": str(root / "temp"), "commands": []}

            provider = ModelBackedCapabilityImplementationProvider(root, temp_validator=validator)
            preview = SimpleNamespace(changes=[
                {"path": str(source), "after": "VALUE = 2\n"},
                {"path": str(test), "after": "import unittest\n"},
            ])
            result = provider._validate_in_temp(preview)

            self.assertTrue(result["ok"])
            self.assertIn(
                ["python", "-m", "unittest", "examples.tech_connector.tests.test_sample"],
                captured["validation_commands"],
            )

    def test_research_anchors_to_operation_owner_not_keyword_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owner = root / "unreal_tools" / "niagara.py"
            owner.parent.mkdir(parents=True)
            owner.write_text("def attach_editable_character_fx():\n    return True\n", encoding="utf-8")
            unrelated = root / "external_tools" / "character_config.py"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("class CharacterConfig:\n    pass\n", encoding="utf-8")
            wrong_plan = ProjectEditPlan(
                prompt="wrong",
                discovery={
                    "project_roots": [str(root)],
                    "best_target": {"path": str(unrelated), "symbols": []},
                    "candidates": [{"path": str(unrelated), "symbols": []}],
                },
                discovery_context=str(unrelated),
                model_prompt="",
            )
            job_plan = {
                "host": "unreal",
                "requested_operation": "niagara.synthesize_source_strategy_stack",
                "resume_operation": "niagara.attach_editable_character_fx",
            }
            provider = ModelBackedCapabilityImplementationProvider(
                root,
                plan_builder=lambda *_args, **_kwargs: wrong_plan,
            )
            from tech_connector.services.capability_acquisition_coordinator import AcquisitionJob

            job = AcquisitionJob(plan=job_plan, original_request="Build character outline FX.")
            result = provider.run_stage({"step_id": "research_host_api", "action": "search"}, job)

            self.assertTrue(result["ok"])
            self.assertEqual(Path(result["evidence"]["best_target"]["path"]), owner)

    def test_cpp_required_contract_prioritizes_plugin_sources_before_python(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [
                root / "unreal_tools" / "niagara.py",
                root / "plugins" / "AIStudioBridge" / "Source" / "AIStudioBridge" / "Private" / "AIStudioBridgeLibrary.cpp",
                root / "plugins" / "AIStudioBridge" / "Source" / "AIStudioBridge" / "Public" / "AIStudioBridgeLibrary.h",
                root / "plugins" / "AIStudioBridge" / "Source" / "AIStudioBridge" / "AIStudioBridge.Build.cs",
            ]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("// evidence\n" if path.suffix != ".py" else "def existing():\n    pass\n", encoding="utf-8")
            provider = ModelBackedCapabilityImplementationProvider(root)
            job = SimpleNamespace(plan={
                "host": "unreal",
                "requested_operation": "niagara.synthesize_source_strategy_stack",
                "requested_behavior_contract": {"required_implementation_layer": "reflected_cpp_bridge"},
            })

            owners = provider._owner_paths(job)

            self.assertEqual(owners[0].suffix, ".cpp")
            self.assertEqual(owners[1].suffix, ".h")
            self.assertTrue(owners[2].name.endswith(".Build.cs"))
            self.assertEqual(owners[3].name, "niagara.py")

    def test_cpp_generation_is_split_and_merged_across_warm_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "cpp_declaration_modules": root / "plugins/AIStudioBridge/Source/AIStudioBridge/Public/AIStudioBridgeLibrary.h",
                "cpp_functional_body": root / "plugins/AIStudioBridge/Source/AIStudioBridge/Private/AIStudioBridgeLibrary.cpp",
                "python_adapter_registry": root / "unreal_tools/niagara.py",
                "focused_behavior_test": root / "tech_connector/examples/tests/test_unreal_execution_pipeline.py",
            }
            build = root / "plugins/AIStudioBridge/Source/AIStudioBridge/AIStudioBridge.Build.cs"
            for path in [*files.values(), build]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("class TestOwner:\n    def test_existing_niagara(self):\n        pass\n" if path.name.startswith("test_") else "// evidence\n", encoding="utf-8")
            calls = []

            def model_query(stage, _model, _prompt=None):
                calls.append((stage.key, stage.num_predict))
                target = files[stage.key]
                return json.dumps({
                    "changes": [{
                        "action": "modify",
                        "path": str(target),
                        "target_symbol": "",
                        "original_content": "",
                        "new_content": f"// {stage.key}\n",
                    }],
                    "report": {
                        "changed": [str(target)],
                        "reused": [],
                        "verification": [stage.key],
                        "remaining_gaps": [],
                    },
                    "blocked_reason": "",
                })

            provider = ModelBackedCapabilityImplementationProvider(root, model_query=model_query)
            provider._state.update({
                "required_implementation_layer": "reflected_cpp_bridge",
                "plan_alignment": {"matches_request": True},
            })
            stage = ProjectEditPromptStage(
                key="patch_generation",
                label="Patch",
                system_prompt="patch",
                user_prompt="patch",
                model_tier="local_code",
                response_format="json",
            )
            job = SimpleNamespace(
                original_request="Build native Niagara source synthesis.",
                context_addenda=[],
                plan={
                    "host": "unreal",
                    "requested_operation": "niagara.synthesize_source_strategy_stack",
                    "resume_operation": "niagara.attach_editable_character_fx",
                    "requested_behavior_contract": {"required_implementation_layer": "reflected_cpp_bridge"},
                },
            )

            merged = json.loads(provider._generate_initial_candidate(stage, "unused", job))

            self.assertEqual(len(merged["changes"]), 4)
            self.assertEqual(
                [key for key, _budget in calls],
                ["cpp_declaration_modules", "cpp_functional_body", "python_adapter_registry", "focused_behavior_test"],
            )
            self.assertEqual(dict(calls)["cpp_functional_body"], 1400)

    def test_full_provider_validates_before_apply_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "adapter.py"
            source.write_text("def existing():\n    return False\n", encoding="utf-8")
            order: list[str] = []
            model_calls: list[str] = []

            edit_plan = ProjectEditPlan(
                prompt="Implement sample.operation",
                discovery={
                    "project_roots": [str(root)],
                    "best_target": {
                        "path": str(source),
                        "symbols": [{"name": "existing"}],
                    },
                    "candidates": [],
                },
                discovery_context=f"Target: {source}\nSymbol: existing",
                model_prompt="",
                active_path=str(source),
            )
            stages = [
                ProjectEditPromptStage(
                    key="target_selection_plan",
                    label="Plan",
                    system_prompt="plan",
                    user_prompt="plan",
                    model_tier="local_plan",
                ),
                ProjectEditPromptStage(
                    key="patch_generation",
                    label="Patch",
                    system_prompt="patch",
                    user_prompt="patch",
                    model_tier="local_code",
                    response_format="json",
                ),
            ]
            plan_output = f"""Intent:
Implement sample.operation as a real callable.
Evidence-backed targets:
Use {source} and its existing symbol.
Existing symbols to reuse:
existing
Proposed changes:
Replace existing and register sample.operation.
Tests and verification:
Compile and import the changed module.
Blockers:
None.
Plan self-check:
The target and symbol are evidence-backed.
Approval scope:
Only {source}.
"""
            patch_output = '{"changes": [], "report": {"changed": [], "reused": [], "verification": [], "remaining_gaps": []}, "blocked_reason": ""}'

            def model_query(stage, _model, _prompt=None):
                model_calls.append(stage.key)
                return plan_output if stage.key == "target_selection_plan" else patch_output

            def previewer(_output, **_kwargs):
                return SimpleNamespace(
                    ok=True,
                    errors=[],
                    changes=[
                        {
                            "action": "modify",
                            "path": str(source),
                            "before": source.read_text(encoding="utf-8"),
                            "after": "def existing():\n    return True\n\ndef acquired():\n    return True\n",
                        }
                    ],
                )

            def temp_validator(**_kwargs):
                order.append("temp_validate")
                return {
                    "ok": True,
                    "temp_workspace": str(root / "temp_validation"),
                    "commands": [{"exit_code": 0}],
                }

            def applier(_output, **_kwargs):
                order.append("apply")
                source.write_text(
                    "def existing():\n    return True\n\ndef acquired():\n    return True\n",
                    encoding="utf-8",
                )
                return SimpleNamespace(
                    ok=True,
                    errors=[],
                    changes=[{"path": str(source), "action": "modify"}],
                    change_session_path=str(root / "undo.json"),
                )

            def operation_validator(operation):
                available = "def acquired" in source.read_text(encoding="utf-8")
                return {
                    "operation": operation,
                    "registered": available,
                    "callable_found": available,
                    "reason": "available" if available else "missing",
                }

            class Decision:
                def to_dict(self):
                    return {
                        "route": "dcc_execute",
                        "operation_mode": "execute",
                        "capability_gaps": [],
                    }

            provider = ModelBackedCapabilityImplementationProvider(
                root,
                active_path=str(source),
                settings={"model": "test-model"},
                model_query=model_query,
                plan_builder=lambda *_args, **_kwargs: edit_plan,
                stage_builder=lambda _plan: stages,
                previewer=previewer,
                applier=applier,
                temp_validator=temp_validator,
                operation_validator=operation_validator,
                live_operation_validator=lambda _status: {"ok": True, "check": "fake_live_readback"},
                route_classifier=lambda _prompt: Decision(),
            )
            plan = {
                "requested_operation": "sample.operation",
                "resume_operation": "sample.original",
                "original_request": "Build the sample feature.",
                "steps": [
                    {"step_id": "confirm_capability_gap", "action": "resolve"},
                    {"step_id": "research_host_api", "action": "search"},
                    {"step_id": "design_dcc_adapter", "action": "plan"},
                    {"step_id": "implement_dcc_adapter", "action": "modify"},
                    {"step_id": "validate_dcc_adapter", "action": "validate"},
                    {"step_id": "replan_original_request", "action": "replan"},
                ],
            }
            coordinator = CapabilityAcquisitionCoordinator(
                plan,
                stage_runner=provider.run_stage,
            )
            coordinator.start()
            result = coordinator.wait(5.0)

            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(order, ["temp_validate", "apply"])
            self.assertEqual(model_calls, ["patch_generation"])
            self.assertEqual(len(result["checkpoints"]), 6)
            self.assertIn("def acquired", source.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
