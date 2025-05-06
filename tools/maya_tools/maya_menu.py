import maya.cmds as cmds
import maya.utils
from maya_tools.Cinematics.SequenceUI import sequence_ui

def create_maya_menu():
    # Avoid duplicate menus
    if cmds.menu("theEntireWorldMenu", exists=True):
        cmds.deleteUI("theEntireWorldMenu", menu=True)

    # Create a top-level menu in Maya's main window
    main_menu = cmds.menu("theEntireWorldMenu", label="The Entire World Tools", parent="MayaWindow", tearOff=True)

    # Add a menu item that calls your animation manager
    cmds.menuItem("sequenceUIItem", label="Sequence UI", parent=main_menu, command=lambda *args: sequence_ui.show_animation_manager())

def create_menu_once():
    create_maya_menu()
    # Defer the scriptJob kill until after this callback finishes
    maya.utils.executeDeferred("import maya.cmds as cmds; cmds.scriptJob(kill={0}, force=True)".format(menu_job_id))

menu_job_id = cmds.scriptJob(event=["SceneOpened", create_menu_once], protected=True)


