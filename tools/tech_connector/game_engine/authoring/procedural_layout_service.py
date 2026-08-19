from __future__ import annotations

"""Spline layout and bounded shape grammar for modular procedural assets."""

from dataclasses import asdict, dataclass, field
import hashlib
import math
from typing import Any

from tech_connector.game_engine.authoring.procedural_generation_service import (
    ProceduralInstance,
    ProceduralPayload,
    ProceduralPoint,
)


Vec3 = tuple[float, float, float]


def _random(*parts: Any) -> float:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)


@dataclass(frozen=True)
class SplinePath:
    control_points: tuple[Vec3, ...]
    closed: bool = False

    def __post_init__(self) -> None:
        if len(self.control_points) < 2:
            raise ValueError("Spline layouts require at least two control points.")

    @property
    def segments(self) -> tuple[tuple[Vec3, Vec3], ...]:
        rows = list(zip(self.control_points, self.control_points[1:]))
        if self.closed:
            rows.append((self.control_points[-1], self.control_points[0]))
        return tuple(rows)

    @property
    def length(self) -> float:
        return sum(math.dist(left, right) for left, right in self.segments)

    def sample(self, distance: float) -> tuple[Vec3, Vec3, int]:
        remaining = max(0.0, min(self.length, float(distance)))
        for index, (left, right) in enumerate(self.segments):
            length = math.dist(left, right)
            if remaining <= length or index == len(self.segments) - 1:
                amount = remaining / length if length else 0.0
                position = tuple(left[axis] + (right[axis] - left[axis]) * amount for axis in range(3))
                tangent = tuple((right[axis] - left[axis]) / (length or 1.0) for axis in range(3))
                return position, tangent, index
            remaining -= length
        return self.control_points[-1], (0.0, 0.0, 1.0), len(self.segments) - 1


@dataclass(frozen=True)
class GrammarModule:
    symbol: str
    asset: str
    length: float
    weight: float = 1.0
    lateral_offset: float = 0.0
    vertical_offset: float = 0.0
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.symbol or not self.asset or self.length <= 0.0:
            raise ValueError("Grammar modules require a symbol, asset, and positive length.")


@dataclass(frozen=True)
class ShapeGrammar:
    axiom: tuple[str, ...]
    modules: tuple[GrammarModule, ...]
    productions: dict[str, tuple[tuple[str, ...], ...]] = field(default_factory=dict)
    seed: int = 0
    max_depth: int = 4
    max_modules: int = 10000
    fit: str = "repeat"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ShapeGrammar":
        return cls(
            axiom=tuple(str(value) for value in data.get("axiom") or ()),
            modules=tuple(GrammarModule(**row) for row in data.get("modules") or ()),
            productions={
                str(symbol): tuple(tuple(str(item) for item in option) for option in options)
                for symbol, options in (data.get("productions") or {}).items()
            },
            seed=int(data.get("seed", 0)),
            max_depth=int(data.get("max_depth", 4)),
            max_modules=int(data.get("max_modules", 10000)),
            fit=str(data.get("fit") or "repeat"),
        )


def expand_shape_grammar(grammar: ShapeGrammar) -> tuple[str, ...]:
    symbols = list(grammar.axiom)
    for depth in range(max(0, grammar.max_depth)):
        expanded: list[str] = []
        changed = False
        for index, symbol in enumerate(symbols):
            options = grammar.productions.get(symbol)
            if not options:
                expanded.append(symbol)
                continue
            selected = min(len(options) - 1, int(_random(grammar.seed, depth, index, symbol) * len(options)))
            expanded.extend(options[selected])
            changed = True
            if len(expanded) > grammar.max_modules:
                raise ValueError("Shape grammar exceeded its module safety limit.")
        symbols = expanded
        if not changed:
            break
    terminal_symbols = {module.symbol for module in grammar.modules}
    unresolved = sorted({symbol for symbol in symbols if symbol not in terminal_symbols})
    if unresolved:
        raise ValueError("Shape grammar contains unresolved symbols: " + ", ".join(unresolved))
    return tuple(symbols)


