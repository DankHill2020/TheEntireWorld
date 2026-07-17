# AI Agent Workflow

1. Understand the goal.
2. Search the project's existing tools first.
3. Search local knowledge/docs second.
4. If no existing tool solves it, generate a helper.
5. Save new helpers only under `ai_generated/pending_review`.
6. Execute/test in Maya or Unreal.
7. Verify.
8. Report files read, tools used, code written, execution result, and verification.

## Safety
Ask before destructive or persistent actions.

## Generated Code Policy
New AI-generated tools must start in:
`<project root>/ai_generated/pending_review`
