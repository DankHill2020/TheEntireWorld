# Tech Connector game engine

This package contains the headless scene-authoring and runtime systems. It is
safe to use without constructing the desktop UI.

- `assets/` — asset database and collision cooking.
- `authoring/` — rigs, procedural tools, graph programs, and world authoring.
- `deformation/` — skinning, anatomy, weight maps, and deformation contracts.
- `integration/` — DCC bridges, viewer commands, host policy, and transfer.
- `rendering/` — materials, lighting, and upscaling contracts.
- `runtime/` — graph, simulation, geometry, build, and console runtimes.
- `scene/` — coordinate spaces, conversion, USD/FBX, and scene deltas.

Qt editor surfaces live in `tech_connector.ui.game_engine`. DCC-connected
scene presentation lives in `tech_connector.ui.dcc_viewer`.

`tech_connector.engine` is intentionally separate: it is the AI request engine,
not the game engine.

