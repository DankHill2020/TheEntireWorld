"""Runtime composition for signed entitlement verification and local policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .configuration import LicensingConfiguration, load_licensing_configuration
from .domain import EntitlementClaims, PolicyContext, PolicyDecision
from .local_storage import FileEntitlementStore, InstallationDeviceIdentity
from .policy import evaluate_entitlement
from .ports import DeviceIdentityProvider, EntitlementStore
from .project_identity import load_project_identity


@dataclass(frozen=True)
class LicensingEvaluation:
    claims: EntitlementClaims | None
    decision: PolicyDecision


class LicensingContext:
    """Connect public configuration, local adapters, signature checks, and policy."""

    def __init__(
        self,
        configuration: LicensingConfiguration,
        *,
        entitlement_store: EntitlementStore,
        device_identity: DeviceIdentityProvider,
    ) -> None:
        self.configuration = configuration
        self.entitlement_store = entitlement_store
        self.device_identity = device_identity
        self.verifier = configuration.build_verifier()

    @classmethod
    def from_defaults(cls, app_data_root: str | Path) -> "LicensingContext":
        root = Path(app_data_root).expanduser() / "licensing"
        return cls(
            load_licensing_configuration(),
            entitlement_store=FileEntitlementStore(root),
            device_identity=InstallationDeviceIdentity(root),
        )

    def token(self, explicit_token: str = "") -> str:
        return str(explicit_token or self.entitlement_store.load_token() or "").strip()

    def cache_verified_token(self, token: str, *, now: datetime | None = None) -> EntitlementClaims:
        """Cache cryptographically valid proof bound to this installation.

        Project authorization is deliberately evaluated at use time because one
        token can carry multiple registered projects.
        """
        current = now or datetime.now(timezone.utc)
        claims = self.verifier.verify(token, now=current)
        if claims.license.status != "active":
            raise ValueError("cannot cache an inactive license")
        if not claims.principal.email_verified:
            raise ValueError("cannot cache an entitlement for an unverified email")
        if claims.activation.device_id_hash != self.device_identity.device_id_hash():
            raise ValueError("entitlement is assigned to a different installation")
        if current.astimezone(timezone.utc) >= claims.offline.expires_at:
            raise ValueError("cannot cache an expired offline entitlement")
        self.entitlement_store.save_token(token)
        return claims

    def evaluate(
        self,
        *,
        token: str = "",
        project_root: str | Path | None = None,
        product: str,
        app_major_version: str,
        commercial_use: bool,
        now: datetime | None = None,
    ) -> LicensingEvaluation:
        current = now or datetime.now(timezone.utc)
        token_value = self.token(token)
        if not token_value:
            return LicensingEvaluation(
                None,
                PolicyDecision(
                    False,
                    "missing_entitlement",
                    "No signed entitlement is cached for this installation.",
                ),
            )
        try:
            claims = self.verifier.verify(token_value, now=current)
        except Exception as exc:
            return LicensingEvaluation(
                None,
                PolicyDecision(False, "invalid_entitlement", str(exc)),
            )

        project_id = ""
        if project_root:
            try:
                identity = load_project_identity(project_root)
                project_id = identity.project_id if identity is not None else ""
            except Exception as exc:
                return LicensingEvaluation(
                    claims,
                    PolicyDecision(False, "invalid_project_identity", str(exc)),
                )
        decision = evaluate_entitlement(
            claims,
            PolicyContext(
                now=current,
                product=product,
                app_major_version=str(app_major_version),
                project_id=project_id,
                commercial_use=bool(commercial_use),
                device_id_hash=self.device_identity.device_id_hash(),
            ),
        )
        return LicensingEvaluation(claims, decision)
