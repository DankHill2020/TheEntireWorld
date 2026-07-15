"""
Maya checks for userSetup.py file and runs it while loading other libraries at the start of the program
This Module :
- Creates the shelf in Maya
- Starts the LiveLink
"""

from maya import cmds

from DHI import PluginLoader
from LiveLink import initLiveLink
from Megascans import Installer

# Runs this code automatically at the start of Maya
cmds.evalDeferred("initPlugin()")


# Delete Old Shelf, create a new shelf (install livelink) and start the listening at socket/start LiveLink
def initPlugin():
    PluginLoader.load()
    Installer.createMSshelf()
    initLiveLink()
