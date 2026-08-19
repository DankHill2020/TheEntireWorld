"""Tests for exact repair-response ownership enforcement."""

from __future__ import annotations

from tech_connector.services.project_edit_agent_service import ProjectEditPromptStage
from tech_connector.services.repair_prompt_enforcement_service import (
    MAX_FUNCTION_REPAIR_CHARS,
    _algorithmic_repair_guidance,
    _bound_atomic_requirement_rows,
    normalize_repair_response,
    prepare_repair_stage,
    validate_repair_response,
)


def _stage(key: str, symbols: list[str]) -> ProjectEditPromptStage:
    """Build one exact-owner repair stage.

    :param key: Repair stage key.
    :param symbols: Owned symbol names.
    :return: Project edit prompt stage.
    """

    return ProjectEditPromptStage(
        key=key,
        label="Repair exact owner",
        system_prompt="Return only the owned declaration.",
        user_prompt="Repair the declared owner.",
        metadata={"symbols": symbols},
    )


def test_function_repair_accepts_exact_owned_callable() -> None:
    """Accept one raw top-level callable with the exact owner name."""

    stage = _stage("function_repair", ["Service.render"])
    response = (
        "def render(value):\n"
        "    \"\"\"Renders value.\n\n"
        "    :param value: value\n"
        "    :return: result\n"
        "    \"\"\"\n"
        "    return str(value)\n"
    )

    assert validate_repair_response(stage, response) == ""


def test_function_repair_rejects_sibling_or_nested_declarations() -> None:
    """Reject declarations outside the exact callable replacement boundary."""

    stage = _stage("function_repair", ["target"])
    sibling = "def target():\n    return 1\n\ndef unrelated():\n    return 2\n"
    nested = "def wrapper():\n    def target():\n        return 1\n    return target()\n"

    assert "exactly the owned declarations" in validate_repair_response(
        stage,
        sibling,
    )
    assert "exactly the owned declarations" in validate_repair_response(
        stage,
        nested,
    )


def test_class_set_repair_rejects_undeclared_extra_class() -> None:
    """Keep coherent class repairs bounded to their manifest owners."""

    stage = _stage("class_set_repair", ["First", "Second"])
    response = (
        "class First:\n    def run(self):\n        return 1\n\n"
        "class Second:\n    def run(self):\n        return 2\n\n"
        "class Undeclared:\n    pass\n"
    )

    assert "exactly the owned declarations" in validate_repair_response(
        stage,
        response,
    )


def test_class_set_repair_rejects_pass_only_owned_classes() -> None:
    """Reject a syntactically complete class set with no implemented behavior."""

    stage = _stage("class_set_repair", ["First", "Second"])
    response = (
        "class First:\n    pass\n\n"
        "class Second:\n"
        "    def run(self):\n"
        "        ...\n"
    )

    reason = validate_repair_response(stage, response)

    assert "placeholder owner bodies" in reason
    assert "First" in reason
    assert "Second" in reason


def test_class_repair_rejects_class_with_only_placeholder_methods() -> None:
    """Treat pass-only methods as an unfinished class implementation."""

    stage = _stage("class_repair", ["Service"])
    response = (
        "class Service:\n"
        "    def start(self):\n"
        "        pass\n\n"
        "    async def stop(self):\n"
        "        ...\n"
    )

    assert "placeholder body" in validate_repair_response(stage, response)


def test_class_repair_accepts_data_owner_without_methods() -> None:
    """Do not mistake a substantive data-only owner for a placeholder."""

    stage = _stage("class_repair", ["Settings"])
    response = "class Settings:\n    timeout: int = 30\n"

    assert validate_repair_response(stage, response) == ""


def test_normalization_extracts_single_matching_fenced_owner() -> None:
    """Recover one exact owner block while discarding surrounding prose."""

    stage = _stage("function_repair", ["target"])
    response = (
        "Here is the repair.\n"
        "```python\n"
        "def target():\n"
        "    return 1\n"
        "```\n"
        "This preserves the behavior."
    )

    normalized, changed = normalize_repair_response(stage, response)

    assert changed is True
    assert normalized == "def target():\n    return 1"
    assert validate_repair_response(stage, normalized) == ""


def test_normalization_refuses_ambiguous_matching_code_blocks() -> None:
    """Do not guess between multiple fenced repairs for the same owner."""

    stage = _stage("function_repair", ["target"])
    response = (
        "First option:\n```python\ndef target():\n    return 1\n```\n"
        "Second option:\n```python\ndef target():\n    return 2\n```"
    )

    normalized, changed = normalize_repair_response(stage, response)

    assert changed is False
    assert normalized == response
    assert "Markdown" in validate_repair_response(stage, normalized)


def test_normalization_closes_only_trailing_unterminated_docstring() -> None:
    """Recover a complete owner truncated only at a docstring delimiter."""

    stage = _stage("class_repair", ["Service"])
    response = (
        "class Service:\n"
        "    def run(self):\n"
        "        \"\"\"Runs the service.\n\n"
        "        :return: result\n"
    )

    normalized, changed = normalize_repair_response(stage, response)

    assert changed is True
    assert normalized.endswith('\"\"\"')
    assert "not valid Python" not in validate_repair_response(stage, normalized)


