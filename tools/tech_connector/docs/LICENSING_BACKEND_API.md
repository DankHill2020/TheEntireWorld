# Private Licensing Backend API Contract

This document defines the public client's provider-neutral HTTPS contract. The
backend implementation, account database, payment webhooks, administrative
tools, private signing keys, and entitlement-issuance policy belong in a
separate private repository.

Every configured endpoint is an exact credential-free HTTPS URL. The client
does not infer provider-specific URL paths. Requests and responses are JSON
objects with `schema_version: 1`. Authentication access tokens are short-lived
Bearer tokens held in memory. Rotating refresh credentials are protected by the
operating-system credential store.

## Permitted metadata

The service may receive:

- account, verified-email, organization, role, and studio-size identifiers;
- license, agreement-version, support, version, named-user seat assignment, and
  per-user device-limit data;
- a random project UUID and its accepted project-terms version;
- a one-way hash of a random installation UUID;
- activation/deactivation identifiers and minimal audit timestamps;
- financial reports entered through the account portal for registered projects.

It must not receive local project paths, project names unless the user enters
one voluntarily in the portal, assets, scenes, source files, prompts, animation,
renders, model inputs/outputs, or other creative content.

## Login start

`POST endpoints.login_start`

```json
{
  "schema_version": 1,
  "product": "tech_connector",
  "device_id_hash": "sha256:...",
  "project_id": "prj_optional"
}
```

`project_id` is optional. When present, the browser flow should show the exact
Community project terms, threshold, lifetime measurement rule, studio-size
rate, and reporting schedule before acceptance. The response is:

```json
{
  "login_attempt_id": "login_...",
  "verification_uri": "https://accounts.example/device",
  "verification_uri_complete": "https://accounts.example/device?code=...",
  "user_code": "ABCD-EFGH",
  "expires_at": "2026-08-24T20:00:00Z",
  "poll_interval_seconds": 5
}
```

The browser flow owns account creation, established-provider authentication,
email verification, organization selection, agreement acceptance, recovery,
and bot/abuse controls. Tech Connector never collects a password.

## Account portal release and support access

The complete Core and Official Tools source is public. Account linking is
therefore not an access boundary for that source. It remains a browser/account-
portal workflow for signed installers, versioned release archives, updates,
support downloads, and genuinely private enterprise components—not a desktop
licensing endpoint and not part of `licensing.json`. After verified-account
authentication, the portal may expose provider-neutral operations equivalent
to:

- begin GitHub identity linking with a one-time state-bound OAuth transaction;
- complete the callback and bind the stable provider-user ID;
- list eligible release versions and existing delivery grants;
- request a protected download or enterprise invitation only after the
  controlling agreement is accepted;
- show invitation/grant/reconciliation status; and
- unlink or replace an identity using step-up authentication.

The private backend—not the browser and not the desktop client—maps a valid
license and named seat to protected delivery channels or enterprise
repositories. A narrowly scoped provider app may perform invitations and
removals. It stores no installation token in the account session, entitlement
token, downloadable artifact, or client configuration. Callback state,
webhooks, invitation requests, and membership changes are single-use or
idempotent as appropriate and are audited.

Perpetual version coverage for official binaries, updates, support, and private
enterprise components must use separately generated archives or protected
delivery records. Public source history is not the perpetual entitlement
boundary. See
[SOURCE_ACCESS_MODEL.md](SOURCE_ACCESS_MODEL.md).

## Login poll

`POST endpoints.login_poll`

```json
{"schema_version": 1, "login_attempt_id": "login_..."}
```

Pending, denied, or expired responses contain only `status`. An authenticated
response contains:

```json
{
  "status": "authenticated",
  "account_id": "acct_...",
  "email": "verified@example.com",
  "email_verified": true,
  "organization_id": "org_optional",
  "access_token": "short-lived opaque token",
  "access_expires_at": "2026-08-24T19:15:00Z",
  "refresh_credential": "rotating opaque credential"
}
```

Login attempts must be single-use, rate-limited, short-lived, and bound to the
installation hash supplied at login start.

## Session refresh and logout

- `POST endpoints.session_refresh` accepts the rotating `refresh_credential`
  and returns a new access token, expiration, and replacement refresh credential.
- `POST endpoints.logout` uses the Bearer token and revokes the server session.
  This endpoint may be omitted; local sign-out still removes cached credentials.

Refresh-token reuse after rotation should revoke the credential family and log
a security event.

