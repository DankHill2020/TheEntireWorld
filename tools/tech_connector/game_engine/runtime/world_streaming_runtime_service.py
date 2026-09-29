"""Budgeted World Partition residency with deterministic source prioritization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class StreamingSource:
    source_id: str
    position: tuple[float, float]
    loading_range: float
    priority: int = 0
    velocity: tuple[float, float] = (0.0, 0.0)


@dataclass
class StreamingCellState:
    cell_id: str
    bounds: tuple[float, float, float, float]
    memory_mb: float
    members: tuple[str, ...] = ()
    resident: bool = False
    requested: bool = False
    last_required_frame: int = -1
    hlod_asset_id: str = ""

    @property
    def center(self) -> tuple[float, float]:
        return ((self.bounds[0] + self.bounds[2]) * 0.5, (self.bounds[1] + self.bounds[3]) * 0.5)


@dataclass(frozen=True)
class StreamingFrameReceipt:
    frame: int
    loaded: tuple[str, ...]
    unloaded: tuple[str, ...]
    resident: tuple[str, ...]
    queued: tuple[str, ...]
    memory_mb: float
    budget_memory_mb: float
    budget_cells: int
    dropped_requests: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorldStreamingRuntime:
    def __init__(
        self, cells: Sequence[StreamingCellState], *, maximum_loaded_cells: int = 256,
        memory_mb: float = 2048.0, maximum_requests: int = 16, unload_hysteresis_frames: int = 8,
        preload_seconds: float = 0.35,
    ) -> None:
        self.cells = {cell.cell_id: cell for cell in cells}
        self.maximum_loaded_cells = max(1, int(maximum_loaded_cells))
        self.memory_budget_mb = max(1.0, float(memory_mb))
        self.maximum_requests = max(1, int(maximum_requests))
        self.unload_hysteresis_frames = max(0, int(unload_hysteresis_frames))
        self.preload_seconds = max(0.0, float(preload_seconds))
        self.frame = 0

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any]) -> "WorldStreamingRuntime":
        cells = []
        for row in manifest.get("cells") or ():
            source = dict(row); bounds = tuple(float(value) for value in source.get("bounds") or (0, 0, 0, 0))
            members = tuple(str(item.get("asset_id") or "") for item in source.get("members") or () if str(item.get("asset_id") or ""))
            cells.append(StreamingCellState(str(source.get("id") or ""), bounds[:4],
                                            float(source.get("memory_mb", max(1.0, len(members) * 4.0))), members,
                                            hlod_asset_id=str(source.get("hlod_asset_id") or "")))
        budgets = dict(manifest.get("budgets") or {})
        return cls(cells, maximum_loaded_cells=int(budgets.get("maximum_loaded_cells", 256)),
                   memory_mb=float(budgets.get("memory_mb", 2048)),
                   maximum_requests=int(budgets.get("maximum_requests", 16)))

    def tick(self, sources: Sequence[StreamingSource], *, delta_seconds: float = 1 / 60) -> StreamingFrameReceipt:
        self.frame += 1
        ranked: list[tuple[int, float, str]] = []
        for cell in self.cells.values():
            best: tuple[int, float] | None = None
            for source in sources:
                predicted = (source.position[0] + source.velocity[0] * self.preload_seconds,
                             source.position[1] + source.velocity[1] * self.preload_seconds)
                distance = _distance_to_bounds(predicted, cell.bounds)
                if distance <= source.loading_range:
                    candidate = (-int(source.priority), distance)
                    if best is None or candidate < best: best = candidate
            cell.requested = best is not None
            if best is not None:
                cell.last_required_frame = self.frame
                ranked.append((best[0], best[1], cell.cell_id))
        ranked.sort()
        selected: list[str] = []; selected_memory = 0.0; dropped = 0
        for _priority, _distance, cell_id in ranked:
            cell = self.cells[cell_id]
            if len(selected) >= self.maximum_loaded_cells or selected_memory + cell.memory_mb > self.memory_budget_mb:
                dropped += 1; continue
            selected.append(cell_id); selected_memory += cell.memory_mb
        selected_set = set(selected)
        loaded: list[str] = []; unloaded: list[str] = []
        request_budget = self.maximum_requests
        for cell_id in selected:
            cell = self.cells[cell_id]
            if not cell.resident and request_budget > 0:
                cell.resident = True; loaded.append(cell_id); request_budget -= 1
        for cell in self.cells.values():
            if cell.resident and cell.cell_id not in selected_set and self.frame - cell.last_required_frame > self.unload_hysteresis_frames:
                cell.resident = False; unloaded.append(cell.cell_id)
        resident = tuple(sorted(cell.cell_id for cell in self.cells.values() if cell.resident))
        queued = tuple(cell_id for cell_id in selected if not self.cells[cell_id].resident)
        memory = sum(cell.memory_mb for cell in self.cells.values() if cell.resident)
        return StreamingFrameReceipt(self.frame, tuple(loaded), tuple(unloaded), resident, queued,
                                     memory, self.memory_budget_mb, self.maximum_loaded_cells, dropped)

    def diagnostics(self) -> dict[str, Any]:
        resident = [cell for cell in self.cells.values() if cell.resident]
        return {"frame": self.frame, "cell_count": len(self.cells), "resident_cells": len(resident),
                "resident_memory_mb": sum(cell.memory_mb for cell in resident),
                "memory_budget_mb": self.memory_budget_mb, "cell_budget": self.maximum_loaded_cells,
                "requested_cells": sum(cell.requested for cell in self.cells.values())}


def _distance_to_bounds(position: tuple[float, float], bounds: tuple[float, float, float, float]) -> float:
    x = max(bounds[0], min(bounds[2], position[0])); z = max(bounds[1], min(bounds[3], position[1]))
    return math.hypot(position[0] - x, position[1] - z)


__all__ = ["StreamingCellState", "StreamingFrameReceipt", "StreamingSource", "WorldStreamingRuntime"]
