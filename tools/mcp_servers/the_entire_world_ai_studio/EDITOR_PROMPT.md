# Editor Prompt

v5.8 adds an editor-specific prompt row.

## Buttons

```text
Ask About File
Ask Selection
Plan Edit
```

## Behavior

The editor prompt sends the currently open file or selected code to the chat context.

This is intentionally separate from direct DCC execution:

```text
Editor prompt = ask/reason about code
Maya/Unreal direct buttons = execute deterministic host actions
```

## Future improvements

- Show editor answers beside the file instead of switching to Chat
- Apply AI patches with preview
- Inline comments
- Diff viewer
- Accept/reject changes