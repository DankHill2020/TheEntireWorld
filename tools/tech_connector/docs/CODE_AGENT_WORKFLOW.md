# Code Agent Workflow

Tech Connector exposes one explicit request contract above the prompt composer.
The contract is stored with route metadata and is enforced after natural-language
classification, so an inferred mutation can never override a user-selected
read-only mode.

## Request controls

| Control | Values | Effect |
| --- | --- | --- |
| Mode | Auto, Ask, Plan, Edit, Review | Selects the requested outcome. Ask, Plan, and Review are read-only. |
| Scope | Auto, Selection, Current file, Folder, Project, DCC session | Caps discovery and generation context. |
| Depth | Fast, Balanced, Deep, Maximum quality | Selects the OpenAI model tier, reasoning effort/context, and response verbosity. |
| Permission | Read only, Preview changes, Apply after review, Automatic safe edits | Sets the maximum local mutation authority. Destructive and external actions remain separately gated. |

Read-only modes always normalize the permission to `read_only`, including when
an older settings file contains a stale mutation-capable value. An inferred edit,
DCC execution, capability-acquisition, action-graph, or pipeline route is converted
to read-only project inspection when Ask, Plan, or Review is selected.

## Depth and OpenAI execution

OpenAI API-key requests use the Responses API. The current presets are:

| Depth | Model | Reasoning | Context | Verbosity |
| --- | --- | --- | --- | --- |
| Fast | `gpt-5.6-luna` | low | current turn | low |
| Balanced | `gpt-5.6-terra` | medium | all turns | medium |
| Deep | `gpt-5.6-sol` | high | all turns | medium |
| Maximum quality | `gpt-5.6-sol` | max, pro | all turns | high |

The model selector follows the chosen depth when OpenAI automatic model selection
is enabled and the selected model belongs to the GPT-5.6/Codex family. Explicitly
selected unrelated models are preserved.

Structured output is sent as `text.format`; developer instructions use
`instructions`; response text is read from `output_text` or the typed output
content sequence. Temperature is omitted for GPT-5 and reasoning model families.

## Model catalog discovery

The Settings model-provider page has a **Refresh models** action. With an API key,
it requests the provider's model-list endpoint in a background thread, merges the
result with the built-in compatibility catalog, caches it for 15 minutes, and
persists the last successful catalog. Static entries remain available offline.

Supported discovery endpoints are OpenAI, Anthropic, Google, and xAI. Account-login
transports continue to work without catalog discovery; discovery itself requires
the corresponding provider API key.

## Review and repair

Generated changes open in the editor diff review surface. Reviewers can:

- include or exclude whole files;
- include or exclude individual changed hunks;
- switch between rendered file content and unified diff;
- see production-readiness and Python syntax evidence before application;
- apply only the selected changes; and
- send failed validation back through a focused repair request.

Python changes are compiled again immediately before the Apply Selected action.
Generation and repair operate on disposable candidates. Project-file writes remain
subject to the selected permission and the existing approval fingerprint.

## Prompt policy

Every normal model prompt receives one compact `CODE REQUEST CONTRACT`. The
project-edit workflow additionally uses one shared invariant policy for API
grounding, scoped repair, blockers, and write authority. Repeated lines are
deduplicated and the before/after character counts are recorded in stage metadata.

This replaces repeated, sometimes conflicting approval prose in individual prompt
layers. A stage-specific response schema and evidence packet remain authoritative.

## Evaluation

Run the profile-aware deterministic benchmark from the repository tools folder:

```powershell
.\.venv\Scripts\python.exe -m tech_connector.scripts.run_prompt_route_plan_eval `
  --fixture tech_connector/scripts/code_prompt_eval_cases.json `
  --project-root C:/depot/tools
```

The cases cover read-only authority, mutation-route demotion, Edit preview routing,
review behavior, DCC scope, confirmation gates, execution suppression, and cold
route timing. Product-level API, provider-catalog, prompt-compaction, and hunk-review
regressions live in `tech_connector/tests/test_code_prompt_product.py`.

For end-to-end coding quality and performance against Codex, including hidden
behavioral graders, disposable repositories, scope scoring, latency, and token
telemetry, see [CODE_AGENT_BENCHMARK.md](CODE_AGENT_BENCHMARK.md).

## Relevant implementation modules

- `services/code_prompt_profile_service.py`: normalization and authority contract.
- `services/llm_router_service.py`: provider routing and OpenAI Responses adapter.
- `services/provider_model_catalog_service.py`: current provider model discovery.
- `services/project_edit_prompt_policy_service.py`: shared compact edit policy.
- `ui/game_engine/unreal_editor_dialogs.py`: canonical diff review surface.
- `services/prompt/prompt_route_eval_service.py`: profile-aware route evaluation.
