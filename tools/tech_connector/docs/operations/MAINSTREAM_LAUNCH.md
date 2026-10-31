# Mainstream Launch Operations

Tech Connector is not production-releasable merely because the application
builds. `tech_connector/config/production_readiness.json` is the machine-readable
release record. The production release gate requires every control below to be
independently verified with an owner, UTC verification time, and durable evidence
reference.

| Control | Required outcome |
| --- | --- |
| Legal and privacy | Qualified counsel approves the controlling license, Community project terms, privacy notice, refund terms, and acceptance evidence design. |
| Production backend | Account, agreement, license, seat, project, activation, and entitlement flows pass staging and production smoke tests. |
| Entitlement key | A non-exportable Ed25519 production key is created in KMS with least-privilege signing access, rotation, and revocation procedures. |
| Payments and tax | Merchant identity, products, prices, webhook, refund policy, tax registrations, tax calculations, and accounting reconciliation are operational. |
| Signed releases | Publisher identity is verified; every shipped executable, DLL, installer, and checksum is produced from a protected release job and verified. |
| Monitoring and incidents | Paging, dashboards, log retention, service-level objectives, escalation, and credential/key compromise procedures are exercised. |
| Backup and restore | Encrypted backups and point-in-time recovery are enabled and a restore drill meets the documented RPO/RTO. |
| Support | Customer contact channels, ownership, triage, response targets, account recovery, machine replacement, refunds, and outage messaging are staffed. |

Never record secrets, personal customer data, private contracts, payment data,
or signing material in the readiness file. Store only references to protected
evidence. A release approver changes the top-level status to
`approved_for_production` only after all controls read `verified`.

For the signed-installer bootstrap only, an approver may use
`approved_for_signing_candidate` with a protected
`signing_candidate_approval_reference` after every other control is verified.
That state authorizes creation of a private signing candidate—not distribution.
The ordinary production gate remains mandatory after the signed-installer
evidence is reviewed and recorded.

The private backend is intentionally outside this public repository. Provider
choices are adapters; the public client depends only on the documented HTTPS and
signed-entitlement contracts.

