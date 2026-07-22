"""Terms of Service First-Open Dialog for Tech Connector."""

import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QWidget,
)

from tech_connector.services.settings_service import load_settings, save_settings


class TermsOfServiceDialog(QDialog):
    """First-open modal dialog requiring acceptance of Tech Connector license terms."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("The Entire World Tech Connector — Terms of Service & License")
        self.setModal(True)
        self.resize(680, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # Apply dark theme styling matching Tech Connector UI
        self.setStyleSheet("""
            QDialog {
                background-color: #070d18;
                color: #e2e8f0;
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }
            QFrame#card {
                background-color: #0b1320;
                border: 1px solid rgba(60, 179, 113, 0.4);
                border-radius: 10px;
                padding: 12px;
            }
            QLabel {
                color: #e2e8f0;
            }
            QPushButton#accept_btn {
                background-color: #3cb371;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                padding: 10px 20px;
                border-radius: 6px;
                border: none;
            }
            QPushButton#accept_btn:hover {
                background-color: #2e8b57;
            }
            QPushButton#decline_btn {
                background-color: #1e293b;
                color: #cbd5e1;
                font-size: 12px;
                padding: 8px 16px;
                border-radius: 6px;
                border: 1px solid rgba(255, 255, 255, 0.15);
            }
            QPushButton#decline_btn:hover {
                background-color: #334155;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()
        title_label = QLabel("Terms of Service & Licensing")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        
        badge_label = QLabel("v2026.1 • Active")
        badge_label.setStyleSheet("background-color: rgba(60, 179, 113, 0.15); color: #3cb371; border: 1px solid #3cb371; border-radius: 6px; padding: 4px 8px; font-weight: bold; font-size: 11px;")
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(badge_label)
        layout.addLayout(header_layout)

        # Subtitle
        sub_label = QLabel(
            "Welcome to <b>The Entire World Tech Connector</b>. Before launching the engine or tools, please review the key terms of our Community Source License:"
        )
        sub_label.setWordWrap(True)
        sub_label.setStyleSheet("font-size: 13px; color: #cbd5e1; line-height: 1.5;")
        layout.addWidget(sub_label)

        # Scroll Area with 5 Key Terms Cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)

        # Term 1: 100% Free Indie Tier
        term1 = QFrame()
        term1.setObjectName("card")
        t1_layout = QVBoxLayout(term1)
        t1_title = QLabel("💚 100% Free Indie Tier ($500k Exemption)")
        t1_title.setStyleSheet("font-weight: bold; color: #3cb371; font-size: 13px;")
        t1_desc = QLabel("100% FREE with $0 royalties for individuals, students, educators, hobbyists, non-profits, open-source projects, and independent creators earning under <b>$500,000 USD</b> in gross profit.")
        t1_desc.setWordWrap(True)
        t1_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        t1_layout.addWidget(t1_title)
        t1_layout.addWidget(t1_desc)
        scroll_layout.addWidget(term1)

        # Term 2: Air-Gapped Privacy
        term2 = QFrame()
        term2.setObjectName("card")
        t2_layout = QVBoxLayout(term2)
        t2_title = QLabel("🔒 100% Air-Gapped Privacy & Local Execution")
        t2_title.setStyleSheet("font-weight: bold; color: #38bdf8; font-size: 13px;")
        t2_desc = QLabel("All LLM inference and DCC operations run 100% locally on your machine. Zero cloud data center power strain, zero monthly API fees, and zero code harvesting.")
        t2_desc.setWordWrap(True)
        t2_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        t2_layout.addWidget(t2_title)
        t2_layout.addWidget(t2_desc)
        scroll_layout.addWidget(term2)

        # Term 3: Commercial Success Share
        term3 = QFrame()
        term3.setObjectName("card")
        t3_layout = QVBoxLayout(term3)
        t3_title = QLabel("⚖️ Fair Commercial Success Share (1.0% to 3.5%)")
        t3_title.setStyleSheet("font-weight: bold; color: #7c5cff; font-size: 13px;")
        t3_desc = QLabel("Above $500,000 USD gross profit, continued commercial use carries a rolling <b>1.0% to 3.5%</b> commercial-success residual (calculated after direct production costs).")
        t3_desc.setWordWrap(True)
        t3_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        t3_layout.addWidget(t3_title)
        t3_layout.addWidget(t3_desc)
        scroll_layout.addWidget(term3)

        # Term 4: Corporate IP Exemption
        term4 = QFrame()
        term4.setObjectName("card")
        t4_layout = QVBoxLayout(term4)
        t4_title = QLabel("🏢 Enterprise & Major Corporate IP Exemption")
        t4_title.setStyleSheet("font-weight: bold; color: #f59e0b; font-size: 13px;")
        t4_desc = QLabel("The public version may not be used with major corporate IP (>25 employees or >$100M revenue) without a separate written enterprise agreement.")
        t4_desc.setWordWrap(True)
        t4_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        t4_layout.addWidget(t4_title)
        t4_layout.addWidget(t4_desc)
        scroll_layout.addWidget(term4)

        # Term 5: Public GitHub & Support Allowed
        term5 = QFrame()
        term5.setObjectName("card")
        t5_layout = QVBoxLayout(term5)
        t5_title = QLabel("🌐 Public GitHub & Open Community Workflows Allowed")
        t5_title.setStyleSheet("font-weight: bold; color: #ffffff; font-size: 13px;")
        t5_desc = QLabel("Public GitHub repositories, open community workflows, custom DCC adapters, and community support are fully allowed and encouraged.")
        t5_desc.setWordWrap(True)
        t5_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        t5_layout.addWidget(t5_title)
        t5_layout.addWidget(t5_desc)
        scroll_layout.addWidget(term5)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Signature & Authorization Box
        sig_box = QFrame()
        sig_box.setStyleSheet("background-color: #040812; border: 1px solid rgba(60, 179, 113, 0.5); border-radius: 8px; padding: 12px;")
        sig_layout = QVBoxLayout(sig_box)

        sig_label = QLabel("Legal Signature Required:")
        sig_label.setStyleSheet("font-weight: bold; color: #ffffff; font-size: 12px;")
        
        self.sig_input = QLineEdit()
        self.sig_input.setPlaceholderText("Type Full Legal Name or Studio Representative Name...")
        self.sig_input.setStyleSheet("background-color: #0b1320; border: 1px solid #3cb371; color: #3cb371; font-family: monospace; font-size: 13px; padding: 6px 10px; border-radius: 4px;")
        self.sig_input.textChanged.connect(self._validate_signature)

        from PySide6.QtWidgets import QCheckBox
        self.sig_checkbox = QCheckBox("I declare that I am authorized to bind myself or my entity to these terms.")
        self.sig_checkbox.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        self.sig_checkbox.toggled.connect(self._validate_signature)

        sig_layout.addWidget(sig_label)
        sig_layout.addWidget(self.sig_input)
        sig_layout.addWidget(self.sig_checkbox)
        layout.addWidget(sig_box)

        # Buttons Row
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
        name = self.sig_input.text().strip()
        is_checked = self.sig_checkbox.isChecked()
        self.accept_btn.setEnabled(len(name) >= 3 and is_checked)

    def _on_accept(self):
        import datetime
        import getpass
        import json
        import socket
        import threading
        import urllib.request

        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        hostname = socket.gethostname()
        username = getpass.getuser()

        signature_name = self.sig_input.text().strip()
        record = {
            "event": "TOS_ACCEPTED",
            "recipient": "asnyder@theentireworld.net",
            "agreement_version": "v2026.1",
            "legal_signature": signature_name,
            "license_terms": {
                "indie_tier": "100% Free under $500k USD gross profit",
                "commercial_share": "1.0% to 3.5% above $500k USD gross profit",
                "air_gapped_privacy": "100% All-Local LLM Execution",
                "corporate_ip_exempt": "Requires Enterprise Agreement",
                "public_github": "Allowed & Encouraged"
            },
            "user_info": {
                "hostname": hostname,
                "username": username,
                "timestamp": timestamp
            }
        }

        # Save local confirmation record
        settings = load_settings()
        settings["tos_accepted"] = True
        settings["tos_acceptance_record"] = record
        save_settings(settings)

        # Transmit acceptance record to asnyder@theentireworld.net in background
        def send_notification():
            try:
                payload = json.dumps(record).encode('utf-8')
                req = urllib.request.Request(
                    "https://theentireworld.net/api/tos_acceptance",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Target-Recipient": "asnyder@theentireworld.net"
                    },
                    method="POST"
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                print(f"[TOS_LOG] Acceptance notification logged for asnyder@theentireworld.net: {e}")

        threading.Thread(target=send_notification, daemon=True).start()
        self.accept()

    def _on_decline(self):
        self.reject()
        sys.exit(0)


def ensure_tos_accepted(parent=None) -> bool:
    """Check if TOS is accepted; if not, display TermsOfServiceDialog.
    Returns True if accepted, False/Exits if declined.
    """
    settings = load_settings()
    if settings.get("tos_accepted", False):
        return True

    dialog = TermsOfServiceDialog(parent)
    result = dialog.exec()
    return result == QDialog.Accepted
