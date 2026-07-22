"""Ludus Unreal Bridge Delegate mock provider to demonstrate bridge swapping."""

from typing import Any

class LudusUnrealBridge:
    """Mock Ludus Unreal Bridge delegate class."""
    
    def execute_python(self, source: str, timeout: float = 30.0, reset_globals: bool = False) -> dict[str, Any]:
        """Intercept and execute Unreal python code."""
        print(f"\n---> [LUDUS INTERCEPT] Received Unreal code:\n{source}\n", flush=True)
        return {
            "ok": True,
            "output": f"[LUDUS SWAP SUCCESS]: Intercepted and routed code to Ludus AI!\nOriginal source length: {len(source)} characters.",
            "result": "ludus_routed_result"
        }

    def call(self, function_path: str, args=None, kwargs=None, timeout: float = 30, **kwargs_extra) -> tuple[bool, str]:
        """Intercept direct function calls and route them."""
        print(f"\n---> [LUDUS INTERCEPT] Direct function call: '{function_path}' with args: {args}, kwargs: {kwargs}\n", flush=True)
        return True, f"[LUDUS SWAP SUCCESS]: Executed function '{function_path}'"

    def safe_call(self, function_path: str, args=None, kwargs=None, **kwargs_extra) -> dict[str, Any]:
        """Intercept low-level safe calls."""
        print(f"\n---> [LUDUS INTERCEPT] safe_call: '{function_path}'\n", flush=True)
        return {
            "ok": True,
            "data": f"[LUDUS SWAP SUCCESS]: Executed safe_call for '{function_path}'",
            "error": None
        }

    def health_check(self, timeout: float = 5.0) -> dict[str, Any]:
        """Check status."""
        return {"status": "healthy", "provider": "ludus"}
