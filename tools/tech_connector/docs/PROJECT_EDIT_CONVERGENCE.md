# Project Edit Convergence Architecture

Tech Connector uses the standalone `reasoning_runtime` package for generic
repair coordination. Python, Qt, DCC, and project-file logic remains inside
Tech Connector.

## Runtime-owned behavior

- `ConvergencePolicy` decides whether a candidate repair is monotonic.
- `RepairCoordinator` orders registered domain providers.
- `RepairContext` carries the candidate and exact validation snapshot.
- `ProductionReadiness`, `ValidationFinding`, and `RepairRecord` remain the
  shared UI/headless result protocol.

## Tech Connector-owned behavior

- Python AST validation and symbol-level replacement;
- generated sibling imports and cross-file callable routing;
- Qt signal, worker, progress, and cleanup contracts;
- Maya, Unreal, Blender, and MotionBuilder evidence;
- disposable Python behavior harnesses;
- application-local bridge execution.

`TechConnectorProjectEditRepairProvider` is registered by
`TechConnectorDomainPackage.get_repair_providers()`. It delegates concrete
repair to `RepairContext.metadata["repair_callable"]`. The provider proposes a
candidate; runtime convergence decides whether the candidate is better after
validation.

## Dependency direction

```text
tech_connector
    -> reasoning_runtime contracts

reasoning_runtime
    -X-> tech_connector
    -X-> PySide / Maya / Unreal / Blender / MotionBuilder
```

## Current workflow integration

The deterministic project-edit transaction converts before/after validation
snapshots into runtime `ValidationFinding` records and calls
`ConvergencePolicy.evaluate()`. Domain-specific protected declarations are
marked in finding metadata before evaluation.

Concrete repair passes remain in `project_edit_workflow_service.py` and can
move behind `TechConnectorProjectEditRepairProvider` incrementally without
changing runtime policy or the public completion protocol.

## Callback example

```python
def repair_project(context):
    candidate = repair_exact_owner_chunks(
        context.candidate,
        context.findings,
    )
    return {
        "candidate": candidate,
        "changed": candidate != context.candidate,
        "owner": "project_edit",
        "strategy": "exact_owner_chunks",
    }
```

The caller validates the proposed candidate and submits both snapshots to the
runtime policy. A proposal is never production-ready merely because a provider
returned it.
