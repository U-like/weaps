"""Machine-readable contract between a virtual fly body and MaleCNS.

The manifest deliberately stores semantic ports separately from the graph.  A
single MaleCNS body may belong to more than one functional mask/port, and the
connectome is never physically split by region.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

PortDirection = Literal["input", "output", "diagnostic"]
PortStatus = Literal["candidate", "validated"]


@dataclass(frozen=True)
class BodyRef:
    body_id: int
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.body_id <= 0:
            raise ValueError(f"body_id must be positive, got {self.body_id}")
        if not self.weight >= 0.0:
            raise ValueError(f"body weight must be non-negative, got {self.weight}")

    @classmethod
    def from_value(cls, value: int | Mapping[str, Any]) -> "BodyRef":
        if isinstance(value, int):
            return cls(value)
        return cls(body_id=int(value["body_id"]), weight=float(value.get("weight", 1.0)))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"body_id": self.body_id}
        if self.weight != 1.0:
            out["weight"] = self.weight
        return out


@dataclass(frozen=True)
class IOPort:
    name: str
    direction: PortDirection
    bodies: tuple[BodyRef, ...]
    modality: str
    role: str
    status: PortStatus = "candidate"
    side: str | None = None
    neuromere: str | None = None
    confidence: float = 0.0
    encoding_policy: str | None = None
    decoding_policy: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or "." not in self.name:
            raise ValueError(f"port name must be a dotted semantic path: {self.name!r}")
        if self.direction not in ("input", "output", "diagnostic"):
            raise ValueError(f"invalid direction: {self.direction}")
        if not self.bodies:
            raise ValueError(f"port {self.name!r} has no bodies")
        if len({b.body_id for b in self.bodies}) != len(self.bodies):
            raise ValueError(f"port {self.name!r} contains duplicate body IDs")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.status == "validated" and self.confidence <= 0.0:
            raise ValueError("validated ports require positive confidence")
        if self.direction == "input" and not self.encoding_policy:
            raise ValueError(f"input port {self.name!r} requires encoding_policy")
        if self.direction in ("output", "diagnostic") and not self.decoding_policy:
            raise ValueError(f"{self.direction} port {self.name!r} requires decoding_policy")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IOPort":
        return cls(
            name=str(data["name"]),
            direction=str(data["direction"]),  # type: ignore[arg-type]
            bodies=tuple(BodyRef.from_value(v) for v in data["bodies"]),
            modality=str(data.get("modality", "unknown")),
            role=str(data.get("role", "unknown")),
            status=str(data.get("status", "candidate")),  # type: ignore[arg-type]
            side=data.get("side"),
            neuromere=data.get("neuromere"),
            confidence=float(data.get("confidence", 0.0)),
            encoding_policy=data.get("encoding_policy"),
            decoding_policy=data.get("decoding_policy"),
            provenance=dict(data.get("provenance", {})),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "direction": self.direction,
            "modality": self.modality,
            "role": self.role,
            "status": self.status,
            "confidence": self.confidence,
            "bodies": [b.to_dict() for b in self.bodies],
        }
        if self.side is not None:
            out["side"] = self.side
        if self.neuromere is not None:
            out["neuromere"] = self.neuromere
        if self.encoding_policy is not None:
            out["encoding_policy"] = self.encoding_policy
        if self.decoding_policy is not None:
            out["decoding_policy"] = self.decoding_policy
        if self.provenance:
            out["provenance"] = dict(self.provenance)
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out


@dataclass(frozen=True)
class IOManifest:
    dataset: str
    ports: tuple[IOPort, ...]
    manifest_version: str = "0.1"
    graph_scope: str = "curated-neuron-induced-graph"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        names = [p.name for p in self.ports]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"duplicate port names: {duplicates}")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IOManifest":
        return cls(
            dataset=str(data["dataset"]),
            ports=tuple(IOPort.from_dict(v) for v in data.get("ports", [])),
            manifest_version=str(data.get("manifest_version", "0.1")),
            graph_scope=str(data.get("graph_scope", "curated-neuron-induced-graph")),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def load(cls, path: str | Path) -> "IOManifest":
        with Path(path).open("r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "dataset": self.dataset,
            "graph_scope": self.graph_scope,
            "metadata": dict(self.metadata),
            "ports": [p.to_dict() for p in self.ports],
        }

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def by_direction(self, direction: PortDirection) -> tuple[IOPort, ...]:
        return tuple(p for p in self.ports if p.direction == direction)

    def get(self, name: str) -> IOPort:
        for port in self.ports:
            if port.name == name:
                return port
        raise KeyError(name)

    def body_ids(self, directions: Iterable[PortDirection] | None = None) -> set[int]:
        allowed = set(directions) if directions is not None else None
        return {
            body.body_id
            for port in self.ports
            if allowed is None or port.direction in allowed
            for body in port.bodies
        }
