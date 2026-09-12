#!/usr/bin/env python3
"""Build conservative head, visual and central-brain motor I/O ports.

This builder intentionally preserves official MaleCNS labels instead of
inventing anatomy that is not present in v1.0 annotations.

Visual ports use only ``rootSide`` and photoreceptor ``type`` because the
``assignedOlHex1/assignedOlHex2`` columns are present but empty for ol_sensory
in MaleCNS v1.0. Central-brain sensory ports use explicit ``entryNerve`` plus
class/subclass/rootSide. Central-brain motor ports use explicit ``exitNerve``
plus subclass/somaSide.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather

from malecns.io_manifest import BodyRef, IOManifest, IOPort

DATASET = "male-cns:v1.0-minconf-0.5"


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def slug(value: str | None, default: str = "unknown") -> str:
    text = (clean(value) or default).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or default


def side_name(value: str | None) -> str:
    return {"L": "left", "R": "right", "M": "midline"}.get(clean(value) or "", "unknown")


def body_column(names: list[str]) -> str:
    for candidate in ("bodyId", "body_id", "body"):
        if candidate in names:
            return candidate
    raise KeyError(f"no body-id column found in {names}")


def subset(table: pa.Table, superclass: str) -> pa.Table:
    return table.filter(pc.equal(table["superclass"], pa.scalar(superclass)))


def write_feather(rows: list[dict[str, Any]], path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        feather.write_feather(pa.Table.from_pylist(rows), target, compression="lz4")
    else:
        feather.write_feather(
            pa.table({
                "body_id": pa.array([], type=pa.int64()),
                "semantic_port": pa.array([], type=pa.string()),
            }),
            target,
            compression="lz4",
        )


def make_port(
    *,
    name: str,
    direction: str,
    body_ids: list[int],
    modality: str,
    role: str,
    side: str | None,
    provenance: dict[str, Any],
    metadata: dict[str, Any],
) -> IOPort:
    kwargs: dict[str, Any] = {}
    if direction == "input":
        kwargs["encoding_policy"] = "uniform_split"
    else:
        kwargs["decoding_policy"] = "mean"
    return IOPort(
        name=name,
        direction=direction,  # type: ignore[arg-type]
        bodies=tuple(BodyRef(int(body)) for body in sorted(set(body_ids))),
        modality=modality,
        role=role,
        status="candidate",
        side=side,
        confidence=0.0,
        provenance=provenance,
        metadata=metadata,
        **kwargs,
    )


def build_visual(table: pa.Table, body_col: str) -> tuple[list[IOPort], list[dict[str, Any]], list[dict[str, Any]]]:
    rows = subset(table, "ol_sensory").to_pylist()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    unresolved: list[dict[str, Any]] = []

    for row in rows:
        body = row.get(body_col)
        receptor_type = clean(row.get("type"))
        root_side = clean(row.get("rootSide"))
        class_name = clean(row.get("class"))
        if body is None or receptor_type is None or root_side not in {"L", "R"}:
            unresolved.append({
                "body_id": int(body) if body is not None else None,
                "superclass": "ol_sensory",
                "reason": "missing_body_type_or_eye_side",
                "type": receptor_type,
                "class": class_name,
                "rootSide": root_side,
                "status": clean(row.get("status")),
            })
            continue
        groups[(root_side, receptor_type)].append(row)

    ports: list[IOPort] = []
    flat: list[dict[str, Any]] = []
    for (root_side, receptor_type), members in sorted(groups.items()):
        side = side_name(root_side)
        name = f"sensory.vision.{side}.{slug(receptor_type)}"
        body_ids = sorted({int(row[body_col]) for row in members})
        status_counts: dict[str, int] = defaultdict(int)
        for row in members:
            status_counts[clean(row.get("status")) or "<null>"] += 1
        port = make_port(
            name=name,
            direction="input",
            body_ids=body_ids,
            modality="visual",
            role="sensory",
            side=root_side,
            provenance={
                "dataset": DATASET,
                "source": "official_body_annotations",
                "superclass": "ol_sensory",
                "group_fields": ["rootSide", "type"],
                "retinotopy": "unavailable_in_v1_annotations",
            },
            metadata={
                "photoreceptor_type": receptor_type,
                "member_count": len(body_ids),
                "status_counts": dict(sorted(status_counts.items())),
                "assignedOlHex1": "all null for ol_sensory in audited v1.0",
                "assignedOlHex2": "all null for ol_sensory in audited v1.0",
            },
        )
        ports.append(port)
        for body_id in body_ids:
            flat.append({
                "body_id": body_id,
                "semantic_port": name,
                "direction": "input",
                "superclass": "ol_sensory",
                "modality": "visual",
                "subclass": receptor_type,
                "nerve": None,
                "side": root_side,
                "source": "official_body_annotations",
                "spatial_coordinate_status": "unavailable",
            })
    return ports, flat, unresolved


def build_head_sensory(table: pa.Table, body_col: str) -> tuple[list[IOPort], list[dict[str, Any]], list[dict[str, Any]]]:
    rows = subset(table, "cb_sensory").to_pylist()
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    unresolved: list[dict[str, Any]] = []

    for row in rows:
        body = row.get(body_col)
        nerve = clean(row.get("entryNerve"))
        class_name = clean(row.get("class")) or "unknown_sensory"
        subclass = clean(row.get("subclass")) or "unspecified"
        root_side = clean(row.get("rootSide"))
        if body is None or nerve is None or root_side not in {"L", "R", "M"}:
            unresolved.append({
                "body_id": int(body) if body is not None else None,
                "superclass": "cb_sensory",
                "reason": "missing_body_entry_nerve_or_side",
                "entryNerve": nerve,
                "class": class_name,
                "subclass": subclass,
                "rootSide": root_side,
            })
            continue
        groups[(nerve, class_name, subclass, root_side)].append(row)

    ports: list[IOPort] = []
    flat: list[dict[str, Any]] = []
    for (nerve, class_name, subclass, root_side), members in sorted(groups.items()):
        side = side_name(root_side)
        # Preserve official nerve abbreviations in the semantic path. Anatomical
        # aliases can be layered later with explicit provenance.
        name = f"sensory.head.{slug(nerve)}.{side}.{slug(class_name)}"
        if subclass != "unspecified":
            name += f".{slug(subclass)}"
        body_ids = sorted({int(row[body_col]) for row in members})
        port = make_port(
            name=name,
            direction="input",
            body_ids=body_ids,
            modality=class_name,
            role="sensory",
            side=root_side,
            provenance={
                "dataset": DATASET,
                "source": "official_body_annotations",
                "superclass": "cb_sensory",
                "entryNerve": nerve,
                "group_fields": ["entryNerve", "class", "subclass", "rootSide"],
            },
            metadata={
                "official_subclass": None if subclass == "unspecified" else subclass,
                "member_count": len(body_ids),
            },
        )
        ports.append(port)
        for body_id in body_ids:
            flat.append({
                "body_id": body_id,
                "semantic_port": name,
                "direction": "input",
                "superclass": "cb_sensory",
                "modality": class_name,
                "subclass": None if subclass == "unspecified" else subclass,
                "nerve": nerve,
                "side": root_side,
                "source": "official_body_annotations",
            })
    return ports, flat, unresolved


def build_head_motor(table: pa.Table, body_col: str) -> tuple[list[IOPort], list[dict[str, Any]], list[dict[str, Any]]]:
    rows = subset(table, "cb_motor").to_pylist()
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    unresolved: list[dict[str, Any]] = []

    for row in rows:
        body = row.get(body_col)
        nerve = clean(row.get("exitNerve"))
        subclass = clean(row.get("subclass")) or "unknown"
        soma_side = clean(row.get("somaSide"))
        if body is None or nerve is None or soma_side not in {"L", "R", "M"}:
            unresolved.append({
                "body_id": int(body) if body is not None else None,
                "superclass": "cb_motor",
                "reason": "missing_body_exit_nerve_or_side",
                "exitNerve": nerve,
                "subclass": subclass,
                "somaSide": soma_side,
            })
            continue
        groups[(nerve, subclass, soma_side)].append(row)

    ports: list[IOPort] = []
    flat: list[dict[str, Any]] = []
    for (nerve, subclass, soma_side), members in sorted(groups.items()):
        side = side_name(soma_side)
        name = f"motor.head.{slug(nerve)}.{side}.{slug(subclass)}"
        body_ids = sorted({int(row[body_col]) for row in members})
        port = make_port(
            name=name,
            direction="output",
            body_ids=body_ids,
            modality="motor",
            role="motor",
            side=soma_side,
            provenance={
                "dataset": DATASET,
                "source": "official_body_annotations",
                "superclass": "cb_motor",
                "exitNerve": nerve,
                "group_fields": ["exitNerve", "subclass", "somaSide"],
            },
            metadata={
                "official_motor_subclass": subclass,
                "member_count": len(body_ids),
                "semantic_expansion": "pending_anatomical_alias_validation",
            },
        )
        ports.append(port)
        for body_id in body_ids:
            flat.append({
                "body_id": body_id,
                "semantic_port": name,
                "direction": "output",
                "superclass": "cb_motor",
                "modality": "motor",
                "subclass": subclass,
                "nerve": nerve,
                "side": soma_side,
                "source": "official_body_annotations",
            })
    return ports, flat, unresolved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("annotations")
    ap.add_argument("--base-manifest")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--visual", required=True)
    ap.add_argument("--head-sensory", required=True)
    ap.add_argument("--head-motor", required=True)
    ap.add_argument("--unresolved", required=True)
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()

    table = feather.read_table(args.annotations)
    body_col = body_column(table.column_names)

    visual_ports, visual_rows, visual_unresolved = build_visual(table, body_col)
    head_ports, head_rows, head_unresolved = build_head_sensory(table, body_col)
    motor_ports, motor_rows, motor_unresolved = build_head_motor(table, body_col)

    base_ports: tuple[IOPort, ...] = ()
    base_version = None
    if args.base_manifest:
        base = IOManifest.load(args.base_manifest)
        if base.dataset != DATASET:
            raise ValueError(f"base manifest dataset mismatch: {base.dataset}")
        base_ports = base.ports
        base_version = base.manifest_version

    all_ports = (*base_ports, *visual_ports, *head_ports, *motor_ports)
    manifest = IOManifest(
        dataset=DATASET,
        ports=tuple(all_ports),
        manifest_version="0.3-whole-body-candidate",
        graph_scope="curated-neuron-induced-graph",
        metadata={
            "base_manifest_version": base_version,
            "head_visual_mapping": "official annotations only",
            "visual_retinotopy": "not available from assignedOlHex1/2 in v1.0 annotations",
            "status": "candidate anatomy grouping; route validation required",
        },
    )
    manifest.save(args.manifest)

    write_feather(visual_rows, args.visual)
    write_feather(head_rows, args.head_sensory)
    write_feather(motor_rows, args.head_motor)

    unresolved = {
        "visual": visual_unresolved,
        "head_sensory": head_unresolved,
        "head_motor": motor_unresolved,
    }
    Path(args.unresolved).write_text(json.dumps(unresolved, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "dataset": DATASET,
        "base_port_count": len(base_ports),
        "visual": {
            "source_rows": subset(table, "ol_sensory").num_rows,
            "resolved_body_memberships": len(visual_rows),
            "unique_bodies": len({row["body_id"] for row in visual_rows}),
            "port_count": len(visual_ports),
            "unresolved_rows": len(visual_unresolved),
        },
        "head_sensory": {
            "source_rows": subset(table, "cb_sensory").num_rows,
            "resolved_body_memberships": len(head_rows),
            "unique_bodies": len({row["body_id"] for row in head_rows}),
            "port_count": len(head_ports),
            "unresolved_rows": len(head_unresolved),
        },
        "head_motor": {
            "source_rows": subset(table, "cb_motor").num_rows,
            "resolved_body_memberships": len(motor_rows),
            "unique_bodies": len({row["body_id"] for row in motor_rows}),
            "port_count": len(motor_ports),
            "unresolved_rows": len(motor_unresolved),
        },
        "combined_manifest_port_count": len(all_ports),
        "notes": [
            "Visual ports preserve eye side and official photoreceptor type but have no retinal coordinates in MaleCNS v1.0 annotations.",
            "Central-brain nerve abbreviations are preserved verbatim; no anatomical alias is invented.",
            "Rows lacking an explicit side or entry/exit nerve are unresolved rather than coerced into a body channel.",
            "Null status is not a rejection criterion when an official sensory superclass is present."
        ],
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
