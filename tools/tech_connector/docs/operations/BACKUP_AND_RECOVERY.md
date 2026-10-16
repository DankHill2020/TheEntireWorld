# Backup and Recovery

Cloud SQL production uses regional high availability, automated encrypted
backups, point-in-time recovery, deletion protection, retained transaction logs,
and a separate protected backup/export location where required. Backups must
cover the canonical database and deployment/offer/agreement configuration;
secrets and signing keys use their provider recovery processes and must not be
copied into database backups.

Approve an RPO and RTO before launch. A reasonable initial target for the small
service is RPO <= 15 minutes and RTO <= 4 hours, but this is a business decision,
not a guarantee. Monitor backup age and failure. Restrict restore and deletion
permissions, require MFA/two-person approval for destructive operations, and
test provider retention/deletion locks.

At least quarterly, restore a production-like backup into an isolated project,
validate row counts and referential integrity, verify agreement acceptances,
licenses, seats, projects, activations, webhook idempotency, and audit continuity,
then destroy the drill environment under an approved change. Never reconnect a
restored copy to production Auth0, Stripe webhooks, email, or KMS signing until a
controlled cutover is approved.

Evidence includes backup/PITR configuration, the latest successful restore drill,
measured RPO/RTO, exceptions, and approver.

## Current staging evidence

The free-tier Neon staging service passed a snapshot-to-isolated-branch recovery
exercise on 2026-10-01. See
`tech_connector/docs/operations/evidence/STAGING_RESTORE_DRILL_2026-10-01.md`.
That drill proves the schema can be recovered without replacing the active
branch, but it does not satisfy this production control: the free plan's current
six-hour history window, single manual snapshot, and lack of approved production
RPO/RTO remain launch limitations.

