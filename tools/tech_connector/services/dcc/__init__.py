"""Deprecated DCC service import paths.

Implementations now live under :mod:`tech_connector.game_engine`. The modules
in this package are compatibility aliases for existing plugins and scripts.
New code should import from ``game_engine.scene``, ``game_engine.authoring``,
``game_engine.deformation``, ``game_engine.runtime``, or
``game_engine.integration``.
"""
