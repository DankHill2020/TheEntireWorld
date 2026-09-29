# Core and Official Tools Repository Migration

This runbook converts the current mixed public repository into two intentional
products without pretending previously public files can be made secret again.

## Target repositories

1. **Tech Connector Core — public, source-available.** Built from the canonical
   `core` package manifest with its own clean history.
2. **Official Tools Bundle — private/account-gated.** Built from the canonical
   `official-tools` manifest and granted only to accounts whose signed
   entitlement includes `official_tools_bundle`.
3. **Private services — separate and never exported.** Authentication,
   entitlement issuance, signing, billing, accounting, administration,
   production deployment, and enterprise-only source.

A `combined` build may package Core and the bundle together for an authorized
customer. It is not an anonymous repository tier.

## Existing-public-history limitation

The current `DankHill2020/TheEntireWorld` repository is public and already has
older Core and tools code in its Git history. Making it private later, deleting
paths, or rewriting history cannot recall clones, forks, caches, or archives.
The controlling source-available license continues to govern those copies, but
the first genuinely account-gated Tools Bundle version must begin from a new
private release boundary. Do not describe previously published versions as
confidential or technically undisclosed.

## Phase 1 — stabilize the local source

1. Preserve the current depot and record the exact local commit.
2. Review and commit the large working tree in coherent, auditable groups.
3. Remove generated caches, databases, virtual environments, build output,
   downloaded dependencies, user settings, project data, and local credentials
   from every publication candidate.
4. Run credential and private-key scanning against both the current tree and
   history. Rotate any exposed credential; deletion alone is insufficient.
5. Confirm third-party licenses permit the intended redistribution of every
   dependency, asset, plugin, and sample.

Do not push the current uncommitted workspace wholesale.

## Phase 2 — stage reproducible products

From the `tools` directory:

```powershell
py -3.14 -m tech_connector.packaging.stage_package core --out dist/repository-staging
py -3.14 -m tech_connector.packaging.stage_package official-tools --out dist/repository-staging
py -3.14 -m tech_connector.packaging.smoke_test_package dist/repository-staging/core
py -3.14 -m tech_connector.packaging.smoke_test_package dist/repository-staging/official-tools
```

Review each `PACKAGE_MANIFEST.json`. Core must not contain first-party bundle
roots. Official Tools must contain `official_tools_bundle.json` and must not
contain the Core application. Both must contain the controlling license and no
production secret material.

## Phase 3 — create clean repository histories

1. Create a new public Core repository from only the staged `core` payload.
2. Create a new private Official Tools repository from only the staged
   `official-tools` payload.
3. Do not copy `.git`, branches, tags, reflogs, CI credentials, or release
   artifacts from the mixed repository.
4. Add branch protection, required review, secret scanning, dependency review,
   and release-signing workflows appropriate to each repository.
5. Decide whether to archive the old public repository with a migration notice
   or change its visibility after preserving required records. Either choice is
   an operational decision, not a way to erase prior public distribution.

## Phase 4 — connect entitlement delivery

1. Configure backend offers to include Core and optionally
   `official_tools_bundle`; do not infer products from Community, Indie, or
   Enterprise labels.
2. Require verified email and immutable agreement acceptance before issuing an
   official Core entitlement.
3. Grant the private Tools repository or signed download only when the same
   entitlement includes `official_tools_bundle`.
4. Store the account, organization, license, named seat, acceptance receipt,
   covered major versions, provider identity, grant status, and audit reason.
5. Reconcile grants after seat, license, organization, or version changes.
6. Never expose GitHub App keys, OAuth secrets, signing keys, or administrator
   credentials to either client repository.

## Phase 5 — cutover verification

Before marking `config/source_access.json` as `operational_verified`, confirm:

- the public repository contains the intended Core source and no Tools Bundle;
- the Tools Bundle repository/download is account-gated;
- a Core-only entitlement cannot obtain or activate the first-party bundle;
- an entitled user can install Core and Tools separately and use them together;
- user-owned `extra_dirs` continue to work without a bundle entitlement;
- perpetual major-version access and annual expiration behave as contracted;
- acceptance receipts are visible to the account user and administrators;
- revocation removes future official access without deleting local user work;
- production endpoints, public verification keys, code signing, and privacy and
  legal approvals pass the release gate; and
- rollback can disable new grants without making valid perpetual Core rights
  disappear.

Only then set the operational fields and attach a dated review reference.
