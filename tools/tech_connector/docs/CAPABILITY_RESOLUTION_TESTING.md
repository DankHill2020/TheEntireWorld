# Capability Resolution Testing

The project-edit workflow resolves dependencies before code generation. A test
run should expose its decisions through the normal status stream.

## Expected resolution order

1. Generated-source overlay.
2. Project capability and symbol indexes.
3. Tools-root capability and symbol indexes.
4. Plugin, bridge, DCC catalog, and prepared host capability records.
5. Runtime installed-package reflection only for unresolved explicit package
   surfaces.
6. Official documentation only after every relevant local provider completed.
7. Reviewed GitHub acquisition only when no authoritative callable was found.

The workflow must never proceed to generation with an invented dependency.

## Status output

Successful grounding prints a line similar to:

```text
Pre-plan capability grounding: 6 intents, 14 evidence records, 312.4ms, cache=miss, online=no
Evidence decision: runtime_reflection=skip (prepared indexed evidence covered the requested surface)
Plan data-flow contracts: 4 callables, 7 bindings, 0 hard errors
```

Important terminal statuses:

| Status | Meaning |
| --- | --- |
| `capability_local_resolution_failed` | A relevant local provider failed. Online search was not allowed to hide the local failure. |
| `capability_acquisition_required` | Local and official sources completed without an authoritative callable. Review the attached GitHub acquisition request. |
| `plan_evidence_unresolved` | Required evidence is still missing and no safe acquisition action is available. |
| `invalid_evidence_request` | A generation worker returned a malformed evidence request. |
| `evidence_unresolved` | A focused generation-time question could not be answered authoritatively. |
| `evidence_resolved` | The same owner can resume with the returned evidence records. |
| `ok` | All required planning, generation, and validation gates passed. |

No failure status is completion.

## Automatic generation evidence resume

When an owner cannot answer one exact API question from its supplied evidence,
it may return `status=evidence_required` without code. The shared model router
resolves that request against the active project context and invokes the same
model again with only the new authoritative evidence.

There is no fixed evidence retry count. Repeating the same request fingerprint
stops immediately with `repeated_evidence_request`; a genuine source gap returns
`capability_acquisition_required`. Successful evidence events are preserved in
the final implementation plan under `generation_evidence_events`.

## Attribution requirements

Every downloaded repository must contain:

```text
TECH_CONNECTOR_ATTRIBUTION.json
```

The record includes repository owner, URL, requested reference, archive hash,
retrieval time, detected license, and the local credit statement. Downloaded
code remains review-only until its license and matching callable are verified.

## Suggested manual checks

Run the same prompt twice. The second run should report `cache=hit` when the
index revision and capability requirements are unchanged.

Use a request containing an indexed internal adapter. It should report
`online=no` and normally skip runtime reflection.

Use an explicit installed-package symbol absent from the prepared index. It
should run runtime reflection once rather than immediately searching online.

Use a deliberately unavailable dependency. The workflow should stop at
`capability_acquisition_required` and include a reviewed GitHub action rather
than generating a plausible import.

Inspect the approved plan. Every selected callable should have:

```text
callable_surface_contracts
data_flow_binding_obligations
evidence_reuse_policy
generation_evidence_request_protocol
```

Any downloaded third-party source must retain its attribution manifest even if
callable verification later fails.
