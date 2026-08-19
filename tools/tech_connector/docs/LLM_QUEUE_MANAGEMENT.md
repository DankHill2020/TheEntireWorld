# LLM Queue Management

Tech Connector routes production LLM calls through a process-wide,
provider-aware queue. The queue prevents overlapping local inference from
exhausting GPU or system memory while allowing separately bounded cloud
provider concurrency.

## Scheduling behavior

- All Ollama models share the `ollama` lane. The default concurrency is one.
- Ollama model warm, residency, and unload requests use that lane as background
  work, preventing resource maintenance from racing active inference.
- Each cloud provider has an independent lane. The default concurrency is four.
- Pending work is bounded. A full lane raises `LLMQueueFullError` immediately.
- Work is priority ordered, FIFO within equal priority, and receives an aging
  boost to prevent starvation.
- Supported categories are `interactive`, `repair`, `validation`, and
  `background`, in descending default priority order.
- A supersede key replaces older queued work with the same key. It does not
  terminate a provider call that has already started.
- A queue deadline limits how long work may wait before starting. The provider
  timeout still governs the inference call after it starts.

## Configuration

The following values can be set in normal Tech Connector settings:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `llm_local_max_concurrent` | `1` | Active calls in the shared Ollama lane. |
| `llm_cloud_max_concurrent` | `4` | Active calls in each cloud-provider lane. |
| `llm_local_queue_max_pending` | `32` | Pending Ollama requests. |
| `llm_cloud_queue_max_pending` | `64` | Pending requests per cloud provider. |
| `llm_queue_max_pending` | `32` | Fallback bound when a lane-specific value is absent. |
| `llm_queue_aging_seconds` | `15.0` | Interval used to increase waiting work's effective priority. |

Lowering concurrency takes effect without interrupting active work. Existing
worker threads become idle until the configured active limit permits them to
run another request.

## Submitting categorized work

`generate_llm_response` remains synchronous and keeps its existing return and
exception behavior. Queue controls are optional keyword arguments:

```python
from tech_connector.services.llm_router_service import generate_llm_response

response = generate_llm_response(
    "Repair the selected function",
    settings,
    queue_category="repair",
    queue_request_id="editor-repair-42",
    queue_supersede_key="active-editor-repair",
    queue_deadline_seconds=20.0,
)
```

Use a stable `queue_request_id` when another thread, UI control, or service may
need to cancel or correlate the request. Use a supersede key for replaceable
work such as validation of rapidly changing editor content.

## Status and cancellation

The supported headless API exposes JSON-compatible telemetry and targeted
cancellation:

```python
from tech_connector.api import cancel_llm_request, llm_queue_status

snapshot = llm_queue_status()
cancelled = cancel_llm_request("editor-repair-42", "User cancelled the repair.")
```

The same operations are available on `TechConnectorHeadlessAPI` as
`api.llm_queue_status()` and `api.cancel_llm_request(...)`, and through the
`llm.queue` feature registry entry.

Snapshots include lane depth, configured capacity, completed/failed/cancelled
counters, average queue and provider durations, active requests, and bounded
recent history. They do not expose prompts or executable callbacks.

Cancellation is immediate for queued work. For a running synchronous HTTP
provider call, cancellation releases the waiting caller and marks the queue
request cancelled, but the underlying provider call may finish in its worker
thread because standard provider clients cannot reliably abort an in-flight
request. The lane remains occupied until that call returns.
