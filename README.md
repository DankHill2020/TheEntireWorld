# The Entire World — Tech Connector

Tech Connector is a local-first production platform that connects AI-assisted
development, DCC applications, game-engine workflows, asset authoring, and a
playable runtime in one project-aware desktop environment.

Current source line: **v6.7**

Publisher: **The Entire World, LLC**

Repository model: **complete public source-available monorepo**

> **Source available — not open source. Account activation is required.**
>
> Downloading a GitHub release, cloning this repository, or downloading its ZIP
> does not create an activated license or grant unrestricted commercial use,
> redistribution, sublicensing, resale, or hosted exploitation. Official use
> requires a registered account, verified email, acceptance of the applicable
> versioned terms, and a valid signed entitlement. Community commercial projects
> must also be registered.
>
> Copyright remains with **The Entire World, LLC**. Read the repository
> [LICENSE](LICENSE), the controlling
> [Tech Connector Community Source License](tools/tech_connector/LICENSE.md),
> and the [source-access model](tools/tech_connector/docs/SOURCE_ACCESS_MODEL.md).

## What is included

The `tools/` directory is the canonical product source. It includes both Tech
Connector Core and the complete Official Tools Bundle; private signing,
identity, billing, accounting, administrative, and deployment services are not
published here.

| Package | What it contains | Entitlement |
| --- | --- | --- |
| **Tech Connector Core** | Desktop shell, project intelligence, AI/code workflows, asset system, DCC bridges, Garden authoring, Kingdom runtime/playtest, headless API, licensing client, and local reasoning runtime | `tech_connector.core` |
| **Official Tools Bundle** | The complete first-party Maya, Blender, Houdini, 3ds Max, MotionBuilder, Substance Painter, Unreal, utility, plugin, and Qt tool collection | `official_tools_bundle` |
| **Combined** | Core and Official Tools in one convenience build; each product keeps its own entitlement meaning | Core plus `official_tools_bundle` |
| **Public monorepo** | The complete source tree used to build all three packages | Visibility alone is not an activated or commercial entitlement |

Official Tools is one bundle—not a collection of separately licensed host tool
packs. It can be packaged with Core, installed beside it, or discovered through
Tech Connector’s existing project/tool directory settings. Your own project
directories and independently obtained tools remain usable without the bundle
capability.

## Product areas

### Tech Connector desktop and AI workflow

- Project-aware chat, editor, repository search, symbols, assets, and pipelines.
- Ask, plan, edit, repair, and review workflows with explicit scope and
  reviewable changes.
- Local and replaceable model-provider routing, including local-model support.
- Project analysis, capability evidence, implementation planning, regression
  qualification, and launch-readiness views.
- A licensed headless API for automation without opening the desktop shell.
- Local-first settings, indexes, project identity, and entitlement caching.

### DCC and engine connectivity

Tech Connector has host-aware bridges and shared workflows for Maya, Blender,
Houdini, MotionBuilder, Substance 3D Painter, 3ds Max, Unreal Engine, Unity,
and GIMP. The Photoshop bridge remains experimental and disabled by default.

The bridge layer supports session discovery, project context, safe structured
calls, scene/selection inspection, and host-specific operations. The federated
DCC viewport provides a common scene, outliner, selection, camera, transform,
and validation model while preserving host ownership of authoritative data.

Host-specific runtime qualification varies. This release has real Maya 2023
`mayapy` evidence for syntax, module imports, scene creation, joints, skinning,
and read-only setup import. Maya 2024–2026 currently carry source-contract
coverage until each version is exercised on an installed host. See
[industry readiness](tools/tech_connector/docs/DCC_ENGINE_INDUSTRY_READINESS_2026_08_08.md)
for the intentionally conservative qualification boundary.

### Garden authoring and Kingdom runtime

- **Garden** is the authoritative scene/level authoring workspace.
- **Kingdom** is the Play & Build workspace for the same saved `.tcscene`.
- The Kingdom runtime preview receives the actual Garden scene, camera,
  deformation bindings, effects, actors, and level hierarchy rather than an
  empty placeholder.
- The runtime World Outliner exposes synchronized level elements and actor
  details; Play Current Level saves and launches that exact scene as an isolated
  playtest copy.
