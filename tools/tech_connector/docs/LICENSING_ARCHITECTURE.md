# Tech Connector Licensing Architecture

Tech Connector uses a local-first entitlement client shared by the desktop app,
headless API, and supported DCC/game-engine hosts. The licensing service receives
identity, entitlement, project-registration, and activation metadata only. It
does not receive project assets, scene data, animation, source files, local
paths, prompts, or other creative content.

## Domain and trust boundaries

The public client contains domain models, policy evaluation, replaceable ports,
a stable project UUID manifest, and an Ed25519 public-key verifier. It does not
contain token-signing functions, private signing keys, payment credentials, or
backend administration code.

Production private keys, account records, organization membership, canonical
license terms, payments, accounting, and entitlement issuance belong to a
separate private backend.

Source and product distribution use a hybrid boundary. Tech Connector Core can
be publicly source-available, while the complete first-party Official Tools
Bundle is a separately downloadable, account-gated product. Backend services,
signing, billing, accounting, administration, and enterprise-only components
remain private. GitHub App and OAuth secrets never enter the client or signed
entitlement. See [SOURCE_ACCESS_MODEL.md](SOURCE_ACCESS_MODEL.md).

Authentication sessions are short-lived and separate from signed offline
entitlements. Refresh credentials must be stored through an operating-system
credential-store adapter. A signed entitlement may be cached locally and used
until its offline expiration. `refresh_after` produces a warning; `expires_at`
requires online revalidation.

## Client modules

- `tech_connector/licensing/domain.py`: versioned domain values.
- `tech_connector/licensing/verification.py`: strict Ed25519 verification.
- `tech_connector/licensing/policy.py`: offline, project, version, and device policy.
- `tech_connector/licensing/project_identity.py`: privacy-safe project UUIDs.
- `tech_connector/licensing/local_storage.py`: separate signed-token cache and
  random installation identity without hardware fingerprinting, plus a
  privacy-safe local licensing audit sink.
- `tech_connector/licensing/acceptance.py`: a readable local acceptance-receipt
  file containing the local notice acknowledgement and evidence extracted from
  a verified signed entitlement, never the raw token or account email.
- `tech_connector/licensing/context.py`: runtime signature and project/device
  policy composition.
- `tech_connector/licensing/ports.py`: replaceable auth, network, storage, clock,
  device, and audit boundaries.
- `tech_connector/config/licensing.json`: public endpoints, public keys, issuer,
  audience, and non-economic safety limits.

`ApplicationService` owns the default licensing context. The headless API now
evaluates production-format signed entitlements through that same contract,
including the current project UUID, installation identity, application major
version, offline window, and commercial-use declaration. The desktop activation
UI uses the provider-neutral HTTPS contract in
[LICENSING_BACKEND_API.md](LICENSING_BACKEND_API.md); the private service
implementation remains external.

## Startup gate and acceptance receipts

Desktop startup completes the local license notice and signed-entitlement
preflight before constructing `MainWindow`. This prevents indexers, watchers,
model services, game-engine runtime services, and DCC bridges from starting
without an allowed entitlement. The receipt is written before an entitlement
can authorize host bridges; a receipt-storage failure therefore fails closed.

The readable local copy is stored at
`<application-data>/licensing/license_acceptance_receipts.json`. License
Management displays that exact path and provides **Open Acceptance Receipts**.
It contains agreement version and time plus opaque account, organization,
license, offer, and token IDs needed to identify the verified grant. It does
not contain the raw entitlement, email address, password, refresh credential,
project path, asset name, scene content, or other creative data. This file is
informational and user-visible; the immutable private-backend record and signed
entitlement are the authoritative evidence.

Embedded Maya, Blender, Unreal, Houdini, MotionBuilder, Substance Painter,
Unity, 3ds Max, and GIMP runtimes use a short-lived local bridge capability
because host runtimes cannot be assumed to support the production cryptography
package. The standalone or signed headless client issues this random capability
only after the shared entitlement policy succeeds and the entitlement includes
`dcc_host_access`. It expires after at most 12 hours and never outlives the
signed offline entitlement. DCC execution servers reject a missing, expired,
wrong-host, or incorrect capability before dispatching the official request.
Maya uses a dedicated JSON socket rather than its raw Python `commandPort`, so
authorization occurs before code decoding and main-thread execution.

The bridge-session file contains only its schema, random token, issue/expiration
times, and allowed host IDs. It contains no account, organization, license,
project, asset, scene, prompt, or financial metadata. It is a local process
authorization mechanism, not a replacement license or backend entitlement.

Auxiliary localhost APIs are part of the same trust boundary. In particular,
the Unreal Project Intelligence daemon requires the Unreal bridge capability
before exposing status, project paths, context, scans, capability execution, or
shutdown. A host integration that cannot validate an entitlement-derived local
capability must remain disabled in production until a compatible pairing design
exists.

