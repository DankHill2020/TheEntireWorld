# Licensing Launch Blocker Matrix — 2026-10-02

This snapshot separates implemented controls from external production approval.
It is not a production approval and does not override
`tech_connector/config/production_readiness.json`.

| Control | Implemented evidence | What still blocks production |
| --- | --- | --- |
| Backend | Render/Neon staging, Auth0 PKCE portals, migrations, signed entitlement publishing, automated tests, custom-domain TLS | Paid/approved production availability target and complete authenticated production smoke matrix |
| Signing key | Asymmetric Ed25519 adapters, versioned public-key endpoint, client verification | Non-exportable production KMS key, least-privilege identity, rotation and emergency-revocation drill |
| Payments/tax | Versioned offer catalog, Stripe adapter, signature verification, idempotency tests | Merchant/bank setup, approved products, registrations, Stripe Tax configuration, refunds and reconciliation evidence |
| Legal/privacy | Draft license/privacy/operations documents and immutable acceptance-evidence design | Qualified counsel approval, approved document hashes, jurisdictions, refund/consumer/tax/privacy decisions |
| Windows release | Reproducible unsigned RC, checksums, frozen launch smoke | Verified publisher identity, protected Authenticode signing, clean-machine install/upgrade/uninstall evidence |
| Monitoring | Liveness/readiness endpoints, public status surface, hourly credential-free watchdog | Named notification recipients, paging delivery drill, dashboard/retention evidence, incident tabletop |
| Backup | Neon snapshot-to-isolated-branch restore drill | Approved production RPO/RTO, retained encrypted backups/PITR, deletion protection and recurring monitored drills |
| Support | Self-service device replacement, structured case intake/history, owner queue, audit events, staff-light runbook | Real primary and backup contacts, inbound/outbound test, account-recovery drill, only the support promises actually staffed |

## Minimal people model

Mainstream launch does not require a call center. It does require one accountable
primary operator and one emergency backup with MFA-protected access. Routine
device replacement and record lookup are automated. Normal cases can be reviewed
once per business day. Urgent security, access, billing, privacy, outage, and
contractual Enterprise cases remain human responsibilities.

The system must continue to fail closed until each external item has durable
evidence. Cost or staffing pressure is not a reason to label a staging control as
production verified.
