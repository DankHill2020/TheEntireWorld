import os
import maya.cmds as cmds
import subprocess
import inspect
import threading


def export_animation_to_fbx(export_path, namespace, start_frame, end_frame, nodes=None, reference_paths=None):
    """
    Subprocess command function which calls the actual export function, to make scene state unchanged
    :param export_path: full path for fbx animation to be exported
    :param namespace: namespace to be exported in the data
    :param start_frame: start frame of exported data
    :param end_frame: end frame of exported data
    :param nodes: Joints or nodes to be exported
    :param reference_paths: Paths to import in the maya py instance from reference

    :return:
    """
    print(f"Starting export for {namespace} from frame {start_frame} to {end_frame}")

    maya_file = cmds.file(q=True, sceneName=True)
    if not maya_file:
        raise ValueError("Scene must be saved before exporting.")

    maya_version = cmds.about(version=True)
    mayapy = os.path.join("C:/Program Files", "Autodesk", f"Maya{maya_version}", "bin", "mayapy.exe")

    # Get script path safely
    current_dir = os.path.dirname(inspect.getfile(lambda: None))
    script_path = os.path.join(current_dir, 'anim_export.py')

    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Script not found: {script_path}")

    # Build command
    cmd = [
        mayapy, "-u", script_path,
        "--maya_file", maya_file,
        "--export_path", export_path,
        "--namespace", namespace,
        "--start_frame", str(int(start_frame)),
        "--end_frame", str(int(end_frame))
    ]
    if nodes:
        if isinstance(nodes, str):
            nodes = [nodes]
        cmd += ["--nodes", ",".join(nodes)]

    if reference_paths:
        cmd += ["--reference_paths", (str(reference_paths))]
    # Set environment variables
    maya_env = os.environ.copy()
    maya_env["MAYA_SCRIPT_PATH"] = os.path.join("C:/Program Files", "Autodesk", f"Maya{maya_version}","scripts")
    maya_env["PYTHONPATH"] = os.path.join("C:/Program Files", "Autodesk", f"Maya{maya_version}","Python", "Lib","site-packages")

    # Run mayapy
    process = export_animation_async(cmd, maya_env, export_path)
    return process


def run_export(cmd, maya_env, export_path):
    """
    exports using subprocess to keep maya scene unchanged / non-destructive
    :param cmd: subprocess command string for export
    :param maya_env: maya env settings from os.environ.copy()
    :param export_path: actual fbx export location
    :return:
    """
    try:
        process = subprocess.Popen(cmd, env=maya_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        stdout, stderr = process.communicate()

        if process.returncode == 0:
            print(f"Animation exported successfully to {export_path}")
        else:
            print(f"Command failed with error code {process.returncode}")
        return process

    except subprocess.CalledProcessError as e:
        print(f"Export failed. Error output: \n{e.stderr}")

        raise RuntimeError(f"Export failed: {e}")
        return None


def export_animation_async(cmd, maya_env, export_path):
    """
    exports on separate thread so maya session isn't locked up during export
    :param cmd: subprocess command string for export
    :param maya_env: maya env settings from os.environ.copy()
    :param export_path: actual fbx export location
    :return:
    """
    thread = threading.Thread(target=run_export, args=(cmd, maya_env, export_path))
    thread.start()
    return thread