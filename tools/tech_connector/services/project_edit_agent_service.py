"""Compatibility facade for dependency-ordered project edit agent services."""
from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import importlib.util
import io
import json
import os
import py_compile
import re
import subprocess
import sys
import time
import textwrap
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


PROJECT_EDIT_CHANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create",
                            "modify",
                            "replace_symbol",
                            "insert_before_symbol",
                            "insert_after_symbol",
                            "replace_text",
                            "insert_before_text",
                            "insert_after_text",
                            "ensure_import",
                        ],
                    },
                    "path": {"type": "string"},
                    "target_symbol": {"type": "string"},
                    "original_content": {"type": "string"},
                    "new_content": {"type": "string"},
                },
                "required": ["action", "path", "target_symbol", "original_content", "new_content"],
                "additionalProperties": False,
            },
        },
        "report": {
            "type": "object",
            "properties": {
                "changed": {"type": "array", "items": {"type": "string"}},
                "reused": {"type": "array", "items": {"type": "string"}},
                "verification": {"type": "array", "items": {"type": "string"}},
                "remaining_gaps": {"type": "array", "items": {"type": "string"}},
                "requirement_coverage": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "requirement": {"type": "string"},
                            "production_owners": {"type": "array", "items": {"type": "string"}},
                            "test_owners": {"type": "array", "items": {"type": "string"}},
                            "validation": {"type": "array", "items": {"type": "string"}},
                            "status": {"type": "string"},
                        },
                        "required": [
                            "id",
                            "requirement",
                            "production_owners",
                            "test_owners",
                            "validation",
                            "status",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "changed",
                "reused",
                "verification",
                "remaining_gaps",
                "requirement_coverage",
            ],
            "additionalProperties": False,
        },
        "blocked_reason": {"type": "string"},
    },
    "required": ["changes", "report", "blocked_reason"],
    "additionalProperties": False,
}

PROJECT_EDIT_SYNTAX_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"corrected_source": {"type": "string"}},
    "required": ["corrected_source"],
    "additionalProperties": False,
}

PROJECT_EDIT_FUNCTION_REPAIR_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string"},
        "algorithm_steps": {"type": "array", "items": {"type": "string"}},
        "preserve": {"type": "array", "items": {"type": "string"}},
        "postconditions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["root_cause", "algorithm_steps", "preserve", "postconditions"],
    "additionalProperties": False,
}

PROJECT_EDIT_ARTIFACT_MANIFEST_SCHEMA = {
    "type": "object",
    "properties": {
        "integration_contracts": {
            "type": "object",
            "properties": {
                "canonical_owners": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                    "items": {"type": "string"},
                },
                "signatures": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "shared_invariants": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "data_layout": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "errors": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
            },
            "required": [
                "canonical_owners",
                "signatures",
                "shared_invariants",
                "data_layout",
                "errors",
            ],
            "additionalProperties": False,
            "description": (
                "Concrete package-wide API/data contracts: canonical owners, exact signatures "
                "and defaults, shared layouts/constants, bounds, and errors."
            ),
        },
        "files": {
            "type": "array",
            "minItems": 3,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "purpose": {"type": "string"},
                    "requirement_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 60,
                        "items": {"type": "string"},
                    },
                    "public_symbols": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {"type": "string"},
                    },
                    "contracts": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "algorithm_steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "validation_steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "is_test": {"type": "boolean"},
                },
                "required": [
                    "path",
                    "purpose",
                    "requirement_ids",
                    "public_symbols",
                    "contracts",
                    "algorithm_steps",
                    "validation_steps",
                    "depends_on",
                    "is_test",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["integration_contracts", "files"],
    "additionalProperties": False,
}

PROJECT_EDIT_INTEGRATION_CONTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "integration_contracts": PROJECT_EDIT_ARTIFACT_MANIFEST_SCHEMA[
            "properties"
        ]["integration_contracts"],
    },
    "required": ["integration_contracts"],
    "additionalProperties": False,
}

PROJECT_EDIT_FILE_MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "minItems": 2,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "purpose": {"type": "string"},
                    "requirement_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 60,
                        "items": {"type": "string"},
                    },
                    "public_symbols": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "is_test": {"type": "boolean"},
                },
                "required": [
                    "path",
                    "purpose",
                    "requirement_ids",
                    "public_symbols",
                    "depends_on",
                    "is_test",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["files"],
    "additionalProperties": False,
}

