# Tech Connector Windows keyboard/mouse preview

This is a separate copy of the third-person exploration acceptance package.
It uses the latest locally built Windows Player and a WASD variant of the
packaged scene. The original acceptance package was not changed. Launch it
manually with `Play.cmd` when you want to see it; no windowed run was performed
while preparing this preview.

The packaged scene was checked in explicit no-window mode for 120 frames
(`TC_PLAYER_OK`); this confirms scene loading, not visual gameplay.
`TC_PLAYER_BUILD.json` retains the source package's original validation block;
its `manual_preview_overlay` separates this modified preview's own evidence.

- W/A/S/D: move relative to the horizontal follow-camera direction.
- Space: jump. Hold C to crouch or V to crawl.
- Hold the right mouse button and drag: orbit the follow camera. Release the
  button to stop looking; focusing or clicking UI, or losing app focus, also
  releases mouse capture.
- Left-click UI buttons, or use Tab/Shift+Tab and Enter. Esc dismisses focused
  UI. During a right-drag, Esc first releases mouse-look; a subsequent Esc
  exits when no UI button is focused.
- With no controller connected, Jump/Crouch/Crawl binding labels are read-only
  keyboard reminders; the controller-rebind buttons appear only when a
  controller connects.
- F5: save. F6: load. This preview has its own scene ID and save slot.

The preview uses acceptance-fixture content, not production art. Camera-relative
movement and facing passed headless tests but have not been visually accepted;
obstacle pull-in passed a headless wall test, but its visual behavior,
save/resume facing, and mouse feel remain unverified. Windows
controller and graphical/performance acceptance remain open, and this build
does not establish Xbox or PS5 readiness.
