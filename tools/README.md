# Tech Connector Tools

Tech Connector is a local-first AI production environment for digital content
creation (DCC) applications and game engines. This repository contains the
desktop application, prompt-to-code and repair workflows, project analysis,
viewer tools, and direct integrations for Unreal Engine, Maya, Blender,
MotionBuilder, Houdini, Substance 3D Painter, and 3ds Max.

The project currently targets Python 3.14 for the desktop shell. Individual DCC
hosts may embed older Python runtimes, so host bridge code preserves compatibility
with the Python version shipped by each supported application.

## Quick start

From PowerShell in the repository root:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r tech_connector\packaging\requirements-runtime.txt
.\.venv\Scripts\python.exe -m tech_connector.app.main_window
```

Optional integrations and development tools are listed in
`tech_connector\packaging\requirements-optional.txt` and
`tech_connector\packaging\requirements-build.txt`.

## Repository map

- `tech_connector/`: desktop shell, planning/runtime services, UI, bridges,
  game-engine integration, viewers, documentation, and release tooling
- `maya_tools/`, `blender_tools/`, `houdini_tools/`, `max_tools/`,
  `motionbuilder_tools/`: host-native production tools
- `unreal_tools/`: Unreal project and editor utilities
- `external_tools/`: vendored integrations and third-party payloads; these are
  not part of the core Tech Connector source

Canonical DCC bridge implementations live under `tech_connector/bridges/`.
Installer scripts under `tech_connector/installers/` bootstrap those bridges
inside their host applications.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tech_connector\examples\tests
```

Some integration checks require their corresponding DCC or game-engine host.
Headless tests skip those checks when the host SDK is unavailable.

## Packaging

Tech Connector uses explicit release tiers rather than a generic wheel build.
See [the packaging guide](tech_connector/packaging/README.md) for staging,
validation, manifests, and optional dependencies. Generated knowledge indexes,
runtime state, caches, and local source art are intentionally excluded from
release packages.

## Documentation and contribution

- [Tech Connector overview](tech_connector/README.md)
- [Documentation index](tech_connector/docs/README.md)
- [Contributing](tech_connector/CONTRIBUTING.md)
- [License](tech_connector/LICENSE.md)

Review the license before redistributing or publishing modified copies. The
repository is source-available; the license, not repository visibility,
determines permitted use and distribution.
