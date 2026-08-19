"""Safety tests for transactional project-edit application and undo."""

from __future__ import annotations

import json
from pathlib import Path
import random
from typing import Any

import pytest

from tech_connector.services import change_history_service
from tech_connector.services import project_edit_agent_part_06 as edit_service


def _configure_history(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Redirect persistent change history into a test directory.

    :param monkeypatch: Pytest monkeypatch fixture.
    :param root: Test root directory.
    :return: None.
    """

    history = root / "history"
    monkeypatch.setattr(change_history_service, "HISTORY_DIR", history)
    monkeypatch.setattr(
        change_history_service,
        "ACTIVE_SESSION_PATH",
        history / "latest_change_session.json",
    )


def _response(changes: list[dict[str, str]]) -> str:
    """Build one complete structured project-edit response.

    :param changes: Structured change rows.
    :return: Serialized response.
    """

    return json.dumps(
        {
            "changes": changes,
            "report": {
                "changed": [],
                "reused": [],
                "verification": [],
                "remaining_gaps": [],
                "requirement_coverage": [],
            },
            "blocked_reason": "",
        }
    )


def _modify(path: Path, before: str, after: str) -> dict[str, str]:
    """Build one exact full-file modification.

    :param path: Target file.
    :param before: Expected source.
    :param after: Replacement source.
    :return: Structured change row.
    """

    return {
        "action": "modify",
        "path": str(path),
        "target_symbol": "",
        "original_content": before,
        "new_content": after,
    }


def test_apply_rejects_source_changed_after_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Refuse to overwrite an external edit made during model preview."""

    _configure_history(monkeypatch, tmp_path)
    source = tmp_path / "service.py"
    before = "VALUE = 1\n"
    source.write_text(before, encoding="utf-8")
    original_preview = edit_service.preview_project_edit_agent_response

    def racing_preview(*args: Any, **kwargs: Any) -> Any:
        preview = original_preview(*args, **kwargs)
        source.write_text("VALUE = 99\n", encoding="utf-8")
        return preview

    monkeypatch.setattr(
        edit_service,
        "preview_project_edit_agent_response",
        racing_preview,
    )
    result = edit_service.apply_project_edit_agent_response(
        _response([_modify(source, before, "VALUE = 2\n")]),
        project_root=str(tmp_path),
    )

    assert result.ok is False
    assert result.status == "stale_source"
    assert source.read_text(encoding="utf-8") == "VALUE = 99\n"
    assert "changed after preview" in result.errors[0]
    assert not change_history_service.HISTORY_DIR.exists()


def test_second_write_failure_rolls_back_first_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Avoid exposing a partially applied multi-file edit."""

    _configure_history(monkeypatch, tmp_path)
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("FIRST = 1\n", encoding="utf-8")
    second.write_text("SECOND = 1\n", encoding="utf-8")
    atomic_write = edit_service._write_text_atomically

    def fail_second(path: Path, content: str) -> None:
        if path.resolve() == second.resolve():
            raise OSError("simulated disk failure")
        atomic_write(path, content)

    monkeypatch.setattr(edit_service, "_write_text_atomically", fail_second)
    result = edit_service.apply_project_edit_agent_response(
        _response(
            [
                _modify(first, "FIRST = 1\n", "FIRST = 2\n"),
                _modify(second, "SECOND = 1\n", "SECOND = 2\n"),
            ]
        ),
        project_root=str(tmp_path),
    )

    assert result.ok is False
    assert result.status == "write_failed_rolled_back"
    assert first.read_text(encoding="utf-8") == "FIRST = 1\n"
    assert second.read_text(encoding="utf-8") == "SECOND = 1\n"
    assert any("simulated disk failure" in error for error in result.errors)
    assert change_history_service.load_change_session() is None
    assert change_history_service.load_change_session(result.change_session_path) is not None


def test_post_write_validation_failure_rolls_back_all_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Restore the previous project state when live validation fails."""

    _configure_history(monkeypatch, tmp_path)
    source = tmp_path / "service.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        edit_service,
        "_validate_changes",
        lambda *_args, **_kwargs: [
            {
                "ok": False,
                "path": str(source),
                "command": "runtime-test",
                "message": "simulated behavioral regression",
            }
        ],
    )

    result = edit_service.apply_project_edit_agent_response(
        _response([_modify(source, "VALUE = 1\n", "VALUE = 2\n")]),
        project_root=str(tmp_path),
    )

    assert result.ok is False
    assert result.status == "validation_failed_rolled_back"
    assert source.read_text(encoding="utf-8") == "VALUE = 1\n"
    assert any("simulated behavioral regression" in error for error in result.errors)
    assert change_history_service.load_change_session() is None
    assert change_history_service.load_change_session(result.change_session_path) is not None


