from __future__ import annotations

import unittest
from unittest.mock import patch

from tech_connector.services.prompt.prompt_execution_context_service import (
    _PLANNING_CACHE,
    build_prompt_execution_context,
    validate_prompt_understanding,
)
from tech_connector.services.prompt.prompt_intent_service import _CACHE, understand_prompt_request
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
from tech_connector.services.prompt.prompt_task_splitter_service import compose_request


TOOLS_ROOT = "C:/depot/tools"


def _no_model(*_args, **_kwargs):
    return None


VERBS = [
    "inspect",
    "review",
    "read",
    "open",
    "search",
    "find",
    "locate",
    "run",
    "export",
    "connect",
    "change",
    "update",
    "plan",
    "summarize",
    "include",
    "check",
]

OBJECTS = [
    "prompt route service",
    "api imports",
    "project details",
    "project tree",
    "semantic budget",
    "startup path",
    "Maya bridge",
    "custom_widgets.py",
    "setup_hik.py",
    "symbol parser",
]


def _generated_composition_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    patterns = [
        ("{v} the {o} and summarize what matters", {"GOAL", "OUTPUT_REQUEST"}, 1),
        ("{v} the {o}, include file names and line numbers", {"GOAL", "OUTPUT_REQUEST"}, 1),
        ("{v} the {o} then verify the result", {"GOAL", "VALIDATION"}, 1),
        ("{v} the {o} but do not edit files", {"GOAL", "CONSTRAINT"}, 1),
        ("{v} the {o} + report blockers", {"GOAL", "OUTPUT_REQUEST"}, 1),
        ("{v} the {o} and {v2} the route decision", {"GOAL"}, 1),
    ]
    for index, verb in enumerate(VERBS):
        obj = OBJECTS[index % len(OBJECTS)]
        for template, roles, min_goals in patterns:
            cases.append(
                {
                    "prompt": template.format(
                        v=verb,
                        o=obj,
                        v2=VERBS[(index + 3) % len(VERBS)],
                    ),
                    "required_roles": roles,
                    "min_goals": min_goals,
                }
            )
    return cases


RICH_COMPOSITION_CASES = [
    {
        "prompt": "create locator move it to wrist parent it under joint verify it exists",
        "required_roles": {"GOAL", "DEPENDENT_GOAL", "VALIDATION"},
        "min_goals": 3,
    },
    {
        "prompt": "create control named b and locator named c move both to wrist parent only c under joint verify b is still selected",
        "required_roles": {"GOAL", "DEPENDENT_GOAL", "VALIDATION"},
        "min_goals": 4,
        "required_names": {"b", "c"},
    },
    {
        "prompt": "create locator and control name them a and b move both to wrist verify both exist",
        "required_roles": {"GOAL", "DEPENDENT_GOAL", "VALIDATION"},
        "min_goals": 3,
        "required_names": {"a", "b"},
        "requires_multi_dependency": True,
    },
    {
        "prompt": "find route service read it summarize owners",
        "required_roles": {"GOAL", "DEPENDENT_GOAL", "OUTPUT_REQUEST"},
        "min_goals": 2,
    },
    {
        "prompt": "search imports open api.py explain why it loads",
        "required_roles": {"GOAL", "OUTPUT_REQUEST"},
        "min_goals": 2,
    },
    {
        "prompt": "plan patch list risks dont edit files",
        "required_roles": {"GOAL", "OUTPUT_REQUEST"},
        "min_goals": 1,
    },
    {
        "prompt": "review startup inspect imports find slow calls include line numbers",
        "required_roles": {"GOAL", "OUTPUT_REQUEST"},
        "min_goals": 2,
    },
    {
        "prompt": "connect button wire signal verify slot fires",
        "required_roles": {"GOAL", "DEPENDENT_GOAL", "VALIDATION"},
        "min_goals": 2,
    },
    {
        "prompt": "open project details refresh tree only if stale",
        "required_roles": {"GOAL"},
        "min_goals": 2,
    },
    {
        "prompt": "check the startup path but do not edit files",
        "required_roles": {"GOAL", "CONSTRAINT"},
        "min_goals": 1,
    },
    {
        "prompt": "the tree and details are slow after tab change",
        "required_roles": {"GOAL"},
        "min_goals": 1,
    },
    {
        "prompt": "project details stale refresh?",
        "required_roles": {"GOAL"},
        "min_goals": 1,
    },
    {
        "prompt": "open or export route diagnostics whichever works",
        "required_roles": {"GOAL", "ALTERNATIVE"},
        "min_goals": 1,
    },
    {
        "prompt": "search classify route + include why unreal wins",
        "required_roles": {"GOAL", "OUTPUT_REQUEST"},
        "min_goals": 1,
    },
    {
        "prompt": "run tests no dcc push",
        "required_roles": {"GOAL"},
        "min_goals": 1,
    },
    {
        "prompt": "what would i do if i needed a class to make a QSlider in @custom_qt.custom_widgets",
        "required_roles": {"GOAL"},
        "min_goals": 1,
    },
    {
        "prompt": "add a QSlider class to @custom_qt.custom_widgets",
        "required_roles": {"GOAL"},
        "min_goals": 1,
    },
]


