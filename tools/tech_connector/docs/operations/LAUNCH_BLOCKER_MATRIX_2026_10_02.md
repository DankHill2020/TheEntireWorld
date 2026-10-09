# Licensing Launch Blocker Matrix — updated 2026-10-03

This snapshot separates implemented controls from external production approval.
It is not a production approval and does not override
`tech_connector/config/production_readiness.json`.

| Control | Implemented evidence | What still blocks production |
| --- | --- | --- |
| Backend | Render/Neon staging, Auth0 PKCE portals, migrations, signed entitlement publishing, catalog-bound audited contact-sale fulfillment, 138 client/release tests, 55 backend tests, custom-domain TLS, passing credential-free live smoke, and a credential-safe read-only authenticated smoke command | Deploy current revision, run authenticated smoke with protected short-lived fixtures, approve a production availability target, and complete the staging mutation matrix |
| Offers and agreements | Hash-bound Community source license, Community project terms, Indie terms, Enterprise terms, and a structurally valid five-offer draft catalog; Community studio schedules are selected and frozen per entitlement | Counsel/tax approval, approved immutable document/catalog metadata, final Official Tools inclusion/add-on decision, and deliberate publication |
| Signing key | Asymmetric Ed25519 adapters, versioned public-key endpoint, client verification | Non-exportable production KMS key, least-privilege identity, rotation and emergency-revocation drill |
| Payments/tax | Versioned offer catalog, manual or Stripe provider mode, fail-closed disabled checkout/webhook, catalog-derived manual purchase ledger, Stripe signature verification, and idempotency tests | Reconcile real invoices or configure merchant/bank products; approve registrations, tax calculations, refunds, and accounting evidence before representing payment/tax operations as verified |
| Legal/privacy | Draft source license, Community project terms, Indie terms, Enterprise terms, privacy/operations documents, and immutable acceptance-evidence design | Qualified counsel approval, approved document hashes, jurisdictions, refund/consumer/tax/privacy decisions |
| Windows release | Reproducible unsigned RC plus a protected two-phase signing-candidate workflow that verifies frozen/installer signatures, runs Defender, exercises clean-runner install/repair/launch/uninstall, and writes checksums/provenance without publishing | Verified publisher identity, a real protected signed candidate, upgrade test from the prior supported release, SmartScreen/account-license/offline validation, reviewed evidence, and final production gate approval |
| Monitoring | Liveness/readiness endpoints, public status surface, and an hourly credential-free watchdog with bounded free-tier cold-start retry and visible retry counts | Named notification recipients, paging delivery drill, dashboard/retention evidence, incident tabletop |
| Backup | Neon snapshot-to-isolated-branch restore drill | Approved production RPO/RTO, retained encrypted backups/PITR, deletion protection and recurring monitored drills |
| Support | Self-service device replacement, structured case intake/history, owner queue, owner views for licenses/organizations/seats/projects/acceptances/devices/audits, catalog-bound paid-license issuance, capacity-checked named-user assignment/revocation with device deactivation, audit events, staff-light runbook | Real primary and backup contacts, inbound/outbound test, account-recovery drill, only the support promises actually staffed |

## Minimal people model

Mainstream launch does not require a call center. It does require one accountable
primary operator and one emergency backup with MFA-protected access. Routine
device replacement and record lookup are automated. Normal cases can be reviewed
once per business day. Urgent security, access, billing, privacy, outage, and
contractual Enterprise cases remain human responsibilities.

The system must continue to fail closed until each external item has durable
evidence. Cost or staffing pressure is not a reason to label a staging control as
production verified.
