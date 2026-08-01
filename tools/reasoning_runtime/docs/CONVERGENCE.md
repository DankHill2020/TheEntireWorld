# Validation and Repair Convergence

`reasoning_runtime` owns the decision about whether a repair advances a task.
Domain packages own the concrete edits required by their files, APIs, hosts, or
application surfaces.

## Responsibility boundary

The runtime owns validation snapshots, failure identity, provider ordering,
candidate acceptance, preservation of the last validated candidate, and the
shared production-readiness protocol.

A domain package owns source parsing, patch construction, host/framework
validation, API evidence, syntax-specific transformations, and focused tests.

The runtime must never import a domain package, PySide, Maya, Unreal, Blender,
or another host API. Domain packages import runtime contracts and register
providers through `ReasoningKernel.install()`.

## Register a repair provider

```python
from reasoning_runtime import RepairContext, RepairProposal, RepairProvider


class MyRepairProvider(RepairProvider):
    name = "my_domain.project_edit"
    priority = 50

    def supports(self, context: RepairContext) -> bool:
        return context.metadata.get("domain") == "project_edit"

    def repair(self, context: RepairContext) -> RepairProposal:
        repaired = repair_only_owned_symbols(
            context.candidate,
            context.findings,
        )
        return RepairProposal(
            candidate=repaired,
            changed=repaired != context.candidate,
        )
```

Expose it from the domain package with `get_repair_providers()`.

## Run convergence

```python
from reasoning_runtime import RepairContext, ReasoningKernel

kernel = ReasoningKernel()
kernel.install(MyDomainPackage())
result = kernel.repair_coordinator().attempt(
    RepairContext(
        request=request,
        candidate=current_candidate,
        findings=tuple(current_findings),
        metadata={"domain": "project_edit"},
    ),
    validate=validate_candidate,
)
```

`ConvergencePolicy` accepts a transition only when the candidate changed, at
least one existing finding was resolved, the finding count decreased, and no
protected finding was introduced. An unchanged or non-monotonic repair never
replaces the current candidate.

Set `ValidationFinding.metadata["protected"] = True` for an invariant that a
repair may not introduce. Domains may alternatively pass an `is_protected`
predicate when classification requires domain evidence.
