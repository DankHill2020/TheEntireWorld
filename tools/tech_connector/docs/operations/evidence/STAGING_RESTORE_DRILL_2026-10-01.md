# Staging Restore Drill — 2026-10-01

This record contains no credentials or customer data. It documents a recovery
exercise against the free-tier Neon staging database used by the Tech Connector
licensing service. It is staging evidence only and does not approve the
`backups_and_restore` production-readiness control.

## Result

- Provider/project: Neon, `Tech Connector`
- Source branch: `production` (staging service data despite the provider-side
  branch name)
- Snapshot type: manual, retained without an expiry date
- Snapshot created: 2026-10-01 16:38:34 UTC
- Restore method: multi-step restore to an isolated branch
- Restored branch ID: `br-round-bar-b53qm1em`
- Restore completed: 2026-10-01 16:39:02 UTC
- Provider-reported restore duration: 0.27 seconds
- Source branch changed: no
- Restored database verified: `tech_connector`
- Restored schema verified: `public`
- Restored tables observed: 17

The restored schema included `accounts`, `organizations`, `memberships`,
`agreements`, `acceptances`, `licenses`, `project_registrations`,
`device_activations`, `seat_assignments`, `offers`, `purchases`,
`financial_reports`, `webhook_events`, `session_credentials`, `login_attempts`,
`audit_events`, and `alembic_version`.

## Remaining production requirements

The free plan currently exposes a six-hour point-in-time history window and one
manual snapshot. Before mainstream production launch, move the canonical service
to an approved production data plan and verify encrypted automated backups,
retention, deletion protection, access controls, monitoring, and an isolated
restore against the approved production RPO/RTO. The drill branch is intentionally
not connected to Auth0, payment webhooks, email, or an entitlement signing key.

