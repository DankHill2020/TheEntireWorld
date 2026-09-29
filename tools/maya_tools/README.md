# Tech Connector Maya Tools

The Maya tool root contains Tech Connector’s first-party animation, cinematic,
rigging, HumanIK, skinning, MetaHuman, export, and authenticated bridge tooling.
It is part of the single Official Tools Bundle and is governed by the
[Tech Connector license](../tech_connector/LICENSE.md).

## Current capabilities

- Animation Manager and cinematic sequence workflows.
- Animation export and Unreal sequence/interchange handoff.
- HumanIK character mapping, T-pose/setup, retargeting, and specialized UI.
- Modular rig creation, joint placement, skinning, rig templates, validation,
  and MetaHuman helpers.
- Authenticated local Maya bridge startup without exposing a raw Python
  `commandPort`.
- Shared project selection and Tech Connector/Unreal workflow integration.

## Supported-version policy

Launchers are provided for Maya 2023, 2024, 2025, and 2026. Maya 2023 has been
executed through the current automated `mayapy` qualification: syntax, module
imports, scene creation, joints, skinning, version reporting, and read-only
setup import passed. Later declared versions retain source-contract coverage
until each is qualified on a real installed runtime; do not interpret launcher
presence alone as full production certification.

## Setup

Use the launcher matching the installed Maya version:

- `run_maya_with_setup_2023.bat`
- `run_maya_with_setup_2024.bat`
- `run_maya_with_setup_2025.bat`
- `run_maya_with_setup_2026.bat`

The setup path adds the current tools checkout to Maya, installs the managed
Tech Connector startup block, and creates the **The Entire World Tools** menu.
Importing `maya_setup.py` alone is intentionally read-only; explicit setup is
performed by running it as a script or calling `install_current_maya_tools()`.

After setup, ordinary Maya launches should retain the managed integration. A
studio’s unrelated `userSetup.py` content is preserved, and repeated installs
are idempotent. The installer targets real Maya 2023+ installations rather than
stale preference directories.

## Manual entry points

Animation Manager:

```python
from maya_tools.Cinematics.SequenceUI import sequence_ui
sequence_ui.show_animation_manager()
```

HumanIK UI:

```python
from maya_tools.Rigging.mocap import hik_ui
hik_ui.launch_hik_ui()
```

## Unreal/project workflow

When the Tech Connector menu opens a project-aware tool, select the intended
Unreal project or configured production project. The bridge and export tools
use that project context for supported animation, sequence, skeleton, and
Control Rig workflows. Tech Connector Core also supports additional project and
tool directories; this Maya root does not need to be copied into every project.

Legacy walkthrough videos remain available at
[The Entire World’s Vimeo page](https://vimeo.com/user58067839), including the
Animation Manager workflow and HumanIK character-builder material. The UI has
continued to evolve, so treat older videos as workflow references rather than
an exact current-screen guide.

## Licensing and privacy

Downloading these files does not create an activated entitlement. Official
Tools execution requires the signed `official_tools_bundle` capability. Bridge
traffic is local and licensing does not upload Maya scenes, rigs, animation,
source assets, or project paths.
