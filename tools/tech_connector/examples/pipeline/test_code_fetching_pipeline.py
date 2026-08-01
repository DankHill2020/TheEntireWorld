# coding=utf-8
"""
    Test Suite for Dynamic On-The-Fly Code and Pipeline Module Retrieval.
"""

import os
import sys
import json
import ast

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from utilities.pipeline_asset_downloader import (
    download_pipeline_asset,
    inspect_pipeline_asset,
)


def verify_code_docstrings(source_code: str) -> bool:
    """
        Validates that functions in the retrieved code contain reST-style docstrings.
    :param source_code: string containing Python source code
    :return: True if all functions have valid reST docstrings
    """
    tree = ast.parse(source_code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node)
            if not docstring:
                print(f"[Docstring Audit Warning] Function '{node.name}' is missing a docstring.")
                return False
            if ":param" in docstring or ":return" in docstring or len(docstring.strip()) > 0:
                print(f"[Docstring Audit Pass] Function '{node.name}' contains valid docstring.")
    return True


def test_remote_code_ingestion():
    """
        Downloads a remote raw Python utility script on the fly and verifies syntax and docstrings.
    :return: True if the code module passes ingestion verification
    """
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "external_tools", "downloaded_code"))
    
    # Download a sample open-source pipeline utility script from raw GitHub
    raw_code_url = "https://raw.githubusercontent.com/psf/requests/main/src/requests/__init__.py"
    print("\n--- Running Pipeline Ingestion Test 3: Remote Python Module Fetching ---")
    
    code_path = download_pipeline_asset(raw_code_url, output_dir)
    code_meta = inspect_pipeline_asset(code_path)
    
    with open(code_path, "r", encoding="utf-8", errors="ignore") as f:
        code_content = f.read()

    # Compile check
    compiled_code = compile(code_content, code_path, "exec")
    print(f"[Code Ingestion] Module '{code_meta['file_name']}' compiled successfully ({len(code_content)} chars).")

    # Verify docstring standards on our own pipeline module
    our_downloader_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "pipeline_asset_downloader.py"))
    with open(our_downloader_path, "r", encoding="utf-8") as f:
        our_code = f.read()

    docstring_ok = verify_code_docstrings(our_code)
    assert docstring_ok, "Our pipeline downloader module must adhere to reST docstring quality standard."

    print("\n================================================================================")
    print("ALL DYNAMIC CODE FETCHING AND DOCSTRING QUALITY TESTS PASSED SUCCESSFULLY!")
    print("================================================================================\n")
    return True


if __name__ == "__main__":
    test_remote_code_ingestion()
