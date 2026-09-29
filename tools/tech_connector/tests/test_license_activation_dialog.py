"""Offscreen construction tests for licensing dialogs."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from tech_connector.app.license_activation_dialog import (
    LicenseActivationDialog,
    LicenseManagementDialog,
    _claims_summary,
)
from tech_connector.app import license_activation_dialog
from tech_connector.licensing.domain import EntitlementClaims
from tech_connector.tests.test_licensing_foundation import _payload


class Client:
    pass


def _application():
    return QApplication.instance() or QApplication([])


def test_activation_dialog_discloses_privacy_and_project_registration():
    _application()
    dialog = LicenseActivationDialog(
        Client(),
        "Activation required",
        "C:/project",
    )
    text = " ".join(label.text() for label in dialog.findChildren(QLabel))

    assert "creative content" in text
    assert "random project ID" in text
    assert "Passwords are never" in text
    dialog.close()


def test_management_dialog_handles_missing_cached_entitlement():
    _application()
    evaluation = SimpleNamespace(claims=None, decision=SimpleNamespace(reason="locked"))
    dialog = LicenseManagementDialog(Client(), evaluation)

    assert "No verified entitlement" in dialog.summary.text()
    assert not dialog.deactivate_button.isEnabled()
    dialog.close()


def test_management_dialog_exposes_commercial_use_declaration():
    _application()
    evaluation = SimpleNamespace(claims=None, decision=SimpleNamespace(reason="locked"))
    dialog = LicenseManagementDialog(Client(), evaluation, commercial_use=False)

    assert not dialog.commercial_use_checkbox.isChecked()
    assert "commercial use" in dialog.commercial_use_checkbox.text()
    dialog.close()


def test_management_dialog_shows_and_opens_acceptance_receipts(tmp_path, monkeypatch):
    _application()
    receipt_path = tmp_path / "license_acceptance_receipts.json"
    receipt_path.write_text('{"records": []}\n', encoding="utf-8")
    opened = []
    monkeypatch.setattr(
        license_activation_dialog.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url) or True,
    )
    evaluation = SimpleNamespace(claims=None, decision=SimpleNamespace(reason="locked"))
    dialog = LicenseManagementDialog(
        Client(),
        evaluation,
        acceptance_receipts_path=receipt_path,
    )

    assert str(receipt_path) in dialog.acceptance_receipts_label.text()
    assert dialog.open_receipts_button.isEnabled()
    dialog.open_acceptance_receipts()
    assert Path(opened[0].toLocalFile()).resolve() == receipt_path.resolve()
    dialog.close()


def test_claims_summary_surfaces_signed_project_economics():
    summary = _claims_summary(EntitlementClaims.from_payload(_payload()))

    assert "USD 500,000.00 (project_lifetime)" in summary
    assert "Residual rate above threshold: 0.75%" in summary
    assert "Reporting period: quarterly" in summary
    assert "Market segment: community" in summary
    assert "Offer: legacy-v1" in summary


def test_claims_summary_surfaces_named_user_seat():
    payload = _payload()
    payload["schema_version"] = 2
    payload["license"].update(
        {
            "market_segment": "indie",
            "offer_id": "indie-annual-2026a",
            "classification_version": "studio-size-2026a",
        }
    )
    payload["seat_assignment"] = {
        "assignment_id": "seat_creator",
        "account_id": "acct_test",
        "status": "active",
        "assigned_at": "2026-08-23T18:00:00+00:00",
    }

    summary = _claims_summary(EntitlementClaims.from_payload(payload))

    assert "Named-user seat: seat_creator (active)" in summary
    assert "Market segment: indie" in summary


def test_claims_summary_surfaces_marginal_residual_schedule():
    payload = _payload()
    payload["terms"].update(
        {
            "calculation_method": "marginal_brackets",
            "rate_basis_points": 0,
            "residual_brackets": [
                {
                    "from_profit_minor": 50_000_000,
                    "to_profit_minor": 100_000_000,
                    "rate_basis_points": 50,
                },
                {
                    "from_profit_minor": 100_000_000,
                    "to_profit_minor": None,
                    "rate_basis_points": 75,
                },
            ],
        }
    )

    summary = _claims_summary(EntitlementClaims.from_payload(payload))

    assert "Residual schedule: marginal brackets" in summary
    assert "USD 500,000.00 to USD 1,000,000.00: 0.50%" in summary
    assert "USD 1,000,000.00 and above: 0.75%" in summary
