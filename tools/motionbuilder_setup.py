import subprocess
import pyfbsdk as fb

def get_motionbuilder_version_string():
    version_number = int(fb.FBSystem().Version)
    major = version_number // 1000
    return f"MotionBuilder 20{major}"

mobu_python = f"C:/Program Files/Autodesk/{get_motionbuilder_version_string()}/bin/x64/python/python.exe"

subprocess.run([mobu_python, "-m", "ensurepip"], check=True)

subprocess.run([mobu_python, "-m", "pip", "install", "--upgrade", "pip"], check=True)

subprocess.run([mobu_python, "-m", "pip", "install", "requests"], check=True)