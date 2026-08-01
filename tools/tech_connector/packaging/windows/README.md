# Windows Packaging Quickstart

This folder contains the local build loop for website-ready Tech Connector packages.

The convenience wrapper lives beside the main script:

```powershell
powershell -ExecutionPolicy Bypass -File tech_connector\packaging\windows\Build_TechConnector_Windows_Package.ps1 -Tier reasoning-runtime -Mode freeze
```

## Package Tiers

- `reasoning-runtime`: lean app package for normal website downloads.
- `full-tools`: larger studio/contributor package with DCC tools and plugins.

## Build Modes

### 1. Stage Only

Use this to verify package contents quickly.

```powershell
powershell -ExecutionPolicy Bypass -File tech_connector\packaging\windows\build_windows_package.ps1 -Tier reasoning-runtime -Mode stage
```

Output:

```text
dist\windows\staged\reasoning-runtime
```

### 2. Frozen App + Portable Zip

Use this before building an installer.

```powershell
powershell -ExecutionPolicy Bypass -File tech_connector\packaging\windows\build_windows_package.ps1 -Tier reasoning-runtime -Mode freeze
```

Outputs:

```text
dist\windows\frozen\reasoning-runtime\TechConnector\TechConnector.exe
dist\windows\portable\TechConnectorReasoningRuntime-<version>-win64-portable.zip
```

### 3. Installer EXE

Install Inno Setup 6 first, then run:

```powershell
powershell -ExecutionPolicy Bypass -File tech_connector\packaging\windows\build_windows_package.ps1 -Tier reasoning-runtime -Mode installer
```

Output:

```text
dist\windows\installer\TechConnectorReasoningRuntime-<version>-win64-setup.exe
```

Build the full package with:

```powershell
powershell -ExecutionPolicy Bypass -File tech_connector\packaging\windows\build_windows_package.ps1 -Tier full-tools -Mode installer
```

## Smoke Tests

Test a staged package import:

```powershell
python tech_connector\packaging\smoke_test_package.py dist\windows\staged\reasoning-runtime
```

Test a frozen executable launch:

```powershell
python tech_connector\packaging\smoke_test_package.py dist\windows\frozen\reasoning-runtime\TechConnector\TechConnector.exe
```

## Iteration Notes

- Use `-Mode stage` when changing package contents.
- Use `-Mode freeze` when testing PyInstaller issues.
- Use `-Mode installer` when testing real install/uninstall behavior.
- Add `-SkipDependencyInstall` after the build venv already has PyInstaller and runtime dependencies.
- Use `-Python "py -3.11"` if you want to force the Windows Python launcher instead of the default `python`.
- The installer writes the app to Program Files by default, while user settings remain in local app data.
- DCC bridge setup should stay opt-in inside the app rather than being forced by the installer.
