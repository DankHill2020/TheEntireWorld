# Public Monorepo Publication Runbook

Status: the earlier public-Core/private-Official-Tools split plan was
superseded on 2026-09-29 by the complete public-monorepo decision.

`DankHill2020/TheEntireWorld` is the canonical source-available monorepo. Its
`tools/` directory contains Tech Connector Core and the complete first-party
Official Tools source. The source-available license—not repository secrecy—
controls use, modification, redistribution, and commercial exploitation.

The clean public `DankHill2020/TechConnector` Core repository and any staged
Official Tools repository or archive may remain useful release channels, but
they are derived products and must not be described as confidentiality
boundaries for source already present in TheEntireWorld.

## Public/private boundary

The public monorepo may contain client applications, DCC and engine tools,
bridge protocols, public verification keys, documentation, tests, examples,
and credential-free build/packaging automation.

It must never contain private entitlement signing keys, account databases,
authentication-provider secrets, payment credentials or webhooks, production
deployment credentials, private billing/accounting services, administrator
override systems, or enterprise-only components not intentionally released.

## Reproducible product packages

Core, Official Tools, and combined releases remain separate product artifacts
even though their source shares one repository. From `tools/`:

```powershell
py -3.14 -m tech_connector.packaging.stage_package core --out dist/repository-staging
py -3.14 -m tech_connector.packaging.stage_package official-tools --out dist/repository-staging
py -3.14 -m tech_connector.packaging.smoke_test_package dist/repository-staging/core
py -3.14 -m tech_connector.packaging.smoke_test_package dist/repository-staging/official-tools
```

Review each `PACKAGE_MANIFEST.json`. Official Tools must carry the
`official_tools_bundle` product/capability declaration. Core-only packages must
not silently include that product. A combined authorized installer may include
both. Public source visibility does not bypass application activation or create
a commercial entitlement.

## Publication checklist

1. Preserve the exact source commit and use a reviewed, non-generated tree.
2. Exclude caches, databases, virtual environments, build output, downloaded
   dependencies, user settings, projects, and local credentials.
3. Scan the candidate tree and history for credentials and private keys; rotate
   exposed credentials because deletion is not sufficient.
4. Confirm third-party licenses permit redistribution of every dependency,
   asset, plugin, and sample.
5. Run the complete automated suite plus available native DCC/runtime
   qualification.
6. Verify root `README.md` and `LICENSE` identify the project as source
   available—not unrestricted open source—and explain activation.
7. Verify `config/source_access.json` records the public monorepo model and the
   exclusion of private services.
8. Publish only after legal, privacy, signing, backend, installer, monitoring,
   and recovery gates required for that release are independently satisfied.

Git history, clones, forks, caches, and archives cannot be recalled. Revocation
may stop future official updates, services, support, and renewed entitlements;
it must not delete user projects or pretend already published source is secret.
