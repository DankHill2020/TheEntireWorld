# Tech Connector Custom Backend Providers Developer Guide

This document provides instructions on how to use the **Customization Panel** to modularize your Tech Connector setup, followed by developer interface specifications for writing your own custom Python providers.

---

## 1. User Configuration Guide

The Customization Panel allows you to swap model classes, override processing services, and connect custom DCC bridge tools without writing code.

### A. Accessing the Panel
You can open the Customization Panel from the main menu bar of the Tech Connector application in three places:
1. `File > Customization Panel...`
2. `AI > Customization Panel...`
3. `Community > Customization Panel...`

### B. Models Configuration
In the **Models Configuration** tab, you can override the default Ollama models used by the Tech Connector:
- **Model Overrides**: Change the model strings (e.g. `qwen2.5-coder:14b`, `llama3:8b`) for semantic understanding, general chat, coding, or embedding tasks.
- **Custom Role Mappings**: Input a JSON dictionary to map specific inner application roles (e.g. `"my_custom_agent_role"`) to any Ollama model name.

### C. Backend Services (GitHub Ingest, Code Intel, Router, Planner)
In the **Backend Services** tab, you can override how tasks are executed. For **GitHub Ingestion**, you have a dropdown selector:
1. **Default (Built-In)**: Downloads the zip archive directly from GitHub and extracts it.
2. **MOD Tech Labs Pipeline**: Automatically routes the zip archive to your MOD Tech Labs pipeline for optimization/processing.
   - When selected, you must enter your **MOD API Key** and **MOD Workflow ID**.
   - The Tech Connector will trigger the workflow run, poll for completion, and download the processed workspace.
3. **Custom Python Module...**: Exposes a text input to enter the path of a custom Python module (e.g. `my_custom_ingest`).

Other services (Code Intel, Router, and Planner) accept a custom Python module path.

### D. Environment & Bridges (VCS, DCC Packages, DCC Bridges)
In the **Environment & Bridges** tab, you can configure integration extensions:
- **VCS Provider**: Set a class path (e.g. `my_vcs.MyVcsProvider`) to run custom version control tasks.
- **Custom DCC Packages**: Enter a comma-separated list of folder names inside your `TOOLS_ROOT` to load them as DCC packages.
- **Custom DCC Adapters**: Enter a JSON mapping of DCC names to custom execution adapters.
- **Custom DCC Bridges**: Enter a JSON mapping of DCC names to custom bridge delegates (e.g. `{"unreal": "ludus_bridge.LudusBridge"}`) to route all direct commands to custom tools like **LUDUS AI**.

### E. Validation & Recovery
- **Validate Configuration**: Click the **Validate Configuration** button at the bottom of the dialog. The system will inspect your custom settings and check if all modules can be imported correctly. If any module is missing or has the wrong signature, it will display a red error message.
- **Restore Defaults**: If a custom module path or model name causes the Tech Connector to crash or throw errors, reopen the panel and click the red **"Restore Defaults"** button. This will instantly revert settings to their factory defaults.

---

## 2. Developer Specifications & Interfaces

All swappable services support dynamic signature matching. Your custom functions do not need to accept all arguments; the system will inspect your function's signature using `inspect.signature` and forward only the arguments your implementation accepts.

### A. GitHub Ingestion (`github_ingest_provider_module`)
Your custom module can implement any of these entry points:

```python
from pathlib import Path
from typing import Optional, Callable

# Custom type or class matching GitHubRepoRef properties
class GitHubRepoRef:
    owner: str
    repo: str
    ref: Optional[str]
    ref_kind: str # 'branch' | 'tag' | 'commit'
    clean_url: str
    api_url: str

def parse_github_repo_reference(repo_ref: str) -> GitHubRepoRef:
    """Parse a GitHub reference string into a structured reference object."""
    pass

def github_api_repo_url(repo_ref: str) -> str:
    """Return the REST API endpoint for the repository."""
    pass

def download_and_extract_repo(
    repo_name: str, 
    repo_url: str, 
    target_parent_dir: Path, 
    progress_cb: Optional[Callable] = None
) -> Path:
    """Download the repository archive and extract it to the target parent directory."""
    pass

def ingest_github_repo(
    repo_ref: GitHubRepoRef, 
    target_dir: Path, 
    progress_cb: Optional[Callable] = None
) -> dict:
    """Compatibility entry point. Returns {'ok': bool, 'path': str, 'error': str}."""
    pass
```

