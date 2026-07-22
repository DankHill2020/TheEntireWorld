"""Register Unreal capabilities without duplicating the canonical bridge adapter."""

from __future__ import annotations


def register_unreal_capabilities(store, project_id: int) -> None:
    from tech_connector.bridges.unreal.unreal_intelligence import _register_default_capabilities

    _register_default_capabilities(store, project_id)

