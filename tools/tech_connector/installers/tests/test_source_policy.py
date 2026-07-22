from services.source_policy import apply_source_policy, live_sources_enabled


def test_live_sources_default_off():
    assert live_sources_enabled({}) is False
    assert live_sources_enabled(None) is False


def test_apply_source_policy_local_only():
    prompt = apply_source_policy("find a rigging tool", {"enable_live_sources": False})

    assert prompt.startswith("Source mode: LOCAL ONLY.")
    assert "find a rigging tool" in prompt
    assert "Do not browse the web" in prompt


def test_apply_source_policy_live_sources():
    prompt = apply_source_policy("find a blender addon", {"enable_live_sources": True})

    assert prompt.startswith("Source mode: LIVE WEB/GITHUB ENABLED.")
    assert "find a blender addon" in prompt
    assert "official docs and primary project" in prompt


def test_apply_source_policy_is_idempotent():
    prompt = "Source mode: LOCAL ONLY.\nUser request:\nhello"

    assert apply_source_policy(prompt, {"enable_live_sources": True}) == prompt
