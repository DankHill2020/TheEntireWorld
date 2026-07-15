import os
import sys
from ctypes import *

from DHI.core.util import MayaUtil
from maya import cmds


def resolve_python_to_use(version):
    pydna_version_mapping = {
        '2022': 'python3',
        '2023': 'python397',
        '2024': 'python3108',
        '2025': 'python311',
    }
    return pydna_version_mapping[version] or 'python3'


def _resolve_running_platform():
    import platform
    platform = platform.system()

    if platform not in ["Windows", "Linux"]:
        platform = "Windows"

    print(f"Running on {platform} ")
    return platform


def _load_pydna(current_folder, loaded_platform, maya_version):
    """
    Initialize required libraries based on Maya version
    Returns
    """
    python_version = resolve_python_to_use(maya_version)
    pydna_folder = os.path.join(current_folder, "plugins", loaded_platform, "pydna", python_version)

    if pydna_folder not in sys.path:
        print(f"Adding PYDNA to path {pydna_folder}")
        sys.path.append(pydna_folder)

    if loaded_platform == "Linux":
        print("Setting LD_LIBRARY_PATH to  %s" % pydna_folder)
        try:
            os.environ["LD_LIBRARY_PATH"] = pydna_folder
            cdll.LoadLibrary(os.path.join(pydna_folder, "libdna.so.7.1.0"))
        except Exception as exc:
            print("Failed to load library:", exc)
            sys.exit(1)


def _load_dna_calib(current_folder, loaded_platform, maya_version):
    pydnac_folder = os.path.join(current_folder, "plugins", loaded_platform, maya_version)

    if pydnac_folder not in sys.path:
        print(f"Adding PYDNACalib to path {pydnac_folder}")
        sys.path.append(pydnac_folder)
        
    if loaded_platform == "Linux":
        print("Setting LD_LIBRARY_PATH to  %s" % pydnac_folder)
        try:
            os.environ["LD_LIBRARY_PATH"] = pydnac_folder
            cdll.LoadLibrary(os.path.join(pydnac_folder, "libdnacalib.so.6"))
        except Exception as exc:
            print("Failed to load library:", exc)
            sys.exit(1)


def _load_rig_logic(current_folder, platform, maya_version):
    try:
        rl_plugin_name = "libembeddedRL4" if platform == "Linux" else "embeddedRL4"

        MayaUtil.load_plugin(
            rl_plugin_name,
            os.path.join(current_folder, "plugins", platform, maya_version),
            platform,
        )
    except Exception as ex:
        print("Failed to load rig logic plugin:", ex)


def _load_rbf(current_folder, platform, maya_version):
    try:
        MayaUtil.load_plugin(
            "MayaUE4RBFPlugin" + maya_version,
            os.path.join(current_folder, "plugins", platform, maya_version),
            platform,
            ".mll",
        )
        MayaUtil.load_plugin(
            "MayaUERBFPlugin",
            os.path.join(current_folder, "plugins", platform, maya_version),
            platform,
            ".mll",
        )
    except Exception as ex:
        print("Failed to load plugins:", ex)


def load():
    platform = _resolve_running_platform()
    maya_version = cmds.about(version=True)
    print(f"Running Maya {maya_version} on {platform}")

    current_folder = os.path.dirname(os.path.abspath(__file__))
    print(f"Current folder: {current_folder}")

    if current_folder not in sys.path:
        print(f"Adding current folder: {current_folder} to sys.path...")
        sys.path.append(current_folder)

    print("Loading plugins...")
    _load_pydna(current_folder, platform, maya_version)
    _load_dna_calib(current_folder, platform, maya_version)
    _load_rig_logic(current_folder, platform, maya_version)
    _load_rbf(current_folder, platform, maya_version)
