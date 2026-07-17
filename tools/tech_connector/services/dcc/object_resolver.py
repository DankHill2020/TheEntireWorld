from __future__ import annotations

"""Host-agnostic typed object resolver contracts for DCC operations.

This layer does not try to store live DCC objects in the desktop process. Live
objects only exist inside the DCC Python interpreter. Instead, it describes the
expected object type, resolver strategy, and serializable handle shape. A DCC-
specific resolver can then resolve the handle into the real host object at the
moment of execution.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

ResolverRisk = Literal["read_only", "low", "medium", "high"]
ResolverCardinality = Literal["one", "many", "optional"]


@dataclass(frozen=True)
class ObjectHandle:
    """Serializable reference to a DCC object."""

    dcc: str
    kind: str
    ref: str
    name: str = ""
    class_name: str = ""
    path: str = ""
    source: str = ""
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolverSpec:
    """A typed input expectation for an operation argument."""

    name: str
    kind: str
    aliases: tuple[str, ...] = ()
    cardinality: ResolverCardinality = "one"
    required: bool = True
    description: str = ""
    strategies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperationContract:
    """Operation metadata that lets the runtime satisfy function arguments."""

    key: str
    dcc: str
    function: str = ""
    expects: tuple[ResolverSpec, ...] = ()
    produces: tuple[str, ...] = ()
    mutates: bool = False
    risk: ResolverRisk = "read_only"
    preflight: tuple[str, ...] = ()
    validate: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["expects"] = [item.to_dict() for item in self.expects]
        return data


class ObjectResolverError(RuntimeError):
    pass


def normalize_query(value: Any) -> str:
    if isinstance(value, ObjectHandle):
        return value.ref or value.path or value.name
    if isinstance(value, dict):
        return str(
            value.get("ref")
            or value.get("path")
            or value.get("name")
            or value.get("label")
            or ""
        )
    return str(value or "").strip()


def handle_from_mapping(
    dcc: str, kind: str, data: dict[str, Any], *, source: str = ""
) -> ObjectHandle:
    return ObjectHandle(
        dcc=dcc,
        kind=kind,
        ref=str(
            data.get("ref")
            or data.get("path")
            or data.get("object_path")
            or data.get("asset_path")
            or ""
        ),
        name=str(data.get("name") or data.get("label") or data.get("display_name") or ""),
        class_name=str(data.get("class") or data.get("class_name") or ""),
        path=str(data.get("path") or data.get("object_path") or data.get("asset_path") or ""),
        source=source or str(data.get("source") or ""),
        confidence=float(data.get("confidence", 1.0) or 1.0),
        metadata={
            k: v
            for k, v in data.items()
            if k
            not in {
                "ref",
                "path",
                "object_path",
                "asset_path",
                "name",
                "label",
                "display_name",
                "class",
                "class_name",
                "confidence",
                "source",
            }
        },
    )
