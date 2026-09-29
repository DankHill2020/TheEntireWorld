# Tech Connector Source and Product Access

Status: production target — the public Core boundary and account-gated Official
Tools distribution must be operationally verified before mainstream release.

Tech Connector adapts the useful parts of Epic's account and entitlement model
without copying its repository boundary. Tech Connector Core is intended to be
publicly visible under the source-available license. The complete Official Tools
Bundle is a separate optional product delivered through an account-gated
download or repository. Backend, signing, billing, accounting, administration,
and enterprise-only systems remain private.

Because a public GitHub repository can be cloned anonymously, accepting terms
cannot technically be a prerequisite to viewing or downloading public Core
source. The repository prominently surfaces the controlling license, and the
official application requires verified-account activation and acceptance before
startup. Possessing source does not create an activated or commercial
entitlement, and removing a client check does not create one.

## Product boundary

### Public source-available Core

The Core repository may contain the desktop and headless clients, public local
APIs, bridge protocols, SDK interfaces, examples, local project-directory and
user-owned tool discovery, client-side entitlement verification using public
keys only, documentation, and credential-free build scripts. Client
verification code is not treated as a secret: security derives from asymmetric
signatures and backend authority, not from hiding the verifier.

### Account-gated Official Tools Bundle

The Official Tools Bundle is one product containing all approved first-party
Maya, Blender, Houdini, 3ds Max, MotionBuilder, Substance Painter, Unreal,
utility, plugin, and Qt tooling. It is not divided into separately licensed
individual tool packs.

The bundle can be downloaded independently, installed beside Core, or included
in a combined package. Its root contains `official_tools_bundle.json`. Users add
that root through Tech Connector's existing project/tool directory settings.
Core discovers the manifest locally and exposes its tool roots only when the
signed entitlement includes the `official_tools_bundle` capability. Paths and
file contents are not sent to the licensing service.

Users may always point Core at their own project directories and independently
obtained tools. An absent Tools Bundle entitlement must not disable ordinary
user-owned directories.

### Always private

- entitlement signing keys and token-issuance services;
- account, organization, acceptance, billing, reporting, and accounting data;
- payment credentials, OAuth secrets, GitHub App keys, and webhook secrets;
- internal administrator and support-override tools;
- enterprise integrations not explicitly shipped to that customer; and
- unreleased or security-sensitive deployment infrastructure.

## Access sequence

1. A user may inspect or clone public Core source under the surfaced license.
2. Before Core starts officially, the user creates an account, verifies email,
   accepts the exact agreement, and activates a supported device.
3. The backend stores an immutable acceptance receipt and issues a signed Core
   entitlement with the applicable license, project, version, support, seat,
   device, and offline claims.
4. If an offer includes the Official Tools Bundle, the same entitlement also
   contains `official_tools_bundle`.
5. The portal provides the authorized private download or repository grant for
   the complete bundle.
6. Core validates the cached signature and capability locally. Community
   commercial projects still require project registration and signed terms.

Public Core source and an already downloaded bundle cannot be remotely erased.
Revocation can prevent future official downloads, updates, hosted services, and
valid refreshed entitlements, while the accepted agreement continues to govern
retained copies. Official clients never delete or upload customer work as a
license-remediation action.

## Offer composition

Prices and bundle inclusion remain versioned backend offer configuration, not
client constants. Community, Indie, Enterprise, and Custom offers can include
Core only, Core plus the complete Official Tools Bundle, or negotiated
enterprise capabilities. The client evaluates signed capabilities rather than
inferring products from a customer segment. Perpetual entitlements preserve the
purchased major-version rights. Annual access and support follow signed dates.
Indie and Enterprise seats remain assigned to named human users.

## Operational controls

- Build public Core and the account-gated Tools Bundle from explicit manifests.
- Reject generated state, databases, downloaded dependencies, private keys, and
  production secrets during staging.
- Sign official installers and publish SHA-256 inventories.
- Record agreement versions and content hashes in immutable backend receipts.
- Grant private bundle repositories through a narrowly permissioned GitHub App
  or provide authenticated signed downloads.
- Reconcile eligibility after license, seat, or organization changes without
  collecting local project content.
- Audit grants, removals, administrative overrides, and entitlement changes.

Epic's workflow remains a useful reference for verified accounts, accepted
agreements, GitHub identity linking, and repository invitations. Tech Connector
differs intentionally by making Core publicly source-available and gating the
complete optional Official Tools Bundle rather than every source file.
