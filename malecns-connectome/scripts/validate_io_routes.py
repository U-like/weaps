#!/usr/bin/env python3
"""Topology-only route validation for the curated MaleCNS runtime graph.

This script answers a deliberately narrow question: does a resolved sensory
body have a directed path through the curated connectome to a resolved motor
body, and can that path pass through a descending neuron that itself can reach
motor output?

Multiple sensory and motor mask files can be supplied so body/VNC, head and
visual interfaces are validated as one virtual-fly boundary without physically
splitting the connectome.

It does NOT simulate membrane dynamics and it does NOT claim that graph
reachability implies biological activation or behaviour.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.ipc as ipc
from scipy.sparse import csr_matrix


def read_runtime_edges(path: str, edge_count: int, node_count: int) -> csr_matrix:
    """Load compact runtime edges into a CSR adjacency matrix (pre -> post)."""
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
        raise RuntimeError(f"edge count mismatch while loading CSR: {offset} != {edge_count}")
    if edge_count and (int(pre.max()) >= node_count or int(post.max()) >= node_count):
        raise ValueError("edge dense ID outside runtime node range")

    data = np.ones(edge_count, dtype=np.int32)
    graph = csr_matrix((data, (pre, post)), shape=(node_count, node_count), dtype=np.int32)
    graph.sum_duplicates()
    graph.sort_indices()
    return graph


def reverse_bfs(graph: csr_matrix, targets: np.ndarray, max_hops: int) -> tuple[np.ndarray, dict[str, Any]]:
    """Shortest directed distance from every node to any target."""
    n = graph.shape[0]
    dist = np.full(n, -1, dtype=np.int16)
    frontier = np.zeros(n, dtype=bool)
    targets = np.unique(targets.astype(np.int64, copy=False))
    targets = targets[(targets >= 0) & (targets < n)]
    frontier[targets] = True
    dist[targets] = 0

    layer_sizes = [int(frontier.sum())]
    for depth in range(1, max_hops + 1):
        if not frontier.any():
            break
        predecessor_counts = graph.dot(frontier.astype(np.int32, copy=False))
        reached = np.asarray(predecessor_counts).reshape(-1) > 0
        new = reached & (dist < 0)
        count = int(new.sum())
        layer_sizes.append(count)
        if count == 0:
            break
        dist[new] = depth
        frontier = new

    return dist, {
        "target_count": int(len(targets)),
        "reachable_node_count": int(np.count_nonzero(dist >= 0)),
        "max_distance_observed": int(dist.max()) if np.any(dist >= 0) else None,
        "layer_sizes": layer_sizes,
    }


def rows_by_port(paths: list[str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        table = feather.read_table(path)
        if "semantic_port" not in table.column_names:
            raise KeyError(f"{path} lacks semantic_port")
        for row in table.to_pylist():
            record = dict(row)
            record["_mask_file"] = Path(path).name
            grouped[str(record["semantic_port"])].append(record)
    return dict(grouped)


def body_to_dense_map(nodes: pa.Table) -> dict[int, int]:
    body = np.asarray(nodes["body_id"].combine_chunks(), dtype=np.int64)
    dense = np.asarray(nodes["dense_id"].combine_chunks(), dtype=np.int64)
    if len(body) != len(np.unique(body)):
        raise ValueError("runtime body IDs are not unique")
    if len(dense) != len(np.unique(dense)):
        raise ValueError("runtime dense IDs are not unique")
    return {int(b): int(d) for b, d in zip(body, dense, strict=True)}


def map_rows(rows: list[dict[str, Any]], body_to_dense: dict[int, int]) -> tuple[np.ndarray, list[int]]:
    dense: list[int] = []
    missing: list[int] = []
    seen: set[int] = set()
    for row in rows:
        body = int(row["body_id"])
        if body in seen:
            continue
        seen.add(body)
        idx = body_to_dense.get(body)
        if idx is None:
            missing.append(body)
        else:
            dense.append(idx)
    return np.asarray(dense, dtype=np.int64), sorted(missing)


def unique_body_count(rows: list[dict[str, Any]]) -> int:
    return len({int(row["body_id"]) for row in rows})


def distance_stats(values: np.ndarray) -> dict[str, Any]:
    values = np.asarray(values)
    values = values[values >= 0]
    if values.size == 0:
        return {"count": 0, "min": None, "median": None, "p95": None, "max": None}
    return {
        "count": int(values.size),
        "min": int(values.min()),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "max": int(values.max()),
    }


def summarize_input_port(
    name: str,
    rows: list[dict[str, Any]],
    body_to_dense: dict[int, int],
    dist_to_motor: np.ndarray,
    dist_to_productive_desc: np.ndarray,
) -> dict[str, Any]:
    # map_rows de-duplicates bodies. Keep the corresponding body list explicit
    # for shortest-path examples so the report never relies on row ordering.
    unique_rows_by_body = {int(row["body_id"]): row for row in rows}
    unique_rows = [unique_rows_by_body[k] for k in sorted(unique_rows_by_body)]
    dense, missing = map_rows(unique_rows, body_to_dense)
    present_rows = [row for row in unique_rows if int(row["body_id"]) not in set(missing)]

    motor_dist = dist_to_motor[dense] if dense.size else np.empty(0, dtype=np.int16)
    desc_dist = dist_to_productive_desc[dense] if dense.size else np.empty(0, dtype=np.int16)
    motor_ok = motor_dist >= 0
    desc_ok = desc_dist >= 0

    best_body = None
    best_hops = None
    if dense.size and np.any(motor_ok):
        valid_indices = np.flatnonzero(motor_ok)
        best_local = int(valid_indices[np.argmin(motor_dist[motor_ok])])
        best_body = int(present_rows[best_local]["body_id"])
        best_hops = int(motor_dist[best_local])

    runtime_count = int(dense.size)
    motor_count = int(motor_ok.sum())
    desc_count = int(desc_ok.sum())
    return {
        "port": name,
        "source_mask_files": sorted({str(row.get("_mask_file")) for row in rows}),
        "body_count": len(unique_rows),
        "runtime_body_count": runtime_count,
        "missing_runtime_body_ids": missing,
        "reachable_any_motor_count": motor_count,
        "reachable_any_motor_fraction": motor_count / runtime_count if runtime_count else 0.0,
        "motor_hops": distance_stats(motor_dist),
        "reachable_productive_descending_count": desc_count,
        "reachable_productive_descending_fraction": desc_count / runtime_count if runtime_count else 0.0,
        "hops_to_productive_descending": distance_stats(desc_dist),
        "topology_route_confirmed": bool(motor_count > 0 and desc_count > 0),
        "best_direct_example_body_id": best_body,
        "best_direct_example_hops": best_hops,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--edges", required=True)
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--sensory", required=True, nargs="+")
    ap.add_argument("--motor", required=True, nargs="+")
    ap.add_argument("--diagnostic", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-hops", type=int, default=32)
    args = ap.parse_args()

    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    nodes = feather.read_table(args.nodes, columns=["dense_id", "body_id"])
    node_count = nodes.num_rows
    expected_nodes = int(metadata["nodes"]["node_count"])
    edge_count = int(metadata["edges"]["edge_count"])
    if node_count != expected_nodes:
        raise ValueError(f"node metadata mismatch: {node_count} != {expected_nodes}")

    body_to_dense = body_to_dense_map(nodes)
    sensory_ports = rows_by_port(args.sensory)
    motor_ports = rows_by_port(args.motor)

    motor_rows = [row for rows in motor_ports.values() for row in rows]
    motor_dense, missing_motor = map_rows(motor_rows, body_to_dense)
    if missing_motor:
        raise ValueError(f"resolved motor bodies missing from runtime: {len(missing_motor)}")

    diagnostic = feather.read_table(args.diagnostic).to_pylist()
    descending_rows = [row for row in diagnostic if row.get("superclass") == "descending_neuron"]
    descending_dense, missing_desc = map_rows(descending_rows, body_to_dense)
    if missing_desc:
        raise ValueError(f"descending bodies missing from runtime: {len(missing_desc)}")

    graph = read_runtime_edges(args.edges, edge_count, node_count)
    dist_to_motor, motor_bfs = reverse_bfs(graph, motor_dense, args.max_hops)

    productive_desc_mask = dist_to_motor[descending_dense] >= 0
    productive_desc = descending_dense[productive_desc_mask]
    dist_to_productive_desc, desc_bfs = reverse_bfs(graph, productive_desc, args.max_hops)

    input_reports = {
        name: summarize_input_port(
            name,
            rows,
            body_to_dense,
            dist_to_motor,
            dist_to_productive_desc,
        )
        for name, rows in sorted(sensory_ports.items())
    }

    all_sensory_rows = [row for rows in sensory_ports.values() for row in rows]
    all_sensory_dense, missing_sensory = map_rows(all_sensory_rows, body_to_dense)
    sensory_motor = dist_to_motor[all_sensory_dense]
    sensory_desc = dist_to_productive_desc[all_sensory_dense]

    output_reports: dict[str, Any] = {}
    for name, rows in sorted(motor_ports.items()):
        dense, missing = map_rows(rows, body_to_dense)
        output_reports[name] = {
            "body_count": unique_body_count(rows),
            "runtime_body_count": int(dense.size),
            "missing_runtime_body_ids": missing,
            "source_mask_files": sorted({str(row.get("_mask_file")) for row in rows}),
        }

    confirmed_ports = [name for name, r in input_reports.items() if r["topology_route_confirmed"]]
    failed_ports = [name for name, r in input_reports.items() if not r["topology_route_confirmed"]]

    out = {
        "dataset": metadata.get("dataset"),
        "validation_kind": "directed topology reachability only; not neural dynamics or behaviour",
        "max_hops_per_reverse_search": args.max_hops,
        "source_masks": {
            "sensory": [Path(p).name for p in args.sensory],
            "motor": [Path(p).name for p in args.motor],
            "diagnostic": Path(args.diagnostic).name,
        },
        "runtime": {
            "nodes": node_count,
            "edges": edge_count,
            "edge_sha256": metadata["edges"].get("edges_sha256"),
            "node_sha256": metadata["nodes"].get("nodes_sha256"),
        },
        "targets": {
            "resolved_motor_bodies": int(len(motor_dense)),
            "motor_port_count": len(motor_ports),
            "descending_bodies": int(len(descending_dense)),
            "productive_descending_bodies": int(len(productive_desc)),
            "productive_descending_fraction": float(len(productive_desc) / len(descending_dense)) if len(descending_dense) else 0.0,
        },
        "searches": {
            "distance_to_any_motor": motor_bfs,
            "distance_to_any_productive_descending": desc_bfs,
        },
        "sensory_global": {
            "resolved_sensory_bodies": int(len(all_sensory_dense)),
            "sensory_port_count": len(sensory_ports),
            "missing_runtime_body_ids": missing_sensory,
            "reachable_any_motor_count": int(np.count_nonzero(sensory_motor >= 0)),
            "reachable_any_motor_fraction": float(np.mean(sensory_motor >= 0)) if sensory_motor.size else 0.0,
            "motor_hops": distance_stats(sensory_motor),
            "reachable_productive_descending_count": int(np.count_nonzero(sensory_desc >= 0)),
            "reachable_productive_descending_fraction": float(np.mean(sensory_desc >= 0)) if sensory_desc.size else 0.0,
            "hops_to_productive_descending": distance_stats(sensory_desc),
        },
        "ports": {
            "input": input_reports,
            "output": output_reports,
            "topology_confirmed_input_ports": confirmed_ports,
            "topology_unconfirmed_input_ports": failed_ports,
        },
        "promotion_policy": {
            "candidate_to_topology_validated": "port has >=1 body reaching any resolved motor and >=1 body reaching a descending neuron that itself reaches motor within configured hop limits",
            "biological_validation": "not performed here; requires signed neural dynamics and stimulus/response tests",
        },
    }

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "runtime_nodes": node_count,
        "runtime_edges": edge_count,
        "motor_bodies": len(motor_dense),
        "motor_ports": len(motor_ports),
        "descending_bodies": len(descending_dense),
        "productive_descending_bodies": len(productive_desc),
        "sensory_bodies": len(all_sensory_dense),
        "sensory_ports": len(sensory_ports),
        "sensory_reach_motor": int(np.count_nonzero(sensory_motor >= 0)),
        "sensory_reach_productive_desc": int(np.count_nonzero(sensory_desc >= 0)),
        "input_ports_confirmed": len(confirmed_ports),
        "input_ports_unconfirmed": len(failed_ports),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
