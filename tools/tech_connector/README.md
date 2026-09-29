# The Entire World Tech Connector

## License Notice

Tech Connector is owned by **The Entire World, LLC** and released under the
[Tech Connector Community Source License](LICENSE.md).

This is a **source-available** project, not an OSI open-source project.

## Download, account, and activation

Downloading a GitHub release, cloning the repository, or downloading its ZIP
does not itself activate Tech Connector and does not grant unrestricted use.
Every official user—including Community, Indie, Enterprise, and Custom users—
must create or use a registered account, verify their email, accept the
applicable versioned license, and activate an allowed user/device before the
main application opens. A cryptographically signed entitlement is then cached
for the permitted offline period.

Community access is free but not anonymous. Community commercial use also
requires registration of each commercial project and acceptance of that
project's versioned terms. Downloading source does not waive the USD $500,000
lifetime Adjusted Project Profit threshold, residual terms, seat rules,
version entitlement, or redistribution restrictions.

The first-launch activation service receives only identity, entitlement,
project-registration, and pseudonymous activation metadata. It does not receive
project assets, scenes, source files, animation, prompts, or other creative
work. See [PRIVACY.md](PRIVACY.md).

For mainstream distribution, Tech Connector Core is publicly source-available
under the controlling license. The complete first-party Official Tools Bundle
is one optional product delivered separately through an account-gated download
or repository. Users can install both together, keep them side by side, or point
Core at the bundle through its existing project/tool directory settings. Users'
own project directories and independently obtained tools do not require the
Official Tools Bundle entitlement. See
[docs/SOURCE_ACCESS_MODEL.md](docs/SOURCE_ACCESS_MODEL.md).

The intent is simple:

- Free for individuals, students, educators, hobbyists, researchers, nonprofits,
  and open-source projects.
- Free for registered Community projects through the first USD $500,000 of
  Adjusted Project Profit; only profit above that threshold may carry the
  accepted success-based residual.
- You own what you create with the tools.
- If a registered project never exceeds the profit threshold, it never owes a residual.
- Indie offers can use success-based, perpetual, or negotiated custom grants;
  studio classification and economics are signed, versioned backend terms.
- Enterprise entitlements are organization-bound, explicitly enabled, and use
  negotiated perpetual or custom terms rather than the public Community grant.
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
The implemented client data boundary is documented in [PRIVACY.md](PRIVACY.md);
that notice is a pre-release draft until counsel approves it for publication.

---

Architecture notes:

- `docs/UI_FEATURES_GUIDE.md` covers the main UI tabs, menus, settings, and workflow builder.
- `docs/BRIDGE_ARCHITECTURE.md` covers adding app bridges.
- `docs/DIRECT_DCC_BRIDGE.md` covers direct Maya, Unreal, Blender, Substance Painter, Unity, and MotionBuilder calls.
- `docs/LIVE_SOURCE_INGESTION.md` covers local-only versus live web/GitHub sourcing.
- `docs/HEADLESS_API.md` covers licensed API/function access without starting the UI.
- `docs/LICENSING_BACKEND_API.md` defines the private account, activation, and
  entitlement-service integration contract without exposing backend code.
- `docs/LICENSING_LAUNCH_READINESS.md` tracks the concrete P0/P1 launch gates
  and separates repository work from private-service and legal dependencies.
- `docs/REASONING_RUNTIME_API.md` explains reasoning requests, contextual threads, progress events, runtime tools, modular features, and extensions with runnable examples.
- `docs/MODEL_PROVIDERS.md` covers OpenAI/Google/Anthropic/local model routing.
- `docs/CODE_AGENT_WORKFLOW.md` covers explicit Ask/Plan/Edit/Review modes, scope,
  reasoning depth, permissions, reviewable diffs, repair, and regression evaluation.
- `docs/UNREAL_SMART_OPERATIONS.md` covers project-aware Unreal scans, navigation, capability validation, and safe prototype operations.
- `docs/ROUTING_ENTRYPOINT_AUDIT.md` and `docs/ENTERPRISE_INTERACTION_BYPASS_AUDIT.md` cover deterministic routing and remaining migration targets.

## Changed

- Editor answers now show the relevant source excerpt first.
- The actual explanation/direct answer appears below the source.
- `Ask About File` can now prepare conservative safe patches for obvious bugs.
- Added `Apply Fix` in the Editor tab.
- Applying a fix creates a `.tew_backup` first.
- The source launcher starts the UI with `pyw -3.14 -m tech_connector.app.main_window`.

## Current safe patch example

For `BrowseDirectory`, if the class defaults `directory=None` but calls
`directory.replace(...)`, the assistant can prepare a fix that guards `None` and
initializes the line edit from the normalized stored directory.

Single launcher:
`Start_The_Entire_World_AI_Studio.bat`
