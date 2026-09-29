"""Desktop account sign-in and device activation flow."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from tech_connector.licensing.activation_client import LoginState
from tech_connector.licensing.http_adapters import LicensingNetworkError
from tech_connector.models.constants import APP_DIR


class _OperationSignals(QObject):
    completed = Signal(object)
    failed = Signal(object)


class LicenseActivationDialog(QDialog):
    """Run a browser/device login without embedding passwords in Tech Connector."""

    def __init__(self, activation_client, reason: str = "", project_root: str = "", parent=None) -> None:
        super().__init__(parent)
        self.activation_client = activation_client
        self.challenge = None
        self.outcome = None
        self.project_root = str(project_root or "").strip()
        self._action_url = ""
        self._busy = False
        self._operations = set()
        self.setWindowTitle("Activate Tech Connector")
        self.setModal(True)
        self.resize(560, 310)

        layout = QVBoxLayout(self)
        title = QLabel("Sign in and activate this installation")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        explanation = QLabel(
            "Tech Connector opens your account page in a browser. Passwords are never "
            "entered into this application. Activation sends only account, entitlement, "
            "project-ID, and pseudonymous installation metadata—not creative content."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        if self.project_root:
            project_notice = QLabel(
                "If this Community entitlement is used commercially, activation will register "
                "the current project's random project ID. Its path and contents stay local."
            )
            project_notice.setWordWrap(True)
            layout.addWidget(project_notice)

        self.reason_label = QLabel(str(reason or "A valid entitlement is required."))
        self.reason_label.setWordWrap(True)
        layout.addWidget(self.reason_label)

        self.code_label = QLabel("")
        self.code_label.setStyleSheet("font-family: monospace; font-size: 20px; font-weight: bold;")
        layout.addWidget(self.code_label)

        self.license_id = QLineEdit()
        self.license_id.setPlaceholderText("Optional license ID when your account has multiple licenses")
        layout.addWidget(self.license_id)

        self.status_label = QLabel("Ready to sign in.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.sign_in_button = QPushButton("Sign in or create account")
        self.sign_in_button.clicked.connect(self.start_login)
        self.open_browser_button = QPushButton("Open account page")
        self.open_browser_button.setEnabled(False)
        self.open_browser_button.clicked.connect(self.open_browser)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.sign_in_button)
        buttons.addWidget(self.open_browser_button)
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_login)

    def start_login(self) -> None:
        self.poll_timer.stop()
        self.challenge = None
        self._action_url = ""
        self.code_label.setText("")
        self.open_browser_button.setEnabled(False)
        self.status_label.setText("Requesting a secure sign-in code...")
        self._run_async(
            lambda: self.activation_client.begin_login(self.project_root),
            self._login_started,
        )

    def _login_started(self, challenge) -> None:
        self.challenge = challenge
        self.code_label.setText(f"Code: {challenge.user_code}")
        self.status_label.setText(
            "Complete sign-in and email verification in your browser. This window will continue automatically."
        )
        self.open_browser_button.setEnabled(True)
        self.open_browser()
        self.poll_timer.start(challenge.poll_interval_seconds * 1000)

    def open_browser(self) -> None:
        target = self._action_url
        if not target and self.challenge is not None:
            target = self.challenge.verification_uri_complete
        if target:
            QDesktopServices.openUrl(QUrl(target))

    def poll_login(self) -> None:
        if self._busy or self.challenge is None:
            return
        if datetime.now(timezone.utc) >= self.challenge.expires_at:
            self.poll_timer.stop()
            self.status_label.setText("The sign-in code expired. Start sign-in again.")
            return
        self._run_async(
            lambda: self.activation_client.poll_login(self.challenge.login_attempt_id),
            self._login_polled,
            retry_on_failure=True,
        )

    def _login_polled(self, result) -> None:
        if result.state is LoginState.PENDING:
            return
        self.poll_timer.stop()
        if result.state is LoginState.AUTHENTICATED:
            self.status_label.setText("Account verified. Activating this installation...")
            self._run_async(
                lambda: self.activation_client.activate_device(self.license_id.text()),
                self._activation_completed,
            )
            return
        self.status_label.setText(
            "Sign-in was denied or expired. Start sign-in again when you are ready."
        )

    def _activation_completed(self, outcome) -> None:
        self.outcome = outcome
        if (
            self.project_root
            and outcome.claims.license.type.value == "community"
            and outcome.claims.projects.registration_required
        ):
            self.status_label.setText("Registering the current project ID...")
            self._run_async(
                lambda: self.activation_client.register_project(
                    self.project_root,
                    outcome.license_id,
                ),
                self._registration_completed,
            )
            return
        self._finish_activation()

    def _registration_completed(self, _claims) -> None:
        self._finish_activation()

    def _finish_activation(self) -> None:
        self.status_label.setText("Tech Connector is activated for offline use.")
        QTimer.singleShot(250, self.accept)

    def _run_async(self, operation, completed, *, retry_on_failure: bool = False) -> None:
        if self._busy:
            return
        self._busy = True
        self.sign_in_button.setEnabled(False)
        signals = _OperationSignals(self)
        self._operations.add(signals)

        def cleanup() -> None:
            self._busy = False
            self.sign_in_button.setEnabled(True)
            self._operations.discard(signals)

        def success(value) -> None:
            cleanup()
            completed(value)

        def failure(error) -> None:
            cleanup()
            if isinstance(error, LicensingNetworkError) and error.action_url:
                self._action_url = error.action_url
                self.open_browser_button.setEnabled(True)
            if (
                retry_on_failure
                and isinstance(error, LicensingNetworkError)
                and error.retryable
                and self.challenge is not None
                and datetime.now(timezone.utc) < self.challenge.expires_at
            ):
                retry_seconds = max(
                    self.challenge.poll_interval_seconds,
                    error.retry_after_seconds,
                )
                self.status_label.setText(
                    _licensing_error_message(error) + f" Retrying in {retry_seconds} seconds."
                )
                self.poll_timer.start(retry_seconds * 1000)
                return
            self.poll_timer.stop()
            self.status_label.setText(_licensing_error_message(error))

        signals.completed.connect(success)
        signals.failed.connect(failure)

        def run() -> None:
            try:
                signals.completed.emit(operation())
            except Exception as exc:
                signals.failed.emit(exc)

        threading.Thread(target=run, daemon=True).start()


def ensure_license_activated(activation_client, reason: str, project_root: str = "", parent=None) -> bool:
    dialog = LicenseActivationDialog(activation_client, reason, project_root, parent)
    return dialog.exec() == QDialog.Accepted


class LicenseManagementDialog(QDialog):
    """Display the signed entitlement and expose refresh/deactivation actions."""

    def __init__(
        self,
        activation_client,
        evaluation,
        parent=None,
        *,
        commercial_use: bool = True,
        acceptance_receipts_path: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.activation_client = activation_client
        self.evaluation = evaluation
        self.session_removed = False
        self._busy = False
        self._operations = set()
        self.setWindowTitle("Tech Connector License & Activation")
        self.resize(560, 300)

        layout = QVBoxLayout(self)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.acceptance_receipts_path = Path(
            acceptance_receipts_path or (APP_DIR / "licensing" / "license_acceptance_receipts.json")
        ).expanduser()
        self.acceptance_receipts_label = QLabel(
            f"Acceptance receipts: {self.acceptance_receipts_path}"
        )
        self.acceptance_receipts_label.setWordWrap(True)
        self.acceptance_receipts_label.setTextInteractionFlags(
            self.acceptance_receipts_label.textInteractionFlags()
            | Qt.TextSelectableByMouse
        )
        layout.addWidget(self.acceptance_receipts_label)

        self.commercial_use_checkbox = QCheckBox(
            "The current project is intended for commercial use"
        )
        self.commercial_use_checkbox.setChecked(bool(commercial_use))
        self.commercial_use_checkbox.setToolTip(
            "Community commercial projects must be registered. Disable this only "
            "for genuinely noncommercial use; changing the declaration does not "
            "override the license terms."
        )
        layout.addWidget(self.commercial_use_checkbox)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh entitlement")
        self.refresh_button.clicked.connect(self.refresh_entitlement)
        self.deactivate_button = QPushButton("Deactivate this installation")
        self.deactivate_button.clicked.connect(self.deactivate)
        self.logout_button = QPushButton("Sign out locally")
        self.logout_button.clicked.connect(self.logout)
        self.open_receipts_button = QPushButton("Open Acceptance Receipts")
        self.open_receipts_button.setEnabled(self.acceptance_receipts_path.is_file())
        self.open_receipts_button.clicked.connect(self.open_acceptance_receipts)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.deactivate_button)
        buttons.addWidget(self.logout_button)
        buttons.addWidget(self.open_receipts_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self._render(evaluation)

    def open_acceptance_receipts(self) -> None:
        if self.acceptance_receipts_path.is_file():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.acceptance_receipts_path.resolve()))
            )

    def _render(self, evaluation) -> None:
        claims = getattr(evaluation, "claims", None)
        if claims is None:
            self.summary.setText("No verified entitlement is cached for this installation.")
            self.deactivate_button.setEnabled(False)
            return
        self.summary.setText(_claims_summary(claims))
        self.status.setText(evaluation.decision.reason)

    def refresh_entitlement(self) -> None:
        self.status.setText("Refreshing entitlement...")
        self._run_async(self.activation_client.refresh_entitlement, self._refresh_completed)

    def _refresh_completed(self, claims) -> None:
        self.summary.setText(_claims_summary(claims))
        self.status.setText("Entitlement refreshed.")

    def deactivate(self) -> None:
        claims = getattr(self.evaluation, "claims", None)
        if claims is None:
            return
        answer = QMessageBox.question(
            self,
            "Deactivate installation",
            "Deactivate this installation so the activation can be used on a replacement machine?",
        )
        if answer != QMessageBox.Yes:
            return
        self.status.setText("Deactivating this installation...")
        self._run_async(
            lambda: self.activation_client.deactivate_device(claims.activation.activation_id),
            lambda _value: self._session_removed("Installation deactivated."),
        )

    def logout(self) -> None:
        self.status.setText("Signing out...")
        self._run_async(
            self.activation_client.logout,
            lambda _value: self._session_removed("Signed out locally."),
        )

    def _session_removed(self, message: str) -> None:
        self.session_removed = True
        self.status.setText(message)
        QTimer.singleShot(250, self.accept)

    def _run_async(self, operation, completed) -> None:
        if self._busy:
            return
        self._busy = True
        for button in (self.refresh_button, self.deactivate_button, self.logout_button):
            button.setEnabled(False)
        signals = _OperationSignals(self)
        self._operations.add(signals)

        def cleanup() -> None:
            self._busy = False
            self._operations.discard(signals)
            for button in (self.refresh_button, self.deactivate_button, self.logout_button):
                button.setEnabled(True)

        def success(value) -> None:
            cleanup()
            completed(value)

        def failure(error) -> None:
            cleanup()
            self.status.setText(_licensing_error_message(error))

        signals.completed.connect(success)
        signals.failed.connect(failure)

        def run() -> None:
            try:
                signals.completed.emit(operation())
            except Exception as exc:
                signals.failed.emit(exc)

        threading.Thread(target=run, daemon=True).start()


def _claims_summary(claims) -> str:
    organization = claims.principal.organization_name or "Individual"
    lines = [
        f"Account: {claims.principal.email}",
        f"Organization: {organization}",
        f"License: {claims.license.license_id} ({claims.license.type.value})",
        f"Market segment: {claims.license.market_segment.value}",
        f"Offer: {claims.license.offer_id}",
        f"Classification: {claims.license.classification_version}",
        f"Studio size: {claims.principal.studio_size_band or 'not classified'}",
        f"Agreement: {claims.license.agreement_version}",
        f"Version entitlement: {', '.join(claims.version_entitlement.perpetual_major_versions) or 'subscription/update window'}",
        f"Support: {claims.support.level}",
        f"Seats/devices: {claims.limits.seat_count} × {claims.limits.device_limit_per_seat}",
        f"Activation: {claims.activation.activation_id}",
        f"Offline access expires: {claims.offline.expires_at.isoformat()}",
    ]
    if claims.seat_assignment is not None:
        lines.insert(
            7,
            f"Named-user seat: {claims.seat_assignment.assignment_id} ({claims.seat_assignment.status})",
        )
    terms = claims.terms
    if terms is not None:
        threshold = terms.profit_threshold_minor / 100
        lines.extend(
            (
                f"Project terms: {terms.terms_id} v{terms.version}",
                f"No-residual threshold: {terms.currency} {threshold:,.2f} ({terms.threshold_period})",
                f"Reporting period: {terms.reporting_period}",
            )
        )
        if terms.calculation_method == "marginal_brackets":
            lines.append("Residual schedule: marginal brackets")
            for bracket in terms.residual_brackets:
                lower = bracket.from_profit_minor / 100
                if bracket.to_profit_minor is None:
                    range_label = f"{terms.currency} {lower:,.2f} and above"
                else:
                    upper = bracket.to_profit_minor / 100
                    range_label = (
                        f"{terms.currency} {lower:,.2f} to "
                        f"{terms.currency} {upper:,.2f}"
                    )
                lines.append(
                    f"  {range_label}: {bracket.rate_basis_points / 100:.2f}%"
                )
        else:
            lines.append(
                f"Residual rate above threshold: {terms.rate_basis_points / 100:.2f}%"
            )
    return "\n".join(lines)


def _licensing_error_message(error) -> str:
    message = str(error or "").strip() or "Licensing operation failed."
    if isinstance(error, LicensingNetworkError) and error.error_code:
        return f"{message} ({error.error_code})"
    return message
