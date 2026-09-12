"""Unified MaleCNS runtime API.

The runtime is intentionally backend-agnostic.  The semantic body interface is
stable while neural dynamics can evolve from structural propagation to signed
LIF or another validated model without changing the virtual-fly integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable

from .body_adapter import BodyAdapter, RuntimeStep
from .io_manifest import IOManifest


@runtime_checkable
class DynamicsBackend(Protocol):
    """Minimal contract for a MaleCNS dynamics implementation."""

    def reset(self) -> None:
        ...

    def step(self, external_drive: Mapping[int, float], dt: float) -> Mapping[int, float]:
        """Advance CNS state and return observable body-level activity."""
        ...


@dataclass(frozen=True)
class RuntimeInfo:
    dataset: str
    manifest_version: str
    input_ports: tuple[str, ...]
    output_ports: tuple[str, ...]
    diagnostic_ports: tuple[str, ...]


class MaleCNSRuntime:
    """One-call interface used by the virtual fly simulation.

    Example::

        motor = brain.step(sensor_state, dt=0.001).motor

    The class does not pretend that the current project already has validated
    biological dynamics.  A concrete DynamicsBackend must be supplied.
    """

    def __init__(self, manifest: IOManifest, backend: DynamicsBackend) -> None:
        if not isinstance(backend, DynamicsBackend):
            raise TypeError("backend does not implement DynamicsBackend")
        self.manifest = manifest
        self.backend = backend
        self.adapter = BodyAdapter(manifest)

    @classmethod
    def from_manifest(cls, manifest_path: str, backend: DynamicsBackend) -> "MaleCNSRuntime":
        return cls(IOManifest.load(manifest_path), backend)

    @property
    def info(self) -> RuntimeInfo:
        return RuntimeInfo(
            dataset=self.manifest.dataset,
            manifest_version=self.manifest.manifest_version,
            input_ports=self.adapter.input_names,
            output_ports=self.adapter.output_names,
            diagnostic_ports=tuple(p.name for p in self.manifest.by_direction("diagnostic")),
        )

    def reset(self) -> None:
        self.backend.reset()

    def step(
        self,
        sensory_state: Mapping[str, float],
        dt: float,
        *,
        strict_inputs: bool = True,
    ) -> RuntimeStep:
        if dt <= 0.0:
            raise ValueError(f"dt must be positive, got {dt}")
        drive = self.adapter.encode_inputs(sensory_state, strict=strict_inputs)
        body_state = self.backend.step(drive, float(dt))
        return RuntimeStep(
            motor=self.adapter.decode_outputs(body_state),
            diagnostic=self.adapter.decode_diagnostics(body_state),
            body_state=body_state,
        )