## Device activation

`POST endpoints.activation`, authenticated:

```json
{
  "schema_version": 1,
  "license_id": "lic_optional_when_account_has_one_default",
  "device_id_hash": "sha256:..."
}
```

Activation must be idempotent for the account/license/installation tuple. It
enforces verified email, organization membership, active named-user seat,
per-user device limits, accepted agreement versions, and license status. Indie
and Enterprise activation cannot borrow unused device capacity from other seats.
Success returns an
`entitlement_token`. If an account has multiple eligible licenses and no ID was
provided, return a stable `license_selection_required` error rather than making
an arbitrary selection.

## Entitlement refresh

`POST endpoints.entitlement`, authenticated, accepts product and schema version
and returns `entitlement_token`. The private service signs the token with an
Ed25519 key held in a KMS/HSM or comparably protected signing service. The
public client contains only public keys selected through `kid`.

The token claims are defined in [LICENSING_ARCHITECTURE.md](LICENSING_ARCHITECTURE.md).
Economic terms are versioned backend data. Existing project terms must never be
silently replaced retroactively.

Newly issued entitlement tokens use entitlement payload schema v2 and include
the separate signed grant model (`community`, `perpetual`, or `custom`) and
market segment (`community`, `indie`, `enterprise`, or `custom`), plus
`offer_id` and `classification_version`. The surrounding HTTPS request/response
envelopes remain schema v1. Clients retain entitlement-schema-v1 compatibility
for migration, but refresh should return v2. Prices, rates, limits, support, and
capabilities must be selected from versioned backend configuration and copied
into signed claims; they must not be inferred in the client from the segment.

Capabilities are explicit signed claims. `official_api_access` authorizes the
headless API; `dcc_host_access` separately authorizes creation of short-lived
local Maya, Blender, Unreal, Houdini, MotionBuilder, Substance Painter, Unity,
3ds Max, and GIMP bridge sessions. A client must not infer either capability
solely from the license type.
`enterprise_use` is additionally required for an Enterprise market segment.

## Project registration

`POST endpoints.project_registration`, authenticated:

```json
{
  "schema_version": 1,
  "project_id": "prj_...",
  "license_id": "lic_..."
}
```

Registration is idempotent. For Community commercial use, it succeeds only
after the account portal records acceptance of the exact project terms. Those
terms include the first USD $500,000 of lifetime Adjusted Project Profit with no
residual, plus the applicable configuration-driven studio-size rate above the
threshold. Registration never uploads project content.

## Deactivation

`POST endpoints.deactivation`, authenticated:

```json
{"schema_version": 1, "activation_id": "act_..."}
```

Deactivation is idempotent, logs the event, releases the activation allowance,
and causes subsequent entitlement refreshes for that activation to fail. The
client removes its cached entitlement only after successful server confirmation.
The account portal must also list active installations and allow a verified
license administrator to deactivate a lost or unavailable machine before
activating its replacement.

## Errors, logging, and operations

Use stable error codes with safe user-facing messages. Expected codes include
`authorization_pending`, `email_verification_required`,
`license_selection_required`, `project_terms_acceptance_required`,
`device_limit_exceeded`, `license_inactive`, `rate_limited`, and
`temporarily_unavailable`. HTTP 429 and 5xx responses are retryable; other 4xx
responses are not automatically retried.

Return errors using this versioned shape:

```json
{
  "error": {
    "code": "project_terms_acceptance_required",
    "message": "Accept the registered project terms in your account.",
    "action_url": "https://accounts.example.com/projects/prj_.../terms"
  }
}
```

`message` must be safe to display directly and must never contain credentials,
tokens, internal traces, or creative metadata. `action_url` is optional and must
use HTTPS. Send `Retry-After` in seconds for rate limits or temporary outages.
Licensing API endpoints must not redirect requests; clients intentionally reject
redirects so bearer tokens and activation metadata cannot be forwarded to a
different origin.

Audit account verification, agreement acceptance, organization changes,
license issuance, project registration, activation/deactivation, entitlement
issuance/revocation, payment-webhook changes, and administrative overrides.
Never log access tokens, refresh credentials, private keys, or creative data.
The desktop client also keeps a small local audit trail containing only event
timestamps and opaque account, organization, license, project, activation, and
entitlement IDs. The backend audit remains authoritative.

Payment and accounting providers update private canonical records through
verified idempotent webhooks. They never issue client entitlements directly.