- Core contains asset browsing/editing, level actors and components, prefabs,
  sequences, gameplay graphs, animation, physics, effects, audio, procedural
  content, simulation, packaging, and native-player integration.

Production claims remain evidence-based. A feature may be present as a
prototype, translated operation, or local reference implementation before it
is qualified across every host, renderer, and target platform.

### Official Tools Bundle

- **Maya:** animation/sequence export, HumanIK mapping and retargeting, rig
  creation modules, skinning, MetaHuman helpers, cinematics, and authenticated
  Live Link bootstrap. See the [Maya guide](tools/maya_tools/README.md).
- **MotionBuilder:** character, animation export, sequence, rig-host, and bridge
  setup workflows. See the
  [MotionBuilder guide](tools/motionbuilder_tools/README.md).
- **Unreal:** project and level operations, animation/sequence interchange,
  Control Rig, retargeting, Blueprint, behavior tree, blackboard, materials,
  Niagara, PCG, MetaSound, navigation, physics, networking, validation, and
  editor/runtime utilities. See the [Unreal guide](tools/unreal_tools/README.md).
- **Blender, Houdini, 3ds Max, and Substance Painter:** host-native tool roots
  plus Core bridge/install support.
- **Shared tooling:** reusable utilities, plugins, and Qt components shipped as
  part of the single bundle.

## Editions and launch pricing direction

The following is the current launch model, not a checkout offer or substitute
for the signed terms shown to a user. Prices, eligibility, residual brackets,
discounts, and included capabilities are versioned backend configuration—not
hardcoded client policy. See the full
[pricing model draft](tools/tech_connector/docs/PRICING_MODEL_DRAFT.md).

| Edition | Current direction |
| --- | --- |
| **Community Success** | $0 upfront. Verified account required. Commercial projects must be registered. No residual on the first **$500,000 of lifetime Adjusted Project Profit**; only profit inside higher marginal brackets uses the accepted studio-size schedule. |
| **Indie Annual** | **$200 per named user/year**, releases during the paid term, two registered devices per user, and no project residual for work under the paid covered version. |
| **Indie Perpetual** | **$500 per named user** for the purchased major version, free minor/patch updates for that major, and an optional **$200 per-user** upgrade to a later major version. The prior licensed major remains perpetual. |
| **Enterprise Annual** | Draft standard price **$1,500 per named user/year** with a five-seat minimum; **$1,250/user** at 25+ seats before custom negotiation. |
| **Enterprise Perpetual** | Draft standard price **$3,500 per named user** for the contracted major version with a five-seat minimum; optional annual support/update plan targeted at 20% of license price. |
| **Custom Partnership** | Negotiated pricing, thresholds, residuals, seats, offline/air-gapped use, support, integrations, deployment, hosted use, redistribution, or other nonstandard rights. |

Indie and Enterprise are named-user licenses. Community residuals are based on
project-lifetime Adjusted Project Profit, with documented, ordinary, necessary,
reasonable, directly attributable costs—not owner draws, inflated related-party
charges, unrelated overhead, artificial fees, or other avoidance devices.

## Activation, offline use, and privacy

The official application does not open its main shell until license acceptance
and activation succeed. The client verifies an Ed25519-signed entitlement with
a public key; private signing keys never ship in the client. Authentication
sessions are short-lived and separate from longer-lived offline entitlements.

Entitlements can express the account, organization, named-user seat, license
type, market segment, version coverage, support, authorized projects,
capabilities, device limit, and offline expiration. A user can deactivate an
old installation and activate a replacement without aggressive hardware
fingerprinting.

The licensing service receives only the minimum identity, entitlement,
project-registration, agreement, and pseudonymous installation metadata needed
for enforcement. It does **not** receive project assets, scenes, source files,
animation, prompts, renders, or other creative work. See the
[privacy notice](tools/tech_connector/PRIVACY.md) and
[licensing architecture](tools/tech_connector/docs/LICENSING_ARCHITECTURE.md).

## Getting started from source