from tech_connector.services.project_edit_agent_part_01 import (
    ProjectEditApplyResult,
    ProjectEditLeafWorkUnits,
    ProjectEditPlan,
    ProjectEditPromptStage,
    _build_project_edit_intelligence_packet,
    _chunk_manifest_declarations,
    _fallback_project_edit_discovery,
    _generated_artifact_project_discovery,
    _lightweight_project_edit_intelligence_packet,
    _project_edit_needs_deep_intelligence,
    _project_edit_protocol_term_present,
    _project_edit_requirement_scope,
    _remove_generated_top_level_await,
    _render_project_edit_intelligence_packet,
    _required_project_edit_protocol_terms,
    _select_artifact_requirement_owner,
    assemble_project_edit_generated_chunks,
    build_code_agent_adaptive_plan,
    build_project_edit_artifact_chunk_stages,
    build_project_edit_artifact_file_stages,
    build_project_edit_chunk_plan_stage,
    build_project_edit_file_map_stage,
    build_project_edit_integration_contract_stage,
    build_project_edit_missing_symbol_stage,
    build_project_edit_requirement_coverage,
    build_user_visible_implementation_plan,
    complete_project_edit_integration_contract_response,
    compose_project_edit_incremental_manifest_response,
    extract_project_edit_artifact_requirements,
    parse_project_edit_chunk_plan,
    parse_project_edit_generated_chunk,
    project_edit_artifact_architecture_requires_coder,
    project_edit_file_worker_model_override,
    project_edit_file_worker_profile,
    render_code_agent_adaptive_plan,
    render_code_agent_expert_context,
    render_project_edit_artifact_architecture,
    validate_project_edit_integration_contract_response,
)

from tech_connector.services.project_edit_agent_part_02 import (
    _FORBIDDEN_EDIT_ROOT_MARKERS,
    _HOST_RUNTIME_MODULES,
    _PLACEHOLDER_PUBLIC_NAMES,
    _UI_WIDGET_IDENTIFIER_STOPWORDS,
    _callable_signature_name,
    _compact_indexed_import_context,
    _edit_error_for_forbidden_path,
    _edit_python_symbol_source,
    _expected_widget_accessor,
    _extract_self_chain_attr,
    _generated_module_import_side_effects,
    _has_factory_argument_call,
    _has_launch_show_call,
    _has_main_window_entrypoint,
    _has_optional_import_guard,
    _has_top_level_import_for_module,
    _has_widget_class_surface,
    _import_targets_module,
    _imported_modules,
    _imported_name_bindings,
    _infer_explicit_runtime_api_requests,
    _infer_prompt_requirements,
    _infer_signal_handler_requirements,
    _infer_ui_widget_requirements,
    _invalid_unreal_get_asset_tools_calls,
    _is_dunder_main_guard,
    _is_forbidden_edit_path,
    _is_importerror_handler,
    _is_module_module_guard,
    _is_placeholder_callable,
    _is_placeholder_class,
    _is_sys_modules,
    _iter_signal_connects,
    _method_updates_widget,
    _method_uses_widget_access,
    _node_parent_map,
    _parse_structured_project_changes,
    _progress_callback_contract_issues,
    _project_edit_requests_new_artifact_plan,
    _project_edit_requires_patch,
    _qt_widget_import_coverage,
    _real_unreal_get_asset_tools_targets,
    _remove_generated_top_level_calls,
    _remove_redundant_generated_initializers,
    _render_ast_arguments,
    _runtime_api_calls_in_tree,
    _runtime_api_paths_in_tree,
    _unresolved_module_scope_names,
    _validated_api_membership_call_chain,
    _widget_ctor_base_name,
    _widget_ctor_is_imported,
    _widget_expected_constructors,
    apply_project_edit_syntax_repair,
    build_project_edit_artifact_manifest_stage,
    build_project_edit_class_repair_stage,
    build_project_edit_class_set_repair_stage,
    build_project_edit_cross_file_failure_notes,
    build_project_edit_function_repair_plan_stage,
    build_project_edit_function_repair_stage,
    build_project_edit_leaf_candidate,
    build_project_edit_multi_file_candidate,
    build_project_edit_syntax_repair_stage,
    format_project_edit_generated_python,
    inspect_project_edit_structured_syntax,
    model_for_project_edit_stage,
    parse_project_edit_function_repair_plan,
    project_edit_plan_fingerprint,
    project_edit_preview_error_score,
    project_edit_validation_failure_signature,
    remove_project_edit_unused_imports,
    repair_project_edit_duplicate_dependency_symbols,
    stabilize_project_edit_import_cycles,
    summarize_project_edit_generated_interface,
    validate_project_edit_plan_output,
)

