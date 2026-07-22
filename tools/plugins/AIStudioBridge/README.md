# AIStudioBridge

Canonical source for the Unreal Editor bridge plugin used by Tech Connector.

- `AIStudioBridge.uplugin`: plugin descriptor
- `AIStudioBridgeCapabilities.json`: reflected Python capability manifest
- `Config/`: plugin packaging filters
- `Source/AIStudioBridge/`: C++ module source
- `.build/`: local isolated package-build artifacts

The source plugin is not considered installed merely because it builds here.
Runtime reflection must be verified against the single enabled project or engine
installation after Unreal Editor restarts.
