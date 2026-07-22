from router.ai_router import AIRouter, RouteDecision


def model_for_role(role):
    return {
        "plan": "ollama:qwen3:14b",
        "code": "ollama:deepseek-coder-v2:16b",
        "dcc": "ollama:deepseek-coder-v2:16b",
    }[role]


def test_editor_active_routes_to_code_session():
    route = AIRouter.route_prompt(
        "summarize this file",
        editor_active=True,
        get_model_for_role=model_for_role,
    )

    assert route == RouteDecision(
        task_role="code",
        session_role="code",
        model="ollama:deepseek-coder-v2:16b",
        reason="editor is active",
    )


def test_maya_and_unreal_share_dcc_session():
    maya_route = AIRouter.route_prompt(
        "fix this Maya HIK rig joint mapping",
        get_model_for_role=model_for_role,
    )
    unreal_route = AIRouter.route_prompt(
        "inspect this Unreal Control Rig blueprint",
        get_model_for_role=model_for_role,
    )

    assert maya_route.task_role == "maya"
    assert maya_route.session_role == "dcc"
    assert maya_route.model == "ollama:deepseek-coder-v2:16b"
    assert unreal_route.task_role == "unreal"
    assert unreal_route.session_role == "dcc"
    assert unreal_route.model == "ollama:deepseek-coder-v2:16b"


def test_docs_and_general_prompts_use_plan_session():
    docs_route = AIRouter.route_prompt(
        "summarize the readme",
        get_model_for_role=model_for_role,
    )
    general_route = AIRouter.route_prompt(
        "what should we do next",
        get_model_for_role=model_for_role,
    )

    assert docs_route.task_role == "docs"
    assert docs_route.session_role == "plan"
    assert docs_route.model == "ollama:qwen3:14b"
    assert general_route.task_role == "plan"
    assert general_route.session_role == "plan"
    assert general_route.model == "ollama:qwen3:14b"


def test_debug_uses_code_session():
    route = AIRouter.route_prompt(
        "debug this traceback",
        get_model_for_role=model_for_role,
    )

    assert route.task_role == "debug"
    assert route.session_role == "code"
    assert route.model == "ollama:deepseek-coder-v2:16b"
