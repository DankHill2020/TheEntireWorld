from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TECH_CONNECTOR_GPU_VIEWPORT", "0")
os.environ.setdefault("TECH_CONNECTOR_DCC_VIEWPORT_STREAM", "0")

from PySide6.QtWidgets import QApplication, QMessageBox

from tech_connector.ui.scene_document_lifecycle import SceneDocumentLifecycle
from tech_connector.ui.scene_document_controller import command_mutates_document, finalize_adaptive_command
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


def test_lifecycle_tracks_dirty_state_and_recovery_paths(tmp_path: Path) -> None:
    lifecycle = SceneDocumentLifecycle(recovery_directory=tmp_path / "recovery", session_id="session")

    assert not lifecycle.dirty
    lifecycle.mark_dirty()
    assert lifecycle.dirty
    assert lifecycle.recovery_path().name == "Untitled-session.autosave.tcscene"
    assert lifecycle.recovery_path(str(tmp_path / "scene.tcscene")).name == ".scene.autosave.tcscene"
    lifecycle.mark_clean()
    assert not lifecycle.dirty


def test_adaptive_command_policy_marks_uncheckpointed_mutations_once() -> None:
    lifecycle = SceneDocumentLifecycle()

    finalize_adaptive_command(lifecycle, "gameplay.set_visual_style", {"executed": True}, 0)
    assert lifecycle.revision == 1
    finalize_adaptive_command(lifecycle, "gameplay.set_visual_style", {"executed": True}, 0)
    assert lifecycle.revision == 1
    assert not command_mutates_document("engine.audit_capability_maturity")
    assert not command_mutates_document("engine.qualify_dcc_host")
    assert not command_mutates_document("engine.qualify_dcc_source_parity")
    assert not command_mutates_document("engine.run_dcc_workflow")


def test_read_only_adaptive_command_does_not_dirty_document() -> None:
    lifecycle = SceneDocumentLifecycle()

    finalize_adaptive_command(lifecycle, "engine.plan_playtest", {"executed": True}, 0)

    assert not lifecycle.dirty


def test_viewer_autosaves_dirty_scene_and_manual_save_clears_recovery(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    widget = ThreeDMeshPainterViewport()
    widget._scene_lifecycle.recovery_directory = tmp_path / "recovery"
    widget.push_viewer_undo_state("Edit mesh")

    recovery = Path(widget.autosave_federated_scene())

    assert recovery.is_file()
    assert widget._scene_lifecycle.dirty
    target = tmp_path / "saved.tcscene"
    assert widget._save_federated_scene_to_path(str(target), publish_live=False)
    assert target.is_file()
    assert not widget._scene_lifecycle.dirty
    assert not recovery.exists()


def test_close_cancel_keeps_dirty_viewer_open(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    widget = ThreeDMeshPainterViewport()
    widget._force_close_prompt_for_testing = True
    widget.push_viewer_undo_state("Edit mesh")

    class Event:
        ignored = False

        def ignore(self) -> None:
            self.ignored = True

    event = Event()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Cancel)

    widget.closeEvent(event)

    assert event.ignored
    assert widget._scene_lifecycle.dirty


def test_nonfatal_diagnostics_are_retained_and_can_surface_status() -> None:
    QApplication.instance() or QApplication([])
    widget = ThreeDMeshPainterViewport()

    message = widget.record_nonfatal_diagnostic("Preference write failed", OSError("disk unavailable"), surface=True)

    assert message == "disk unavailable"
    assert widget._nonfatal_diagnostics[-1] == {
        "context": "Preference write failed",
        "message": "disk unavailable",
        "type": "OSError",
    }
    assert "disk unavailable" in widget._resolved_shaded_status
