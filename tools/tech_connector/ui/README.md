# Tech Connector UI architecture

The UI package is organized by product surface rather than widget type:

- `dcc_viewer/` — connected-host controls, scene-document state, component
  picking, GPU viewport presentation, and the 3D mesh painter.
- `game_engine/` — sequencer, simulation, physics-joint, and Unreal editor UI.
- `image_viewer/` — image canvas, layer editor, brush shapes, and visual-art
  inspection.
- root modules — application-wide shell components such as navigation, chat,
  project panels, menus, and reusable dialogs.

The headless game engine lives in `tech_connector/game_engine`. The separate
`tech_connector/engine` package is the AI request engine, not a rendering or
simulation engine.

Legacy root-level viewer modules are compatibility aliases. New code should
import from the domain packages above.

