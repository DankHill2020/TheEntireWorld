# Entitlement Signing-Key Management

Production entitlement tokens use Ed25519. The private key must be generated as
a non-exportable key in a managed KMS or comparably protected signer; it is never generated in the client,
written to a repository, environment file, build artifact, or operator laptop.
Google Cloud KMS supports `EC_SIGN_ED25519` as a software-protected,
non-exportable signing key. It currently does not offer Ed25519 at its HSM
protection level, so do not claim HSM custody for this reference deployment.

Use separate staging and production key rings and keys. Grant the runtime service
identity only the permission to sign with the active production key version.
Grant public-key read access separately. Require MFA and two-person approval for
key administration. Enable immutable admin/data-access audit logs and alerts for
key disablement, destruction scheduling, IAM changes, and unusual signing volume.

Asymmetric keys do not support automatic Cloud KMS rotation. Rotation is
additive and operator-controlled: create a new version and `kid`, publish its public key to
clients, deploy issuers using the new `kid`, retain the old public key until every
token it signed has expired, then disable the old signing version. Emergency
revocation follows the same order where possible; a compromised issuer also
requires session revocation, incident response, and a forced online revalidation
decision.

Verification evidence includes resource names, algorithms, IAM policy review,
public-key fingerprints, successful cross-verification by the release client,
rotation drill, audit-log destination, and named key custodians. It must not
include private material.
