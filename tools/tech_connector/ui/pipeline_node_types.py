from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import ast
import re
from pathlib import Path

FLOW_PORT = "__flow__"

_NONE_RETURN_TYPES = {"None", "NoneType", "void", "NoReturn"}
_UNKNOWN_RETURN_TYPES = {"", "Any", "Unknown", "object"}


@dataclass
class PortInfo:
    name: str
    python_type: str = "Any"
    semantic_type: str = ""
    package: str = ""
    description: str = ""
    default: Any = ""
    editable: bool = True
    connectable: bool = True

    def to_param(self) -> dict[str, Any]:
        data = {
            "name": self.name,
            "annotation": self.python_type or "Any",
            "python_type": self.python_type or "Any",
            "semantic_type": self.semantic_type or "",
            "package": self.package or "",
            "description": self.description or "",
            "default": self.default,
            "editable": self.editable,
            "connectable": self.connectable,
        }
        return data


@dataclass
class ReturnInfo:
    name: str = "result"
    python_type: str = "Unknown"
    semantic_type: str = ""
    package: str = ""
    is_none: bool = False
    element_type: str = ""

    def to_output(self) -> dict[str, Any]:
        if self.is_none:
            return {}
        annotation = self.python_type or "Unknown"
        if self.element_type and annotation == "list":
            annotation = f"list[{self.element_type}]"
        return {
            "name": self.name or "result",
            "annotation": annotation,
            "python_type": annotation,
            "semantic_type": self.semantic_type or "",
            "package": self.package or "",
            "element_type": self.element_type or "",
        }


@dataclass
class WorkflowNodeMetadata:
    package: str = "Project"
    source_kind: str = "project"
    semantic_type: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)