def test_normalization_wraps_bare_class_member_in_qualified_owner() -> None:
    """Normalize a bare member response into its exact class owner."""

    stage = _stage("artifact_missing_symbol", ["EventJournal.clear"])
    response = (
        "def clear(self) -> None:\n"
        "    \"\"\"Clear retained events.\n\n"
        "    :return: None.\n"
        "    \"\"\"\n"
        "    self.events.clear()\n"
    )

    normalized, changed = normalize_repair_response(stage, response)

    assert changed is True
    assert normalized.startswith("class EventJournal:")
    assert validate_repair_response(stage, normalized) == ""


def test_function_repair_adversarial_response_matrix_is_rejected() -> None:
    """Reject common malformed or scope-widening model response shapes."""

    stage = _stage("function_repair", ["target"])
    invalid_responses = {
        "empty": "",
        "syntax": "def target(:\n    return 1\n",
        "wrong owner": "def other():\n    return 1\n",
        "duplicate owner": (
            "def target():\n    return 1\n\n"
            "def target():\n    return 2\n"
        ),
        "assignment sibling": "VALUE = 1\n\ndef target():\n    return VALUE\n",
        "explanation": "Use this repair: def target(): return 1",
        "nested owner": (
            "class Wrapper:\n"
            "    def target(self):\n"
            "        return 1\n"
        ),
        "ellipsis": "def target():\n    ...\n",
        "empty return": "def target():\n    return None\n",
        "not implemented": (
            "def target():\n"
            "    raise NotImplementedError()\n"
        ),
        "docstring only": 'def target():\n    """Not implemented."""\n',
    }

    for label, response in invalid_responses.items():
        assert validate_repair_response(stage, response), label


def test_placeholder_repair_is_rejected() -> None:
    """Reject syntactically valid repairs that implement no behavior."""

    stage = _stage("function_repair", ["target"])

    assert "placeholder body" in validate_repair_response(
        stage,
        "def target():\n    pass\n",
    )


def test_oversized_function_repair_is_bounded_end_to_end() -> None:
    """Replace verbose shared policy as well as compacting owner evidence."""

    owner_source = (
        "def execution_batches(graph: dict[str, set[str]]):\n"
        "    return tuple((name,) for name in graph)\n"
    )
    stage = ProjectEditPromptStage(
        key="function_repair",
        label="Repairing execution_batches",
        system_prompt="Verbose policy.\n" * 800,
        user_prompt=(
            "Original objective:\nCompute stable dependency batches.\n\n"
            "Deterministic validation failures:\n"
            "- independent tasks must share one sorted batch\n"
            "- dependencies must appear in later batches\n\n"
            "Exact current owner source:\n```python\n"
            + owner_source
            + "```\n"
            + ("Unrelated package context.\n" * 900)
        ),
        metadata={
            "symbol": "execution_batches",
            "owner_source": owner_source,
            "canonical_repair_contract": {
                "symbol": "execution_batches",
                "source": owner_source,
                "requirements": [
                    "independent tasks must share one sorted batch",
                    "dependencies must appear in later batches",
                ],
            },
        },
    )

    prepared, report = prepare_repair_stage(stage)
    total_chars = len(prepared.system_prompt) + len(prepared.user_prompt)

    assert report["compacted"] is True
    assert total_chars <= MAX_FUNCTION_REPAIR_CHARS
    assert report["required_context_expansion"] is False
    assert "Verbose policy." not in prepared.system_prompt
    assert owner_source.strip() in prepared.user_prompt


def test_atomic_requirement_budget_preserves_late_distinct_constraints() -> None:
    """Share compact prompt space across all failures instead of truncating the tail."""

    rows = [
        {
            "id": f"R{index}",
            "owner": "execution_batches",
            "failure": text + (" detailed evidence" * 60),
        }
        for index, text in enumerate(
            (
                "sorted independent tasks share a batch",
                "include tasks that appear only as dependencies",
                "raise ValueError for a self cycle",
                "include all cycle members in the message",
            ),
            start=1,
        )
    ]

    bounded = _bound_atomic_requirement_rows(rows, max_chars=1200)

    assert len(bounded) == 4
    assert "sorted independent" in bounded[0]["failure"]
    assert "all cycle members" in bounded[-1]["failure"]


def test_dependency_requirements_derive_layering_invariants() -> None:
    """Give the owner model a concise standard-algorithm frame from requirements."""

    guidance = _algorithmic_repair_guidance([
        "Return batches containing all currently runnable tasks.",
        "Include dependency-only tasks and reject cycles with all members.",
    ])

    assert "mapping keys and every dependency value" in guidance
    assert "ready = sorted" in guidance
    assert "deps <= completed" in guidance
    assert "never mutate" in guidance
