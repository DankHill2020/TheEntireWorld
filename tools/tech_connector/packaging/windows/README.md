# Windows Packaging Quickstart

This folder contains the local build loop for website-ready Tech Connector
packages. Release freezes require 64-bit CPython 3.14. The default `auto`
setting checks normal per-user and system install paths before trying
`py -3.14`. PyInstaller bundles that interpreter, so installed users do not
need Python on their machine.

Run the convenience wrapper from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tech_connector\packaging\windows\Build_TechConnector_Windows_Package.ps1 -Tier core -Mode freeze
```

## Package Tiers

- `core`: the Tech Connector application without the Official Tools Bundle.
- `official-tools`: the separately downloadable content bundle (`stage` only).
- `combined`: Core plus the complete Official Tools Bundle.

`reasoning-runtime` and `full-tools` remain compatibility aliases for `core`
and `combined`.

## Build Modes

Stage package contents without freezing:

```powershell
powershell -ExecutionPolicy Bypass -File tech_connector\packaging\windows\build_windows_package.ps1 -Tier core -Mode stage
```

Create the installed app and portable ZIP:

```powershell
powershell -ExecutionPolicy Bypass -File tech_connector\packaging\windows\build_windows_package.ps1 -Tier core -Mode freeze
```

Create the Inno Setup installer EXE:

```powershell
powershell -ExecutionPolicy Bypass -File tech_connector\packaging\windows\build_windows_package.ps1 -Tier core -Mode installer -SigningCertificateThumbprint <thumbprint>
```

Use `-Tier combined` for the combined package. Use `-Tier official-tools -Mode
stage` for the separately downloadable bundle. Installer mode fails closed
unless Inno Setup 6, production HTTPS licensing endpoints, entitlement public
keys, and a current-user Authenticode code-signing certificate are configured.
Local `stage` and `freeze` modes remain available for unsigned iteration.

## Outputs

```text
dist\windows\staged\<tier>
dist\windows\frozen\<tier>\TechConnector\TechConnector.exe
dist\windows\portable\<package>-<version>-win64-portable.zip
dist\windows\installer\<package>-<version>-win64-setup.exe
```

The freeze builds and tests the C++ graph runtime, packages its DLL, and writes
`PYTHON_RUNTIME.txt` beside the application with the exact bundled interpreter.

## Smoke Tests

```powershell
python tech_connector\packaging\smoke_test_package.py dist\windows\staged\core
python tech_connector\packaging\smoke_test_package.py dist\windows\frozen\core\TechConnector\TechConnector.exe
```

## Iteration Notes

- Install the current Python release first with the official Python installer.
- `-Python auto` is the default. An explicit path must still point to 64-bit
  CPython 3.14.
- Use `-Mode stage` for package-content changes and `-Mode freeze` for
  PyInstaller changes.
- Add `-SkipDependencyInstall` only after the build environment is populated.
- User settings remain in local app data; they are not written to Program Files.
- DCC bridge setup remains an opt-in action inside the app.
