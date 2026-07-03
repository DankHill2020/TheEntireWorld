import builtins

def maya_execute_and_capture(encoded_code):
    import sys
    import io
    import base64
    import traceback
    
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    
    try:
        # Execute the code in global namespace so variables persist across sessions
        exec(base64.b64decode(encoded_code.encode('utf-8')).decode('utf-8'), globals())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        
    out = sys.stdout.getvalue()
    err = sys.stderr.getvalue()
    sys.stdout = old_stdout
    sys.stderr = old_stderr
    
    if err:
        return f"STDOUT:\n{out}\nSTDERR:\n{err}"
    return out

builtins.maya_execute_and_capture = maya_execute_and_capture

import maya.cmds as cmds
import maya.utils
from maya_tools.Cinematics.SequenceUI import sequence_ui
from maya_tools.Rigging.mocap import hik_ui


# Apply monkeypatch to fix Autodesk's Python 3 CommandPort bugs (bytes translation & socket writing)
try:
    import sys
    import socket
    import maya.app.general.CommandPort as cp
    
    # Bug 1: Autodesk's receiveData uses Python 2 syntax for bytes translation: data.translate(None, b'\x00')
    # This raises TypeError in Python 3. We patch it to use data.replace(b'\x00', b'') instead.
    def patched_receiveData(self):
        import socket
        import maya
        import sys
        cp = sys.modules['maya.app.general.CommandPort']
        encodingType = getattr(cp, 'encodingType', 'utf8')
        
        nextdata = self.request.recv(self.server.bufferSize)
        if nextdata is None:
            return None
        data = nextdata   
        if len(data) == 0:
            return None
        oldtimeout = self.request.gettimeout()
        self.request.settimeout(1.5)
        while len(nextdata) >= self.server.bufferSize:
            try:
                nextdata = self.request.recv(self.server.bufferSize)
                data += nextdata
            except socket.timeout:
                break
        self.request.settimeout(oldtimeout)

        # Fix the Python 3 translate bug
        data = data.replace(b'\x00', b'')

        from sys import stderr as sys_stderr
        try:
            data = data.decode(encodingType).strip()
        except:
            warnMsg = maya.stringTable['y_maya_app_general_CommandPort.kInvalidUTF8' ]
            sys_stderr.write(warnMsg + "\n")
            return None
        return data

    # Bug 2: Autodesk's handle method writes strings to wfile (which requires bytes in Python 3)
    def patched_handle(self):
        import socket
        import maya
        from maya import utils
        import sys
        cp = sys.modules['maya.app.general.CommandPort']
        encodingType = getattr(cp, 'encodingType', 'utf8')
        
        try:
            if self.server.echoOutput:
                self.request.settimeout(1.5)
            while not self.server.die:
                # check for pending command messages
                if self.server.echoOutput:
                    while not self.server.commandMessageQueue.empty():
                        msg = self.server.commandMessageQueue.get() + self.resp_term
                        self.wfile.write(msg.encode(encodingType))
                # set self.data to be the incoming message
                try:
                    self.data = self.receiveData()
                except socket.timeout:
                    continue
                if self.data is None: 
                    break
                # check if we need to display the security warning
                if self.server.securityWarning:
                    utils.executeInMainThreadWithResult(self.postSecurityWarning)
                    if self.dialog_result is False:
                        msg = maya.stringTable['y_maya_app_general_CommandPort.kExecutionDeniedByMaya' ] + self.resp_term
                        self.wfile.write(msg.encode(encodingType))
                        return
                    elif self.dialog_result is True:
                        self.server.securityWarning = False

                # execute the message
                response = utils.executeInMainThreadWithResult(self._languageExecute)
                self.wfile.write(response.encode(encodingType))
        except socket.error:
            pass
        except Exception as e:
            import traceback
            sys.stderr.write(f"Error in commandPort handler: {e}\n")
            traceback.print_exc(file=sys.stderr)

    cp.TcommandHandler.receiveData = patched_receiveData
    cp.TcommandHandler.handle = patched_handle
    print("CommandPort Python 3 monkeypatches applied successfully!")
