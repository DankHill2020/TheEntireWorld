# Tech Connector Distribution Packaging Plan

## Distribution Channels

### GitHub: Contributor Source Package

Use GitHub for engineers, TDs, and contributors who want to inspect code, fix bugs, improve tools, or run from source.

Expected user:
- Wants the repository.
- Has or can install 64-bit CPython 3.14 for source development and release builds.
- May edit DCC bridge scripts, UI modules, plugins, or pipeline logic.
- Accepts developer setup steps.

Deliverables:
- Source repository.
- `Start_The_Entire_World_Tech_Connector.bat` for source launch.
- `CONTRIBUTING.md`.
- Issue templates and bug report templates.
- Optional dev bootstrap script.

### Website: Installed App Packages

Use the website for normal users who want to install and run Tech Connector without cloning the repo.

Expected user:
- Wants an installer.
- Should not need to install Python manually.
- Should not see source setup prompts.
- Should be able to uninstall cleanly.

Deliverables:
- Windows `.exe` installer.
- Later: macOS `.dmg` or signed `.pkg`.
- Release notes.
- Checksums.
- Clear package choice: Reasoning Runtime or Full Tools Package.

## Package Tiers

### 1. Reasoning Runtime

Smallest practical installed build. This is the default website download.

Includes:
- Tech Connector desktop UI.
- Chat, model/provider settings, pipeline editor/runtime.
- Knowledge/index services needed by the app.
- Prompt routing and local/cloud provider configuration.
- Splash/assets required by the installed app.
- Minimal DCC connection status and bridge clients.

Excludes:
- Full external tool depot.
- Heavy sample assets.
- Downloaded third-party repositories.
- DCC installer payloads that are not required for basic use.
- Contributor scripts and scratch/dev artifacts.

Best for:
- Artists, designers, coordinators, and users who mainly want AI reasoning, pipelines, and app orchestration.

### 2. Full Tools Package

Larger package for studios, TDs, and contributors who want every integrated tool.

Includes:
- Everything in Reasoning Runtime.
- DCC bridge installers and scripts for Maya, Unreal, Blender, Substance Painter, Unity, Houdini, and MotionBuilder where available.
- Pipeline tools, examples, and supported integration packages.
- Optional sample projects/assets that are safe to redistribute.
- Developer diagnostics and repair utilities.

Excludes:
- Private/local scratch folders.
- `.git`, caches, downloaded transient packages, and user settings.
- Any third-party code/assets without redistribution permission.

Best for:
- Technical artists, pipeline engineers, source contributors, and studio integration installs.

## Windows Build Strategy

Preferred first implementation:
1. Use PyInstaller or Nuitka to produce a frozen `TechConnector.exe`.
2. Package the frozen app with Inno Setup or WiX Toolset into a signed installer.
3. Create two installer definitions:
   - `TechConnector-ReasoningRuntime-<version>-win64.exe`
   - `TechConnector-FullTools-<version>-win64.exe`
4. Write app data to `%LOCALAPPDATA%\TheEntireWorld\TechConnector`, not inside `Program Files`.
5. Keep optional DCC bridge installation as an in-app action, not as a forced installer side effect.

The installed app must not depend on the install path being named `tools`.
Release builds are frozen with the latest CPython 3.14 patch release. The build
script rejects older interpreters and records the exact bundled patch version in
`PYTHON_RUNTIME.txt`. Installed users do not need a separate Python installation.

## macOS Build Strategy

Target shape:
- `TechConnector.app` bundled with Python runtime and Qt dependencies.
- `.dmg` for drag-install or signed `.pkg` if installer steps become necessary.
- Runtime data under `~/Library/Application Support/TheEntireWorld/TechConnector`.

Mac caveats:
- DCC app automation, window capture, and keyboard/mouse forwarding may require Accessibility and Screen Recording permissions.
- DCC executable discovery needs macOS-specific paths.
- Signing/notarization should be planned before public website downloads.

## Release Checklist

- App launches from an install path that is not named `tools`.
- Splash screen is the only visible window until reveal.
- No first-run popups appear before the splash is closed.
- Reasoning Runtime runs without DCC apps installed.
- Full Tools Package exposes DCC bridge setup without forced launches.
- User settings persist across updates.
- Uninstaller preserves user data by default and offers a remove-user-data option.
- Installer and app are signed before public website release.
- Release artifact checksums are published.

## Immediate Engineering Tasks

- Add a Windows build spec for the Reasoning Runtime.
- Add a Windows build spec for the Full Tools Package.
- Audit import/path assumptions for installed locations.
- Move bundled release configuration into `tech_connector/packaging`.
- Add CI/manual release scripts that produce both package tiers.
- Add website copy that explains which package to choose.
