# Windows Graphics Stall Runbook

## Signal

The useful clue is that ending Desktop Window Manager (`dwm.exe`) makes the whole desktop responsive again. On modern Windows this usually means DWM was the visible victim of a graphics stack stall, not the root cause.

For long Codex or LLM sessions, the leading suspects are:

- Chromium/WebView GPU-process memory growth from long streaming chats and large retained pages.
- NVIDIA driver instability after mixed desktop, browser, DCC, and local AI workloads.
- VRAM pressure or fragmentation, especially with multiple monitors and content-creation tools open.
- Overlay or capture hooks such as GeForce overlay, Discord overlay, Steam overlay, screen recorders, or monitor/RGB utilities.
- Less commonly, high DPC latency from GPU, audio, USB, or network drivers.

## Capture Procedure

Take three captures whenever possible:

1. Healthy baseline shortly after reboot.
2. Slow state while windows, menus, or the mouse are stuttering.
3. Recovery state immediately after DWM restarts or after ending the Chromium/WebView GPU process.

Run from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File C:\depot\tools\tech_connector\scripts\capture_windows_graphics_stall.ps1 -Label healthy
powershell -ExecutionPolicy Bypass -File C:\depot\tools\tech_connector\scripts\capture_windows_graphics_stall.ps1 -Label slow
powershell -ExecutionPolicy Bypass -File C:\depot\tools\tech_connector\scripts\capture_windows_graphics_stall.ps1 -Label after_dwm_restart
```

The script writes reports under `%TEMP%\tech_connector_graphics_stall`.

## What To Compare

- `samples.jsonl`: look for `dwm`, `chrome`, `msedge`, `ChatGPT`, `Codex`, `Discord`, `steamwebhelper`, `maya`, `UnrealEditor`, and `ollama` memory growth. The same file includes repeated `nvidia-smi` rows when NVIDIA tooling is available.
- `graphics_stall_report.txt`: check whether dedicated VRAM approaches the card limit, GPU utilization remains high while the desktop is idle, or power/temperature is unusual.
- `display_events.csv`: check for `nvlddmkm`, display-driver recovery, WHEA, or LiveKernelEvent-adjacent entries.
- `dxdiag.txt`: confirm driver branch/version and monitor details.

## Reproduction Matrix

Use one variable at a time:

- Codex/LLM browser tabs only, no Maya/Unreal.
- Codex desktop app only, browser closed.
- Browser LLM tabs with hardware acceleration disabled.
- Same workload after disabling GeForce, Discord, Steam, and recorder overlays.
- Single monitor versus both monitors.
- Matched refresh rates versus mixed refresh rates.
- NVIDIA Studio Driver versus Game Ready Driver.

## Prevention Candidates

Start with low-risk mitigations:

- Keep LLM tabs pruned during very long sessions.
- Restart only the browser GPU process before touching DWM.
- Disable browser hardware acceleration as an A/B test.
- Disable overlays and screen capture utilities during Codex-heavy sessions.
- Use the NVIDIA Studio Driver for DCC/development-heavy machines.
- Keep monitors on matched refresh rates for a trial run.

Treat DWM restart as a recovery action only. If it consistently clears the issue, the captured data should point to the process or driver condition that made DWM stall.