def clean_type(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if text in {"", "None", "NoneType", "void", "NoReturn"}:
        return text
    return text.replace("typing.", "")


def safe_port_name(value: Any, fallback: str = "result") -> str:
    import keyword
    text = "" if value is None else str(value).strip()
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    if not text:
        text = fallback or "result"
    if text[0].isdigit():
        text = f"output_{text}"
    if keyword.iskeyword(text):
        text = f"{text}_value"
    return text


def annotation_from_ast(annotation: ast.AST | None) -> str:
    if annotation is None:
        return ""
    try:
        return clean_type(ast.unparse(annotation))
    except Exception:
        return ""


def function_ast(symbol: dict[str, Any]) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    source = symbol.get("source") or ""
    if not source:
        return None
    try:
        tree = ast.parse(source)
    except Exception:
        return None
    target_name = symbol.get("name") or ""
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for node in functions:
        if node.name == target_name:
            return node
    return functions[0] if len(functions) == 1 else None


def infer_package(symbol: dict[str, Any]) -> str:
    if symbol.get("utility_kind") or symbol.get("kind") == "utility":
        return "Utility"
    package = symbol.get("package") or symbol.get("source_package") or symbol.get("module") or ""
    file_path = str(symbol.get("file_path") or "").replace("\\", "/").lower()
    name = str(symbol.get("name") or "").lower()
    source = str(symbol.get("source") or "")[:4000]

    if package:
        p = str(package)
        if "maya" in p.lower():
            return "Maya"
        if "unreal" in p.lower():
            return "Unreal"
        if "blender" in p.lower() or "bpy" in p.lower():
            return "Blender"
        if "houdini" in p.lower() or "hou" == p.lower():
            return "Houdini"
        if "pathlib" in p.lower():
            return "pathlib"
        if "os.path" in p.lower():
            return "os.path"
        return p
    text = " ".join([file_path, name, source.lower()])
    if "maya" in text or "maya.cmds" in text or "cmds." in text:
        return "Maya"
    if "unreal" in text:
        return "Unreal"
    if "blender" in text or "bpy." in text:
        return "Blender"
    if "motionbuilder" in text or "mobu" in text:
        return "MotionBuilder"
    if "substance" in text:
        return "Substance"
    if "github" in text:
        return "GitHub"
    if "pathlib" in text:
        return "pathlib"
    if "os.path" in text:
        return "os.path"
    return "Project"


def infer_source_kind(symbol: dict[str, Any]) -> str:
    pkg = infer_package(symbol).lower()
    if pkg == "utility":
        return "utility"
    if pkg == "github":
        return "github"
    if pkg in {"maya", "unreal", "blender", "motionbuilder", "substance", "houdini"}:
        return "dcc"
    return "project"


def infer_semantic_from_name(name: str, python_type: str = "", package: str = "") -> str:
    n = (name or "").lower()
    pkg = (package or "").lower()
    if "path" in n or "file" in n or "filename" in n:
        return "filesystem.path.file" if "file" in n or "filename" in n else "filesystem.path"
    if "directory" in n or "folder" in n:
        return "filesystem.path.directory"
    if "maya" in pkg or any(k in n for k in ("joint", "ctrl", "control", "node", "mesh", "curve", "object")):
        if "joint" in n:
            return "maya.joint"
        if "mesh" in n:
            return "maya.mesh"
        if "curve" in n:
            return "maya.curve"
        if "ctrl" in n or "control" in n:
            return "maya.control"
        if "node" in n or "object" in n:
            return "maya.node"
    if "unreal" in pkg and ("asset" in n or "path" in n):
        return "unreal.asset"
    return ""


def infer_expr_type(expr: ast.AST | None, assignments: dict[str, ReturnInfo] | None = None) -> ReturnInfo:
    assignments = assignments or {}
    if expr is None:
        return ReturnInfo(name="", python_type="None", is_none=True)
    if isinstance(expr, ast.Constant):
        if expr.value is None:
            return ReturnInfo(name="", python_type="None", is_none=True)
        return ReturnInfo(name="result", python_type=type(expr.value).__name__)
    if isinstance(expr, (ast.List, ast.ListComp)):
        return ReturnInfo(name="result", python_type="list")
    if isinstance(expr, (ast.Tuple, ast.GeneratorExp)):
        return ReturnInfo(name="result", python_type="tuple")
    if isinstance(expr, (ast.Dict, ast.DictComp)):
        return ReturnInfo(name="result", python_type="dict")
    if isinstance(expr, (ast.Set, ast.SetComp)):
        return ReturnInfo(name="result", python_type="set")
    if isinstance(expr, ast.Name):
        info = assignments.get(expr.id)
        if info:
            return ReturnInfo(
                name=expr.id,
                python_type=info.python_type,
                semantic_type=info.semantic_type,
                package=info.package,
                is_none=info.is_none,
                element_type=info.element_type,
            )
        return ReturnInfo(name=expr.id, python_type="Unknown")
    if isinstance(expr, ast.Call):
        func = expr.func
        func_name = ""
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr
        if func_name in {"list", "sorted", "range"}:
            return ReturnInfo(name="result", python_type="list")
        if func_name in {"dict"}:
            return ReturnInfo(name="result", python_type="dict")
        if func_name in {"set"}:
            return ReturnInfo(name="result", python_type="set")
        if func_name in {"tuple"}:
            return ReturnInfo(name="result", python_type="tuple")
        if func_name in {"listRelatives", "ls"}:
            return ReturnInfo(name="result", python_type="list", element_type="str", semantic_type="maya.node")
        if func_name.startswith("list") or func_name.endswith("s"):
            return ReturnInfo(name="result", python_type="list")
    if isinstance(expr, ast.BinOp):
        left = infer_expr_type(expr.left, assignments)
        right = infer_expr_type(expr.right, assignments)
        if left.python_type == right.python_type and left.python_type not in _UNKNOWN_RETURN_TYPES:
            return ReturnInfo(name="result", python_type=left.python_type)
    return ReturnInfo(name="result", python_type="Unknown")


def _update_assignment_from_method_call(assignments: dict[str, ReturnInfo], target_name: str, call: ast.Call) -> None:
    """Infer container element type from common mutations like x.extend(cmds.listRelatives(...))."""
    if not isinstance(call.func, ast.Attribute):
        return
    attr = call.func.attr
    receiver = call.func.value
    if not isinstance(receiver, ast.Name):
        return
    container = assignments.get(receiver.id)
    if not container:
        return
    if attr in {"append"} and call.args:
        item_info = infer_expr_type(call.args[0], assignments)
        if container.python_type == "list" and item_info.python_type not in _UNKNOWN_RETURN_TYPES:
            container.element_type = item_info.python_type
    elif attr in {"extend", "update"} and call.args:
        src = infer_expr_type(call.args[0], assignments)
        if container.python_type == "list":
            container.element_type = src.element_type or ("str" if src.semantic_type.startswith("maya") else container.element_type)
            if src.semantic_type:
                container.semantic_type = src.semantic_type


def infer_symbol_return(symbol: dict[str, Any]) -> ReturnInfo:
    if symbol.get("utility_kind"):
        ret = clean_type(symbol.get("return_annotation") or symbol.get("python_type") or "Unknown") or "Unknown"
        outputs = symbol.get("outputs") or []
        if outputs:
            out = outputs[0]
            return ReturnInfo(
                name=out.get("name") or "result",
                python_type=clean_type(out.get("annotation") or ret),
                semantic_type=out.get("semantic_type") or "",
                package="Utility",
            )
        return ReturnInfo(name="result", python_type=ret, package="Utility")

    package = infer_package(symbol)
    for key in ("return_annotation", "returns"):
        ret = clean_type(symbol.get(key) or "")
        if ret:
            return ReturnInfo(name="result", python_type=ret, package=package, semantic_type=infer_semantic_from_name("result", ret, package), is_none=ret in _NONE_RETURN_TYPES)

    fn = function_ast(symbol)
    if fn is None:
        return ReturnInfo(name="result", python_type="Unknown", package=package)

    annotated = annotation_from_ast(getattr(fn, "returns", None))
    if annotated:
        return ReturnInfo(name="result", python_type=annotated, package=package, semantic_type=infer_semantic_from_name("result", annotated, package), is_none=annotated in _NONE_RETURN_TYPES)

    assignments: dict[str, ReturnInfo] = {}
    returns: list[ReturnInfo] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            inferred = infer_expr_type(node.value, assignments)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    semantic = infer_semantic_from_name(target.id, inferred.python_type, package)
                    assignments[target.id] = ReturnInfo(
                        name=target.id,
                        python_type=inferred.python_type,
                        semantic_type=semantic or inferred.semantic_type,
                        package=package,
                        element_type=inferred.element_type,
                        is_none=inferred.is_none,
                    )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            ann = annotation_from_ast(node.annotation)
            inferred = infer_expr_type(node.value, assignments) if node.value else ReturnInfo(node.target.id, ann or "Unknown")
            assignments[node.target.id] = ReturnInfo(
                name=node.target.id,
                python_type=ann or inferred.python_type,
                semantic_type=infer_semantic_from_name(node.target.id, ann or inferred.python_type, package) or inferred.semantic_type,
                package=package,
                element_type=inferred.element_type,
            )
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute):
                # mutate an existing assignment
                receiver = call.func.value
                if isinstance(receiver, ast.Name):
                    _update_assignment_from_method_call(assignments, receiver.id, call)
        elif isinstance(node, ast.Return):
            info = infer_expr_type(node.value, assignments)
            if info.name == "result" and isinstance(node.value, ast.Name):
                info.name = node.value.id
            if not info.package:
                info.package = package
            if not info.semantic_type:
                info.semantic_type = infer_semantic_from_name(info.name, info.python_type, package)
            returns.append(info)

    if not returns:
        return ReturnInfo(name="", python_type="None", package=package, is_none=True)
    non_none = [r for r in returns if not r.is_none and r.python_type not in _NONE_RETURN_TYPES]
    if not non_none:
        return ReturnInfo(name="", python_type="None", package=package, is_none=True)
    known = [r for r in non_none if r.python_type not in _UNKNOWN_RETURN_TYPES]
    return known[0] if known else non_none[0]


