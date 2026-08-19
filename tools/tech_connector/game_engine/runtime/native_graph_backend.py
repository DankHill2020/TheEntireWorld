from __future__ import annotations

"""ctypes boundary for the dependency-free TC native graph runtime."""

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Iterable


TC_GRAPH_ABI_VERSION = 1


class NativeGraphBackendError(RuntimeError):
    pass


class _Vector2(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float)]


class _Vector3(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("z", ctypes.c_float),
    ]


class _MovementInput(ctypes.Structure):
    _fields_ = [
        ("direction", _Vector2),
        ("current_velocity", _Vector3),
        ("maximum_speed", ctypes.c_float),
        ("acceleration", ctypes.c_float),
        ("delta_seconds", ctypes.c_float),
    ]


@dataclass(frozen=True)
class NativeGraphBackendStatus:
    available: bool
    library_path: str = ""
    abi_version: int = 0
    message: str = ""


class NativeGraphBackend:
    def __init__(self, library_path: str | Path | None = None) -> None:
        path = Path(library_path) if library_path else discover_native_graph_library()
        if path is None or not path.is_file():
            raise NativeGraphBackendError(
                "TC native graph runtime is not installed. Build or install "
                "tech_connector/game_engine/native first."
            )
        self.library_path = path.resolve()
        try:
            self._library = ctypes.CDLL(str(self.library_path))
        except OSError as exc:
            raise NativeGraphBackendError(
                f"Could not load native graph runtime '{self.library_path}': {exc}"
            ) from exc
        self._configure_signatures()
        version = int(self._library.tc_graph_abi_version())
        if version != TC_GRAPH_ABI_VERSION:
            raise NativeGraphBackendError(
                f"Native graph ABI {version} is incompatible with expected "
                f"ABI {TC_GRAPH_ABI_VERSION}."
            )

    @property
    def abi_version(self) -> int:
        return int(self._library.tc_graph_abi_version())

    def clamp_input_axis(self, value: Any) -> tuple[float, float]:
        x, y = _vector(value, 2, "Input Action")
        source = _Vector2(x, y)
        output = _Vector2()
        self._check(
            self._library.tc_graph_clamp_input_axis(
                ctypes.byref(source),
                ctypes.byref(output),
            )
        )
        return float(output.x), float(output.y)

    def calculate_movement_velocity(
        self,
        *,
        direction: Any,
        current_velocity: Any,
        maximum_speed: float,
        acceleration: float,
        delta_seconds: float,
    ) -> tuple[float, float, float]:
        direction_x, direction_y = _vector(direction, 2, "Direction")
        velocity_x, velocity_y, velocity_z = _vector(
            current_velocity,
            3,
            "Current Velocity",
        )
        source = _MovementInput(
            _Vector2(direction_x, direction_y),
            _Vector3(velocity_x, velocity_y, velocity_z),
            float(maximum_speed),
            float(acceleration),
            float(delta_seconds),
        )
        output = _Vector3()
        self._check(
            self._library.tc_graph_calculate_movement_velocity(
                ctypes.byref(source),
                ctypes.byref(output),
            )
        )
        return float(output.x), float(output.y), float(output.z)

    def _configure_signatures(self) -> None:
        self._library.tc_graph_abi_version.argtypes = []
        self._library.tc_graph_abi_version.restype = ctypes.c_uint32
        self._library.tc_graph_status_message.argtypes = [ctypes.c_int]
        self._library.tc_graph_status_message.restype = ctypes.c_char_p
        self._library.tc_graph_clamp_input_axis.argtypes = [
            ctypes.POINTER(_Vector2),
            ctypes.POINTER(_Vector2),
        ]
        self._library.tc_graph_clamp_input_axis.restype = ctypes.c_int
        self._library.tc_graph_calculate_movement_velocity.argtypes = [
            ctypes.POINTER(_MovementInput),
            ctypes.POINTER(_Vector3),
        ]
        self._library.tc_graph_calculate_movement_velocity.restype = ctypes.c_int

    def _check(self, status: int) -> None:
        if int(status) == 0:
            return
        raw = self._library.tc_graph_status_message(int(status))
        message = raw.decode("utf-8", errors="replace") if raw else "Unknown error"
        raise NativeGraphBackendError(f"Native graph operation failed: {message}.")


def discover_native_graph_library(
    search_roots: Iterable[str | Path] = (),
) -> Path | None:
    names = (
        "tc_graph_runtime.dll",
        "libtc_graph_runtime.dylib",
        "libtc_graph_runtime.so",
    )
    candidates: list[Path] = []
    configured = os.environ.get("TECH_CONNECTOR_NATIVE_GRAPH_LIBRARY", "").strip()
    if configured:
        candidates.append(Path(configured))
    game_engine_root = Path(__file__).resolve().parents[1]
    workspace_root = Path(__file__).resolve().parents[3]
    roots = [
        *(Path(root) for root in search_roots),
        game_engine_root / "native" / "bin",
        workspace_root / ".tc_native_build",
        workspace_root / "dist" / "tech_connector" / "native",
    ]
    for root in roots:
        for name in names:
            candidates.append(root / name)
            candidates.append(root / "Release" / name)
    return next((path.resolve() for path in candidates if path.is_file()), None)


def native_graph_backend_status() -> NativeGraphBackendStatus:
    path = discover_native_graph_library()
    if path is None:
        return NativeGraphBackendStatus(
            False,
            message="Native graph runtime is not built or installed.",
        )
    try:
        backend = NativeGraphBackend(path)
    except NativeGraphBackendError as exc:
        return NativeGraphBackendStatus(False, str(path), message=str(exc))
    return NativeGraphBackendStatus(
        True,
        str(backend.library_path),
        backend.abi_version,
        "Native graph runtime is ready.",
    )


def _vector(value: Any, size: int, label: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"{label} must contain exactly {size} values.")
    return tuple(float(component) for component in value)


__all__ = [
    "NativeGraphBackend",
    "NativeGraphBackendError",
    "NativeGraphBackendStatus",
    "TC_GRAPH_ABI_VERSION",
    "discover_native_graph_library",
    "native_graph_backend_status",
]
