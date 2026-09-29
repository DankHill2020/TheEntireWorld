# Monitoring and Incident Response

Collect structured request IDs, latency, status code, stable error code, endpoint,
deployment revision, database/KMS/provider dependency health, and audit-event
counts. Do not log tokens, credentials, agreement evidence containing network
identifiers, project paths, payment payload bodies, or creative content.

Initial service objectives are configuration and must be approved before launch:
availability for sign-in/activation/refresh, p95 latency, webhook processing
delay, and error budget. Page on sustained 5xx/latency, readiness failure,
database exhaustion, KMS errors, payment webhook backlog, backup failure,
certificate expiry, and suspicious authentication/signing activity. Route pages
to a named primary and secondary; test delivery outside business hours.

Maintain playbooks for service outage, Auth0/Stripe/KMS outage, leaked session
credential, compromised admin, signing-key concern, bad entitlement issuance,
database corruption, privacy incident, and erroneous payment/license revocation.
Each playbook identifies incident commander, containment, customer messaging,
evidence preservation, rollback, recovery, legal notification assessment, and
post-incident review.

Verification requires dashboard and alert links, retention/access policy,
synthetic activation results, a paging drill, and one tabletop incident. The
OpenTelemetry Collector example configuration is not itself production-ready;
pin, harden, authenticate, resource-limit, and monitor any collector deployment.

