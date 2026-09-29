"""Desktop lifecycle coverage for the licensing gate."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from tech_connector.app import licensing_gate, tos_dialog
from tech_connector.services.application_service import ApplicationService


def _decision(*, allowed: bool, reason: str = "", warnings=()):
    return SimpleNamespace(
        decision=SimpleNamespace(
            allowed=allowed,
            reason=reason,
            warnings=tuple(warnings),
        )
    )


class _GateService:
    def __init__(self, evaluations):
        self.settings = {"active_project": "C:/active"}
        self._evaluations = iter(evaluations)
        self.evaluation_calls = []
        self.authorized = []
        self.acceptance_records = []

    @staticmethod
    def development_entitlement_bypass_allowed():
        return False

    def evaluate_current_entitlement(self, **kwargs):
        self.evaluation_calls.append(kwargs)
        return next(self._evaluations)

    def authorize_host_bridges(self, evaluation):
        self.authorized.append(evaluation)

    def record_license_acceptance(self, evaluation):
        self.acceptance_records.append(evaluation)

    @staticmethod
    def licensing_activation_client():
        return object()


def test_candidate_project_is_evaluated_before_authorization():
    evaluation = _decision(allowed=True, warnings=("offline renewal due soon",))
    service = _GateService([evaluation])

    allowed, _reason, warnings = licensing_gate.ensure_entitlement(
        service,
        project_root="C:/candidate",
    )

    assert allowed
    assert service.evaluation_calls == [{"project_root": "C:/candidate"}]
    assert service.acceptance_records == [evaluation]
    assert service.authorized == [evaluation]
    assert warnings == ("offline renewal due soon",)


def test_denied_candidate_is_not_authorized_when_activation_is_cancelled(monkeypatch):
    service = _GateService([_decision(allowed=False, reason="Project registration required")])
    captured = {}

    def cancel_activation(_client, reason, project_root, _parent):
        captured.update(reason=reason, project_root=project_root)
        return False

    monkeypatch.setattr(
        "tech_connector.app.license_activation_dialog.ensure_license_activated",
        cancel_activation,
    )

    allowed, reason, _warnings = licensing_gate.ensure_entitlement(
        service,
        project_root="C:/candidate",
    )

    assert not allowed
    assert reason == "Project registration required"
    assert captured == {
        "reason": "Project registration required",
        "project_root": "C:/candidate",
    }
    assert service.authorized == []


def test_receipt_failure_prevents_bridge_authorization():
    evaluation = _decision(allowed=True)
    service = _GateService([evaluation])

    def fail_receipt(_evaluation):
        raise OSError("acceptance receipt could not be stored")

    service.record_license_acceptance = fail_receipt

    try:
        licensing_gate.ensure_entitlement(service)
    except OSError as exc:
        assert "could not be stored" in str(exc)
    else:
        raise AssertionError("receipt storage failure must fail closed")

    assert service.authorized == []


def test_terms_rejection_stops_before_entitlement_evaluation(monkeypatch):
    service = _GateService([_decision(allowed=True)])
    monkeypatch.setattr(tos_dialog, "ensure_tos_accepted", lambda _parent=None: False)

    allowed, reason, warnings = licensing_gate.ensure_desktop_preflight(service)

    assert not allowed
    assert "not accepted" in reason
    assert warnings == ()
    assert service.evaluation_calls == []
    assert service.acceptance_records == []
    assert service.authorized == []


def test_application_shell_without_project_is_not_treated_as_commercial_project():
    calls = []
    context = SimpleNamespace(
        configuration=SimpleNamespace(product="tech_connector"),
        evaluate=lambda **kwargs: calls.append(kwargs) or "evaluation",
    )
    service = ApplicationService.__new__(ApplicationService)
    service.settings = {
        "active_project": "",
        "tech_connector_commercial_use": True,
    }
    service.licensing_context = context

    assert service.evaluate_current_entitlement() == "evaluation"
    assert calls[0]["project_root"] is None
    assert calls[0]["commercial_use"] is False


def test_local_notice_does_not_collect_a_typed_legal_name(monkeypatch):
    QApplication.instance() or QApplication([])
    saved = []
    receipts = []
    settings = {}
    monkeypatch.setattr(tos_dialog, "load_settings", lambda: settings)
    monkeypatch.setattr(tos_dialog, "save_settings", lambda value: saved.append(dict(value)))
    monkeypatch.setattr(
        tos_dialog,
        "acceptance_receipt_store",
        lambda: SimpleNamespace(
            record_local_notice=lambda **values: receipts.append(values)
        ),
    )
    dialog = tos_dialog.TermsOfServiceDialog()

    assert dialog.findChildren(QLineEdit) == []
    dialog.acknowledgement_checkbox.setChecked(True)
    assert dialog.accept_btn.isEnabled()
    dialog._on_accept()

    record = saved[-1]["tos_acceptance_record"]
    assert record["acceptance_scope"] == "local_notice"
    assert "legal_signature" not in record
    assert "account_email" not in record
    assert "license_id_present" not in record
    assert receipts == [
        {
            "agreement_version": tos_dialog.TERMS_VERSION,
            "accepted_at": record["accepted_at"],
        }
    ]
    dialog.close()


def test_existing_local_acceptance_is_migrated_to_remove_pii(monkeypatch):
    settings = {
        "tos_accepted": True,
        "tos_version": tos_dialog.TERMS_VERSION,
        "tos_acceptance_record": {
            "accepted_at": "2026-09-01T00:00:00+00:00",
            "legal_signature": "Example Person",
            "account_email": "person@example.com",
            "license_id_present": True,
        },
    }
    saved = []
    receipts = []
    monkeypatch.setattr(tos_dialog, "load_settings", lambda: settings)
    monkeypatch.setattr(tos_dialog, "save_settings", lambda value: saved.append(dict(value)))
    monkeypatch.setattr(
        tos_dialog,
        "acceptance_receipt_store",
        lambda: SimpleNamespace(
            record_local_notice=lambda **values: receipts.append(values)
        ),
    )

    assert tos_dialog.ensure_tos_accepted()
    record = saved[-1]["tos_acceptance_record"]
    assert record == {
        "event": "LOCAL_LICENSE_NOTICE_ACKNOWLEDGED",
        "agreement_version": tos_dialog.TERMS_VERSION,
        "accepted_at": "2026-09-01T00:00:00+00:00",
        "acceptance_scope": "local_notice",
    }
    assert receipts == [
        {
            "agreement_version": tos_dialog.TERMS_VERSION,
            "accepted_at": "2026-09-01T00:00:00+00:00",
        }
    ]


def test_existing_acceptance_without_record_is_migrated_once(monkeypatch):
    settings = {
        "tos_accepted": True,
        "tos_version": tos_dialog.TERMS_VERSION,
    }
    saved = []
    receipts = []
    monkeypatch.setattr(tos_dialog, "load_settings", lambda: settings)
    monkeypatch.setattr(tos_dialog, "save_settings", lambda value: saved.append(dict(value)))
    monkeypatch.setattr(
        tos_dialog,
        "acceptance_receipt_store",
        lambda: SimpleNamespace(
            record_local_notice=lambda **values: receipts.append(values)
        ),
    )

    assert tos_dialog.ensure_tos_accepted()

    record = saved[-1]["tos_acceptance_record"]
    assert record["accepted_at"]
    assert receipts[-1]["accepted_at"] == record["accepted_at"]
