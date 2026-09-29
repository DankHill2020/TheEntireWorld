"""Authentication, activation, project registration, and token-cache orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from .configuration import LicensingConfiguration
from .context import LicensingContext
from .domain import EntitlementClaims, parse_timestamp
from .http_adapters import HttpAuthenticationProvider, HttpLicensingGateway, UrllibJsonTransport
from .local_storage import FileLicensingAuditSink
from .ports import AuditSink, AuthenticationProvider, CredentialStore, LicensingGateway
from .project_identity import ensure_project_identity


class LoginState(str, Enum):
    PENDING = "pending"
    AUTHENTICATED = "authenticated"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(frozen=True)
class LoginChallenge:
    login_attempt_id: str
    verification_uri: str
    verification_uri_complete: str
    user_code: str
    expires_at: datetime
    poll_interval_seconds: int


@dataclass(frozen=True)
class LoginPollResult:
    state: LoginState
    account_id: str = ""
    verified_email: str = ""
    organization_id: str = ""


@dataclass(frozen=True)
class ActivationOutcome:
    claims: EntitlementClaims
    license_id: str
    activation_id: str


class LicensingActivationClient:
    """Coordinates replaceable providers without ever handling project content."""

    REFRESH_CREDENTIAL_KEY = "tech_connector.licensing.refresh_credential"

    def __init__(
        self,
        configuration: LicensingConfiguration,
        *,
        authentication: AuthenticationProvider,
        gateway: LicensingGateway,
        credential_store: CredentialStore,
        licensing_context: LicensingContext,
        audit_sink: AuditSink | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.configuration = configuration
        self.authentication = authentication
        self.gateway = gateway
        self.credential_store = credential_store
        self.licensing_context = licensing_context
        self.audit_sink = audit_sink
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._access_token = ""
        self._access_expires_at: datetime | None = None

    @classmethod
    def from_defaults(
        cls,
        app_data_root: str | Path,
        licensing_context: LicensingContext,
    ) -> "LicensingActivationClient":
        from tech_connector.services.credential_store import default_credential_store

        configuration = licensing_context.configuration
        transport = UrllibJsonTransport()
        return cls(
            configuration,
            authentication=HttpAuthenticationProvider(configuration, transport),
            gateway=HttpLicensingGateway(configuration, transport),
            credential_store=default_credential_store(app_data_root),
            licensing_context=licensing_context,
            audit_sink=FileLicensingAuditSink(Path(app_data_root).expanduser() / "licensing"),
        )

    def begin_login(self, project_root: str | Path = "") -> LoginChallenge:
        project_id = ""
        if str(project_root or "").strip():
            root = Path(project_root).expanduser().resolve()
            if not root.is_dir():
                raise ValueError("The current project directory does not exist.")
            project_id = ensure_project_identity(root).project_id
        payload = self.authentication.begin_login(
            self.licensing_context.device_identity.device_id_hash(),
            project_id,
        )
        attempt_id = _required_text(payload, "login_attempt_id")
        verification_uri = _https_url(payload.get("verification_uri"), "verification_uri")
        complete_value = str(payload.get("verification_uri_complete") or "").strip()
        verification_uri_complete = (
            _https_url(complete_value, "verification_uri_complete")
            if complete_value
            else verification_uri
        )
        expires_at = parse_timestamp(payload.get("expires_at"), field_name="expires_at")
        if expires_at <= self.clock().astimezone(timezone.utc):
            raise ValueError("login challenge is already expired")
        interval = int(payload.get("poll_interval_seconds") or 5)
        if not 2 <= interval <= 30:
            raise ValueError("poll_interval_seconds must be between 2 and 30")
        return LoginChallenge(
            login_attempt_id=attempt_id,
            verification_uri=verification_uri,
            verification_uri_complete=verification_uri_complete,
            user_code=_required_text(payload, "user_code"),
            expires_at=expires_at,
            poll_interval_seconds=interval,
        )

    def poll_login(self, login_attempt_id: str) -> LoginPollResult:
        payload = self.authentication.poll_login(str(login_attempt_id or "").strip())
        try:
            state = LoginState(str(payload.get("status") or "pending"))
        except ValueError as exc:
            raise ValueError("login poll returned an unsupported status") from exc
        if state is not LoginState.AUTHENTICATED:
            return LoginPollResult(state)
        self._accept_session(payload)
        if not bool(payload.get("email_verified", False)):
            self.clear_local_session()
            raise PermissionError("Email verification is required before activation.")
        self._record(
            "login_authenticated",
            account_id=_required_text(payload, "account_id"),
            organization_id=str(payload.get("organization_id") or ""),
        )
        return LoginPollResult(
            state,
            account_id=_required_text(payload, "account_id"),
            verified_email=_required_text(payload, "email"),
            organization_id=str(payload.get("organization_id") or ""),
        )

    def activate_device(self, license_id: str = "") -> ActivationOutcome:
        access_token = self._valid_access_token()
        payload = self.gateway.activate_device(
            access_token,
            str(license_id or "").strip(),
            self.licensing_context.device_identity.device_id_hash(),
        )
        token = str(payload.get("entitlement_token") or "").strip()
        if not token:
            token = self.gateway.refresh_entitlement(access_token)
        claims = self.licensing_context.cache_verified_token(token, now=self.clock())
        self._record(
            "device_activated",
            license_id=claims.license.license_id,
            activation_id=claims.activation.activation_id,
            token_id=claims.token_id,
        )
        return ActivationOutcome(claims, claims.license.license_id, claims.activation.activation_id)

    def refresh_entitlement(self) -> EntitlementClaims:
        token = self.gateway.refresh_entitlement(self._valid_access_token())
        claims = self.licensing_context.cache_verified_token(token, now=self.clock())
        self._record(
            "entitlement_refreshed",
            license_id=claims.license.license_id,
            activation_id=claims.activation.activation_id,
            token_id=claims.token_id,
        )
        return claims

    def register_project(self, project_root: str | Path, license_id: str) -> EntitlementClaims:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("The current project directory does not exist.")
        identity = ensure_project_identity(root)
        self.gateway.register_project(
            self._valid_access_token(),
            identity.project_id,
            str(license_id or "").strip(),
        )
        self._record(
            "project_registered",
            project_id=identity.project_id,
            license_id=str(license_id or "").strip(),
        )
        return self.refresh_entitlement()

    def deactivate_device(self, activation_id: str) -> None:
        self.gateway.deactivate_device(
            self._valid_access_token(),
            _required_value(activation_id, "activation_id"),
        )
        self._record("device_deactivated", activation_id=activation_id)
        # Once the server releases the activation, remove both the signed
        # entitlement and the refresh credential. A deactivated installation
        # must not silently sign itself back in on the next launch.
        self.clear_local_session()
        self.licensing_context.entitlement_store.clear()
        self._clear_bridge_session()

    def logout(self) -> None:
        try:
            if self._access_token:
                try:
                    self.authentication.logout(self._access_token)
                except Exception:
                    # Access sessions are short-lived. Local sign-out must still
                    # succeed when the optional revocation endpoint is offline.
                    pass
        finally:
            self._record("local_sign_out")
            self.clear_local_session()
            self.licensing_context.entitlement_store.clear()
            self._clear_bridge_session()

    def clear_local_session(self) -> None:
        self._access_token = ""
        self._access_expires_at = None
        self.credential_store.delete(self.REFRESH_CREDENTIAL_KEY)

    def _accept_session(self, payload: Mapping[str, Any]) -> None:
        access_token = _required_text(payload, "access_token")
        refresh_credential = _required_text(payload, "refresh_credential")
        expires_at = parse_timestamp(payload.get("access_expires_at"), field_name="access_expires_at")
        if expires_at <= self.clock().astimezone(timezone.utc):
            raise ValueError("authentication session is already expired")
        self.credential_store.save(self.REFRESH_CREDENTIAL_KEY, refresh_credential)
        self._access_token = access_token
        self._access_expires_at = expires_at

    def _valid_access_token(self) -> str:
        now = self.clock().astimezone(timezone.utc)
        if self._access_token and self._access_expires_at and now + timedelta(seconds=30) < self._access_expires_at:
            return self._access_token
        refresh_credential = self.credential_store.load(self.REFRESH_CREDENTIAL_KEY)
        if not refresh_credential:
            raise PermissionError("Sign in is required before activation.")
        payload = self.authentication.refresh_session(refresh_credential)
        self._accept_session(payload)
        return self._access_token

    def _record(self, event: str, **metadata: str) -> None:
        if self.audit_sink is None:
            return
        try:
            self.audit_sink.record(event, metadata)
        except Exception:
            # Local audit is operational evidence, not an entitlement oracle.
            # A read-only disk must not lock a legitimate signed entitlement.
            pass

    def _clear_bridge_session(self) -> None:
        try:
            from tech_connector.bridges.session_authorization import (
                bridge_session_path_for_context,
                clear_bridge_session,
            )

            clear_bridge_session(path=bridge_session_path_for_context(self.licensing_context))
        except Exception:
            pass


def _required_text(payload: Mapping[str, Any], name: str) -> str:
    return _required_value(payload.get(name), name)


def _required_value(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _https_url(value: Any, name: str) -> str:
    text = _required_value(value, name)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{name} must be a credential-free HTTPS URL")
    return text
