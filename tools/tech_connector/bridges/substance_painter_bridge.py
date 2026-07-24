"""Compatibility shim for the canonical host bridge module.

The implementation lives in ``tech_connector.bridges.substance_painter.substance_painter_bridge``.
Keep this root import path for older callers while avoiding duplicate logic.
"""

from tech_connector.bridges.substance_painter.substance_painter_bridge import *  # noqa: F401,F403
