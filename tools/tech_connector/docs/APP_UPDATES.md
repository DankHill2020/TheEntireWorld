# App Updates

Tech Connector can update itself when it is running from a Git checkout.

Menu:

```text
Tools > App Updates > Check Git Status
Tools > App Updates > Update from Latest
Tools > App Updates > Update from Git Ref
```

`Update from Latest` runs:

```text
git fetch --all --prune
git pull --ff-only
```

`Update from Git Ref` accepts a branch, tag, or commit SHA and runs:

```text
git fetch --all --prune
git checkout <ref>
```

Both update paths refuse to run when the working tree has local changes. Commit,
stash, or discard local edits first. Restart Tech Connector after an update changes
the checked-out commit.
