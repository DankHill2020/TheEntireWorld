# Tech Connector MotionBuilder Tools

This root contains the first-party MotionBuilder character, animation export,
sequence, rig-host, project I/O, menu, setup, and local bridge integration. It
is part of the single Official Tools Bundle and is governed by the
[Tech Connector license](../tech_connector/LICENSE.md).

## Setup

Use the launcher matching the installed MotionBuilder version:

- `run_motionbuilder_with_setup_2023.bat`
- `run_motionbuilder_with_setup_2024.bat`
- `run_motionbuilder_with_setup_2025.bat`
- `run_motionbuilder_with_setup_2026.bat`

The setup installs the Tech Connector menu/bootstrap for the selected host and
connects it to the project-aware Core bridge. Launcher presence describes the
supported setup surface; production qualification should still be recorded on
the exact MotionBuilder build used by a studio.

## Included workflows

- Character and scene I/O helpers.
- Animation export and sequence utilities.
- Rigging host adapter behavior shared with broader Tech Connector workflows.
- Local session discovery and authenticated host dispatch through Core.
- Unreal/project handoff using the configured production project context.

Tech Connector can discover this directory through its normal project/tool
directory settings, so the package may be installed beside Core or included in
a combined installation.

Downloading these files does not create an activated entitlement. Official
Tools execution requires the signed `official_tools_bundle` capability, and
licensing does not upload MotionBuilder scenes or animation data.
