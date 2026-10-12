# Licensing Launch Blocker Matrix — updated 2026-10-11

This snapshot separates implemented controls from external production approval.
It is not a production approval and does not override
`tech_connector/config/production_readiness.json`.

| Control | Implemented evidence | What still blocks production |
| --- | --- | --- |
| Backend | Render/Neon staging, Auth0 PKCE portals, migrations, signed entitlement publishing, catalog-bound audited contact-sale fulfillment, custom-domain TLS, passing credential-free live smoke, owner/user portal surfaces, and a credential-safe authenticated smoke command | Deploy the versioned Auth0 post-login Action with the exact owner subject, obtain a fresh owner token, run authenticated smoke with protected short-lived fixtures, approve an availability target, and complete the mutation matrix |
| Offers and agreements | Hash-bound Community source license, Community project terms, Indie terms, Enterprise terms, and a structurally valid five-offer draft catalog; Community studio schedules are selected and frozen per entitlement | Counsel/tax approval, approved immutable document/catalog metadata, final Official Tools inclusion/add-on decision, and deliberate publication |
| Signing key | Asymmetric Ed25519 adapters, versioned public-key endpoint, client verification, explicit fail-closed production software-key acknowledgement, and a KMS-ready provider boundary | For the free-tier launch: protected host secret, encrypted offline recovery copy, separate production key/`kid`, fingerprint review, named custodians, and recovery/rotation drill. Non-exportable KMS remains the preferred funded migration. |
| Payments/tax | Versioned offer catalog, manual or Stripe provider mode, fail-closed disabled checkout/webhook, catalog-derived manual purchase ledger, Stripe signature verification, and idempotency tests | Reconcile real invoices or configure merchant/bank products; approve registrations, tax calculations, refunds, and accounting evidence before representing payment/tax operations as verified |
| Legal/privacy | Draft source license, Community project terms, Indie terms, Enterprise terms, privacy/operations documents, and immutable acceptance-evidence design | Qualified counsel approval, approved document hashes, jurisdictions, refund/consumer/tax/privacy decisions |
| Windows release | Reproducible unsigned RC plus a protected two-phase signing-candidate workflow that verifies frozen/installer signatures, runs Defender, exercises clean-runner install/repair/launch/uninstall, writes checksums/manifests, and creates GitHub attestations for every release artifact without publishing | Verified publisher identity, a real protected signed candidate, upgrade test from the prior supported release, SmartScreen/account-license/offline validation, reviewed evidence, and final production gate approval |
| Monitoring | Liveness/readiness endpoints, public status surface, and a six-hour credential-free watchdog with bounded free-tier cold-start retry, visible retry counts, and seven-day workflow retention | Named notification recipients, failure-delivery drill, dashboard/retention evidence, incident tabletop |
| Backup | Neon snapshot-to-isolated-branch restore drill plus an opt-in daily workflow that validates `pg_dump`, encrypts it with age, uploads only ciphertext and a non-secret manifest, and retains seven days | Configure the protected database URL and public age recipient, keep the age identity offline, prove restore from an encrypted artifact, approve production RPO/RTO, and run recurring monitored drills |
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
