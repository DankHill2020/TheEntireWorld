# Packaging Tech Connector

Tech Connector supports two staged release tiers:

- `reasoning-runtime`: the application, reasoning runtime, DCC integration code,
  documentation, and core assets without bundled third-party tool depots.
- `full-tools`: the complete first-party tool package, including Blender,
  Houdini, 3ds Max, Maya, MotionBuilder, Substance Painter, Unreal, shared
  pipeline utilities, Qt helpers, and the Unreal plugin source.

Both tiers omit tests, generated knowledge databases, capability registries,
Python bytecode, local state, build staging, and downloaded tool payloads. A
clean installation rebuilds its local indices when needed.

Stage and validate a tier with Python 3.14:

```powershell
py -3.14 -m tech_connector.packaging.stage_package reasoning-runtime --out dist/staged
py -3.14 -m tech_connector.packaging.smoke_test_package dist/staged/reasoning-runtime
```

Every staged result contains `PACKAGE_MANIFEST.json`, including the SHA-256 and
size of each shipped file. Install `requirements-runtime.txt` for supported core
features. `requirements-optional.txt` lists heavier integrations with graceful
fallbacks. Maya, Blender, Unreal, MotionBuilder, and Substance modules are
provided by their host applications and are not ordinary pip dependencies.