### B. Code Intelligence (`code_intel_provider_module`)
Enables replacing the deterministic RAG and symbol analysis engine.

```python
from typing import Any

def build_code_intelligence_packet(
    objective: str,
    *,
    active_path: str | None = None,
    limit: int = 20,
    include_repo_map: bool = True,
) -> dict[str, Any]:
    """Gather context facts, symbols, or file paths for the prompt objective."""
    pass

def render_code_intelligence_packet(
    packet: dict[str, Any] | None, 
    *, 
    max_context_chars: int = 5000
) -> str:
    """Render the gathered packet into a string prefix injected into the prompt."""
    pass
```

### C. Cognitive Routing (`cognitive_routing_provider_module`)
Enables replacing how user prompts are parsed and categorized.

```python
class PromptRouteDecision:
    route: str
    confidence: float
    intent_category: str
    reasons: list[str]
    requires_plan: bool
    requires_confirmation: bool
    reasoning_pipeline: dict

def upgrade_route_decision(
    prompt: str, 
    baseline: PromptRouteDecision, 
    **kwargs
) -> PromptRouteDecision:
    """Analyze the prompt and augment or replace the baseline routing decision."""
    pass
```

### D. Planning Engine (`planning_provider_module`)
Enables replacing the A-to-Z execution DAG generator.

```python
from typing import Any

def build_goal_gap_plan(
    prompt: str, 
    decision: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return an action graph DAG dictionary with 'actions' and 'dependencies'."""
    pass
```

---

## 3. Version Control System (VCS) Provider (`vcs_provider_module`)

Your custom VCS class must subclass or implement the interface of `VersionControlProvider`:

```python
from pathlib import Path
from typing import Optional

class CustomVcsProvider:
    @property
    def kind(self) -> str:
        return "custom_vcs_name"

    def detect(self, root: Path) -> bool:
        """Return True if this VCS governs the given path."""
        pass

    def status(self, root: Path) -> str:
        """Return a summary string of the status."""
        pass

    def sync(self, root: Path) -> tuple[bool, str]:
        """Synchronize/update the workspace. Return (success, message)."""
        pass

    def checkout_file(self, path: Path) -> tuple[bool, str]:
        """Make a file writeable. Return (success, message)."""
        pass

    def revert_file(self, path: Path) -> tuple[bool, str]:
        """Revert changes to a file. Return (success, message)."""
        pass

    def changed_files(self, root: Path) -> list[dict]:
        """Return list of modified files, e.g. [{'path': str, 'status': str}]."""
        return []
```

---

## 4. DCC Execution Adapters (`custom_dcc_adapters`)

To execute scene queries and mutations inside DCC tools using your own logic, implement a class matching `DccExecutionAdapter` and register it in settings (e.g. `{"unreal": "my_module.MyUnrealAdapter"}`):

```python
from typing import Any

class MyDccExecutionAdapter:
    def execute_action(self, action: dict[str, Any], context: Any) -> dict[str, Any]:
        """Execute a plan action. Return response dict with 'status' ('succeeded'/'failed')."""
        pass

    def query_context(self, category: str, context: Any) -> Any:
        """Query state like active selection or file path."""
        pass
```

---

## 5. Custom DCC Bridges (`custom_dcc_bridges`)

If you want to route all direct communications to a running instance of a tool (e.g., routing Unreal commands to **LUDUS AI** instead of the built-in HTTP bridge), implement a custom bridge class. 

For instance, your Unreal bridge delegate might look like this:

```python
from typing import Any

class LudusUnrealBridge:
    def execute_python(self, source: str, timeout: float = 30.0, reset_globals: bool = False) -> dict[str, Any]:
        """Execute python code inside Unreal Engine."""
        # Route to LUDUS AI execution endpoint
        return {
            "ok": True,
            "output": "Executed via Ludus AI",
            "result": None
        }

    def health_check(self, timeout: float = 5.0) -> dict[str, Any]:
        """Check if the bridge connection is healthy."""
        return {"status": "healthy", "provider": "ludus"}
```

When configured in settings via `"custom_dcc_bridges": {"unreal": "my_ludus_module.LudusUnrealBridge"}`, the system's `UnrealBridge` will transparently instantiate this class and delegate all calls to it.
