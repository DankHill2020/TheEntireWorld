import pyfbsdk as fb
from maya_tools.Cinematics.SequenceUI import sequence_ui



def create_motionbuilder_menu():
    """Create a custom menu in MotionBuilder UI."""
    menu_manager = fb.FBMenuManager()
    custom_menu_name = "The Entire World Tools"
    menu_manager.InsertBefore(None, "Help", custom_menu_name)
    main_menu = menu_manager.GetMenu(custom_menu_name)

    menu_item_name = "Sequence UI"
    main_menu.InsertLast(menu_item_name, 0)

    main_menu.OnMenuActivate.Add(on_menu_click)


def on_menu_click(control, event):
    if event.Name == "Sequence UI":
        sequence_ui.show_animation_manager()


create_motionbuilder_menu()


