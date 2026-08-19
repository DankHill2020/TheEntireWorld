# Code Agent Quality and Performance Benchmark

This benchmark compares Tech Connector's production project-edit workflow with
Codex non-interactive mode on identical disposable repositories. It measures the
product as configured, not just the underlying language model.

## What is measured

- behavioral correctness with evaluators unavailable during generation;
- deterministic maintainability, including public documentation, dead literals,
  redundant lock nesting, overlong lines, and readable docstring layout;
- Python syntax across the completed workspace;
- scope discipline against an explicit path allowlist;
- completion and patch size;
- wall-clock latency and time to first Codex event;
- input, cached-input, output, and reasoning tokens when the adapter reports them;
- Codex command/tool/file-change events; and
- aggregate pass rate, quality, latency, and quality points per minute.

Quality and speed remain separate columns. The report does not allow a quick but
incorrect attempt to look successful, and it does not turn a large patch into a
quality bonus.

## Cases

| Case | Product lane | Primary risk |
| --- | --- | --- |
| `dcc_falsey_result` | Shared DCC execution | Falsey host results incorrectly treated as failure |
| `dcc_shared_path_policy` | Blender/Maya consolidation | Duplicate, inconsistent, unsafe export paths |
| `image_viewer_lru_cache` | Image viewer | TTL, LRU, falsey values, thread safety, hot-path cost |
| `game_engine_command_registry` | Game engine | Alias collisions, capability checks, atomic concurrency |
| `game_engine_operation_contract` | Game engine integration | Planner, registry, wrapper, serialization, and executor drift |
| `prompt_priority_job_queue` | Prompt runtime | Priority/FIFO ordering, cancellation, falsey payloads, and producer concurrency |

Every workspace contains only the seed source. Its evaluator is written after the
agent exits, then executed in a separate Python process with a timeout.

## Run a small live comparison

From `C:\depot\tools`:

```powershell
.\.venv\Scripts\python.exe -m tech_connector.benchmarks.code_agent.cli `
  --agent both `
  --case dcc_falsey_result `
  --keep-workspaces
```

Run the complete matrix with three repetitions:

```powershell
.\.venv\Scripts\python.exe -m tech_connector.benchmarks.code_agent.cli `
  --agent both `
  --repeat 3 `
  --codex-model gpt-5.6-terra `
  --codex-model gpt-5.6-sol
