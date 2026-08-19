"""Run the canonical Tech Connector Maya bridge bootstrap in the current Maya session."""

from tech_connector.bridges.maya.maya_livelink_plugin import MAYA_USER_SETUP_CODE


exec(compile(MAYA_USER_SETUP_CODE, "<tech_connector_maya_bridge>", "exec"), globals(), globals())
