# Entitlement Signing-Key Management

Production entitlement tokens use Ed25519. The private key is never generated
in or shipped to a client, written to a repository or environment file, or
included in a build artifact.

The initial no-paid-service deployment may use the backend's software signer
only when all of these controls are satisfied:

- production mode explicitly sets
  `TC_ACKNOWLEDGE_EXPORTABLE_PRODUCTION_SIGNING_KEY=true`;
- the key is generated outside the repository and stored only as a protected
  hosting secret, with a separately encrypted offline recovery copy;
- staging and production use different keys and `kid` values;
- the checked-in client trusts only the reviewed production public key;
- logs, diagnostics, support exports, and backups never contain private key
  material; and
- named custodians record a successful sign/verify and rotation-recovery drill.

This is a controlled free-tier launch floor, not equivalent to non-exportable
custody. The preferred funded deployment uses a non-exportable managed KMS or a
comparably protected signer. Google Cloud KMS supports `EC_SIGN_ED25519` as a
software-protected, non-exportable signing key. It currently does not offer
Ed25519 at its HSM protection level, so do not claim HSM custody for that
reference deployment.

For KMS, use separate staging and production key rings and keys. Grant the
runtime service identity only permission to sign with the active production key
version, and grant public-key read access separately. Require MFA and two-person
approval for key administration. Enable immutable admin/data-access audit logs
and alerts for key disablement, destruction scheduling, IAM changes, and unusual
signing volume. For the free-tier software signer, restrict hosting access with
MFA, minimize service administrators, audit secret changes, and treat any secret
read or unexplained replacement as a key-compromise incident.

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

The software-signer control is not verified merely because the service starts.
Evidence must additionally identify the protected-secret location, recovery-copy
custodians, explicit acknowledgement setting, public-key fingerprint, and the
completed recovery/rotation exercise. Migrate to non-exportable KMS custody when
funding permits without changing the entitlement or client verification schema.
