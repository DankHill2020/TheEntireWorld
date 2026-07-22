from pathlib import Path
from types import SimpleNamespace

from services.update_service import GitUpdater, find_repo_root


class FakeRunner:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def __call__(self, args, timeout=120):
        self.calls.append((args, timeout))
        key = tuple(args[1:])
        value = self.outputs.get(key, "")
        if isinstance(value, Exception):
            return SimpleNamespace(returncode=1, stdout=str(value))
        return SimpleNamespace(returncode=0, stdout=value)


def test_find_repo_root_walks_up(tmp_path):
    root = tmp_path / "repo"
    nested = root / "a" / "b"
    (root / ".git").mkdir(parents=True)
    nested.mkdir(parents=True)

    assert find_repo_root(nested) == root


def test_update_latest_blocks_dirty_tree(tmp_path):
    runner = FakeRunner({("status", "--porcelain"): " M app.py"})
    updater = GitUpdater(tmp_path, runner=runner)

    result = updater.update_latest()

    assert result.ok is False
    assert "local changes" in result.message
    assert ("git", "fetch", "--all", "--prune") not in [tuple(call[0]) for call in runner.calls]


def test_update_latest_uses_fast_forward_pull(tmp_path):
    runner = FakeRunner(
        {
            ("status", "--porcelain"): "",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): "origin/main",
            ("rev-parse", "--short", "HEAD"): "bbb222",
            ("fetch", "--all", "--prune"): "fetched",
            ("pull", "--ff-only"): "updated",
        }
    )
    updater = GitUpdater(tmp_path, runner=runner)

    result = updater.update_latest()

    assert result.ok is True
    assert ("git", "pull", "--ff-only") in [tuple(call[0]) for call in runner.calls]


def test_update_ref_checks_out_requested_ref(tmp_path):
    runner = FakeRunner(
        {
            ("status", "--porcelain"): "",
            ("rev-parse", "--short", "HEAD"): "bbb222",
            ("fetch", "--all", "--prune"): "fetched",
            ("checkout", "abc123"): "checked out",
        }
    )
    updater = GitUpdater(tmp_path, runner=runner)

    result = updater.update_ref("abc123")

    assert result.ok is True
    assert ("git", "checkout", "abc123") in [tuple(call[0]) for call in runner.calls]
