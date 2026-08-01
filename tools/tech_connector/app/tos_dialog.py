"""Signed Terms of Service acceptance dialog for Tech Connector."""

from __future__ import annotations

import datetime
import json
import socket
import sys
import threading
import urllib.request

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tech_connector.services.settings_service import load_settings, save_settings


TERMS_VERSION = "v2026.1"


class TermsOfServiceDialog(QDialog):
    """First-open modal dialog requiring a signed license acceptance."""

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
        badge_label = QLabel(f"{TERMS_VERSION} - Signature Required")
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
            "Before using The Entire World Tech Connector, review and sign the "
            "Community Source License summary below. The full license controls."
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
                "Free for individuals, students, educators, hobbyists, nonprofits, open-source projects, independent creators, and small studios below $500,000 USD in attributable revenue.",
                "#3cb371",
            ),
            (
                "Commercial Success License",
                "Above the $500,000 USD threshold, continued commercial use requires a written commercial license. The public summary describes a marginal 1.0% to 5.0% commercial-success share unless a separate agreement says otherwise.",
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
        sig_label = QLabel("Legal Signature Required")
        sig_label.setStyleSheet("font-weight: bold; color: #ffffff; font-size: 12px;")
        self.sig_input = QLineEdit()
        self.sig_input.setPlaceholderText("Type full legal name or authorized studio representative name")
        self.sig_input.setStyleSheet(
            "background-color: #0b1320; border: 1px solid #3cb371; color: #3cb371; "
            "font-family: monospace; font-size: 13px; padding: 6px 10px; border-radius: 4px;"
        )
        self.sig_input.textChanged.connect(self._validate_signature)
        self.sig_checkbox = QCheckBox(
            "I am authorized to bind myself or my entity to these terms and I agree to the Tech Connector Community Source License."
        )
        self.sig_checkbox.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        self.sig_checkbox.toggled.connect(self._validate_signature)
        sig_layout.addWidget(sig_label)
        sig_layout.addWidget(self.sig_input)
        sig_layout.addWidget(self.sig_checkbox)
        layout.addWidget(sig_box)

        btn_layout = QHBoxLayout()
        self.accept_btn = QPushButton("Sign & Accept Terms")
        self.accept_btn.setObjectName("accept_btn")
        self.accept_btn.setEnabled(False)
        self.accept_btn.clicked.connect(self._on_accept)
        self.decline_btn = QPushButton("Decline & Exit")
        self.decline_btn.setObjectName("decline_btn")
        self.decline_btn.clicked.connect(self._on_decline)
        btn_layout.addWidget(self.accept_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.decline_btn)
        layout.addLayout(btn_layout)

    def _validate_signature(self):
        self.accept_btn.setEnabled(len(self.sig_input.text().strip()) >= 3 and self.sig_checkbox.isChecked())

    def _on_accept(self):
        settings = load_settings()
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        signature_name = self.sig_input.text().strip()
        record = {
            "event": "TOS_ACCEPTED",
            "agreement_version": TERMS_VERSION,
            "accepted_at": timestamp,
            "legal_signature": signature_name,
            "account_email": str(settings.get("tech_connector_account_email") or ""),
            "license_id_present": bool(settings.get("tech_connector_license_token")),
            "machine_name": socket.gethostname(),
            "terms_summary": {
                "free_use_threshold": "$500,000 USD attributable revenue",
                "commercial_license": "Required above threshold unless a separate agreement says otherwise",
                "enterprise_redistribution_hosted_use": "Separate written agreement required",
                "telemetry": "Opt-in/configured only",
            },
        }
        settings["tos_accepted"] = True
        settings["tos_version"] = TERMS_VERSION
        settings["tos_acceptance_record"] = record
        save_settings(settings)

        endpoint = str(settings.get("activation_log_endpoint") or "").strip()
        if endpoint:
            threading.Thread(target=self._post_acceptance, args=(endpoint, record), daemon=True).start()
        self.accept()

    def _post_acceptance(self, endpoint: str, record: dict):
        try:
            payload = json.dumps(record).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as exc:
            print(f"[TOS_LOG] Acceptance notification could not be sent: {exc}", flush=True)

    def _on_decline(self):
        self.reject()
        sys.exit(0)


def ensure_tos_accepted(parent=None) -> bool:
    """Show signed Terms acceptance when no current acceptance record exists."""
    settings = load_settings()
    if settings.get("tos_accepted", False) and settings.get("tos_version") == TERMS_VERSION:
        return True
    dialog = TermsOfServiceDialog(parent)
    return dialog.exec() == QDialog.Accepted
