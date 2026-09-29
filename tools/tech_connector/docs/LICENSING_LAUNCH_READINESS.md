# Tech Connector Licensing Launch Readiness

Status date: 2026-09-28

This checklist covers the licensing and source-distribution launch boundary.
It does not claim that every Tech Connector product feature is production-ready.

## P0 completed in the public repository

- Source-available notices, custom license terms, redistribution restrictions,
  and the Community USD $500,000 lifetime Adjusted Project Profit threshold are
  surfaced and protected by release checks.
- Production clients accept only Ed25519-signed, versioned entitlements. Private
  signing keys and backend issuance code are excluded from the repository.
- Desktop and headless startup paths fail closed without a valid entitlement;
  source-development bypasses cannot unlock a frozen build.
- Desktop terms and entitlement preflight now completes before the main window
  constructs or schedules indexers, watchers, DCC services, or model runtimes.
  Candidate projects are authorized before they become active, and cancelling
  project registration preserves the prior workspace.
- Browser authentication, verified email, protected refresh credentials,
  activation, deactivation, offline caching, project authorization, version
  entitlement, device limits, and Community signed terms are wired through
  replaceable interfaces.
- Production configuration validation checks required HTTPS endpoints, rejects
  embedded credentials/query strings/redirects, validates public keys, and caps
  configured offline access at 90 days.
- Staging scans for secrets and private keys. The staged payload is checked
  against its SHA-256 inventory before import. Windows release artifacts receive
  SHA-256 sidecars and production installers require Authenticode signing.
- Local audit events contain only timestamps and opaque IDs. Tokens, email
  addresses, project paths, assets, and creative metadata are excluded.
- The local license notice stores no typed legal name, email address, or token
  presence. Authoritative agreement acceptance belongs to the verified-account
  service and the signed entitlement. Legacy local acceptance records are
  migrated to remove those fields.
- Each successful desktop preflight writes a human-readable, privacy-minimal
  acceptance receipt before host authorization. License Management shows its
  exact path and opens it for the user; a receipt-write failure prevents the
  licensed application shell from starting.
- The product-access model now separates public source-available Core from the
  single account-gated Official Tools Bundle, while retaining verified account
  acceptance, least-privilege grants, reconciliation, revocation limits, and
  provider-secret isolation.
- A packaged privacy/data-handling draft now documents the implemented data
  boundary, and the production gate fails until counsel marks it approved.

## P0 external launch gates

These cannot be completed safely in the public client repository:

- Obtain counsel approval for `LICENSE.md`, `PRIVACY.md`, agreement acceptance, the Adjusted
  Project Profit definition, eligible-cost exclusions, audit/reporting language,
  governing law, remedies, privacy notice, and tax treatment.
- Deploy the private account, organization, agreement, project, activation, and
  entitlement service described in `LICENSING_BACKEND_API.md`.
- Split public Core from the complete Official Tools Bundle. Deploy the private
  GitHub App or authenticated-download broker, require recorded agreement
  acceptance before bundle access, and validate Community, annual,
  perpetual-major, Enterprise, and Custom grants end to end.
- After independent verification, update `config/source_access.json` with the
  operational status, UTC verification time, and internal review reference.
  The production release gate intentionally fails while Official Tools remain
  in the public Core repository or the bundle broker is unverified.
- Execute and retain evidence for every phase in
  `SOURCE_REPOSITORY_MIGRATION.md`; use clean-history public Core and private
  Official Tools repositories rather than deleting paths from the old branch.
- Store the production Ed25519 signing key in KMS/HSM, configure rotation and
  revocation procedures, and publish only approved public verification keys.
- Configure real HTTPS endpoints and run `release_gate.py --production`.
- Provision the Authenticode certificate and complete a clean-machine signed
  installer/uninstaller test on supported Windows versions.
- Keep the repository-root README, LICENSE, and GitHub workflow checks installed
  in the public landing repository, without complete protected source or
  private build/security components.
- Establish monitoring, backups, rate limits, abuse controls, incident response,
  support escalation, and an emergency entitlement-key rotation drill.

No public production release should be published until every external P0 item
has an accountable owner and recorded completion evidence.

## P1 completed in the public repository

- Concurrent DCC applications converge on one atomically created project UUID
  and never overwrite an unknown future project-manifest schema.
- Safe backend error codes, user messages, HTTPS action links, `Retry-After`, and
  retryable outage behavior are preserved without exposing response internals.
- Login polling recovers from rate limits and temporary server failures while
  the browser challenge remains valid.
- The desktop license manager displays signed organization, version, support,
  seat/device, offline, project-threshold, rate, and reporting terms.
- Entitlement schema v2 separates Community/Indie/Enterprise/Custom customer
  segments from Community/perpetual/custom grant models. Schema-v1 tokens remain
  compatible; Enterprise is organization-bound with an explicit capability,
  while Indie economics remain configuration-driven signed terms.
- Indie and Enterprise v2 entitlements require an active named-user seat bound
  to the verified account. Device limits apply per assigned user rather than
  allowing one user to consume the organization-wide seat pool.
- Community users can declare genuinely noncommercial project use without
  registering that project. Commercial is the conservative default, and
  commercial Community projects still fail closed until registered.
- Standalone and signed headless clients issue a metadata-free, host-scoped DCC
  capability only when the entitlement includes `dcc_host_access`. Official
  Maya, Blender, Unreal, Houdini, MotionBuilder, Substance Painter, Unity,
  3ds Max, and GIMP clients carry it and their embedded execution handlers
  reject unauthorized requests before code or typed commands are dispatched.
- The Unreal Project Intelligence daemon requires the same host capability for
  status, project context, scans, execution, and shutdown. Legacy Maya setup and
  HIK UI paths no longer open separate unauthenticated Python ports.
- Maya bridge bootstrap version 3 replaces the raw Python `commandPort` with a
  bounded authenticated JSON socket and dispatches only validated requests onto
  Maya's main thread. Existing managed bootstrap blocks upgrade in place.
- Photoshop's UXP prototype fails closed in ordinary and frozen operation. Its
  client and installer require both `TECH_CONNECTOR_DEV_LICENSE_BYPASS=1` and
  `TECH_CONNECTOR_ENABLE_EXPERIMENTAL_PHOTOSHOP_BRIDGE=1` in a source checkout.
- Local verifier preflight covers overlapping Ed25519 public keys, removal of
  the retired key, exact 30/60/90-day offline expiration boundaries, and
  rejection of offline windows above the configured maximum.

## P1 integration backlog

- Build and test the self-service account portal: organization roles, license
  selection, agreement history, GitHub identity/source grants, project terms,
  and lost-device deactivation.
- Add sandbox payment/webhook adapters and idempotency/replay test vectors in the
  private backend; payment systems must never sign entitlements directly.
- Exercise the checked-in public-key overlap/removal and 30/60/90-day offline
  vectors, plus entitlement revocation and device replacement, against a
  deployed staging service.
- Add an explicit financial-reporting workflow that collects only authorized
  accounting fields and documents—not project assets or creative source data.
- Run accessibility, localization, proxy/firewall, TLS interception, clock-skew,
  and account-recovery UX testing on the activation dialogs.
- Keep the Photoshop UXP bridge out of the official licensed endpoint set until
  it has an entitlement-derived pairing design compatible with the UXP file
  sandbox. Do not substitute a perpetual hardcoded plugin secret.
- Extend the same host-session protocol to every future execution bridge before
  treating it as an official licensed endpoint.