NON_UNREAL_OFFICIAL_FLOW_PROMPTS = [
    "Open project details or refresh the tree if stale.",
    "are we importing the new api anywhere find that and dont load it",
    "check the startup path but do not edit files",
    "the tree and details are slow after tab change",
    "project details stale refresh?",
    "read prompt_intent_service.py, inspect semantic budgeting usage, include timeout settings",
    "search project details refresh, read matching files, plan patch, then run tests",
    "run py_compile, run focused unittest, include commands, no DCC push",
    "inspect custom_qt custom widgets and tell me whether BrowseToDirectory exists",
    "find route service read it summarize owners",
    "search imports open api.py explain why it loads",
    "review route oddities for project details and api imports, then add focused tests",
    "plan a golden suite for 100 prompts, include ambiguous examples and typos",
    "check if tab cahnge refreshes tree, crete a regression test, and dont touch unrelated files",
    "what would i do if i needed a class to make a QSlider in @custom_qt.custom_widgets",
    "add a QSlider class to @custom_qt.custom_widgets",
]


EXPECTED_ROUTE_PROMPTS = [
    ("Open project details or refresh the tree if stale.", "target_discovery"),
    ("are we importing the new api anywhere find that and dont load it", "project_search"),
    ("what would i do if i needed a class to make a QSlider in @custom_qt.custom_widgets", "project_search"),
    ("add a QSlider class to @custom_qt.custom_widgets", "target_discovery"),
    ("In Maya create a locator named wrist_loc and verify it exists", "dcc_execute"),
    ("In Maya, list joints in the current scene. Do not modify anything.", "dcc_query"),
]


CREATIVE_SCOPED_PROMPT_CASES = [
    ("if i wanted a tiny slider widget in @custom_qt.custom_widgets what would that class look like", "project_search", False),
    ("can you add a tiny slider widget class to @custom_qt.custom_widgets and keep it pyside2 compatible", "target_discovery", True),
    ("need a qslider helper in custom_qt/custom_widgets.py show me an example not an edit", "project_search", False),
    ("put a non scrolling slider class in custom_qt/custom_widgets.py", "target_discovery", True),
    ("what class pattern in @custom_qt.custom_widgets should i copy for a QSlider", "project_search", False),
    ("make @custom_qt.custom_widgets have a LabeledSlider class but dont touch anything else", "target_discovery", True),
    ("do we already have qslider in @custom_qt.custom_widgets or should i add one", "project_search", False),
    ("add qslider class then run py_compile no dcc push in @custom_qt.custom_widgets", "target_discovery", True),
    ("could @custom_qt.custom_widgets use a slider class like BrowseDirectory but horizontal", "project_search", False),
    ("write the qslider class for @custom_qt.custom_widgets", "target_discovery", True),
    ("find where the at menu turns custom_widgets.py into py and fix it", "target_discovery", True),
    ("why is @custom_qt.custom_widgets showing as py in autocomplete, inspect and patch", "target_discovery", True),
    ("autocomplete says py for custom widgets find the label builder and explain the fix", "project_search", False),
    ("open or explain the custom widgets @ mention candidate whichever is safer", "project_search", False),
    ("do not edit: show me how an @custom_qt.custom_widgets qslider class would work", "project_search", False),
    ("create a qslider class in @custom_qt.custom_widgets call it LabeledSlider verify import still works", "target_discovery", True),
    ("the user types @custom_q and menu says py, test that it says custom_widgets", "target_discovery", True),
    ("where should a slider widget live custom_qt.custom_widgets or elsewhere give an example", "project_search", False),
    ("add q slider class to custom widgets py", "target_discovery", True),
    ("what would i do if i needed browse directory but with qslider instead in @custom_qt.custom_widgets", "project_search", False),
    ("create locator and qslider? no wait just explain the qslider class in @custom_qt.custom_widgets", "project_search", False),
    ("in maya create locator then in @custom_qt.custom_widgets show qslider example only", "project_search", False),
    ("add class to @custom_qt.custom_widgets: QSlider with label, value label, range args", "target_discovery", True),
    ("@custom_qt.custom_widgets needs a slider thing please implement smallest class", "target_discovery", True),
    ("@custom_qt.custom_widgets slider thing what would the code be", "project_search", False),
    ("check @custom_qt.custom_widgets for slider class, if none show example", "project_search", False),
    ("check @custom_qt.custom_widgets for slider class, if none add one", "target_discovery", True),
    ("dont mutate, but pretend we were adding a qslider class to custom_widgets.py", "project_search", False),
    ("can you patch custom_widgets.py with LabeledSlider and summarize tests", "target_discovery", True),
    ("is there already a qslider wrapper in custom widgets", "project_search", False),
]