def _choose_module(grammar: ShapeGrammar, symbol: str, occurrence: int) -> GrammarModule:
    candidates = [module for module in grammar.modules if module.symbol == symbol and module.weight > 0.0]
    if not candidates:
        raise ValueError(f"Shape grammar has no module for terminal symbol {symbol}.")
    total = sum(module.weight for module in candidates)
    pick = _random(grammar.seed, symbol, occurrence) * total
    cursor = 0.0
    for module in candidates:
        cursor += module.weight
        if pick <= cursor:
            return module
    return candidates[-1]


def place_shape_grammar_on_spline(path: SplinePath, grammar: ShapeGrammar) -> ProceduralPayload:
    symbols = expand_shape_grammar(grammar)
    if not symbols:
        return ProceduralPayload()
    chosen: list[GrammarModule] = []
    occurrence = 0
    cursor = 0.0
    pattern_index = 0
    while cursor < path.length and len(chosen) < grammar.max_modules:
        symbol = symbols[pattern_index]
        module = _choose_module(grammar, symbol, occurrence)
        if cursor + module.length > path.length and grammar.fit == "complete_only":
            break
        chosen.append(module)
        cursor += module.length
        occurrence += 1
        pattern_index += 1
        if pattern_index >= len(symbols):
            if grammar.fit != "repeat":
                break
            pattern_index = 0
    if len(chosen) >= grammar.max_modules and cursor < path.length:
        raise ValueError("Spline grammar placement exceeded its module safety limit.")

    points: list[ProceduralPoint] = []
    instances: list[ProceduralInstance] = []
    cursor = 0.0
    for index, module in enumerate(chosen):
        center_distance = min(path.length, cursor + module.length * 0.5)
        position, tangent, segment = path.sample(center_distance)
        yaw = math.degrees(math.atan2(tangent[0], tangent[2]))
        right = (tangent[2], 0.0, -tangent[0])
        position = (
            position[0] + right[0] * module.lateral_offset,
            position[1] + module.vertical_offset,
            position[2] + right[2] * module.lateral_offset,
        )
        point_id = f"grammar:{index}:{module.symbol}"
        attributes = {
            "asset": module.asset,
            "symbol": module.symbol,
            "module_length": module.length,
            "spline_distance": center_distance,
            "spline_u": center_distance / max(path.length, 1e-8),
            "spline_segment": segment,
            "tangent": tangent,
            "tags": module.tags,
        }
        point = ProceduralPoint(
            point_id=point_id,
            position=position,
            rotation=(0.0, yaw, 0.0),
            attributes=attributes,
            seed=grammar.seed,
        )
        points.append(point)
        instances.append(
            ProceduralInstance(
                instance_id=point_id,
                asset=module.asset,
                position=position,
                rotation=point.rotation,
                attributes=attributes,
            )
        )
        cursor += module.length
    return ProceduralPayload(
        points=points,
        instances=instances,
        metadata={
            "path_length": path.length,
            "filled_length": min(cursor, path.length),
            "remainder": max(0.0, path.length - cursor),
            "module_count": len(instances),
            "closed": path.closed,
        },
    )


def create_road_layout(
    path: SplinePath,
    *,
    segment_asset: str,
    segment_length: float,
    width: float = 7.0,
    lanes: int = 2,
    seed: int = 0,
) -> ProceduralPayload:
    module = GrammarModule("R", segment_asset, segment_length, tags=("road",))
    payload = place_shape_grammar_on_spline(
        path,
        ShapeGrammar(axiom=("R",), modules=(module,), seed=seed, fit="repeat"),
    )
    for instance in payload.instances:
        instance.attributes.update({"road_width": width, "lane_count": lanes})
    for point in payload.points:
        point.attributes.update({"road_width": width, "lane_count": lanes})
    payload.metadata.update({"road_width": width, "lane_count": lanes, "network_role": "road"})
    return payload
