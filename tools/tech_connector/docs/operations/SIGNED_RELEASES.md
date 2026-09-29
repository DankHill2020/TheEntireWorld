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

