# Licensing Backend Integration Contract

The backend is intentionally not implemented in the public repository. Client
code depends on the interfaces in `tech_connector/licensing/ports.py`.

## Required private records

- accounts and verified email state;
- organizations and role-bearing memberships;
- individual or organization licenses;
- versioned offer definitions and studio-size classification rules;
- immutable/versioned license and project terms;
- project registrations keyed by Tech Connector project UUID;
- named-user seat assignments and per-user device activations;
- agreement acceptances and entitlement issuance audit events;
- linked source-provider identities and version-scoped repository grants;
- later, project financial reports, residual calculations, invoices, and payments.

Each authoritative agreement acceptance is an immutable record, separate from
the entitlement token. At minimum it records a unique acceptance ID, account
ID, optional organization and project IDs, license/offer ID, exact agreement
and project-terms versions, a hash of the rendered legal document, UTC
acceptance time, acceptance method, and the superseded acceptance (if any).
Corrections append records; they never rewrite history. Any network/security
evidence beyond this minimum needs an approved retention and privacy basis.

The private account portal must let a user view and download their acceptance
history. Organization license administrators may view receipts made for their
organization, subject to role checks. Internal access and exports must be
least-privilege and audited. The local client receipt is a readable convenience
copy; the backend acceptance record and its representation in a verified signed
entitlement remain authoritative.

## Entitlement-controlled Official Tools access

Official Tools execution and official release/update access follow
[SOURCE_ACCESS_MODEL.md](SOURCE_ACCESS_MODEL.md). The bundle source is publicly
visible, but agreement acceptance must be authoritative and committed before a
signed execution entitlement or protected release download is issued. The
private delivery broker consumes account, organization, license, named-seat,
accepted-agreement, and covered-major-version records; it never trusts a
customer-selected tier or a desktop-client assertion.

The release-delivery broker is a private backend adapter. GitHub OAuth secrets,
GitHub App keys, installation tokens, organization IDs, repository IDs, team
IDs, and administrative APIs do not belong in the desktop client or public
configuration. Grants are idempotent, least-privilege, version-scoped,
reconciled against actual provider membership, and fully audited.

The public provider-neutral grant contract is
`docs/schemas/source_access_grant.v1.schema.json`; private database tables may
be normalized differently but must preserve its required relationships.

Repository visibility or authenticated-download access is not the entitlement
itself. A linked identity may download protected artifacts only for versions
covered by its grant, while running official Tech Connector clients still
requires the separately signed offline entitlement and
`official_tools_bundle` capability. Public Core and Official Tools source do
not require a private repository invitation. Revoking a delivery grant cannot
recall an existing clone or download, so the accepted license continues to
govern retained copies and modifications.

## Minimum client-to-server metadata

Permitted metadata includes account and organization IDs, license ID, project
UUID, commercial-use declaration, accepted terms version, pseudonymous device
ID, application version, activation timestamps, and audit event type.

The default client device ID represents a random installation, not hardware.
The activation service should allow a user or organization administrator to
deactivate that installation and activate a replacement within the signed limit.

The client must not upload project paths, asset names, source code, scenes,
animation, images, audio, prompts, production files, or project financial data
outside an explicit reporting workflow initiated by an authorized user.

## Entitlement issuance

The service signs `TC-ENT` compact tokens with Ed25519. Tokens contain `kid` for
public-key rotation and the standard issuer, audience, subject, token ID, issued,
not-before, and expiration claims. The payload schema is versioned.

New entitlements use payload schema v2. The signed `license` object includes:

- `type`: `community`, `perpetual`, or `custom`;
- `market_segment`: `community`, `indie`, `enterprise`, or `custom`;
- `offer_id`: the immutable/configuration-driven offer identifier;
- `classification_version`: the classification rules used at issuance;
- agreement version and acceptance time; and
- individual or organization grantee identity.

Community commercial and Indie success-based offers use the same registered
project-terms mechanism; their exact rate can differ because the rate is signed
terms data. Indie perpetual offers carry covered major versions instead of
silently acquiring success-based terms. Enterprise issuance requires an active
organization membership, organization grantee, and explicit `enterprise_use`
capability. A segment name alone never grants a feature or determines a price.

Indie and Enterprise schema-v2 tokens also require `seat_assignment` with an
immutable assignment ID, the authenticated account ID, active/revoked status,
and assignment timestamp. The account ID must match the token principal. The
backend enforces the purchased organization seat pool and treats
`activation.active_device_count` as the assigned user's active-device count.
Human seats cannot be shared accounts. Organization administrators can revoke
or reassign seats under a configurable anti-sharing/cooldown policy, with
audited support override for legitimate staff changes. Contractors receive
their own verified-account assignment. CI, render farms, and unattended service
workers require separately negotiated non-human entitlements and capabilities.

Schema-v1 tokens are accepted only as a compatibility path. The backend should
issue schema v2 on the next successful refresh while preserving the applicable
agreement, project registration, and immutable terms version.

Community project terms include:

- calculation basis (`adjusted_project_profit`);
- currency;
- profit threshold in minor currency units;
- threshold measurement period;
- project-receipts basis;
- eligible-cost and documentation standard;
- owner/founder labor standard and any pre-agreed cap;
- related-party arm's-length standard;
- shared-cost allocation standard;
- excluded cost categories;
- residual calculation method and either one rate or a contiguous marginal
  bracket schedule in basis points;
- reporting period and immutable terms ID/version.

The currently intended Community threshold is USD $500,000 of Adjusted Project
Profit per registered project, measured cumulatively over that project's
lifetime. Only profit above the threshold may be included in the residual
calculation. Eligible costs must be actual, documented, ordinary, necessary,
reasonable, and directly attributable. Related-party charges are limited to the
lower of actual cost or an arm's-length fair-market amount. Each marginal rate
applies only within its signed bracket and does not retroactively apply to lower
profit. The exact schedule, deductions, exclusions, allocation rules, and reporting requirements are
selected by backend terms and presented before acceptance.

Reporting and any compliance review are limited to relevant financial records.
The backend must not request or ingest project assets or creative source data as
evidence of project costs.

## Future adapters

Authentication, email verification, payments, tax/invoicing, accounting,
transactional email, and storage providers must remain behind private backend
interfaces. Changing one provider must not change the entitlement token schema
or local policy API.
