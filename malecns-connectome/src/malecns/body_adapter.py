"""Semantic body I/O adapter for the MaleCNS runtime.

This module contains no biological guesses.  It only applies the encoding and
 decoding policies declared in an :class:`IOManifest`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .io_manifest import IOManifest, IOPort


@dataclass(frozen=True)
class RuntimeStep:
    motor: dict[str, float]
    diagnostic: dict[str, float]
    body_state: Mapping[int, float]


def _normalized_weights(port: IOPort) -> list[float]:
    weights = [float(b.weight) for b in port.bodies]
    total = sum(weights)
    if total <= 0.0:
        return [1.0 / len(weights)] * len(weights)
    return [w / total for w in weights]


class BodyAdapter:
    """Translate semantic virtual-body channels to/from MaleCNS body IDs."""

    def __init__(self, manifest: IOManifest) -> None:
        self.manifest = manifest
        self._inputs = {p.name: p for p in manifest.by_direction("input")}
        self._outputs = {p.name: p for p in manifest.by_direction("output")}
        self._diagnostics = {p.name: p for p in manifest.by_direction("diagnostic")}

    @property
    def input_names(self) -> tuple[str, ...]:
        return tuple(self._inputs)

    @property
    def output_names(self) -> tuple[str, ...]:
        return tuple(self._outputs)

    def encode_inputs(self, sensory_state: Mapping[str, float], *, strict: bool = True) -> dict[int, float]:
        """Encode semantic sensor values into external body-level drive.

        Supported policies:
        - ``broadcast``: same value to each body, scaled by BodyRef.weight.
        - ``uniform_split``: divide the value equally across the port bodies.
        - ``weighted_split``: divide according to normalized BodyRef.weight.

        Contributions from overlapping ports are summed deliberately; masks are
        allowed to overlap.
        """

        if strict:
            unknown = sorted(set(sensory_state) - set(self._inputs))
            if unknown:
                raise KeyError(f"unknown sensory ports: {unknown}")

        drive: dict[int, float] = {}
        for name, raw_value in sensory_state.items():
            port = self._inputs.get(name)
            if port is None:
                continue
            value = float(raw_value)
            policy = port.encoding_policy
            if policy == "broadcast":
                values = [value * b.weight for b in port.bodies]
            elif policy == "uniform_split":
                values = [value / len(port.bodies)] * len(port.bodies)
            elif policy == "weighted_split":
                values = [value * w for w in _normalized_weights(port)]
            else:
                raise ValueError(f"unsupported encoding policy {policy!r} for {name}")

            for body, contribution in zip(port.bodies, values, strict=True):
                drive[body.body_id] = drive.get(body.body_id, 0.0) + float(contribution)
        return drive

    @staticmethod
    def _decode_port(port: IOPort, body_state: Mapping[int, float]) -> float:
        values = [float(body_state.get(b.body_id, 0.0)) for b in port.bodies]
        policy = port.decoding_policy
        if policy == "mean":
            return sum(values) / len(values)
        if policy == "sum":
            return sum(values)
        if policy == "max":
            return max(values)
        if policy == "weighted_mean":
            weights = _normalized_weights(port)
            return sum(v * w for v, w in zip(values, weights, strict=True))
        raise ValueError(f"unsupported decoding policy {policy!r} for {port.name}")

    def decode_outputs(self, body_state: Mapping[int, float]) -> dict[str, float]:
        return {name: self._decode_port(port, body_state) for name, port in self._outputs.items()}

    def decode_diagnostics(self, body_state: Mapping[int, float]) -> dict[str, float]:
        return {name: self._decode_port(port, body_state) for name, port in self._diagnostics.items()}
