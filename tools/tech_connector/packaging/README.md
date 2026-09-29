# Packaging Tech Connector

Tech Connector has two products and one convenience package:

- `core`: the Tech Connector application, local APIs, bridge protocols,
  project/tool-directory support, game-engine runtime, documentation, and core
  assets. This is the public source-available product.
- `official-tools`: the complete optional first-party DCC and pipeline tool
  collection. It contains no Core application and requires the signed
  `official_tools_bundle` capability.
- `combined`: Core and the Official Tools Bundle in one payload. Product
  capabilities remain separate even when the files ship together.

The legacy names `reasoning-runtime` and `full-tools` remain accepted as aliases
for `core` and `combined` so existing build automation does not break.

The Official Tools Bundle is one product. Maya, Blender, Houdini, 3ds Max,
MotionBuilder, Substance Painter, Unreal, utilities, plugins, and Qt helpers are
not staged or licensed as individual tool packs. Users can place the separately
downloaded bundle anywhere and add its root through Core's existing project/tool
directory settings. User-owned directories continue to work without the bundle.

All packages omit tests, generated knowledge databases, capability registries,
Python bytecode, local state, build staging, and downloaded third-party payloads.
Staging rejects private-key material and common production-secret artifacts.

Stage and validate products with Python 3.14:

```powershell
py -3.14 -m tech_connector.packaging.stage_package core --out dist/staged
py -3.14 -m tech_connector.packaging.stage_package official-tools --out dist/staged
py -3.14 -m tech_connector.packaging.stage_package combined --out dist/staged
py -3.14 -m tech_connector.packaging.smoke_test_package dist/staged/core
```

Every staged result contains `PACKAGE_MANIFEST.json`, including the product ID,
required capability, requested/canonical tier, SHA-256, and size of every file.
The smoke test verifies that inventory before importing staged code. Windows
portable ZIPs and installers also receive adjacent `.sha256` checksum files.

The documentation-only public landing exporter remains available for a website
or small onboarding repository:

```powershell
py -3.14 -m tech_connector.packaging.source_distribution --out dist/public-landing
```

It is not the Core source package. Public Core source is staged with the `core`
tier. Do not publish `official-tools` or `combined` anonymously. Backend,
signing, billing, accounting, administrator, and enterprise-only source is not
included in any client package.

Install `requirements-runtime.txt` for supported Core features.
`requirements-optional.txt` lists heavier integrations with graceful fallbacks.
DCC hosts provide their own embedded modules and are not ordinary pip
dependencies.
