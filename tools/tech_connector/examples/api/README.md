# Tech Connector API Examples

These examples use the installed Tech Connector login and provider settings.
They do not contain provider API keys or machine-specific project paths.

Set an optional project root:

```powershell
$env:TECH_CONNECTOR_PROJECT_ROOT = "C:\my_project"
```

Run an example with the Tech Connector virtual environment:

```powershell
C:\path\to\tools\.venv\Scripts\python.exe reasoning_quickstart.py
```

Examples:

| File | Demonstrates |
| --- | --- |
| `reasoning_quickstart.py` | API creation, login check, capabilities, and one reasoning request |
| `thread_context_example.py` | Caller-owned canonical conversation history |
| `feature_registry_example.py` | Granular discovery and adapter invocation |
| `custom_feature_example.py` | Registering an external modular feature |
| `feature_replacement_example.py` | Replacing one feature contract in one API instance |
| `custom_runtime_package_example.py` | Adding context to the reasoning setup through a runtime package |
| `tool_approval_example.py` | Tool schemas, mutability, and safe dry runs |

Read [REASONING_RUNTIME_API.md](../../docs/REASONING_RUNTIME_API.md) for the
complete explanation and method reference.