```

Use `--tech-model` to choose a Tech Connector route. The default is the installed
local `ollama:qwen2.5-coder:7b`. A cloud route such as `openai:gpt-5.6-sol`
requires that provider to be connected in Tech Connector. Codex reuses its saved
CLI authentication. The report records whether API-key environment variables are
present, but never writes credential values.

If the Microsoft Store app exposes an AppX alias that cannot execute from a test
runner, pass a normal CLI binary with `--codex-executable` or set
`TECH_CONNECTOR_CODEX_EXECUTABLE`.

The Codex adapter follows the official
[non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
contract: `codex exec` emits JSONL with `--json`, runs ephemerally, and retains
the CLI's normal authentication and workspace-write approval boundary.

By default, artifacts go to
`%TEMP%\tech_connector_code_agent_benchmarks\<timestamp>`. Each attempt retains
JSON metadata, adapter logs, hidden-evaluator output, and its score. Workspaces are
removed unless `--keep-workspaces` is supplied.

## Scoring

| Dimension | Points |
| --- | ---: |
| Hidden behavioral assertions | 60 |
| Deterministic maintainability | 10 |
| Syntax | 10 |
| Scope discipline | 10 |
| Completed patch | 10 |

A credible comparison should use at least three repetitions per case and model.
Run the matrix on an otherwise idle machine, alternate model order between larger
runs, retain failures, and compare medians plus P95 latency rather than only the
fastest attempt. Local-model token counts come from Ollama inference telemetry;
Codex counts come from its `turn.completed` JSONL usage event. A zero count means
the adapter did not expose telemetry for that run.

Version 1.2 prevents behaviorally correct but visibly weak code from receiving a
perfect score. A patch loses maintainability credit for generic or missing public
docstrings, displaced string literals, redundant nested `self._lock` contexts,
or generated lines longer than 120 characters.

This suite is deliberately small enough for frequent regression checks. It is not
a replacement for full-repository acceptance tests, DCC host integration tests,
or human review of architecture and UX.

## Verified live baseline

The first eligible Windows baseline was captured on 2026-08-09 with one isolated
repetition per case. Tech Connector used `ollama:qwen2.5-coder:7b`; Codex used the
authenticated default model selected by `codex-cli 0.147.0-alpha.6.5`. The model
name behind Codex's `default` route was not exposed, so this table does not infer
one. The local benchmark process used the project virtual environment's Python
3.13.3; Python 3.14 remains the repository target but was not the active local
runtime for these measurements. These historical results used the earlier 1.1
scoring contract and should not be compared directly with 1.2 maintainability
scores.

| Case | Agent | Result | Hidden assertions | Wall time | Input tokens | Cached input | Output tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `dcc_falsey_result` | Tech Connector | 100/100 | 12/12 | 119.37 s | 35,586 | 0 | 6,153 |
| `dcc_falsey_result` | Codex default | 100/100 | 12/12 | 41.41 s | 88,208 | 75,264 | 1,120 |
| `dcc_shared_path_policy` | Tech Connector | 100/100 | 21/21 | 120.52 s | 40,098 | 0 | 3,369 |
| `dcc_shared_path_policy` | Codex default | 96.7/100 | 20/21 | 69.53 s | 95,419 | 77,312 | 2,110 |

Both products were perfect on the focused result-envelope repair. On the stricter
cross-file DCC case, Tech Connector passed all 21 assertions while Codex passed
20: Codex incorrectly appended `.fbx` to an existing `.obj` suffix. Tech Connector
was 2.88 times slower on the focused single-function repair and 1.73 times slower
on the cross-file consolidation; combined wall time was 2.16 times higher. After
live status streaming was added, the cross-file run's first Tech Connector update
arrived at 0.43 seconds, versus the first Codex JSONL event at 0.58 seconds. The
remaining performance gap is completion latency rather than silent-start latency.

Token totals describe different orchestration designs and must not be treated as
model-efficiency equivalents. Tech Connector sums local inference telemetry.
Codex reports turn usage, including cached input and its tool-driven inspection
loop. Quality and wall time are the directly comparable primary measurements.

These are smoke-baseline results, not a statistically stable leaderboard. A
release comparison should run all four cases at least three times, alternate run
order, and report medians and P95 latency. A run is eligible only when the agent
transport works, the process reaches its own terminal status, and the hidden
evaluator executes. For example, an earlier Codex path-policy attempt blocked by
Windows socket error 10013 was excluded as an infrastructure failure rather than
scored as a product-quality failure.

The baseline exposed and drove fixes for existing-function ownership, explicit
multi-file declaration ownership, unrelated DCC evidence leakage, invented
cross-adapter dependencies, falsey result contracts, redundant repair retries,
disposable harness contradictions, live timeout diagnostics, validation-cycle
state, reviewer false positives, and completion scoring. Manual review also found
that the original 14-assertion path grader missed relative project roots and
existing non-FBX suffixes. It was first strengthened to 16 behavioral assertions,
then to 19 assertions so the requested `:param`/`:return:` docstring convention
was executable rather than subjective, and finally to 21 so adapter annotations
must describe `str | Path` inputs and `Path` outputs rather than broad `object` or
`Any` boundaries. The docstring pass also exposed a Tech
Connector semantic-review hallucination: the source contained every required
annotation and field, but the reviewer claimed they were absent and entered a
repair cycle. Source-backed AST/docstring proof now prevents that failure. The
remaining measured gap is primarily planning/review latency: the cross-file Tech
run still performs several small ownership-planning and disposable
harness-generation calls before completion.

## Python 3.14 randomized regression round

A second live round was captured on 2026-08-09 after rebuilding `.venv` with
CPython 3.14.7. The case order was selected with seed `20260809`:
`image_viewer_lru_cache`, then `game_engine_command_registry`. Each attempt used a
fresh disposable workspace and the hidden evaluator was materialized only after
the agent exited.

| Case | Agent | Result | Hidden assertions | Wall time | Input tokens | Output tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `image_viewer_lru_cache` | Tech Connector (`qwen2.5-coder:7b`) | 100/100 | 15/15 | 73.30 s | 19,712 | 2,575 |
| `image_viewer_lru_cache` | Codex default | 100/100 | 15/15 | 72.16 s | 101,318 | 2,515 |
| `game_engine_command_registry` | Tech Connector (`qwen2.5-coder:7b`) | 100/100 | 15/15 | 170.37 s | 34,882 | 2,670 |
| `game_engine_command_registry` | Codex default | 100/100 | 15/15 | 61.08 s | 96,812 | 2,279 |

The final eligible attempts were all behaviorally perfect. Tech Connector was
roughly tied with Codex on the image cache and 2.79 times slower on the command
registry. The game-engine gap came primarily from the source-grounded semantic
review; the deterministic implementation and public-API runtime proofs completed
well before the final review response.

The initial Tech Connector attempts in this round were not eligible baselines:
they stopped at plan correction before modifying a file. Repeated live reruns
then exposed defects in existing-class ownership, qualified callable extraction,
TTL/LRU state separation, constant-clock testing, atomic registry invariants,
generated fixture ownership, invalid `patch.call` references, and semantic-review
claims contradicted by executable AST evidence. Those defects now have focused
regression tests. Intermediate partial scores were retained as diagnostic
artifacts, but only fresh terminal `preview_ok` runs are reported above.

## Transactional repair regression round

On 2026-08-10, after adding bounded LLM queues, falsey-result diagnosis fixes,
strict repair ownership, and transactional patch application, two fresh local
Qwen attempts passed their hidden evaluators:

| Case | Result | Hidden assertions | Wall time | Changed files | Scope violations |
| --- | ---: | ---: | ---: | ---: | ---: |
| `dcc_falsey_result` | 100/100 | 12/12 | 113.51 s | 1 | 0 |
| `dcc_shared_path_policy` | 100/100 | 21/21 | 124.97 s | 3 | 0 |

The authenticated Codex comparison lane was attempted but remained ineligible:
Windows denied execution of the Microsoft Store AppX binary with `WinError 5`
before the CLI process started. That attempt is recorded as infrastructure
failure and is not included in comparative quality or latency conclusions.

The queue integration initially caused local inference metrics to remain keyed
to the worker thread. A subsequent production fix transfers those metrics to
the synchronous submitting thread. A real Qwen smoke call then reported 35
input tokens, 3 output tokens, and 80.02 generated tokens per second, confirming
that future benchmark attempts can collect queue-backed telemetry again.

## Prompt-to-code reliability round

On 2026-08-11, the `image_viewer_lru_cache` case was repeatedly executed from
fresh seed workspaces to investigate near-correct and stalled prompt-to-code
results. The initial attempt passed 13/15 hidden assertions but exposed an
invalid disposable test produced after rejection cleanup. Later attempts
retained behaviorally correct candidates while cycling between non-idempotent
test-fixture transformations or following an incorrect LRU oracle.

The resulting fixes made multi-file undo transactional, rejected duplicate
active queue request identifiers, prevented inference metrics from leaking
between prompts, rejected placeholder-only repair owners, kept disposable test
cleanup syntactically valid, inferred exact callable ownership from ordered
behavior steps, made fixture repair AST-idempotent, and grounded cache recency
proofs in their explicit behavior bindings.

The unchanged final live case completed successfully:

| Case | Status | Result | Hidden assertions | Wall time | Input tokens | Output tokens | Scope violations |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `image_viewer_lru_cache` | `preview_ok` | 100/100 | 15/15 | 87.23 s | 20,214 | 3,180 | 0 |

The final production regression contained 498 passes and 7 skips. The separate
reasoning runtime passed 30 tests, while the broader prompt/project-edit example
corpus passed 299 tests and 138 subtests.
