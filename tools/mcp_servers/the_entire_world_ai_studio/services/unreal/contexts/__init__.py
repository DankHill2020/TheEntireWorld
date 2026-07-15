"""Structured Unreal context builders.

Keep this package init lightweight. Domain builders are imported lazily by the
call sites that actually need them so simple Unreal requests do not pull every
asset-family context module into memory.
"""

__all__ = ["UnrealSelectedContextService"]
