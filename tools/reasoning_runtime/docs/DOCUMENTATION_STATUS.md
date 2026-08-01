# Documentation Status

This page distinguishes current architecture guidance from historical planning
records. Use it when two documents appear to describe different ownership.

## Current Runtime Documentation

| Document | Use it for |
| --- | --- |
| [EXTENSION_GUIDE.md](EXTENSION_GUIDE.md) | Supported runtime contracts and domain extension points |
| [USAGE.md](USAGE.md) | Installing a domain package and using runtime APIs |
| [CONVERGENCE.md](CONVERGENCE.md) | Validation findings, repair providers, and convergence acceptance |
| [INTEGRATION_STATUS.md](INTEGRATION_STATUS.md) | Current runtime/Tech Connector ownership boundary |

## Current Tech Connector Documentation

| Document | Use it for |
| --- | --- |
| [REASONING_RUNTIME_API.md](../../tech_connector/docs/REASONING_RUNTIME_API.md) | Public Tech Connector API and lifecycle feature access |
| [CUSTOMIZATION_GUIDE.md](../../tech_connector/docs/CUSTOMIZATION_GUIDE.md) | Replacing or extending adapters, policies, validation, and repair |
| [PROJECT_EDIT_CONVERGENCE.md](../../tech_connector/docs/PROJECT_EDIT_CONVERGENCE.md) | Concrete project-edit integration with runtime convergence |
| [REASONING_RUNTIME_TESTING.md](../../tech_connector/docs/REASONING_RUNTIME_TESTING.md) | Runtime separation and integration checks |

## Point-In-Time Reports

Audit and production-readiness reports elsewhere in Tech Connector are evidence
from the date they were produced, not active API guidance. Superseded migration
plans and compatibility-shim inventories are removed instead of being retained
as instructions.

## Current Ownership Rule

```text
reasoning_runtime
  owns validation/repair contracts, provider coordination, and convergence policy

domain package (for example, tech_connector)
  owns concrete candidate mutation, host behavior, and domain validation
```

When documentation conflicts, this ownership rule and the current documents
listed above take precedence over point-in-time audit reports.
