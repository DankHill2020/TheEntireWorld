# Reasoning Runtime Separation Testing

Tech Connector uses `reasoning_runtime` as a standalone package. The runtime
must never import Tech Connector; Tech Connector installs its DCC-specific
adapters through `tech_connector.adapters.domain_package`.

## Smoke Test

Run from `C:/depot/tools`:

```powershell
python tech_connector/scripts/run_reasoning_runtime_smoke.py
```

This verifies:

- importing `reasoning_runtime` alone does not import `tech_connector`
- `TechConnectorDomainPackage` installs the expected adapters into `ReasoningKernel`
- the package installs its project-edit repair provider without reversing the
  runtime dependency boundary
- `RequestEngine.process(...)` attaches `reasoning_runtime` metadata for the UI path
- sensitive prompt context is sanitized before entering runtime metadata
- progress events still emit through the Tech Connector request path

## Runtime Unit Tests

```powershell
python -m unittest discover reasoning_runtime\tests
```

This verifies the standalone runtime contracts, including import boundaries,
prompt contracts, model provider locking/escalation, indexing contracts,
request preparation, repair-provider registration, and monotonic convergence
decisions.

## Source Compile Check

```powershell
python -m compileall -q reasoning_runtime tech_connector
```

This catches stale imports and syntax errors across the active Python packages.
An inaccessible `.pytest_cache` directory can be reported by `compileall` without
failing the command.

## Expected Dependency Direction

Allowed:

```text
tech_connector -> reasoning_runtime
tech_connector.adapters.domain_package -> tech_connector.adapters -> reasoning_runtime contracts
```

Forbidden:

```text
reasoning_runtime -> tech_connector
reasoning_runtime -> DCC APIs such as Maya, Unreal, Blender, PySide
```
