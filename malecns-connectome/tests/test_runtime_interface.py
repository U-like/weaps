from __future__ import annotations

from typing import Mapping

import pytest

from malecns.body_adapter import BodyAdapter
from malecns.io_manifest import BodyRef, IOManifest, IOPort
from malecns.runtime import MaleCNSRuntime


def sample_manifest() -> IOManifest:
    return IOManifest(
        dataset="male-cns:v1.0-test",
        ports=(
            IOPort(
                name="leg.front_left.touch",
                direction="input",
                modality="mechanosensory_tactile",
                role="sensory",
                status="validated",
                confidence=1.0,
                side="L",
                neuromere="T1",
                bodies=(BodyRef(101), BodyRef(102)),
                encoding_policy="uniform_split",
            ),
            IOPort(
                name="motor.leg.front_left",
                direction="output",
                modality="motor",
                role="motor",
                status="validated",
                confidence=1.0,
                side="L",
                neuromere="T1",
                bodies=(BodyRef(201), BodyRef(202)),
                decoding_policy="mean",
            ),
            IOPort(
                name="diagnostic.descending.front_left",
                direction="diagnostic",
                modality="descending",
                role="descending",
                status="validated",
                confidence=1.0,
                side="L",
                bodies=(BodyRef(301),),
                decoding_policy="sum",
            ),
        ),
    )


def test_manifest_roundtrip(tmp_path):
    manifest = sample_manifest()
    path = tmp_path / "io_manifest.json"
    manifest.save(path)
    loaded = IOManifest.load(path)
    assert loaded == manifest
    assert loaded.get("leg.front_left.touch").neuromere == "T1"


def test_input_encoding_and_output_decoding():
    adapter = BodyAdapter(sample_manifest())
    drive = adapter.encode_inputs({"leg.front_left.touch": 2.0})
    assert drive == {101: 1.0, 102: 1.0}

    body_state = {201: 0.25, 202: 0.75, 301: 3.0}
    assert adapter.decode_outputs(body_state) == {"motor.leg.front_left": 0.5}
    assert adapter.decode_diagnostics(body_state) == {"diagnostic.descending.front_left": 3.0}


class DummyBackend:
    def __init__(self) -> None:
        self.last_drive: dict[int, float] = {}

    def reset(self) -> None:
        self.last_drive.clear()

    def step(self, external_drive: Mapping[int, float], dt: float) -> Mapping[int, float]:
        self.last_drive = dict(external_drive)
        # Deliberately deterministic stand-in.  This tests the public runtime
        # contract only; it is not presented as a biological neural model.
        total = sum(external_drive.values())
        return {201: total * 0.25, 202: total * 0.75, 301: total}


def test_runtime_sensor_to_motor_contract():
    backend = DummyBackend()
    runtime = MaleCNSRuntime(sample_manifest(), backend)
    result = runtime.step({"leg.front_left.touch": 2.0}, dt=0.001)

    assert backend.last_drive == {101: 1.0, 102: 1.0}
    assert result.motor["motor.leg.front_left"] == pytest.approx(1.0)
    assert result.diagnostic["diagnostic.descending.front_left"] == pytest.approx(2.0)


def test_runtime_rejects_unknown_sensor_port():
    runtime = MaleCNSRuntime(sample_manifest(), DummyBackend())
    with pytest.raises(KeyError):
        runtime.step({"made.up.sensor": 1.0}, dt=0.001)