class PromptCompositionGoldenSuiteTests(unittest.TestCase):
    def test_broad_composition_matrix_has_goals_roles_and_no_unresolved_edges(self) -> None:
        cases = _generated_composition_cases() + RICH_COMPOSITION_CASES
        self.assertGreaterEqual(len(cases), 100)

        failures: list[str] = []
        for index, case in enumerate(cases, start=1):
            prompt = str(case["prompt"])
            composed = compose_request(prompt).to_dict()
            roles = {str(clause.get("role") or "") for clause in composed.get("clauses") or []}
            goals = list(composed.get("goals") or [])
            required_roles = set(case.get("required_roles") or set())
            missing_roles = sorted(required_roles - roles)
            names = {
                str(goal.get("arguments", {}).get("name") or "")
                for goal in goals
                if goal.get("arguments", {}).get("name")
            }
            required_names = set(case.get("required_names") or set())
            missing_names = sorted(required_names - names)
            has_multi_dependency = any(len(goal.get("depends_on") or []) >= 2 for goal in goals)

            if composed.get("unresolved_relationships"):
                failures.append(f"{index}: unresolved {composed['unresolved_relationships']} :: {prompt}")
            if missing_roles:
                failures.append(f"{index}: missing roles {missing_roles}; got {sorted(roles)} :: {prompt}")
            if len(goals) < int(case.get("min_goals") or 1):
                failures.append(f"{index}: goal count {len(goals)} below {case.get('min_goals')} :: {prompt}")
            if missing_names:
                failures.append(f"{index}: missing names {missing_names}; got {sorted(names)} :: {prompt}")
            if case.get("requires_multi_dependency") and not has_multi_dependency:
                failures.append(f"{index}: expected a multi-goal dependency :: {prompt}")

        self.assertFalse(failures, "\n".join(failures[:30]))

    def test_official_flow_matrix_keeps_non_unreal_prompts_out_of_unreal_route(self) -> None:
        prompts = NON_UNREAL_OFFICIAL_FLOW_PROMPTS + [
            case["prompt"]
            for case in _generated_composition_cases()[::5]
        ]
        self.assertGreaterEqual(len(prompts), 30)

        failures: list[str] = []
        with patch("tech_connector.services.prompt.prompt_intent_service._model_understanding", side_effect=_no_model), patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            side_effect=_no_model,
        ):
            _CACHE.clear()
            _PLANNING_CACHE.clear()
            for index, prompt in enumerate(prompts, start=1):
                context = build_prompt_execution_context(
                    str(prompt),
                    decision_facts={
                        "project_roots": [TOOLS_ROOT],
                        "settings": {"ai_work_memory_enabled": False},
                    },
                )
                validate_prompt_understanding(context)
                decision = classify_prompt_route(str(prompt), execution_context=context)
                composed = context.task_graph.get("composed_request") or {}
                if decision.route == "unreal_capability":
                    failures.append(f"{index}: unexpected unreal route :: {prompt}")
                if composed.get("unresolved_relationships"):
                    failures.append(f"{index}: unresolved composition {composed['unresolved_relationships']} :: {prompt}")

        self.assertFalse(failures, "\n".join(failures[:30]))

    def test_official_flow_route_expectations_for_representative_hosts(self) -> None:
        with patch("tech_connector.services.prompt.prompt_intent_service._model_understanding", side_effect=_no_model), patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            side_effect=_no_model,
        ):
            _CACHE.clear()
            _PLANNING_CACHE.clear()
            for prompt, expected_route in EXPECTED_ROUTE_PROMPTS:
                with self.subTest(prompt=prompt):
                    context = build_prompt_execution_context(
                        prompt,
                        decision_facts={
                            "project_roots": [TOOLS_ROOT],
                            "settings": {"ai_work_memory_enabled": False},
                        },
                    )
                    decision = classify_prompt_route(prompt, execution_context=context)
                    self.assertEqual(expected_route, decision.route)

    def test_creative_scoped_prompts_keep_guidance_and_mutation_separate(self) -> None:
        failures: list[str] = []
        with patch("tech_connector.services.prompt.prompt_intent_service._model_understanding", side_effect=_no_model), patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            side_effect=_no_model,
        ):
            _CACHE.clear()
            _PLANNING_CACHE.clear()
            for index, (prompt, expected_route, expected_mutation) in enumerate(
                CREATIVE_SCOPED_PROMPT_CASES,
                start=1,
            ):
                understanding = understand_prompt_request(prompt)
                context = build_prompt_execution_context(
                    prompt,
                    decision_facts={
                        "project_roots": [TOOLS_ROOT],
                        "settings": {"ai_work_memory_enabled": False},
                    },
                )
                validate_prompt_understanding(context)
                decision = classify_prompt_route(prompt, execution_context=context)
                composed = context.task_graph.get("composed_request") or compose_request(prompt).to_dict()

                if decision.route != expected_route:
                    failures.append(
                        f"{index}: route {decision.route!r} expected {expected_route!r} :: {prompt}"
                    )
                if bool(understanding.mutation_requested) != bool(expected_mutation):
                    failures.append(
                        f"{index}: mutation {understanding.mutation_requested!r} expected {expected_mutation!r} :: {prompt}"
                    )
                if composed.get("unresolved_relationships"):
                    failures.append(
                        f"{index}: unresolved composition {composed['unresolved_relationships']} :: {prompt}"
                    )

        self.assertFalse(failures, "\n".join(failures[:30]))


if __name__ == "__main__":
    unittest.main()