except Exception as e:
    print(f"Failed to apply CommandPort monkeypatches: {e}")

# Expose helper utilities requested by user
def save_port_to_file(port):
    try:
        import os
        path = "C:/Users/Aaron/.gemini/antigravity/brain/96780b9e-50af-48f5-bf67-f9aa5b5a9101/scratch/maya_port.txt"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(str(port))
        print("Saved active commandPort to file: {}".format(port))
    except Exception as e:
        print("Failed to save commandPort to file: {}".format(e))

def get_command_port():
    port = None
    try:
        import maya.mel as mel
        port = mel.eval('$temp = $g_commandPort')
    except:
        pass
    return port

def send_command(command, port = 8192):
    import socket
    HOST = '127.0.0.1'
    PORT = port
    ADDR=(HOST,PORT)
     
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(0.2) # CRITICAL: Prevent Maya from hanging forever on startup
    client.connect(ADDR)
     
    if isinstance(command, str):
        command = command.encode('utf-8')
    client.send(command)
    data = client.recv(1024)
    client.close()
    
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    return data

def create_command_port(port=8192, stp='python'):
    if get_command_port() is None:
        # disable default command port
        cmds.optionVar( iv=('commandportOpenByDefault', 0))

        while True:
            try:
                send_command('print \'\'', port = port)
            except:
                break
            port += 1

        name_and_port = 'port:{}'.format(port)

        try:
            import maya.mel as mel
            cmd_port = cmds.commandPort(name=name_and_port, stp=stp, echoOutput=False, noreturn=False)
            print("Maya Command Port: {}".format(port))
            mel.eval('global int $g_commandPort = {}'.format(port))
            save_port_to_file(port)
            return cmd_port
        except Exception as e:
            print("Maya Command Port could not be established.")
            print(getattr(e, 'message', str(e)), e.args)
    return None

# Try establishing commandPort automatically on startup
try:
    # First, make sure port 7001 is closed or open
    active_ports = cmds.commandPort(q=True, listPorts=True) or []
    for port in active_ports:
        if "7001" in port:
            cmds.commandPort(name=port, close=True)
            break
except Exception as e:
    print(f"Error checking/closing existing commandPort: {e}")

try:
    cmds.commandPort(
        name=":7001",
        sourceType="python",
        echoOutput=False,
        noreturn=False
    )
    print("Maya commandPort open on :7001 (Python mode)")
    save_port_to_file(7001)
except Exception as e:
    print(f"Failed to open commandPort :7001: {e}")

# Run user's dynamic port allocator starting at 8192
try:
    create_command_port(port=8192)
except Exception as e:
    print(f"Failed to run create_command_port: {e}")

def on_before_save(*args):
    try:
        scene_name = cmds.file(q=True, sceneName=True)
        if scene_name:
            import os
            import sys
            tools_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if tools_dir not in sys.path:
                sys.path.append(tools_dir)
            from utilities import p4_utils
            p4_utils.p4_edit(scene_name)
    except Exception as e:
        print(f"P4 Auto-checkout failed: {e}")

def create_maya_menu():
    # Avoid duplicate menus
    if cmds.menu("theEntireWorldMenu", exists=True):
        cmds.deleteUI("theEntireWorldMenu", menu=True)

    # Create a top-level menu in Maya's main window
    main_menu = cmds.menu("theEntireWorldMenu", label="The Entire World Tools", parent="MayaWindow", tearOff=True)

    # Add a menu item that calls your animation manager
    cmds.menuItem("sequenceUIItem", label="Sequence UI", parent=main_menu, command=lambda *args: sequence_ui.show_animation_manager())
    cmds.menuItem("hikUIItem", label="Human IK UI", parent=main_menu, command=lambda *args: hik_ui.launch_hik_ui())

def create_menu_once():
    create_maya_menu()
    
    # Register BeforeSave P4 auto-checkout
    try:
        cmds.scriptJob(event=["BeforeSave", on_before_save], protected=True)
    except Exception as e:
        print(f"Failed to register BeforeSave scriptJob: {e}")

maya.utils.executeDeferred(create_menu_once)