def display_param_type(param: dict[str, Any]) -> str:
    name = (param.get("name") or "").strip().lower()
    annotation = clean_type(param.get("annotation") or param.get("python_type") or param.get("type") or param.get("default_type") or "")
    if annotation:
        return annotation
    if any(t in name for t in ("file_path", "filepath", "filename", "maya_file")):
        return "Path"
    if name in {"export_path", "source_path", "destination_path", "dest_path"}:
        return "Path"
    if any(t in name for t in ("folder", "directory", "dir_path", "directory_path")):
        return "Directory"
    if (
        name == "root_joint"
        or name.endswith("_joint")
        or name.endswith("_bone")
        or name.endswith("_ctrl")
        or name.endswith("_control")
        or name.endswith("_node")
        or name.endswith("_object")
        or name.endswith("_mesh")
        or name.endswith("_curve")
        or name in {"joint", "joint_name", "root", "root_node", "namespace", "object", "mesh", "curve", "node"}
    ):
        return "str"
    if name.endswith("_list") or name.endswith("_names") or name.endswith("_paths") or name in {"nodes", "joints", "meshes", "curves", "objects", "items", "reference_paths"}:
        return "list"
    if "frame" in name or name.startswith("num_") or name.startswith("max_") or name.startswith("min_") or name in {"index", "start", "end", "count", "iterations"}:
        return "int"
    if name.startswith("is_") or name.startswith("has_") or name.startswith("use_") or name.startswith("enable_"):
        return "bool"
    if any(t in name for t in ("weight", "scale", "radius", "amount", "threshold", "tolerance")):
        return "float"
    return "Any"


