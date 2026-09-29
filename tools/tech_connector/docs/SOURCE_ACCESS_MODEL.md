# Tech Connector Source and Product Access

Status: operational repository model — complete public source-available
monorepo with entitlement-controlled official execution and private services.

Tech Connector adapts the useful parts of Epic's account and entitlement model
without requiring source secrecy. `DankHill2020/TheEntireWorld` is the complete
public monorepo: Tech Connector Core and the first-party Official Tools source
are publicly source-available under the controlling license. Repository
visibility is not a runtime entitlement, an unrestricted open-source grant, or
permission for commercial exploitation.

Because a public GitHub repository can be cloned anonymously, accepting terms
cannot technically be a prerequisite to viewing or downloading its source. The
repository therefore surfaces the controlling license prominently, while the
official application requires verified-account activation and acceptance before
startup. Possessing or modifying source does not create an activated or
commercial entitlement, and removing a client check does not create one.

## Product boundary

### Complete public monorepo

The public repository contains the desktop and headless clients, public local
APIs, bridge protocols, SDK interfaces, examples, local project-directory and
user-owned tool discovery, client-side entitlement verification using public
keys only, documentation, credential-free build scripts, and the complete
first-party Official Tools source beneath `tools/`.

Client verification code is not treated as a secret: security derives from
asymmetric signatures, backend authority, immutable acceptance records, and
the license—not from hiding the verifier. Public visibility does not permit
redistribution, sublicensing, resale, hosted access, or commercial use outside
the accepted license or a separate written agreement.

### Entitlement-controlled Official Tools Bundle

The Official Tools Bundle is one product containing all approved first-party
Maya, Blender, Houdini, 3ds Max, MotionBuilder, Substance Painter, Unreal,
utility, plugin, and Qt tooling. It is not divided into separately licensed
individual tool packs.

Its source is included in the public monorepo. Official combined installers,
standalone bundle packages, updates, execution, and support remain governed by
the signed `official_tools_bundle` capability. The bundle can be packaged with
Core, installed beside Core, or added through Tech Connector's existing
project/tool directory settings. The local `official_tools_bundle.json`
manifest identifies the collection without uploading its path or contents.

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

1. A user may inspect or clone the complete public monorepo under the surfaced
   source-available license.
2. Before the official application starts, the user creates an account,
   verifies email, accepts the exact agreement, and activates a supported
   device.
3. The backend stores an immutable acceptance receipt and issues a signed Core
   entitlement with the applicable license, project, version, support, seat,
   device, and offline claims.
4. If an offer includes Official Tools, the entitlement also contains
   `official_tools_bundle`; the client checks that capability before exposing
   official bundle execution.
5. The account portal may provide signed installers, versioned archives,
   updates, or support downloads covered by the entitlement. Those delivery
   channels are conveniences and update boundaries, not claims that the public
   source is confidential.
6. Community commercial projects still require project registration and signed
   project terms.

Public source and already downloaded packages cannot be remotely erased.
Revocation can prevent future official updates, hosted services, support, and
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

- Publish the complete intended source tree while excluding generated state,
  databases, downloaded dependencies, private keys, credentials, private
  services, and production secrets.
- Build Core-only, Official-Tools-only, and combined artifacts from explicit
  manifests, even though their source shares one public repository.
- Sign official installers and publish SHA-256 inventories.
- Record agreement versions and content hashes in immutable backend receipts.
- Use a narrowly permissioned GitHub App only for optional account-linked
  releases, support downloads, or genuinely private enterprise components;
  GitHub App keys never belong in the public client.
- Reconcile entitlement eligibility after license, seat, or organization
  changes without collecting local project content.
- Audit grants, removals, administrative overrides, and entitlement changes.

Epic's workflow remains a useful reference for verified accounts, accepted
agreements, identity linking, and entitlement-backed downloads. Tech Connector
differs intentionally: the complete Core and Official Tools source is public,
while private authority, official execution, services, updates, and commercial
rights remain license-controlled.
