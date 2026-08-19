"""Compatibility facade for implementation-plan quality services."""
from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


_UI_ATTRIBUTE_SUFFIXES = (
    "_bar",
    "_btn",
    "_button",
    "_checkbox",
    "_combo",
    "_dial",
    "_editor",
    "_group",
    "_input",
    "_label",
    "_list",
    "_radio",
    "_slider",
    "_spinbox",
    "_stack",
    "_table",
    "_tabs",
    "_tree",
    "_view",
    "_widget",
)
_MODULE_CALLABLES = {
    name.casefold()
    for name in dir(builtins)
    if callable(getattr(builtins, name, None))
}
from tech_connector.services.implementation_plan_quality_contract import (
    APPROVED_PLAN_SCHEMA,
    APPROVED_PLAN_VALIDATOR_VERSION,
)

from tech_connector.services.implementation_plan_quality_part_01 import (
    _attribute_contracts,
    _callable_signatures,
    _class_base,
    _explicit_callable_declaration,
    _mechanics,
    _observable_actions,
    _plan_store,
    _prompt_hash,
    _property_names,
    _propose_cross_file_interfaces,
    _required_method_names,
    _requirement_texts,
    _signal_contracts,
    _stable_hash,
    _state_root,
    _structured_record_state_terms,
    _validation_cases,
    implementation_plan_approval_id,
    load_approved_plan_candidate,
    persist_approved_plan_candidate,
)

from tech_connector.services.implementation_plan_quality_part_02 import (
    _call_names,
    _definition_nodes,
    _materialize_threaded_progress_declarations,
    _method_map,
    enrich_implementation_plan,
    materialize_threaded_progress_declarations,
    validate_implementation_plan_completeness,
)

from tech_connector.services.implementation_plan_quality_part_03 import (
    _boundary_trim_requirement_gaps,
    _discarded_pure_transform_gaps,
    _final_value_guard_gaps,
    _regex_requirement_gaps,
    _verification_proof_gaps,
)

from tech_connector.services.implementation_plan_quality_part_04 import (
    validate_generated_files_against_implementation_plan,
)

from tech_connector.services.implementation_plan_quality_part_05 import (
    apply_deterministic_implementation_plan_repairs,
)