def display_output_type(output: dict[str, Any], symbol: dict[str, Any] | None = None) -> str:
    annotation = clean_type(output.get("annotation") or output.get("python_type") or output.get("type") or output.get("return_annotation") or "")
    if annotation and annotation not in _UNKNOWN_RETURN_TYPES:
        return annotation
    info = infer_symbol_return(symbol or {})
    return info.to_output().get("annotation", "Unknown") if not info.is_none else "None"


def symbol_has_data_return(symbol: dict[str, Any], outputs: list[dict[str, Any]] | None = None) -> bool:
    if symbol.get("utility_kind"):
        return True
    info = infer_symbol_return(symbol)
    if info.is_none or info.python_type in _NONE_RETURN_TYPES:
        return False
    explicit_outputs = outputs if outputs is not None else symbol.get("outputs")
    if explicit_outputs:
        for out in explicit_outputs:
            anno = clean_type((out or {}).get("annotation") or (out or {}).get("type") or "")
            name = str((out or {}).get("name") or "").lower()
            if name in {"none", "void"} or anno in _NONE_RETURN_TYPES:
                continue
            return True
    return True


def normalized_outputs(symbol: dict[str, Any], outputs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    info = infer_symbol_return(symbol)
    if info.is_none or info.python_type in _NONE_RETURN_TYPES:
        return []
    raw_outputs = outputs if outputs is not None else symbol.get("outputs")
    if raw_outputs:
        result = []
        for idx, raw in enumerate(raw_outputs):
            out = dict(raw or {})
            name = str(out.get("name") or "").strip().lower()
            anno = clean_type(out.get("annotation") or out.get("python_type") or out.get("type") or "")
            if name in {"none", "void"} or anno in _NONE_RETURN_TYPES:
                continue
            out.setdefault("name", "result" if idx == 0 else f"output_{idx + 1}")
            if not anno or anno in _UNKNOWN_RETURN_TYPES:
                out["annotation"] = info.to_output().get("annotation", info.python_type)
            out.setdefault("semantic_type", info.semantic_type)
            out.setdefault("package", info.package)
            result.append(out)
        return result
    return [info.to_output()]
