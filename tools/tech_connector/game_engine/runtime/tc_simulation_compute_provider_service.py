"""Truthful compute-provider discovery and persistent simulation buffer boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
from typing import Any

import numpy as np


@dataclass(frozen=True)
class ComputeProviderStatus:
    provider_id: str
    available: bool
    device_type: str
    device_name: str
    supports_persistent_buffers: bool
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PersistentComputeBuffer:
    provider_id: str
    handle: Any
    shape: tuple[int, ...]
    dtype: str
    nbytes: int
    residency: str
    revision: int = 0


class ArrayComputeProvider:
    """Small NumPy/CuPy-compatible boundary; solver kernels remain separately registered."""

    def __init__(self, status: ComputeProviderStatus, array_module: Any) -> None:
        self.status = status
        self.array_module = array_module

    def allocate(self, shape: tuple[int, ...], dtype: str = "float32") -> PersistentComputeBuffer:
        if not self.status.available:
            raise RuntimeError(self.status.reason or f"Compute provider {self.status.provider_id} is unavailable.")
        handle = self.array_module.empty(shape, dtype=dtype)
        residency = "persistent_device" if self.status.device_type == "gpu" else "persistent_host_soa"
        return PersistentComputeBuffer(
            self.status.provider_id, handle, tuple(int(value) for value in shape), str(handle.dtype),
            int(handle.nbytes), residency,
        )

    def upload(self, buffer: PersistentComputeBuffer, values: Any) -> None:
        self._require_owned(buffer)
        incoming = self.array_module.asarray(values, dtype=buffer.dtype)
        if tuple(incoming.shape) != buffer.shape:
            raise ValueError(f"Buffer shape {buffer.shape} does not match upload shape {tuple(incoming.shape)}.")
        buffer.handle[...] = incoming
        buffer.revision += 1

    def download(self, buffer: PersistentComputeBuffer) -> np.ndarray:
        self._require_owned(buffer)
        if self.status.device_type == "gpu":
            return np.asarray(self.array_module.asnumpy(buffer.handle))
        return np.asarray(buffer.handle).copy()

    def synchronize(self) -> None:
        if self.status.device_type == "gpu":
            self.array_module.cuda.get_current_stream().synchronize()

    def _require_owned(self, buffer: PersistentComputeBuffer) -> None:
        if buffer.provider_id != self.status.provider_id:
            raise ValueError(f"Buffer belongs to {buffer.provider_id}, not {self.status.provider_id}.")


COMPUTE_PROVIDERS: dict[str, ArrayComputeProvider] = {}


def register_compute_provider(provider: ArrayComputeProvider) -> None:
    if not isinstance(provider, ArrayComputeProvider):
        raise TypeError("A compute provider must implement the ArrayComputeProvider boundary.")
    COMPUTE_PROVIDERS[provider.status.provider_id] = provider


def compute_provider(provider_id: str) -> ArrayComputeProvider:
    try:
        return COMPUTE_PROVIDERS[str(provider_id)]
    except KeyError as exc:
        raise KeyError(f"Unknown compute provider: {provider_id}") from exc


def compute_provider_statuses(*, refresh: bool = False) -> list[dict[str, Any]]:
    if refresh or not COMPUTE_PROVIDERS:
        discover_compute_providers(refresh=refresh)
    return [
        {
            "provider_id": item.status.provider_id,
            "available": item.status.available,
            "device_type": item.status.device_type,
            "device_name": item.status.device_name,
            "supports_persistent_buffers": item.status.supports_persistent_buffers,
            "reason": item.status.reason,
            "metadata": dict(item.status.metadata),
        }
        for item in COMPUTE_PROVIDERS.values()
    ]


def discover_compute_providers(*, refresh: bool = False) -> list[ArrayComputeProvider]:
    if COMPUTE_PROVIDERS and not refresh:
        return list(COMPUTE_PROVIDERS.values())
    COMPUTE_PROVIDERS.clear()
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus("numpy_cpu", True, "cpu", "NumPy CPU", True,
                              metadata={"numpy_version": np.__version__}),
        np,
    ))
    if importlib.util.find_spec("cupy") is None:
        register_compute_provider(ArrayComputeProvider(
            ComputeProviderStatus("cupy_cuda", False, "gpu", "CUDA GPU", True,
                                  "CuPy is not installed; no CUDA provider was activated."),
            np,
        ))
        return list(COMPUTE_PROVIDERS.values())
    try:
        import cupy as cp

        device_count = int(cp.cuda.runtime.getDeviceCount())
        if device_count <= 0:
            raise RuntimeError("CUDA reported zero devices")
        properties = cp.cuda.runtime.getDeviceProperties(0)
        raw_name = properties.get("name", "CUDA GPU")
        device_name = raw_name.decode() if isinstance(raw_name, bytes) else str(raw_name)
        register_compute_provider(ArrayComputeProvider(
            ComputeProviderStatus("cupy_cuda", True, "gpu", device_name, True,
                                  metadata={"device_count": device_count, "cupy_version": cp.__version__}),
            cp,
        ))
    except Exception as exc:  # CUDA driver/runtime failures must remain visible, not become fake GPU support.
        register_compute_provider(ArrayComputeProvider(
            ComputeProviderStatus("cupy_cuda", False, "gpu", "CUDA GPU", True,
                                  f"CUDA provider probe failed: {exc}"),
            np,
        ))
    return list(COMPUTE_PROVIDERS.values())


discover_compute_providers()


__all__ = [
    "ArrayComputeProvider", "ComputeProviderStatus", "PersistentComputeBuffer",
    "compute_provider", "compute_provider_statuses", "discover_compute_providers", "register_compute_provider",
]
