# Live Demo Readiness

Tech Connector treats demo readiness as two equally important lanes:

- prompt-driven behavior, including understanding, routing, planning, progress,
  generation, validation, repair, and completion
- direct UI behavior, including menus, graph editing, search, model selection,
  editor actions, history, and status feedback

Passing only one lane is not sufficient for a live-demo claim.

## Run the Focused Suite

```powershell
C:\depot\tools\.venv\Scripts\python.exe `
  C:\depot\tools\tech_connector\scripts\run_live_demo_readiness.py
```

The runner:

- runs independent feature lanes so one failure does not hide later failures
- prints each lane's purpose, pytest output, and wall time
- returns a nonzero exit code if any lane fails
- writes reports and pytest temporary files under the system temporary folder
- disables bytecode and pytest cache output in the project
- does not impose an arbitrary feature timeout

Run selected lanes:

```powershell
python tech_connector\scripts\run_live_demo_readiness.py --lane direct_ui
python tech_connector\scripts\run_live_demo_readiness.py --lane pipeline_ui
python tech_connector\scripts\run_live_demo_readiness.py --lane prompt_runtime
python tech_connector\scripts\run_live_demo_readiness.py --lane api_runtime
```

Include the real local-model prompt smoke:

```powershell
python tech_connector\scripts\run_live_demo_readiness.py --include-live
```

The `live_model` lane is not a mocked model-selection test. It invokes
`prompt_smoke_ollama.py` with `--require-synthesis`, prints the selected model,
first-token time, inference time, total time, output assessment, and returns a
failure exit code when the assessed output fails.

## Readiness Lanes

| Lane | Visible risk covered |
| --- | --- |
| `direct_ui` | Prompt editing, streaming, autocomplete, model selection, editor progress |
| `pipeline_ui` | Smart menus, source-aware function search, graphs, code materialization |
| `prompt_runtime` | Progress, routing, understanding, previews, exact-index fast paths |
| `api_runtime` | Non-UI parity, modular providers, model selection, API discovery |
| `live_model` | Forced real Ollama synthesis with first-token, inference, and total timing |

## Pass Rules

A run is `passed` only when every selected lane exits successfully. A failed
lane is never reported as complete or production-ready.

Speed is reported rather than hidden behind one global budget. Slow individual
tests appear in pytest's duration table so optimization can target the actual
stage instead of shortening retries or dropping validation.

## Expansion Rule

Every visible feature should have:

1. a deterministic contract test for its stable behavior
2. a UI interaction test when a user can click, type, drag, connect, or select it
3. a timing signal around work that can block visible feedback
4. a real integration lane when it depends on a model, DCC, bridge, or external service
5. useful failure output naming the feature, action, stage, and evidence

New tests belong in the lane matching what the user experiences. Test reports
and generated artifacts must remain in the system temporary directory.
