"""Local license-notice acknowledgement for Tech Connector."""

from __future__ import annotations

import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tech_connector.services.settings_service import load_settings, save_settings
from tech_connector.models.constants import APP_DIR
from tech_connector.licensing.acceptance import FileLicenseAcceptanceStore


TERMS_VERSION = "v2026.2"


def acceptance_receipt_store() -> FileLicenseAcceptanceStore:
    return FileLicenseAcceptanceStore(APP_DIR / "licensing")


class TermsOfServiceDialog(QDialog):
    """First-open notice; authoritative account acceptance happens online."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("The Entire World Tech Connector - Terms of Service & License")
        self.setModal(True)
        self.resize(720, 620)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.setStyleSheet(
            """
            QDialog {
                background-color: #070d18;
                color: #e2e8f0;
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }
            QFrame#card {
                background-color: #0b1320;
                border: 1px solid rgba(60, 179, 113, 0.4);
                border-radius: 8px;
                padding: 12px;
            }
            QLabel { color: #e2e8f0; }
            QPushButton#accept_btn {
                background-color: #3cb371;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                padding: 10px 20px;
                border-radius: 6px;
                border: none;
            }
            QPushButton#accept_btn:disabled {
                background-color: #244334;
                color: #8aa99a;
            }
            QPushButton#decline_btn {
                background-color: #1e293b;
                color: #cbd5e1;
                font-size: 12px;
                padding: 8px 16px;
                border-radius: 6px;
                border: 1px solid rgba(255, 255, 255, 0.15);
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header_layout = QHBoxLayout()
        title_label = QLabel("Terms of Service & Licensing")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        badge_label = QLabel(f"{TERMS_VERSION} - Acceptance Required")
        badge_label.setStyleSheet(
            "background-color: rgba(60, 179, 113, 0.15); color: #3cb371; "
            "border: 1px solid #3cb371; border-radius: 6px; padding: 4px 8px; "
            "font-weight: bold; font-size: 11px;"
        )
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(badge_label)
        layout.addLayout(header_layout)

        subtitle = QLabel(
            "Before using The Entire World Tech Connector, review the Community "
            "Source License summary below. The full license controls. Commercial "
            "and custom terms are accepted through your verified account."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 13px; color: #cbd5e1;")
        layout.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)

        for title, body, color in (
            (
                "Free Creator & Community Use",
                "Free for individuals, students, educators, hobbyists, nonprofits, and open-source projects. Community commercial projects owe no residual on the first $500,000 USD of Adjusted Project Profit.",
                "#3cb371",
            ),
            (
                "Commercial Success License",
                "Community commercial projects must be registered. No residual is owed on the first $500,000 USD of lifetime Adjusted Project Profit. Profit uses actual documented project costs, with arm's-length limits for owner and affiliate charges.",
                "#7c5cff",
            ),
            (
                "Enterprise, Hosted Use & Redistribution",
                "Enterprise pipeline use, major corporate IP work, redistribution, resale, hosted access, and commercializing Tech Connector itself require a separate written agreement.",
                "#f59e0b",
            ),
            (
                "Privacy & Local-First Operation",
                "Tech Connector is local-first. Local models and DCC operations can run on your machine. Cloud providers, activation, update checks, and telemetry require explicit configuration or consent.",
                "#38bdf8",
            ),
            (
                "Contributions & Provenance",
                "GitHub issues, patches, and community workflows are encouraged under the contribution terms. Generated code/assets may include transparent local provenance markers for licensing, troubleshooting, and project records.",
                "#ffffff",
            ),
        ):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_title = QLabel(title)
            card_title.setStyleSheet(f"font-weight: bold; color: {color}; font-size: 13px;")
            card_body = QLabel(body)
            card_body.setWordWrap(True)
            card_body.setStyleSheet("color: #94a3b8; font-size: 12px;")
            card_layout.addWidget(card_title)
            card_layout.addWidget(card_body)
            scroll_layout.addWidget(card)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        sig_box = QFrame()
        sig_box.setStyleSheet(
            "background-color: #040812; border: 1px solid rgba(60, 179, 113, 0.5); "
            "border-radius: 8px; padding: 12px;"
        )
        sig_layout = QVBoxLayout(sig_box)
        sig_label = QLabel("Local License Notice")
        sig_label.setStyleSheet("font-weight: bold; color: #ffffff; font-size: 12px;")
        self.acknowledgement_checkbox = QCheckBox(
            "I have read and agree to the Tech Connector Community Source License."
        )
        self.acknowledgement_checkbox.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        self.acknowledgement_checkbox.toggled.connect(self._validate_acknowledgement)
        sig_layout.addWidget(sig_label)
        sig_layout.addWidget(self.acknowledgement_checkbox)
        layout.addWidget(sig_box)

        btn_layout = QHBoxLayout()
        self.accept_btn = QPushButton("Acknowledge & Continue")
        self.accept_btn.setObjectName("accept_btn")
        self.accept_btn.setEnabled(False)
        self.accept_btn.clicked.connect(self._on_accept)
        self.decline_btn = QPushButton("Decline & Exit")
        self.decline_btn.setObjectName("decline_btn")
        self.decline_btn.clicked.connect(self._on_decline)
        btn_layout.addWidget(self.accept_btn)
        self.full_license_btn = QPushButton("View Full License")
        self.full_license_btn.setObjectName("decline_btn")
        self.full_license_btn.clicked.connect(self._open_full_license)
        btn_layout.addWidget(self.full_license_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.decline_btn)
        layout.addLayout(btn_layout)

    def _validate_acknowledgement(self):
        self.accept_btn.setEnabled(self.acknowledgement_checkbox.isChecked())

    def _open_full_license(self):
        license_path = Path(__file__).resolve().parents[1] / "LICENSE.md"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(license_path)))

    def _on_accept(self):
        settings = load_settings()
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        record = {
            "event": "LOCAL_LICENSE_NOTICE_ACKNOWLEDGED",
            "agreement_version": TERMS_VERSION,
            "accepted_at": timestamp,
            "acceptance_scope": "local_notice",
            "terms_summary": {
                "community_project_threshold": "$500,000 USD Adjusted Project Profit",
                "measurement_period": "Registered project lifetime",
                "eligible_costs": "Actual documented, reasonable, necessary, directly attributable project costs",
                "commercial_terms": "Only profit above the threshold may be subject to accepted versioned project terms",
                "enterprise_redistribution_hosted_use": "Separate written agreement required",
                "telemetry": "Opt-in/configured only",
            },
        }
        acceptance_receipt_store().record_local_notice(
            agreement_version=TERMS_VERSION,
            accepted_at=timestamp,
        )
        settings["tos_accepted"] = True
        settings["tos_version"] = TERMS_VERSION
        settings["tos_acceptance_record"] = record
        save_settings(settings)

        self.accept()

    def _on_decline(self):
        self.reject()


def ensure_tos_accepted(parent=None) -> bool:
    """Show the local notice and remove PII from legacy local records."""
    settings = load_settings()
    if settings.get("tos_accepted", False) and settings.get("tos_version") == TERMS_VERSION:
        record = settings.get("tos_acceptance_record")
        accepted_at = ""
        if isinstance(record, dict):
            accepted_at = str(record.get("accepted_at") or "")
        if not accepted_at:
            accepted_at = datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds"
            )
        sanitized_record = {
            "event": "LOCAL_LICENSE_NOTICE_ACKNOWLEDGED",
            "agreement_version": TERMS_VERSION,
            "accepted_at": accepted_at,
            "acceptance_scope": "local_notice",
        }
        acceptance_receipt_store().record_local_notice(
            agreement_version=TERMS_VERSION,
            accepted_at=accepted_at,
        )
        if record != sanitized_record:
            settings["tos_acceptance_record"] = sanitized_record
            save_settings(settings)
        return True
    dialog = TermsOfServiceDialog(parent)
    return dialog.exec() == QDialog.Accepted