The default configuration contains no production public keys or endpoints, so
this foundation does not silently activate a network service. A signed token is
cached only after its signature, verified-email state, active-license state,
offline window, and installation binding pass validation.

Production release validation checks every required endpoint as a
credential-free HTTPS URL, rejects query strings and redirects, validates each
Ed25519 public key, and constrains the offline window to no more than 90 days.
Signed claims must also agree across account subject, individual/organization
grantee, project IDs, activation counts, and entitlement dates.

## Grant model and customer segment

Entitlement schema v2 separates two concepts that must not be conflated:

- `license.type` is the economic/legal grant model: `community`, `perpetual`,
  or `custom`.
- `license.market_segment` is the signed customer classification: `community`,
  `indie`, `enterprise`, or `custom`.

The signed `offer_id` identifies the backend-configured offer, while
`classification_version` records the version of the studio-size classification
rules used when the entitlement was issued. Prices, residual rates, thresholds,
seat counts, support, update windows, and capabilities remain explicit signed
claims or referenced versioned terms; the client never derives them from the
market segment.

Optional products use signed capability identifiers rather than inferred tier
names. Core startup remains controlled by the ordinary signed entitlement. The
single complete first-party tools product uses `official_tools_bundle`.
Community, Indie, Enterprise, and Custom offers may include or omit that
capability without creating individual Maya, Blender, rigging, or engine tool
SKUs. Independently configured user project/tool directories are not treated as
the Official Tools Bundle merely because Core can discover them.

| Market segment | Supported grant models | Required boundary |
| --- | --- | --- |
| Community | Community | Commercial projects use registered, versioned project terms. |
| Indie | Community, perpetual, or custom | Named-user seat, signed studio-size band, and classification version are required. |
| Enterprise | Perpetual or custom | Named-user seat, organization grantee, and explicit `enterprise_use` capability are required. |
| Custom | Perpetual or custom | The signed offer, terms, limits, and capabilities control. |

Schema-v1 tokens remain valid during migration. They map Community grants to
the Community segment and other legacy grants to Custom. New production
issuance should use schema v2; a refresh can upgrade an existing v1 entitlement
without changing its accepted agreement or project terms.

For Indie and Enterprise, `limits.seat_count` is the purchased organization
pool and the token's `seat_assignment` binds one seat to the authenticated
`principal.account_id`. Its status must be active. `activation.active_device_count`
is that named user's device count and is checked against
`device_limit_per_seat`, not against the entire organization pool. Organization
administrators may reassign seats through the private account portal, but a
seat is never a shared concurrent-user identity. Non-human build, render, or
service automation requires a separately modeled Custom/Enterprise capability.

## Community project economics

Community commercial use requires project registration. No residual is owed on
the first USD $500,000 of Adjusted Project Profit for a registered project. The
signed project terms specify the measurement period and the rate applicable only
above that threshold. Rates, prices, and studio-size schedules are backend data,
not client constants.

New project terms may use `marginal_brackets`. Each signed bracket contains an
inclusive lower profit boundary, an exclusive upper boundary (or no upper bound
for the final bracket), and a rate in basis points. Brackets must begin at the
no-residual threshold, remain contiguous, cover all higher profit, and never
decrease in rate. A higher bracket applies only to profit inside that bracket;
it does not retroactively reprice lower profit. Legacy terms using one
`flat_above_threshold` rate remain valid.

`licensing/economics.py` provides an integer, half-up-rounded local estimate for
display and testability. It consumes only already signed terms and reported
Adjusted Project Profit. It does not collect financial data or replace the
private backend's authoritative statements, adjustments, invoices, or dispute
workflow.

The Community measurement period is the registered project's lifetime. Signed
terms also identify the receipts basis, eligible-cost standard, related-party
arm's-length standard, owner-labor standard, shared-cost allocation standard,
and excluded cost categories. The client displays these terms but does not
perform authoritative financial accounting.

## Offline behavior

A perpetual license grants continuing rights to the covered major version, but
the cached proof of that right still expires and must periodically be refreshed.
Device binding is deliberately soft: a user can deactivate an old device and
activate a replacement. The signed entitlement carries only a pseudonymous
device hash and activation metadata. The default device adapter generates a
random per-installation UUID; it does not read a MAC address, hostname, disk
serial number, CPU identifier, or other hardware fingerprint.

When offline proof expires, the application should preserve access to local
data and provide a clear reactivation path. Destructive changes, deletion, or
upload of user work are never license-remediation actions.

## Legacy migration

`services/license_entitlement_service.py` retains legacy `tc1` HMAC helpers only
for explicit source-level compatibility tests. Legacy grants are disabled by
default and cannot be enabled in a frozen release. Production clients accept
only asymmetric signed entitlements selected by public key ID.

Release staging rejects private-key PEM markers and common production-secret
artifacts before constructing a distributable package.
