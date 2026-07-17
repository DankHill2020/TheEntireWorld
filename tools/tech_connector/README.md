# The Entire World Tech Connector

⚠️ **License Notice: Source-Available (Non-Commercial, Non-Redistribution)**

This repository is owned by **The Entire World, LLC**. It is **source-available** for personal study, local run, and educational purposes. It is **not** licensed under a permissive open-source license (like MIT).

Under the terms of the [LICENSE](LICENSE.md):
- **Redistribution is prohibited**: You may not copy, re-host, or distribute this software.
- **Commercial use and resale are strictly prohibited**: Selling your own version, packaging it as a paid product, or commercially exploiting this software in any form is a direct violation of copyright law.

---

Architecture notes:

- `docs/UI_FEATURES_GUIDE.md` covers the main UI tabs, menus, settings, and workflow builder.
- `docs/BRIDGE_ARCHITECTURE.md` covers adding app bridges.
- `docs/DIRECT_DCC_BRIDGE.md` covers direct Maya, Unreal, Blender, Substance Painter, Unity, and MotionBuilder calls.
- `docs/LIVE_SOURCE_INGESTION.md` covers local-only versus live web/GitHub sourcing.
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

For `BrowseDirectory`, if the class defaults `directory=None` but calls `directory.replace(...)`, the assistant can prepare a fix that guards `None` and initializes the line edit from the normalized stored directory.

Single launcher:
`Start_The_Entire_World_AI_Studio.bat`
