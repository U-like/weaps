#!/usr/bin/env python3
"""Classify resolved sensory bodies that have no directed route to motor output.

This audit is intentionally structural. A body is called ``unreachable`` only
with respect to directed graph reachability in the curated runtime graph and
the selected motor masks. It says nothing about physiological responsiveness.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.ipc as ipc
from scipy.sparse import csr_matrix


def load_edges(path: str, node_count: int, edge_count: int) -> csr_matrix:
    pre = np.empty(edge_count, dtype=np.uint32)
    post = np.empty(edge_count, dtype=np.uint32)
    offset = 0
    with pa.memory_map(path, "r") as source:
        reader = ipc.open_file(source)
        for i in range(reader.num_record_batches):
            batch = reader.get_batch(i)
            n = batch.num_rows
            if n == 0:
                continue
            pre[offset:offset + n] = np.asarray(batch.column(batch.schema.get_field_index("pre")))
            post[offset:offset + n] = np.asarray(batch.column(batch.schema.get_field_index("post")))
            offset += n
    if offset != edge_count:
        raise RuntimeError(f"edge row mismatch: {offset} != {edge_count}")
    graph = csr_matrix(
        (np.ones(edge_count, dtype=np.int8), (pre, post)),
        shape=(node_count, node_count),
        dtype=np.int8,
    )
    graph.sum_duplicates()
    graph.sort_indices()
    return graph


def body_to_dense(nodes: pa.Table) -> dict[int, int]:
    bodies = np.asarray(nodes["body_id"].combine_chunks(), dtype=np.int64)
    dense = np.asarray(nodes["dense_id"].combine_chunks(), dtype=np.int64)
    return {int(body): int(idx) for body, idx in zip(bodies, dense, strict=True)}


def reverse_reachable(graph: csr_matrix, targets: np.ndarray, max_hops: int) -> tuple[np.ndarray, np.ndarray]:
    n = graph.shape[0]
    dist = np.full(n, -1, dtype=np.int16)
    frontier = np.zeros(n, dtype=bool)
    targets = np.unique(targets.astype(np.int64, copy=False))
    targets = targets[(targets >= 0) & (targets < n)]
    frontier[targets] = True
    dist[targets] = 0
    for depth in range(1, max_hops + 1):
        if not frontier.any():
            break
        reached = np.asarray(graph.dot(frontier.astype(np.int16, copy=False))).reshape(-1) != 0
        new = reached & (dist < 0)
        if not new.any():
            break
        dist[new] = depth
        frontier = new
    return dist >= 0, dist


def load_rows(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        table = feather.read_table(path)
        for row in table.to_pylist():
            record = dict(row)
            record["source_mask_file"] = Path(path).name
            rows.append(record)
    return rows


def clean(value: Any) -> str:
    if value is None:
        return "<null>"
    text = str(value).strip()
    return text if text else "<empty>"


def grouped_counts(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    c = Counter(clean(record.get(field)) for record in records)
    return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))


def compound_counts(records: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, ...]] = Counter(
        tuple(clean(record.get(field)) for field in fields) for record in records
    )
    return [
        {**{field: key[i] for i, field in enumerate(fields)}, "count": int(count)}
        for key, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--edges", required=True)
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--sensory", required=True, nargs="+")
    ap.add_argument("--motor", required=True, nargs="+")
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-hops", type=int, default=32)
    args = ap.parse_args()

    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    nodes = feather.read_table(args.nodes, columns=["dense_id", "body_id"])
    n = nodes.num_rows
    edge_count = int(metadata["edges"]["edge_count"])
    if n != int(metadata["nodes"]["node_count"]):
        raise ValueError("runtime node metadata mismatch")
    mapping = body_to_dense(nodes)

    sensory_rows = load_rows(args.sensory)
    motor_rows = load_rows(args.motor)

    motor_bodies = sorted({int(row["body_id"]) for row in motor_rows})
    missing_motor = [body for body in motor_bodies if body not in mapping]
    if missing_motor:
        raise ValueError(f"motor bodies missing from runtime: {len(missing_motor)}")
    motor_dense = np.asarray([mapping[body] for body in motor_bodies], dtype=np.int64)

    graph = load_edges(args.edges, n, edge_count)
    reachable, dist = reverse_reachable(graph, motor_dense, args.max_hops)
    out_degree = np.diff(graph.indptr).astype(np.int64, copy=False)

    # A body may appear in more than one semantic mask. Keep all memberships in
    # the detail record while counting each body only once globally.
    memberships: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sensory_rows:
        body = int(row["body_id"])
        memberships[body].append(row)

    missing_runtime: list[int] = []
    unreachable_details: list[dict[str, Any]] = []
    reachable_count = 0
    for body in sorted(memberships):
        idx = mapping.get(body)
        if idx is None:
            missing_runtime.append(body)
            continue
        if reachable[idx]:
            reachable_count += 1
            continue
        rows = memberships[body]
        unreachable_details.append({
            "body_id": body,
            "dense_id": idx,
            "out_degree": int(out_degree[idx]),
            "zero_out_degree": bool(out_degree[idx] == 0),
            "distance_to_motor": int(dist[idx]),
            "memberships": [
                {
                    "semantic_port": row.get("semantic_port"),
                    "source_mask_file": row.get("source_mask_file"),
                    "superclass": row.get("superclass"),
                    "modality": row.get("modality"),
                    "class": row.get("class"),
                    "subclass": row.get("subclass"),
                    "nerve": row.get("nerve"),
                    "side": row.get("side"),
                }
                for row in rows
            ],
        })

    # Flatten memberships of unreachable bodies for interpretable aggregate
    # counts. A body with multiple memberships can contribute more than once to
    # membership-level summaries, while the body-level total remains unique.
    flat_unreachable = [
        {"body_id": detail["body_id"], **membership}
        for detail in unreachable_details
        for membership in detail["memberships"]
    ]

    zero_out = sum(1 for detail in unreachable_details if detail["zero_out_degree"])
    out = {
        "dataset": metadata.get("dataset"),
        "audit_kind": "directed topology reachability to selected motor bodies",
        "max_hops": args.max_hops,
        "runtime": {"nodes": n, "edges": edge_count},
        "source_masks": {
            "sensory": [Path(p).name for p in args.sensory],
            "motor": [Path(p).name for p in args.motor],
        },
        "summary": {
            "unique_resolved_sensory_bodies": len(memberships),
            "present_in_runtime": len(memberships) - len(missing_runtime),
            "reachable_motor_bodies": reachable_count,
            "unreachable_motor_bodies": len(unreachable_details),
            "unreachable_fraction": len(unreachable_details) / (len(memberships) - len(missing_runtime)) if len(memberships) > len(missing_runtime) else 0.0,
            "unreachable_zero_out_degree": zero_out,
            "unreachable_nonzero_out_degree": len(unreachable_details) - zero_out,
            "missing_runtime_body_ids": missing_runtime,
        },
        "unreachable_membership_counts": {
            "source_mask_file": grouped_counts(flat_unreachable, "source_mask_file"),
            "semantic_port": grouped_counts(flat_unreachable, "semantic_port"),
            "superclass": grouped_counts(flat_unreachable, "superclass"),
            "modality": grouped_counts(flat_unreachable, "modality"),
            "class": grouped_counts(flat_unreachable, "class"),
            "subclass": grouped_counts(flat_unreachable, "subclass"),
            "nerve": grouped_counts(flat_unreachable, "nerve"),
            "side": grouped_counts(flat_unreachable, "side"),
            "source_superclass_modality": compound_counts(
                flat_unreachable,
                ["source_mask_file", "superclass", "modality"],
            ),
        },
        "unreachable_bodies": unreachable_details,
        "notes": [
            "Unreachable means no directed path to any selected motor body within the configured hop limit.",
            "A zero-out-degree sensory body is a sink in the curated neuron-induced graph; this can reflect segmentation/annotation scope rather than biological absence of output.",
            "Bodies with nonzero out-degree but no motor route belong to directed subgraphs that do not reach the selected motor interface under this topology-only test.",
            "No membrane dynamics, transmitter signs or stimulus semantics are used in this audit."
        ],
    }

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "sensory_bodies": out["summary"]["unique_resolved_sensory_bodies"],
        "reachable": reachable_count,
        "unreachable": len(unreachable_details),
        "zero_out_degree": zero_out,
        "nonzero_out_degree": len(unreachable_details) - zero_out,
        "by_source_mask": out["unreachable_membership_counts"]["source_mask_file"],
        "by_superclass": out["unreachable_membership_counts"]["superclass"],
        "by_modality": out["unreachable_membership_counts"]["modality"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
