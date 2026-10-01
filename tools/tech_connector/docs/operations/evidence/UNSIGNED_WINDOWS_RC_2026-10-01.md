# Unsigned Windows Release Candidate — 2026-10-01

This record contains no credentials. It documents packaging evidence for the
unsigned Tech Connector 6.7 core release candidate and does not approve the
`signed_installers` production-readiness control.

## Build result

- Release runtime: CPython 3.14.7 x64
- Package tier: `core`
- Package mode: `freeze`
- Native build/tests: passed (3 tests)
- Focused release/test suite: passed (110 tests)
- Frozen executable launch smoke: passed
- Frozen smoke behavior: process launched and remained healthy until the smoke
  harness terminated it at the timeout
- Portable archive: `TechConnectorCore-6.7-win64-portable.zip`
- Portable archive size: 292,654,374 bytes
- Portable archive SHA-256:
  `2e64b5dbc4edeb4a7d636acc0346f52af3749c5f0681afd758d4c83fe292406d`
- Frozen launcher SHA-256:
  `c5fd71017885166c7a2ae49e6ec5ffb0857322494178c871afb79ef94d2bcc38`

## Remaining signing requirements

The artifacts are deliberately not distribution-ready. The production release
still requires a verified publisher identity, protected Authenticode signing,
trusted timestamping, post-signature checksums, malware scanning, an installer
assembled from the signed inventory, and clean-machine install/upgrade/uninstall
tests. Rebuild from a clean, pinned commit before signing; do not sign these local
dirty-worktree artifacts.

