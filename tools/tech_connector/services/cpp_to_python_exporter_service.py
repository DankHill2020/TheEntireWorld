# coding=utf-8
"""
    C++ to Unreal Python Binding & Exporter Service for Tech Connector.
    Generates UFUNCTION(BlueprintCallable) reflection wrappers, Unreal C++ headers,
    and Python binding stubs so native C++ features are exposed directly to Unreal Python scripts.
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path


class CppToPythonExporterService:
    """
        Generates Unreal Engine C++ reflection headers and Python bindings to expose C++ features to Python.
    """

    def generate_cpp_reflection_header(self, class_name: str, functions: list[dict]) -> str:
        """
            Generates Unreal C++ header file (.h) with UCLASS and UFUNCTION(BlueprintCallable) macros.
        :param class_name: C++ class name (e.g. UTechConnectorGraphBridge)
        :param functions: list of function specification dicts (name, return_type, params)
        :return: string containing complete Unreal C++ header file content
        """
        lines = []
        lines.append('#pragma once')
        lines.append('')
        lines.append('#include "CoreMinimal.h"')
        lines.append('#include "Kismet/BlueprintFunctionLibrary.h"')
        lines.append(f'#include "{class_name}.generated.h"')
        lines.append('')
        lines.append('/**')
        lines.append(f' * {class_name}: Automatically generated C++ to Python reflection bridge.')
        lines.append(' */')
        lines.append('UCLASS(BlueprintType, Blueprintable)')
        lines.append(f'class TECHCONNECTOR_API {class_name} : public UBlueprintFunctionLibrary')
        lines.append('{')
        lines.append('\tGENERATED_BODY()')
        lines.append('')
        lines.append('public:')

        for fn in functions:
            fn_name = fn.get("name", "ExecuteFeature")
            ret_type = fn.get("return_type", "bool")
            params = fn.get("params", [])
            param_str = ", ".join([f"{p['type']} {p['name']}" for p in params])
            
            lines.append('\t/**')
            lines.append(f'\t * {fn_name}: Exposed to Unreal Python via UFUNCTION(BlueprintCallable).')
            lines.append('\t */')
            lines.append('\tUFUNCTION(BlueprintCallable, Category = "TechConnector|CppBridge")')
            lines.append(f'\tstatic {ret_type} {fn_name}({param_str});')
            lines.append('')

        lines.append('};')
        return "\n".join(lines)

    def generate_python_wrapper_stub(self, class_name: str, functions: list[dict]) -> str:
        """
            Generates Python wrapper stub file allowing Python scripts to invoke the reflected C++ class cleanly.
        :param class_name: C++ class name
        :param functions: list of function dicts
        :return: Python wrapper script string
        """
        lines = []
        lines.append('# coding=utf-8')
        lines.append('"""')
        lines.append(f'    Python Wrapper for Reflected C++ Class `{class_name}`.')
        lines.append('"""')
        lines.append('')
        lines.append('import unreal')
        lines.append('')
        lines.append(f'class {class_name}Wrapper:')
        lines.append('\t"""')
        lines.append(f'\t    Provides Python interface to native Unreal C++ feature `{class_name}`.')
        lines.append('\t"""')
        lines.append('')

        for fn in functions:
            fn_name = fn.get("name", "ExecuteFeature")
            params = [p['name'] for p in fn.get("params", [])]
            param_str = ", ".join(params)
            call_param_str = ", ".join(params)

            lines.append(f'\t@staticmethod')
            lines.append(f'\tdef {fn_name.lower()}({param_str}):')
            lines.append('\t\t"""')
            lines.append(f'\t\t    Invokes reflected C++ method `{class_name}.{fn_name}`.')
            lines.append('\t\t"""')
            lines.append(f'\t\tcpp_class = getattr(unreal, "{class_name}", None)')
            lines.append('\t\tif not cpp_class:')
            lines.append(f'\t\t\traise RuntimeError("Native C++ class \'{class_name}\' is not loaded in Unreal Python environment.")')
            lines.append(f'\t\treturn cpp_class.{fn_name.lower()}({call_param_str})')
            lines.append('')

        return "\n".join(lines)

    def export_cpp_feature_to_python(self, class_name: str, functions: list[dict], export_dir: str) -> dict[str, str]:
        """
            Exports both the Unreal C++ header file and Python wrapper script into target directory.
        :param class_name: C++ class name
        :param functions: list of function dicts
        :param export_dir: target output directory
        :return: dict mapping artifact names to exported file paths
        """
        os.makedirs(export_dir, exist_ok=True)
        header_content = self.generate_cpp_reflection_header(class_name, functions)
        python_content = self.generate_python_wrapper_stub(class_name, functions)

        header_path = os.path.join(export_dir, f"{class_name}.h")
        python_path = os.path.join(export_dir, f"{class_name.lower()}_wrapper.py")

        with open(header_path, "w", encoding="utf-8") as f:
            f.write(header_content)

        with open(python_path, "w", encoding="utf-8") as f:
            f.write(python_content)

        print(f"[CppToPython Exporter] Exported C++ Header: {header_path}")
        print(f"[CppToPython Exporter] Exported Python Wrapper: {python_path}")

        return {
            "cpp_header": header_path,
            "python_wrapper": python_path,
        }
