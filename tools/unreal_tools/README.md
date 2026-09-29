# Tech Connector Unreal Tools

The Unreal tool root is the first-party project/editor utility layer used by
Tech Connector’s Unreal bridge and smart-operation system. It is part of the
single Official Tools Bundle and is governed by the
[Tech Connector license](../tech_connector/LICENSE.md).

## Included domains

- Project inspection, validation, editor utilities, assets, and level actors.
- Animation import/interchange, sequences, Sequencer, skeletal assets,
  retargeting, motion matching, and Control Rig.
- Blueprint graphs, variables, events, behavior trees, blackboards, widgets,
  and data tables.
- Materials, Niagara, PCG, MetaSound, Sound Cue, navigation, physics,
  networking, gameplay, and runtime helpers.
- Transaction/rollback support and project-aware target resolution.

Core’s Unreal Project Intelligence layer resolves the current project, level,
selection, assets, and available operations before dispatch. Mutating actions
remain subject to the active workflow’s preview/approval policy and the signed
DCC-host capability.

## Connection model

Open the Unreal project through the configured Tech Connector project context,
install/enable the required local bridge components, and select the intended
live session in Tech Connector. The bridge uses local structured requests and
does not send project assets or source content to the licensing service.

The modules in this directory are implementation surfaces, not a promise that
every Unreal feature or engine version is equally qualified. Review
[Unreal smart operations](../tech_connector/docs/UNREAL_SMART_OPERATIONS.md),
[direct DCC bridge behavior](../tech_connector/docs/DIRECT_DCC_BRIDGE.md), and
[industry readiness](../tech_connector/docs/DCC_ENGINE_INDUSTRY_READINESS_2026_08_08.md)
before treating a workflow as production-certified.

Downloading these files does not create an activated entitlement. Official
Tools execution requires the signed `official_tools_bundle` capability.
