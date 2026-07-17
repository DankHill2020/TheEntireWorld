# Maya Python Quick Reference

For Maya actions, use `maya__maya_execute_python`.

Always print results.

## Current scene file
```python
import maya.cmds as cmds
print(cmds.file(q=True, sceneName=True))
```

## Selected objects
```python
import maya.cmds as cmds
print(cmds.ls(sl=True))
```

## All joints
```python
import maya.cmds as cmds
print(cmds.ls(type="joint"))
```

## Current frame
```python
import maya.cmds as cmds
print(cmds.currentTime(q=True))
```

## Add tools depot to sys.path
```python
import sys
path = r"C:/depot/tools"
if path not in sys.path:
    sys.path.append(path)
print("Added tools path")
```

## Safety
Ask before deleting, saving, exporting, overwriting, mass renaming, modifying references, or running external processes.