from tech_connector.services.project_edit_agent_part_03 import (
    _RUNTIME_API_VALIDATION_CACHE,
    _bridge_query_unreal_api_contract,
    _callable_definition_map,
    _dynamic_host_api_member_issues,
    _existing_module_path,
    _generated_docstring_contract_issues,
    _generated_docstring_is_useful,
    _host_result_and_redundant_guard_issues,
    _import_specs,
    _imported_call_api_contracts,
    _incomplete_generated_type_hints,
    _invalid_runtime_api_contracts,
    _local_module_exports,
    _local_module_path,
    _missing_explicit_bool_rejections,
    _official_unreal_call_signature_issues,
    _official_unreal_editor_property_issues,
    _prime_runtime_api_validation_cache,
    _public_definition_map,
    _qt_progress_surface_issues,
    _quality_result,
    _repair_local_module_fallback_imports,
    _requested_identifier_contracts,
    _requested_pre_side_effect_contract_issues,
    _resolve_local_module_symbol_fallback,
    _resolved_runtime_chain_exists,
    _sanitize_python_candidate_text,
    _tree_uses_identifier,
    _unresolved_generated_names,
    _unresolved_generated_names_by_callable,
    _verified_installed_qt_symbol,
    apply_project_edit_missing_symbol,
    build_project_edit_function_repair_contract,
    infer_project_edit_generated_dependencies,
    resolve_project_edit_cross_file_symbols,
    resolve_project_edit_standard_library_symbols,
)

from tech_connector.services.project_edit_agent_part_04 import (
    _artifact_manifest_item_is_test,
    _is_test_path,
    _resolve_import_spec,
    apply_project_edit_generated_class_repair,
    apply_project_edit_generated_class_set_repair,
    apply_project_edit_generated_symbol_repair,
    build_deterministic_project_edit_chunk_plan,
    build_project_edit_file_generation_stages,
    parse_project_edit_artifact_manifest,
    parse_project_edit_generated_file,
    resolve_project_edit_failure_symbol,
    validate_project_edit_generated_module_graph,
)

from tech_connector.services.project_edit_agent_part_05 import (
    _ast_has_validation_failure_filter,
    _ast_references_name,
    _build_explicit_active_edit_discovery,
    _ensure_python_from_import,
    _indexed_symbol_source_entries,
    _is_self_import,
    _leaf_ranking_terms,
    _objective_requires_validation_result_collection,
    _path_is_within,
    _project_edit_leaf_handoff_fingerprint,
    _python_symbol_source_entries,
    _requested_public_symbol_names,
    _requires_behavior_test,
    _resolve_model_changes,
    _select_leaf_integration_symbol,
    _select_leaf_test_anchor,
    _sha1_file,
    _unwrap_single_test_method,
    _validate_candidate_changes_in_disposable_workspace,
    _validate_project_edit_leaf_objective_contract,
    compile_project_edit_leaf_work_units,
    enforce_project_edit_explicit_cleanup,
    enforce_project_edit_requested_test_contracts,
    ensure_project_edit_requested_docstrings,
    isolate_project_edit_generated_test_fixture,
    normalize_project_edit_async_test_lifecycle,
    parse_project_edit_leaf_source,
    project_edit_has_core_contract_failure,
    project_edit_leaf_work_units_handoff,
    restore_project_edit_leaf_work_units,
)

from tech_connector.services.project_edit_agent_part_06 import (
    _compact_discovery_evidence,
    _focused_project_edit_source_context,
    _format_candidate_line,
    _infer_code_agent_host,
    _line_delta,
    _stage,
    _trim_text,
    _validate_candidate_changes,
    _validate_changes,
    apply_project_edit_agent_response,
    build_project_edit_agent_request,
    build_project_edit_leaf_stage,
    build_project_edit_model_stages,
    build_project_edit_plan_from_leaf_work_units,
    build_project_edit_repair_stage,
    preview_project_edit_agent_response,
    render_grounded_project_edit_handoff,
    render_project_edit_agent_report,
    select_code_agent_experts,
    validate_project_edit_paths,
)