def test_validation_rollback_restores_modify_and_removes_create(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Rollback mixed existing and newly created files as one transaction."""

    _configure_history(monkeypatch, tmp_path)
    existing = tmp_path / "existing.txt"
    created = tmp_path / "created.txt"
    existing.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(
        edit_service,
        "_validate_changes",
        lambda *_args, **_kwargs: [
            {"ok": False, "message": "mixed transaction validation failed"}
        ],
    )
    result = edit_service.apply_project_edit_agent_response(
        _response(
            [
                _modify(existing, "old\n", "new\n"),
                {
                    "action": "create",
                    "path": str(created),
                    "target_symbol": "",
                    "original_content": "",
                    "new_content": "created\n",
                },
            ]
        ),
        project_root=str(tmp_path),
    )

    assert result.status == "validation_failed_rolled_back"
    assert existing.read_text(encoding="utf-8") == "old\n"
    assert created.exists() is False


def test_randomized_multi_file_write_failures_are_atomic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Rollback every randomized failure position without partial state."""

    rng = random.Random(908_172_635)
    atomic_write = edit_service._write_text_atomically
    for attempt in range(24):
        root = tmp_path / f"attempt_{attempt}"
        root.mkdir()
        _configure_history(monkeypatch, root)
        file_count = rng.randint(2, 9)
        failure_index = rng.randrange(file_count)
        paths = [root / f"file_{index}.txt" for index in range(file_count)]
        changes: list[dict[str, str]] = []
        for index, path in enumerate(paths):
            before = f"before-{attempt}-{index}\n"
            after = f"after-{attempt}-{index}\n"
            path.write_text(before, encoding="utf-8")
            changes.append(_modify(path, before, after))

        def fail_selected(path: Path, content: str) -> None:
            if path.resolve() == paths[failure_index].resolve():
                raise OSError(f"failure-at-{failure_index}")
            atomic_write(path, content)

        monkeypatch.setattr(edit_service, "_write_text_atomically", fail_selected)
        result = edit_service.apply_project_edit_agent_response(
            _response(changes),
            project_root=str(root),
            validate=False,
        )

        assert result.status == "write_failed_rolled_back", (
            attempt,
            failure_index,
            result,
        )
        for index, path in enumerate(paths):
            assert path.read_text(encoding="utf-8") == f"before-{attempt}-{index}\n"


def test_undo_refuses_to_overwrite_newer_user_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Require an explicit force flag before undo overwrites a later edit."""

    _configure_history(monkeypatch, tmp_path)
    source = tmp_path / "service.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    session = change_history_service.create_change_session(
        {
            str(source): {
                "action": "modify",
                "original_content": "VALUE = 1\n",
                "new_content": "VALUE = 2\n",
                "current": "VALUE = 2\n",
            }
        }
    )
    source.write_text("VALUE = 3\n", encoding="utf-8")

    ok, message, changed = change_history_service.undo_change_session(session)

    assert ok is False
    assert changed == []
    assert "changed after the AI edit" in message
    assert source.read_text(encoding="utf-8") == "VALUE = 3\n"

    forced_ok, _forced_message, forced_changes = (
        change_history_service.undo_change_session(session, force=True)
    )
    assert forced_ok is True
    assert forced_changes == [str(source)]
    assert source.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_multi_file_undo_conflict_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preflight every undo target before reverting any file.

    :param monkeypatch: Pytest monkeypatch fixture.
    :param tmp_path: Temporary project root.
    :return: None.
    """

    _configure_history(monkeypatch, tmp_path)
    conflicted = tmp_path / "conflicted.py"
    clean = tmp_path / "clean.py"
    conflicted.write_text("VALUE = 99\n", encoding="utf-8")
    clean.write_text("CLEAN = 2\n", encoding="utf-8")
    session = change_history_service.create_change_session(
        {
            str(conflicted): _modify(
                conflicted,
                "VALUE = 1\n",
                "VALUE = 2\n",
            ),
            str(clean): _modify(clean, "CLEAN = 1\n", "CLEAN = 2\n"),
        }
    )

    ok, message, changed = change_history_service.undo_change_session(session)

    assert ok is False
    assert "refused before changing files" in message
    assert changed == []
    assert conflicted.read_text(encoding="utf-8") == "VALUE = 99\n"
    assert clean.read_text(encoding="utf-8") == "CLEAN = 2\n"


def test_multi_file_undo_write_failure_rolls_back_prior_restores(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Restore the applied state when an undo write fails midway.

    :param monkeypatch: Pytest monkeypatch fixture.
    :param tmp_path: Temporary project root.
    :return: None.
    """

    _configure_history(monkeypatch, tmp_path)
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("FIRST = 2\n", encoding="utf-8")
    second.write_text("SECOND = 2\n", encoding="utf-8")
    session = change_history_service.create_change_session(
        {
            str(first): _modify(first, "FIRST = 1\n", "FIRST = 2\n"),
            str(second): _modify(second, "SECOND = 1\n", "SECOND = 2\n"),
        }
    )
    atomic_write = change_history_service._write_text_atomically
    failure_injected = False

    def fail_first_restore(path: Path, content: str) -> None:
        nonlocal failure_injected
        if path.resolve() == first.resolve() and not failure_injected:
            failure_injected = True
            raise OSError("simulated undo disk failure")
        atomic_write(path, content)

    monkeypatch.setattr(
        change_history_service,
        "_write_text_atomically",
        fail_first_restore,
    )
    ok, message, changed = change_history_service.undo_change_session(session)

    assert ok is False
    assert "failed and was rolled back" in message
    assert "simulated undo disk failure" in message
    assert changed == []
    assert first.read_text(encoding="utf-8") == "FIRST = 2\n"
    assert second.read_text(encoding="utf-8") == "SECOND = 2\n"


def test_change_session_listing_excludes_latest_pointer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Return only loadable sessions from history discovery."""

    _configure_history(monkeypatch, tmp_path)
    session = change_history_service.create_change_session({})
    saved = change_history_service.save_change_session(session)

    assert change_history_service.list_change_sessions() == [saved]


def test_deactivating_rollback_restores_previous_active_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep the prior successful edit available after a later rollback."""

    _configure_history(monkeypatch, tmp_path)
    first = change_history_service.create_change_session({})
    first_path = change_history_service.save_change_session(first)
    second = change_history_service.create_change_session({})
    second_path = change_history_service.save_change_session(second)
    assert first_path != second_path

    change_history_service.deactivate_change_session(second)

    active = change_history_service.load_change_session()
    assert active is not None
    assert active.session_id == first.session_id
