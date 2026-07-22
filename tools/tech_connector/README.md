# The Entire World Tech Connector

## License Notice

Tech Connector is owned by **The Entire World, LLC** and released under the
[Tech Connector Community Source License](LICENSE.md).

This is a **source-available** project, not an OSI open-source project.

The intent is simple:

- Free for individuals, students, educators, hobbyists, researchers, nonprofits,
  and open-source projects.
- Free for independent creators and small studios until commercial success.
- You own what you create with the tools.
- If you never make money from use of the tools, you never owe royalties.
- Commercial use above the license threshold requires a commercial license.
- No resale, sublicensing, repackaging, hosting, or redistribution of Tech
  Connector or modified Tech Connector without a written commercial agreement.
- No AI training, model distillation, embedding, benchmarking, or competing
  automation/tool generation using Tech Connector source, docs, prompts,
  signatures, traces, or call plans.
- Programmable function access must go through Tech Connector's licensed app,
  local service, hosted API, SDK, or another expressly authorized interface.
- Community contributions are welcome, but submitted contributions may be used
  in both free community releases and commercial versions of the product.

See [docs/COMMERCIAL_MODEL.md](docs/COMMERCIAL_MODEL.md) and
[CONTRIBUTING.md](CONTRIBUTING.md) for the practical version of these rules.

---

Architecture notes:

- `docs/UI_FEATURES_GUIDE.md` covers the main UI tabs, menus, settings, and workflow builder.
- `docs/BRIDGE_ARCHITECTURE.md` covers adding app bridges.
- `docs/DIRECT_DCC_BRIDGE.md` covers direct Maya, Unreal, Blender, Substance Painter, Unity, and MotionBuilder calls.
- `docs/LIVE_SOURCE_INGESTION.md` covers local-only versus live web/GitHub sourcing.
- `docs/HEADLESS_API.md` covers licensed API/function access without starting the UI.
- `docs/MODEL_PROVIDERS.md` covers OpenAI/Google/Anthropic/local model routing.
- `docs/UNREAL_SMART_OPERATIONS.md` covers project-aware Unreal scans, navigation, capability validation, and safe prototype operations.
- `docs/ROUTING_ENTRYPOINT_AUDIT.md` and `docs/ENTERPRISE_INTERACTION_BYPASS_AUDIT.md` cover deterministic routing and remaining migration targets.

## Changed

- Editor answers now show the relevant source excerpt first.
- The actual explanation/direct answer appears below the source.
- `Ask About File` can now prepare conservative safe patches for obvious bugs.
- Added `Apply Fix` in the Editor tab.
- Applying a fix creates a `.tew_backup` first.
- The main launcher starts the UI with `pyw -3.11 -m app.main_window`.

## Current safe patch example

For `BrowseDirectory`, if the class defaults `directory=None` but calls
`directory.replace(...)`, the assistant can prepare a fix that guards `None` and
initializes the line edit from the normalized stored directory.

Single launcher:
`Start_The_Entire_World_AI_Studio.bat`
