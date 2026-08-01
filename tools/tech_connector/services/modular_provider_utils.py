"""Utility for dynamic custom provider loading and signature-matching execution."""

import importlib
import inspect
import sys
from typing import Any, Callable, Optional


def discover_module_callables(module_path: Optional[str]) -> dict[str, str]:
    """Return public callable names and human-readable signatures for a module."""
    path_str = str(module_path or "").strip()
    if not path_str or path_str == "default":
        return {}
    module = importlib.import_module(path_str)
    callables: dict[str, str] = {}
    for name in sorted(dir(module)):
        if name.startswith("_"):
            continue
        value = getattr(module, name, None)
        if not callable(value):
            continue
        try:
            signature = str(inspect.signature(value))
        except Exception:
            signature = "(...)"
        callables[name] = f"{name}{signature}"
    return callables


def resolve_custom_provider_binding(
    topic: str,
    module_path: Optional[str],
    default_callable: str,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    """Resolve a Tech Connector provider port to the user's selected function."""
    path_str = str(module_path or "").strip()
    if not path_str or path_str == "default":
        return "default"
    if settings is None:
        try:
            from tech_connector.services.settings_service import load_settings
            settings = load_settings()
        except Exception:
            settings = {}
    bindings = settings.get("custom_provider_function_bindings") or {}
    topic_bindings = bindings.get(topic) if isinstance(bindings, dict) else {}
    selected = default_callable
    if isinstance(topic_bindings, dict):
        selected = str(topic_bindings.get(default_callable) or default_callable).strip() or default_callable
    return f"{path_str}.{selected}"


def signature_accepts_expected(candidate: Callable[..., Any], expected: Callable[..., Any]) -> tuple[bool, str]:
    """Best-effort check that a candidate can accept the expected function inputs."""
    try:
        candidate_sig = inspect.signature(candidate)
        expected_sig = inspect.signature(expected)
    except Exception:
        return True, "signature unavailable"

    candidate_params = list(candidate_sig.parameters.values())
    expected_params = list(expected_sig.parameters.values())
    has_var_positional = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in candidate_params)
    has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in candidate_params)
    candidate_names = {
        p.name
        for p in candidate_params
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    positional_capacity = sum(
        1
        for p in candidate_params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    )
    required_positional = [
        p for p in expected_params
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    missing_names = [
        p.name for p in expected_params
        if p.kind == inspect.Parameter.KEYWORD_ONLY
        and p.default is inspect.Parameter.empty
        and not has_var_keyword
        and p.name not in candidate_names
    ]
    if missing_names:
        return False, "missing keyword input(s): " + ", ".join(missing_names)
    if not has_var_positional and positional_capacity < len(required_positional):
        return False, f"accepts {positional_capacity} positional input(s), expected at least {len(required_positional)}"
    return True, "signature compatible"


def invoke_custom_provider(
    provider_path: Optional[str],
    fallback_fn: Callable[..., Any],
    *args: Any,
    allow_fallback: bool = True,
    **kwargs: Any
) -> Any:
    """Resolve a custom provider function/module path and invoke it with signature matching.

    If provider_path is None, empty, or "default", calls fallback_fn.
    Otherwise, resolves the target function, inspects its signature, maps matching
    arguments, and invokes it. Fallback is opt-in for configured providers so a
    missing or failing custom module cannot silently bypass an intended workflow.
    """
    path_str = str(provider_path or "").strip()
    if not path_str or path_str == "default":
        return fallback_fn(*args, **kwargs)

    try:
        target_fn = None
        # Try to resolve as a full function path (e.g. module.submodule.func_name)
        if "." in path_str:
            parts = path_str.split(".")
            # Try progressively shorter module paths in case the function name has dots or there are nested modules
            for i in range(len(parts) - 1, 0, -1):
                mod_name = ".".join(parts[:i])
                attr_name = ".".join(parts[i:])
                try:
                    mod = importlib.import_module(mod_name)
                    # Traverse nested attributes if necessary
                    obj = mod
                    for sub_attr in attr_name.split("."):
                        obj = getattr(obj, sub_attr)
                    if callable(obj):
                        target_fn = obj
                        break
                except (ImportError, AttributeError):
                    continue

        # If not resolved yet, try treating path_str as a module path and finding a function with fallback_fn's name
        if not target_fn:
            try:
                mod = importlib.import_module(path_str)
                func_name = fallback_fn.__name__
                if hasattr(mod, func_name):
                    obj = getattr(mod, func_name)
                    if callable(obj):
                        target_fn = obj
            except ImportError:
                pass

        if not target_fn:
            if not allow_fallback:
                raise RuntimeError(f"Could not resolve custom provider: '{path_str}'.")
            print(f"[ModularProvider] Warning: Could not resolve custom provider: '{path_str}'. Falling back to default.", file=sys.stderr, flush=True)
            return fallback_fn(*args, **kwargs)

        # Inspect target signature to match arguments
        sig = inspect.signature(target_fn)
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        has_var_positional = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())

        # If it takes *args and **kwargs (or we want to just pass everything), check parameter names
        target_args = []
        target_kwargs = {}

        # List of positional/keyword parameters of the target function
        params = list(sig.parameters.values())

        # Track which kwargs have been consumed or matched
        consumed_kwargs = set()

        # Map positional args and kwargs to parameters
        arg_index = 0
        for param in params:
            if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                # Check if we can satisfy this from kwargs by name first
                if param.name in kwargs:
                    target_kwargs[param.name] = kwargs[param.name]
                    consumed_kwargs.add(param.name)
                # Else satisfy from positional args if available
                elif arg_index < len(args):
                    target_args.append(args[arg_index])
                    arg_index += 1
                # Else let Python use default value or raise error if required
            elif param.kind == inspect.Parameter.KEYWORD_ONLY:
                if param.name in kwargs:
                    target_kwargs[param.name] = kwargs[param.name]
                    consumed_kwargs.add(param.name)
            elif param.kind == inspect.Parameter.VAR_POSITIONAL:
                # Add any remaining positional args
                while arg_index < len(args):
                    target_args.append(args[arg_index])
                    arg_index += 1

        if has_var_keyword:
            # Pass all remaining keyword arguments
            for k, v in kwargs.items():
                if k not in target_kwargs:
                    target_kwargs[k] = v
        else:
            # If no **kwargs, but there are unconsumed kwargs, check if the target function accepts them or drop them
            for k, v in kwargs.items():
                if k not in consumed_kwargs and k in sig.parameters:
                    target_kwargs[k] = v

        return target_fn(*target_args, **target_kwargs)

    except Exception as exc:
        if not allow_fallback:
            raise
        print(f"[ModularProvider] Error calling custom provider '{path_str}': {exc}. Falling back to default.", file=sys.stderr, flush=True)
        return fallback_fn(*args, **kwargs)


class DCCBridgeDelegateMixin:
    """Mixin to delegate all bridge calls to a custom provider if configured in settings."""

    def init_delegate(self, dcc_name: str) -> None:
        self._custom_delegate = None
        try:
            from tech_connector.services.settings_service import load_settings
            import importlib
            settings = load_settings()
            custom_bridges = settings.get("custom_dcc_bridges")
            if isinstance(custom_bridges, dict):
                custom_path = custom_bridges.get(dcc_name.lower())
                if custom_path and custom_path != "default":
                    if "." in custom_path:
                        mod_name, class_name = custom_path.rsplit(".", 1)
                        mod = importlib.import_module(mod_name)
                        cls_obj = getattr(mod, class_name)
                        self._custom_delegate = cls_obj()
        except Exception as e:
            print(f"[DCCBridgeDelegateMixin] Error loading custom bridge for {dcc_name}: {e}", file=sys.stderr, flush=True)

    def __getattribute__(self, name: str) -> Any:
        if name in ("_custom_delegate", "init_delegate", "__dict__", "__class__"):
            return object.__getattribute__(self, name)

        delegate = None
        try:
            delegate = object.__getattribute__(self, "_custom_delegate")
        except AttributeError:
            pass

        if delegate is not None and hasattr(delegate, name):
            return getattr(delegate, name)

        return object.__getattribute__(self, name)
