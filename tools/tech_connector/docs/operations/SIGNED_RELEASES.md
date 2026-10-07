# Signed Windows Releases

Production Windows artifacts require a publicly trusted publisher identity using
Azure Artifact Signing (formerly Trusted Signing) or an equivalently protected
Authenticode certificate. Publisher verification and the signing account belong
to The Entire World, LLC; they cannot be manufactured in source code.

The release job must use an approved protected environment, a pinned source
commit, locked dependencies, Python 3.14 x64, the production release gate, and a
clean build. Sign every shipped `.exe` and `.dll` before packaging, build the
installer from that frozen signed inventory, then sign the installer. Timestamp
all signatures, verify `Get-AuthenticodeSignature` is `Valid`, generate SHA-256
sidecars after final signing, malware-scan the artifacts, and retain the build
manifest, provenance, hashes, and job URL.

Never expose a PFX, certificate password, or provider credential to pull-request
jobs. Use short-lived workload identity/OIDC and a protected GitHub Environment
with required reviewers. A release is rejected if any binary is unsigned,
modified after signing, signed by the wrong subject, untrusted, or missing its
checksum.

Test install, upgrade, repair, uninstall, SmartScreen reputation behavior, clean
machine startup, mandatory account/license acceptance, offline restart, and
deactivation/replacement on every release candidate.

The first signed artifact cannot require its own completed evidence as a
prerequisite. Use the protected `approved_for_signing_candidate` readiness state
and `signing_candidate_approval_reference` only after every control except
`signed_installers` is verified. The signing workflow may then produce a private
candidate, verify signatures, scan it, exercise install/repair/launch/uninstall,
and write provenance. It is not a public production release. After independent
review and upgrade testing from the prior supported release, attach the durable
candidate evidence to `signed_installers`, mark that control verified, change
the top-level readiness state to `approved_for_production`, and run the ordinary
production gate again before publication.

## Current unsigned evidence

The core 6.7 Windows freeze build and executable launch smoke passed on CPython
3.14.7 on 2026-10-01. See
`tech_connector/docs/operations/evidence/UNSIGNED_WINDOWS_RC_2026-10-01.md`.
This validates the packaging path but cannot satisfy the signed-release control
until publisher verification, protected signing, and clean-machine installer
tests are complete.