Tech Connector’s desktop release target is Python 3.14. From `tools/` in
PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r tech_connector\packaging\requirements-runtime.txt
.\.venv\Scripts\python.exe -m tech_connector.app.main_window
```

The source launcher follows the same account, license-acceptance, and activation
flow as an installed build; cloning the repository does not enable a developer
or Community bypass.

Host setup and optional dependencies vary:

- [Maya setup and tools](tools/maya_tools/README.md)
- [MotionBuilder setup and tools](tools/motionbuilder_tools/README.md)
- [Unreal integration and tools](tools/unreal_tools/README.md)
- [Bridge architecture](tools/tech_connector/docs/BRIDGE_ARCHITECTURE.md)
- [Direct DCC bridge behavior](tools/tech_connector/docs/DIRECT_DCC_BRIDGE.md)
- [Model providers](tools/tech_connector/docs/MODEL_PROVIDERS.md)

## Repository map

```text
tools/
├── tech_connector/            Core application, services, UI, bridges, engine, licensing
├── reasoning_runtime/         Local planning and execution runtime
├── maya_tools/                Maya animation, cinematics, rigging, HIK, Live Link
├── motionbuilder_tools/       MotionBuilder animation, character, sequence, bridge tools
├── unreal_tools/              Unreal project, level, animation, graph, asset utilities
├── blender_tools/             Blender-native tools
├── houdini_tools/             Houdini-native tools
├── max_tools/                 3ds Max-native tools
├── substance_painter_tools/   Substance Painter-native tools
├── custom_qt/                 Shared UI components
├── plugins/                   Shared product plugins
├── utilities/                 Shared utility modules
└── official_tools_bundle.json Official Tools product manifest
```

`external_tools/` contains vendored or externally sourced integration material
and may carry its own notices. Generated state, virtual environments, caches,
downloaded dependencies, projects, credentials, signing keys, and private
backend systems are excluded from release publication.

## Packaging and validation

The source tree produces explicit Core, Official Tools, and Combined artifacts:

```powershell
.\.venv\Scripts\python.exe -m tech_connector.packaging.stage_package core --out dist\repository-staging
.\.venv\Scripts\python.exe -m tech_connector.packaging.stage_package official-tools --out dist\repository-staging
.\.venv\Scripts\python.exe -m tech_connector.packaging.stage_package combined --out dist\repository-staging
```

The release pipeline rejects private keys, production secrets, generated state,
unsafe repository surfaces, and packages whose SHA-256 inventory changes before
import. Current repository validation covers licensing, startup enforcement,
offline entitlement policy, device/project authorization, DCC workflows,
authoring/runtime behavior, package staging, and release gates.

## Documentation

- [Core overview](tools/tech_connector/README.md)
- [UI features](tools/tech_connector/docs/UI_FEATURES_GUIDE.md)
- [Package architecture](tools/tech_connector/docs/PACKAGE_ARCHITECTURE.md)
- [Engine authoring experience](tools/tech_connector/docs/TC_ENGINE_AUTHORING_EXPERIENCE.md)
- [Native engine and graphs](tools/tech_connector/docs/TC_NATIVE_ENGINE_AND_GRAPH_ARCHITECTURE.md)
- [Character intelligence](tools/tech_connector/docs/TC_CHARACTER_INTELLIGENCE_ARCHITECTURE.md)
- [Simulation and effects](tools/tech_connector/docs/TC_SIMULATION_EFFECTS_ENGINE_ARCHITECTURE.md)
- [Federated DCC viewport](tools/tech_connector/docs/FEDERATED_DCC_VIEWPORT.md)
- [Headless API](tools/tech_connector/docs/HEADLESS_API.md)
- [Licensing launch readiness](tools/tech_connector/docs/LICENSING_LAUNCH_READINESS.md)
- [Contribution policy](tools/tech_connector/CONTRIBUTING.md)

## Release-status note

The repository and client foundations are substantially hardened, but a
mainstream commercial release still depends on external gates including legal
approval of the final license/privacy text, deployment of the private account
and entitlement service, production signing-key custody, real payment/tax
integration, signed installer qualification, monitoring, backups, and support
operations. The launch-readiness documentation treats those as blockers rather
than implying that checked-in client code alone completes the business system.
