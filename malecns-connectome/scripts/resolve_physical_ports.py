#!/usr/bin/env python3
"""Resolve candidate MaleCNS I/O masks into conservative physical body channels.

Only mappings explicitly listed in ``physical_channel_map.json`` are used.
Mapped ports remain ``candidate`` until connectivity route validation succeeds.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.feather as feather

from malecns.io_manifest import BodyRef, IOManifest, IOPort


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def side_suffix(side: str, side_map: dict[str, str]) -> str | None:
    return side_map.get(side)


def sensory_port(channel: str, side: str, modality: str) -> str:
    if channel.startswith("leg."):
        limb = channel.split(".", 1)[1]
        return f"sensory.leg.{limb}_{side}.{modality}"
    return f"sensory.{channel}.{side}.{modality}"


def motor_port(channel: str, side: str) -> str:
    if channel.startswith("leg."):
        limb = channel.split(".", 1)[1]
        return f"motor.leg.{limb}_{side}"
    return f"motor.{channel}.{side}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensory", required=True)
    ap.add_argument("--motor", required=True)
    ap.add_argument("--diagnostic", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--resolved-sensory", required=True)
    ap.add_argument("--resolved-motor", required=True)
    ap.add_argument("--unresolved", required=True)
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()

    mapping = load_json(args.map)
    side_map = mapping["side_map"]
    modality_map = mapping["sensory_class_to_modality"]
    nerve_map = mapping["sensory_nerve_map"]
    motor_map = mapping["motor_subclass_map"]

    sensory_rows = feather.read_table(args.sensory).to_pylist()
    motor_rows = feather.read_table(args.motor).to_pylist()
    diagnostic_rows = feather.read_table(args.diagnostic).to_pylist()

    sensory_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    motor_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unresolved: list[dict[str, Any]] = []

    for row in sensory_rows:
        nerve = row.get("nerve")
        side = side_suffix(str(row.get("side")), side_map) if row.get("side") else None
        nerve_spec = nerve_map.get(str(nerve)) if nerve is not None else None
        modality = modality_map.get(str(row.get("class")), "unknown")
        if nerve_spec is None or side is None:
            unresolved.append({
                "body_id": int(row["body_id"]),
                "direction": "input",
                "reason": "unmapped_nerve" if nerve_spec is None else "unknown_side",
                "nerve": nerve,
                "side": row.get("side"),
                "class": row.get("class"),
                "subclass": row.get("subclass"),
            })
            continue
        name = sensory_port(nerve_spec["channel"], side, modality)
        enriched = dict(row)
        enriched["semantic_port"] = name
        enriched["physical_channel"] = nerve_spec["channel"]
        enriched["modality"] = modality
        enriched["resolved_neuromere"] = nerve_spec.get("neuromere")
        sensory_groups[name].append(enriched)

    for row in motor_rows:
        subclass = str(row.get("subclass")) if row.get("subclass") is not None else None
        side = side_suffix(str(row.get("side")), side_map) if row.get("side") else None
        motor_spec = motor_map.get(subclass) if subclass else None
        if motor_spec is None or motor_spec.get("channel") is None or side is None:
            unresolved.append({
                "body_id": int(row["body_id"]),
                "direction": "output",
                "reason": "unknown_motor_target" if motor_spec is None or motor_spec.get("channel") is None else "unknown_side",
                "nerve": row.get("nerve"),
                "side": row.get("side"),
                "subclass": subclass,
            })
            continue
        name = motor_port(motor_spec["channel"], side)
        enriched = dict(row)
        enriched["semantic_port"] = name
        enriched["physical_channel"] = motor_spec["channel"]
        enriched["resolved_neuromere"] = motor_spec.get("neuromere")
        motor_groups[name].append(enriched)

    ports: list[IOPort] = []
    for name, members in sorted(sensory_groups.items()):
        first = members[0]
        ports.append(IOPort(
            name=name,
            direction="input",
            bodies=tuple(BodyRef(int(row["body_id"])) for row in sorted(members, key=lambda r: int(r["body_id"]))),
            modality=str(first["modality"]),
            role="sensory",
            status="candidate",
            side=str(first["side"]),
            neuromere=first.get("resolved_neuromere"),
            confidence=0.0,
            encoding_policy="uniform_split",
            provenance={
                "source": "official_body_annotations + published_peripheral_nerve_nomenclature",
                "nerve": first.get("nerve"),
                "mapping_version": mapping["version"],
            },
            metadata={"physical_channel": first["physical_channel"], "member_count": len(members)},
        ))

    for name, members in sorted(motor_groups.items()):
        first = members[0]
        ports.append(IOPort(
            name=name,
            direction="output",
            bodies=tuple(BodyRef(int(row["body_id"])) for row in sorted(members, key=lambda r: int(r["body_id"]))),
            modality="motor",
            role="motor",
            status="candidate",
            side=str(first["side"]),
            neuromere=first.get("resolved_neuromere"),
            confidence=0.0,
            decoding_policy="mean",
            provenance={
                "source": "official_body_annotations + published_motor_subclass_nomenclature",
                "subclass": first.get("subclass"),
                "mapping_version": mapping["version"],
            },
            metadata={"physical_channel": first["physical_channel"], "member_count": len(members)},
        ))

    # Diagnostics are useful to observe brain↔VNC flow but are not body
    # actuators. Group them conservatively by superclass-like source label,
    # side, and neuromere from the already-generated candidate table.
    diag_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in diagnostic_rows:
        superclass = str(row.get("superclass") or "diagnostic")
        side = side_suffix(str(row.get("side")), side_map) if row.get("side") else "unknown"
        neuromere = str(row.get("neuromere") or "unknown")
        diag_groups[(superclass, side or "unknown", neuromere)].append(row)
    for (superclass, side, neuromere), members in sorted(diag_groups.items()):
        short = "ascending" if superclass == "ascending_neuron" else "descending" if superclass == "descending_neuron" else superclass
        name = f"diagnostic.{short}.{neuromere.lower()}.{side}"
        ports.append(IOPort(
            name=name,
            direction="diagnostic",
            bodies=tuple(BodyRef(int(row["body_id"])) for row in sorted(members, key=lambda r: int(r["body_id"]))),
            modality=short,
            role=superclass,
            status="candidate",
            side=side if side != "unknown" else None,
            neuromere=neuromere if neuromere != "unknown" else None,
            confidence=0.0,
            decoding_policy="mean",
            provenance={"source": "official_body_annotations", "superclass": superclass},
            metadata={"member_count": len(members)},
        ))

    manifest = IOManifest(
        dataset="male-cns:v1.0-minconf-0.5",
        ports=tuple(ports),
        manifest_version="0.2-physical-candidate",
        graph_scope="curated-neuron-induced-graph",
        metadata={
            "physical_mapping_version": mapping["version"],
            "status": "candidate: anatomy mapped, graph-route validation pending",
        },
    )
    manifest.save(args.manifest)

    def flatten(groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        return [row for name in sorted(groups) for row in groups[name]]

    def write_rows(rows: list[dict[str, Any]], path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        feather.write_feather(pa.Table.from_pylist(rows), target)

    resolved_sensory = flatten(sensory_groups)
    resolved_motor = flatten(motor_groups)
    write_rows(resolved_sensory, args.resolved_sensory)
    write_rows(resolved_motor, args.resolved_motor)
    Path(args.unresolved).write_text(json.dumps({"rows": unresolved}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "manifest_version": manifest.manifest_version,
        "semantic_input_ports": len(sensory_groups),
        "semantic_output_ports": len(motor_groups),
        "diagnostic_ports": len(diag_groups),
        "resolved_sensory_bodies": len(resolved_sensory),
        "resolved_motor_bodies": len(resolved_motor),
        "unresolved_rows": len(unresolved),
        "input_ports": {name: len(rows) for name, rows in sorted(sensory_groups.items())},
        "output_ports": {name: len(rows) for name, rows in sorted(motor_groups.items())},
        "status": "anatomy-mapped candidate; route validation pending",
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
