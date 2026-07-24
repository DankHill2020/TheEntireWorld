# Live Source Ingestion

The Studio is local-only by default. Live web/GitHub sourcing is enabled only
when the `Web/GitHub` checkbox is on.

## Modes

```text
Local only:
Use local project files, local knowledge index, configured MCP tools, and LLM prompts.

Live web/GitHub:
Allow live searches and GitHub/project inspection when current external context matters.
```

## Intended Flow

1. User enables `Web/GitHub`.
2. User asks for a tool, workflow, plugin, or docs that may exist online.
3. Chat policy allows live web/GitHub context for normal prompts, or a
   repository-ingestion prompt opens the Web / GitHub Import dialog.
4. Assistant searches primary sources first:
   - official documentation
   - GitHub repository
   - release notes
   - package metadata
5. Assistant summarizes:
   - source URL/repo identity
   - apparent license
   - files or workflows worth ingesting
   - risk notes
6. User approves ingestion.
7. Studio downloads/extracts the selected GitHub repository through
   `services/github_ingest_service.py`, preserving folder structure and writing
   an ingest log.
8. User approves indexing, workflow composition, or bridge/plugin registration.

## Guardrails

Live source mode does not mean automatic trust.

The Studio should not:

```text
clone repositories
install dependencies
run downloaded code
overwrite local files
register new bridges/plugins
```

without explicit user approval.

## Current Implementation

Implemented pieces:

```text
services/source_policy.py
services/github_ingest_service.py
services/version_control_service.py
ui/unreal_editor_dialogs.py WebImportDialog
app/main_window_history_assets.py trigger_web_import
services/prompt/prompt_route_service.py github_ingest route
services/prompt/prompt_dispatch_service.py GitHubHandler UI passthrough
```

The current GitHub route is intentionally UI-mediated. `PromptDispatchService`
passes repository import intent to `MainWindow.trigger_web_import` instead of
silently downloading code from chat.

Supported GitHub inputs include shorthand, HTTPS, SSH, branch, tag, and commit
forms such as:

```text
owner/repo
github.com/owner/repo
https://github.com/owner/repo/tree/branch-name
https://github.com/owner/repo/releases/tag/tag-name
https://github.com/owner/repo/commit/sha
git@github.com:owner/repo.git
```

## Planned Improvements

Suggested services:

```text
services/source_search_service.py
services/source_review_service.py
```

Suggested staging path:

```text
%LOCALAPPDATA%\TA_AI_Studio_MCPHost\source_staging
```

Suggested capabilities:

```text
search_github(query)
inspect_repo(url)
summarize_license(repo)
stage_repo(url) / download_and_extract_repo(url)
index_staged_source(path)
register_bridge_from_manifest(path)
```
