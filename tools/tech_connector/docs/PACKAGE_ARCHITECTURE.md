# Package architecture

Tech Connector separates headless domain behavior from Qt editor surfaces and
host-specific bridges.

```text
tech_connector/
├── app/                         desktop application orchestration
├── engine/                      AI request preparation and dispatch
├── game_engine/                 headless scene authoring and runtime
│   ├── assets/
│   ├── authoring/
│   ├── deformation/
│   ├── integration/
│   ├── rendering/
│   ├── runtime/
│   └── scene/
├── bridges/                     host-specific Blender, Maya, Unreal, etc.
├── services/                    application and cross-domain services
└── ui/
    ├── dcc_viewer/              connected scene viewer
    │   └── mesh_painter/        3D painting viewport implementation
    ├── game_engine/             sequencer, simulation, and engine editor UI
    └── image_viewer/            image canvas, editor, and inspection
```

## Dependency direction

UI packages may depend on `game_engine`, services, and bridges. Headless
`game_engine` scene, authoring, deformation, and runtime modules must not depend
on Qt or on legacy compatibility paths.

Old root-level viewer modules remain small module-identity aliases for external
scripts and plugins. New code must import from the canonical domain packages.

