import os
import subprocess
import stat
import re

def create_changelist(description, cwd=None):
    """
    Creates a new changelist with the given description and returns its ID.
    Returns None if creation fails.
    """
    try:
        p1 = subprocess.Popen(['p4', 'change', '-o'], stdout=subprocess.PIPE, text=True, cwd=cwd)
        change_spec, _ = p1.communicate()
        
        new_spec = ""
        for line in change_spec.splitlines():
            if line.startswith("Description:"):
                new_spec += "Description:\n\t" + description + "\n"
            elif line.startswith("\t<enter description here>"):
                continue
            elif line.startswith("Files:"):
                break # Don't automatically add default files
            else:
                new_spec += line + "\n"
                
        p2 = subprocess.Popen(['p4', 'change', '-i'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=cwd)
        out, _ = p2.communicate(new_spec)
        
        match = re.search(r"Change (\d+) created", out)
        if match:
            return match.group(1)
    except Exception:
        pass
        
    return None

def p4_edit(filepath, changelist=None):
    """
    Checks out a file in Perforce. Safe to call even if P4 is offline or file is unmanaged.
    The 'p4' command automatically detects the correct workspace and user based on the 
    current directory's P4CONFIG file or the system's global P4 variables.
    
    Also ensures the file is writable locally so Maya tools don't crash if offline.
    """
    if not filepath:
        return False
        
    if os.path.exists(filepath):
        try:
            filepath = os.path.abspath(filepath)
            cwd = os.path.dirname(filepath)
            cmd = ['p4', 'edit']
            if changelist:
                cmd.extend(['-c', str(changelist)])
            cmd.append(filepath)
            
            subprocess.run(cmd, check=False, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass
            
        # Fallback: forcefully remove read-only flag so Python/Maya don't crash
        # when trying to overwrite a P4-managed file if the server is unreachable.
        try:
            os.chmod(filepath, os.stat(filepath).st_mode | stat.S_IWRITE)
        except Exception:
            pass
            
    return True


def prepare_file_for_write(filepath):
    """Check out existing outputs, falling back to local write permission."""
    filepath = os.path.abspath(os.fspath(filepath))
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath):
        p4_edit(filepath)
        if not os.stat(filepath).st_mode & stat.S_IWRITE or not os.access(filepath, os.W_OK):
            raise PermissionError("Cannot make output writable: {}".format(filepath))
    return filepath

def p4_add(filepath, changelist=None):
    """
    Adds a new file to Perforce. Safe to call even if P4 is offline.
    """
    if not filepath or not os.path.exists(filepath):
        return False
        
    try:
        cwd = os.path.dirname(filepath)
        cmd = ['p4', 'add']
        if changelist:
            cmd.extend(['-c', str(changelist)])
        cmd.append(filepath)
        
        subprocess.run(cmd, check=False, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        pass
        
    return False
