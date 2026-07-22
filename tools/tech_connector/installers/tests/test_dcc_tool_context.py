from router.ai_router import AIRouter
from router.command_router import CommandRouter


def test_ai_router_routes_all_bridged_dccs_to_dcc_session():
    assert AIRouter.route_prompt("create a cube in Blender").session_role == "dcc"
    assert AIRouter.route_prompt("show Substance Painter texture sets").session_role == "dcc"
    assert AIRouter.route_prompt("list MotionBuilder takes").session_role == "dcc"
    assert AIRouter.route_prompt("get Unity selected GameObjects").session_role == "dcc"


def test_unreal_natural_asset_query_uses_internal_asset_tool():
    query = CommandRouter().unreal_natural_asset_query("show me all material assets in Unreal under /Game/Characters")

    assert query is not None
    label, function_path, args, kwargs = query
    assert label == "Unreal Materials"
    assert function_path == "unreal_tools.get_skeletons.get_all_assets_of_type"
    assert args == ["Material", "/Game/Characters"]
    assert kwargs == {}


def test_dcc_context_names_host_tool_domain():
    context = CommandRouter().build_dcc_tool_context("use Unreal internal tools to find blueprints")

    assert "DCC routing context:" in context
    assert "- unreal: unreal_tools" in context
    assert "Do not invent internal function names" in context
