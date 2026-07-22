from editor.diff import analyze_patch_safety, apply_patch, patch_diff


def test_patch_safety_blocks_empty_replacement():
    patch = {
        "symbol": "make_widget",
        "old": "def make_widget():\n    a = 1\n    b = 2\n    return a + b\n",
        "new": "",
    }

    safety = analyze_patch_safety(patch)

    assert safety["safe"] is False
    assert "empty" in " ".join(safety["blockers"])


def test_patch_safety_blocks_lost_symbol_definition():
    patch = {
        "symbol": "Widget",
        "old": "class Widget:\n    def a(self):\n        return 1\n",
        "new": "class BetterWidget:\n    def a(self):\n        return 1\n",
    }

    safety = analyze_patch_safety(patch)

    assert safety["safe"] is False
    assert "no longer defines `Widget`" in " ".join(safety["blockers"])


def test_patch_safety_warns_large_deletion():
    patch = {
        "symbol": "make_widget",
        "old": "\n".join(["def make_widget():"] + [f"    value_{i} = {i}" for i in range(20)] + ["    return value_0"]),
        "new": "\n".join(["def make_widget():"] + [f"    value_{i} = {i}" for i in range(9)] + ["    return value_0"]),
    }

    safety = analyze_patch_safety(patch)

    assert safety["safe"] is True
    assert safety["warnings"]


def test_patch_diff_includes_unified_markers():
    diff = patch_diff({
        "symbol": "f",
        "old": "def f():\n    return 1\n",
        "new": "def f():\n    return 2\n",
    })

    assert "--- f (current)" in diff
    assert "+++ f (proposed)" in diff
    assert "-    return 1" in diff
    assert "+    return 2" in diff


def test_apply_patch_refuses_unsafe_replacement(tmp_path):
    path = tmp_path / "sample.py"
    old = "def make_widget():\n    a = 1\n    b = 2\n    return a + b\n"
    path.write_text(old, encoding="utf-8")

    ok, msg, updated = apply_patch({
        "path": str(path),
        "symbol": "make_widget",
        "old": old,
        "new": "",
    })

    assert ok is False
    assert "safety checks" in msg
    assert updated is None
    assert path.read_text(encoding="utf-8") == old
