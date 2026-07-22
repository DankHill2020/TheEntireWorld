# coding=utf-8
"""
    Searches codebase for existing Blueprint and Control Rig Python graph pin connection code.
"""

import os
import sys

def search_codebase_for_pin_wiring():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    print(f"[Search Engine] Searching {root_dir} for Control Rig & Blueprint Python pin wiring functions...")

    matches = []
    keywords = ["connect_pin", "add_node", "rig_vm", "control_rig", "blueprint_editor", "make_link", "pin_name", "connect"]

    for root, dirs, files in os.walk(root_dir):
        if ".venv" in root or ".git" in root or "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                full_path = os.path.join(root, f)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as file_obj:
                        lines = file_obj.readlines()
                        for idx, line in enumerate(lines, 1):
                            line_lower = line.lower()
                            if any(kw in line_lower for kw in ["connect_pin", "add_node", "rig_vm", "controlrig", "rigvm", "link_pin", "connect_rig"]):
                                matches.append({
                                    "file": os.path.relpath(full_path, root_dir),
                                    "line": idx,
                                    "content": line.strip()
                                })
                except Exception:
                    pass

    print(f"\n[Search Results]: Found {len(matches)} potential pin wiring references:")
    for m in matches[:30]:
        print(f"  - {m['file']}:{m['line']} -> {m['content']}")

    return matches

if __name__ == "__main__":
    search_codebase_for_pin_wiring()
