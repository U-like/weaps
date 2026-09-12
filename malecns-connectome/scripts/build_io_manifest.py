#!/usr/bin/env python3
"""Build conservative candidate MaleCNS simulation I/O ports.

Only explicit official annotation superclasses are eligible.  This script does
not infer missing anatomy and does not promote candidate ports to validated.
The output is therefore safe to inspect and route-test without pretending the
whole virtual-fly interface is already biologically validated.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.feather as feather

from malecns.io_manifest import BodyRef, IOManifest, IOPort


def clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def slug(value: str | None, unknown: str) -> str:
    text = clean(value) or unknown
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or unknown


def first_present(row: dict[str, Any], fields: Iterable[str]) -> tuple[str | None, str | None]:
    for field in fields:
        value = clean(row.get(field))
        if value is not None:
            return value, field
    return None, None


def body_column(names: list[str]) -> str:
    for candidate in ("bodyId", "body_id", "body"):
        if candidate in names:
            return candidate
    raise KeyError(f"no body ID column in {names}")


def load_rules(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def make_name(
    *,
    prefix: str,
    nerve: str | None,
    class_name: str | None,
    subclass: str | None,
    side: str | None,
    neuromere: str | None,
    unknown: str,
) -> str:
    # Nerve comes immediately after prefix because it is the most physical
    # body-interface descriptor in the official annotations.
    parts = [prefix, slug(nerve, unknown)]
    if class_name:
        parts.append(slug(class_name, unknown))
    if subclass:
        parts.append(slug(subclass, unknown))
    if neuromere:
        parts.append(slug(neuromere, unknown))
    if side:
        parts.append(slug(side, unknown))
    return ".".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("annotations")
    ap.add_argument("--rules", default="config/io_port_rules.json")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--sensory-feather", required=True)
    ap.add_argument("--motor-feather", required=True)
    ap.add_argument("--diagnostic-feather", required=True)
    ap.add_argument("--unknowns", required=True)
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()

    rules = load_rules(args.rules)
    table = feather.read_table(args.annotations)
    names = table.column_names
    body_col = body_column(names)
    rows = table.to_pylist()

    allowed_status = set(rules.get("include_status", []))
    unknown = rules.get("policy", {}).get("unknown_token", "unknown")
    candidate_status = rules.get("policy", {}).get("port_status", "candidate")
    candidate_confidence = float(rules.get("policy", {}).get("port_confidence", 0.0))

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    unknown_rows: list[dict[str, Any]] = []
    eligible_rows = 0
    status_filtered = 0

    for row in rows:
        superclass = clean(row.get("superclass"))
        spec = rules.get("groups", {}).get(superclass)
        if spec is None:
            continue
        status = clean(row.get("status"))
        if allowed_status and status not in allowed_status:
            status_filtered += 1
            continue
        body_value = row.get(body_col)
        if body_value is None:
            unknown_rows.append({"reason": "missing_body_id", "superclass": superclass})
            continue

        eligible_rows += 1
        nerve, nerve_source = first_present(row, spec.get("nerve_fields", []))
        side, side_source = first_present(row, spec.get("side_fields", []))
        neuromere, neuromere_source = first_present(row, spec.get("neuromere_fields", []))
        class_name = clean(row.get("class")) if "class" in spec.get("group_fields", []) else None
        subclass = clean(row.get("subclass")) if "subclass" in spec.get("group_fields", []) else None

        # Unknown anatomy is retained as an explicit candidate group, never
        # silently promoted to a physical body channel.
        key = (
            superclass,
            nerve,
            class_name,
            subclass,
            side,
            neuromere,
            nerve_source,
            side_source,
            neuromere_source,
        )
        groups[key].append(row)

    ports: list[IOPort] = []
    flat_rows: dict[str, list[dict[str, Any]]] = {"input": [], "output": [], "diagnostic": []}

    for key, members in sorted(groups.items(), key=lambda kv: tuple(str(x or "") for x in kv[0])):
        (
            superclass,
            nerve,
            class_name,
            subclass,
            side,
            neuromere,
            nerve_source,
            side_source,
            neuromere_source,
        ) = key
        spec = rules["groups"][superclass]
        direction = spec["direction"]
        name = make_name(
            prefix=spec["name_prefix"],
            nerve=nerve,
            class_name=class_name,
            subclass=subclass,
            side=side,
            neuromere=neuromere,
            unknown=unknown,
        )

        # A rare collision can happen when different source fields carry the
        # same visible value.  Preserve provenance by disambiguating rather than
        # merging silently.
        existing = {p.name for p in ports}
        if name in existing:
            suffix = slug(nerve_source or side_source or neuromere_source or "source", unknown)
            base = f"{name}.{suffix}"
            name = base
            idx = 2
            while name in existing:
                name = f"{base}_{idx}"
                idx += 1

        body_ids = sorted({int(row[body_col]) for row in members})
        role = "sensory" if direction == "input" else ("motor" if direction == "output" else superclass)
        modality = class_name or subclass or superclass
        provenance = {
            "dataset": rules["dataset"],
            "source": "official_body_annotations",
            "superclass": superclass,
            "nerve": nerve,
            "nerve_source_field": nerve_source,
            "side_source_field": side_source,
            "neuromere_source_field": neuromere_source,
        }
        metadata = {
            "class": class_name,
            "subclass": subclass,
            "member_count": len(body_ids),
            "contains_unknown_nerve": nerve is None,
            "contains_unknown_side": side is None,
            "contains_unknown_neuromere": neuromere is None,
        }
        port = IOPort(
            name=name,
            direction=direction,
            bodies=tuple(BodyRef(body_id) for body_id in body_ids),
            modality=modality,
            role=role,
            status=candidate_status,
            side=side,
            neuromere=neuromere,
            confidence=candidate_confidence,
            encoding_policy=spec.get("encoding_policy"),
            decoding_policy=spec.get("decoding_policy"),
            provenance=provenance,
            metadata=metadata,
        )
        ports.append(port)

        for body_id in body_ids:
            flat_rows[direction].append({
                "body_id": body_id,
                "port_name": name,
                "direction": direction,
                "superclass": superclass,
                "class": class_name,
                "subclass": subclass,
                "side": side,
                "neuromere": neuromere,
                "nerve": nerve,
                "nerve_source_field": nerve_source,
                "status": candidate_status,
            })

    manifest = IOManifest(
        dataset=rules["dataset"],
        ports=tuple(ports),
        manifest_version="0.1-candidate",
        graph_scope="curated-neuron-induced-graph",
        metadata={
            "source": "official MaleCNS v1.0 body annotations",
            "port_policy": "candidate-only; nerve-first; no inferred missing anatomy",
            "allowed_status": sorted(allowed_status),
        },
    )
    manifest.save(args.manifest)

    def write_feather(records: list[dict[str, Any]], path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if records:
            feather.write_feather(pa.Table.from_pylist(records), target)
        else:
            feather.write_feather(pa.table({"body_id": pa.array([], type=pa.int64())}), target)

    write_feather(flat_rows["input"], args.sensory_feather)
    write_feather(flat_rows["output"], args.motor_feather)
    write_feather(flat_rows["diagnostic"], args.diagnostic_feather)

    unresolved = []
    for port in ports:
        if any((port.provenance.get("nerve") is None, port.side is None, port.neuromere is None)):
            unresolved.append({
                "port_name": port.name,
                "direction": port.direction,
                "body_count": len(port.bodies),
                "missing": [
                    field
                    for field, missing in (
                        ("nerve", port.provenance.get("nerve") is None),
                        ("side", port.side is None),
                        ("neuromere", port.neuromere is None),
                    )
                    if missing
                ],
            })
    Path(args.unknowns).write_text(json.dumps({
        "unresolved_ports": unresolved,
        "rejected_rows": unknown_rows,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "dataset": rules["dataset"],
        "eligible_annotation_rows": eligible_rows,
        "status_filtered_rows": status_filtered,
        "port_counts": {
            direction: sum(1 for p in ports if p.direction == direction)
            for direction in ("input", "output", "diagnostic")
        },
        "body_memberships": {direction: len(records) for direction, records in flat_rows.items()},
        "unique_body_ids": {
            direction: len({r["body_id"] for r in records})
            for direction, records in flat_rows.items()
        },
        "unresolved_port_count": len(unresolved),
        "validated_port_count": 0,
        "candidate_port_count": len(ports),
        "notes": rules.get("policy", {}).get("notes", []),
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
