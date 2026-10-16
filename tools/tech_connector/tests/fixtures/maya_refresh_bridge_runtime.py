"""Refresh the live Maya bridge runtime after source-development updates."""

import importlib
import json

import maya.cmds as cmds
import tech_connector.bridges.session_authorization as session_authorization


session_authorization = importlib.reload(session_authorization)
print(json.dumps({
    "scene": cmds.file(query=True, sceneName=True) or "",
    "selection": cmds.ls(selection=True) or [],
    "authorization_path": str(session_authorization.bridge_session_path()),
    "authorization_valid": bool(
        session_authorization.load_bridge_session("maya")
    ),
}, sort_keys=True))
