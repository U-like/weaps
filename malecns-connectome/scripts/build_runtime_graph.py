#!/usr/bin/env python3
"""Build the compact stateful MaleCNS neuron graph from official flat files.

Raw MaleCNS weights contain every synaptic segment, not just neurons.  The
runtime node set is induced by bodies with an assigned official ``superclass``.
This reproduces the 166,700 annotated neuronal entries while excluding raw
segmentation fragments and explicit glia/unclassified objects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather
import pyarrow.ipc as ipc


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def sha256(path: str | Path, chunk: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()


def body_column(names: list[str]) -> str:
    for candidate in ("bodyId", "body_id", "body"):
        if candidate in names:
            return candidate
    raise KeyError(f"no body ID column in {names}")


def neuron_mask(table: pa.Table) -> pa.Array | pa.ChunkedArray:
    if "superclass" not in table.column_names:
        raise KeyError("annotations lack superclass")
    superclass = table["superclass"]
    assigned = pc.and_(pc.is_valid(superclass), pc.not_equal(superclass, pa.scalar("")))
    if "status" in table.column_names:
        # Belt-and-suspenders exclusion. In v1.0 explicit Glia rows have no
        # superclass, but never rely on that coincidence silently.
        status = table["status"]
        not_glia_status = pc.or_(pc.is_null(status), pc.not_equal(status, pa.scalar("Glia")))
        assigned = pc.and_(assigned, not_glia_status)
    return assigned


def attach_neurotransmitters(nodes: pa.Table, nt_path: str | None) -> tuple[pa.Table, dict[str, Any]]:
    if not nt_path:
        return nodes, {"included": False}

    nt = feather.read_table(nt_path)
    nt_body_col = body_column(nt.column_names)
    if nt[nt_body_col].null_count:
        raise ValueError("neurotransmitter body ID column contains nulls")
    nt_ids = np.asarray(nt[nt_body_col].combine_chunks())
    if len(np.unique(nt_ids)) != len(nt_ids):
        raise ValueError("neurotransmitter table has duplicate body IDs")

    node_ids = nodes["body_id"].combine_chunks()
    index = pc.index_in(node_ids, value_set=nt[nt_body_col].combine_chunks())
    matched = pc.greater_equal(index, pa.scalar(0, index.type))
    matched_count = int(pc.sum(pc.cast(matched, pa.int64())).as_py())

    # ``take`` cannot use -1 as a null sentinel, so replace unmatched indexes
    # with 0, take, then apply the validity mask to every joined column.
    safe_index = pc.if_else(matched, index, pa.scalar(0, index.type))
    for name in nt.column_names:
        if name == nt_body_col:
            continue
        col = pc.take(nt[name].combine_chunks(), safe_index)
        col = pc.if_else(matched, col, pa.nulls(len(nodes), type=col.type))
        out_name = name if name not in nodes.column_names else f"nt_{name}"
        nodes = nodes.append_column(out_name, col)

    return nodes, {
        "included": True,
        "source_file": Path(nt_path).name,
        "source_rows": nt.num_rows,
        "source_columns": nt.column_names,
        "matched_nodes": matched_count,
        "unmatched_nodes": nodes.num_rows - matched_count,
        "sha256": sha256(nt_path),
    }


def build_nodes(annotations_path: str, nt_path: str | None, output_path: str) -> tuple[pa.Table, dict[str, Any]]:
    annotations = feather.read_table(annotations_path)
    source_body = body_column(annotations.column_names)
    nodes = annotations.filter(neuron_mask(annotations))

    ids_np = np.asarray(nodes[source_body].combine_chunks(), dtype=np.int64)
    order = np.argsort(ids_np, kind="stable")
    nodes = pc.take(nodes, pa.array(order, type=pa.int64()))
    ids_np = ids_np[order]
    if len(np.unique(ids_np)) != len(ids_np):
        raise ValueError("selected annotations contain duplicate body IDs")

    if source_body != "body_id":
        names = ["body_id" if n == source_body else n for n in nodes.column_names]
        nodes = nodes.rename_columns(names)
    dense = pa.array(np.arange(nodes.num_rows, dtype=np.uint32), type=pa.uint32())
    nodes = nodes.add_column(0, "dense_id", dense)
    nodes, nt_meta = attach_neurotransmitters(nodes, nt_path)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    feather.write_feather(nodes, target, compression="lz4")

    status_counts: dict[str, int] = {}
    if "status" in nodes.column_names:
        for item in pc.value_counts(pc.drop_null(nodes["status"])).to_pylist():
            status_counts[str(item["values"])] = int(item["counts"])

    return nodes, {
        "node_count": nodes.num_rows,
        "body_id_min": int(ids_np.min()),
        "body_id_max": int(ids_np.max()),
        "node_policy": "official superclass assigned; explicit Glia excluded",
        "status_counts": status_counts,
        "annotations_sha256": sha256(annotations_path),
        "neurotransmitters": nt_meta,
        "nodes_sha256": sha256(target),
    }


def build_edges(weights_path: str, nodes: pa.Table, output_path: str) -> dict[str, Any]:
    body_ids = nodes["body_id"].combine_chunks()
    node_count = nodes.num_rows
    if node_count > np.iinfo(np.uint32).max:
        raise ValueError("too many nodes for uint32 dense IDs")

    source = pa.memory_map(weights_path, "r")
    reader = ipc.open_file(source)
    required = {"body_pre", "body_post", "weight"}
    if not required.issubset(reader.schema.names):
        raise ValueError(f"weights schema missing {sorted(required - set(reader.schema.names))}")

    out_schema = pa.schema([
        pa.field("pre", pa.uint32(), nullable=False),
        pa.field("post", pa.uint32(), nullable=False),
        pa.field("weight", pa.uint16(), nullable=False),
    ])
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    sink = pa.OSFile(str(target), "wb")
    options = ipc.IpcWriteOptions(compression="lz4")
    writer = ipc.new_file(sink, out_schema, options=options)

    source_rows = 0
    edge_count = 0
    self_edges = 0
    weight_sum = 0
    weight_min: int | None = None
    weight_max = 0
    batches_written = 0

    try:
        for i in range(reader.num_record_batches):
            batch = reader.get_batch(i)
            source_rows += batch.num_rows
            pre = batch.column(batch.schema.get_field_index("body_pre"))
            post = batch.column(batch.schema.get_field_index("body_post"))
            weight = batch.column(batch.schema.get_field_index("weight"))

            pre_idx = pc.index_in(pre, value_set=body_ids)
            post_idx = pc.index_in(post, value_set=body_ids)
            valid = pc.and_(
                pc.greater_equal(pre_idx, pa.scalar(0, pre_idx.type)),
                pc.greater_equal(post_idx, pa.scalar(0, post_idx.type)),
            )
            if int(pc.sum(pc.cast(valid, pa.int64())).as_py()) == 0:
                continue

            dense_pre = pc.cast(pc.filter(pre_idx, valid), pa.uint32())
            dense_post = pc.cast(pc.filter(post_idx, valid), pa.uint32())
            kept_weight_i64 = pc.filter(weight, valid)
            batch_min = int(pc.min(kept_weight_i64).as_py())
            batch_max = int(pc.max(kept_weight_i64).as_py())
            if batch_min < 0 or batch_max > np.iinfo(np.uint16).max:
                raise ValueError(f"weight outside uint16 range: {batch_min}..{batch_max}")
            kept_weight = pc.cast(kept_weight_i64, pa.uint16())

            out = pa.record_batch([dense_pre, dense_post, kept_weight], schema=out_schema)
            writer.write_batch(out)
            batches_written += 1
            edge_count += out.num_rows
            self_edges += int(pc.sum(pc.cast(pc.equal(dense_pre, dense_post), pa.int64())).as_py())
            weight_sum += int(pc.sum(pc.cast(kept_weight, pa.int64())).as_py())
            weight_min = batch_min if weight_min is None else min(weight_min, batch_min)
            weight_max = max(weight_max, batch_max)
    finally:
        writer.close()
        sink.close()
        source.close()

    # Validate the generated Arrow/Feather-compatible IPC file immediately.
    with pa.memory_map(str(target), "r") as verify_source:
        verify = ipc.open_file(verify_source)
        verify_rows = sum(verify.get_batch(i).num_rows for i in range(verify.num_record_batches))
    if verify_rows != edge_count:
        raise RuntimeError(f"edge output row mismatch: {verify_rows} != {edge_count}")

    return {
        "source_rows": source_rows,
        "edge_count": edge_count,
        "retained_fraction": edge_count / source_rows if source_rows else 0.0,
        "record_batches_written": batches_written,
        "self_edges": self_edges,
        "weight_sum": weight_sum,
        "weight_min": weight_min,
        "weight_max": weight_max,
        "edge_schema": {"pre": "uint32 dense_id", "post": "uint32 dense_id", "weight": "uint16"},
        "weights_sha256": sha256(weights_path),
        "edges_sha256": sha256(target),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("annotations")
    ap.add_argument("weights")
    ap.add_argument("--neurotransmitters")
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--edges", required=True)
    ap.add_argument("--metadata", required=True)
    args = ap.parse_args()

    nodes, node_meta = build_nodes(args.annotations, args.neurotransmitters, args.nodes)
    edge_meta = build_edges(args.weights, nodes, args.edges)
    metadata = {
        "runtime_format_version": "0.1",
        "dataset": "male-cns:v1.0-minconf-0.5",
        "graph_semantics": "induced directed weighted graph over official annotated neuronal bodies",
        "nodes": node_meta,
        "edges": edge_meta,
        "important": [
            "Raw weights are segment-to-segment; only edges whose endpoints are selected official neuron bodies are retained.",
            "Dense edge IDs map to body IDs via neurons.feather:dense_id/body_id.",
            "No weight threshold is applied to the curated neuron graph.",
            "Neurotransmitter properties are stored but no excitatory/inhibitory sign convention is imposed here."
        ],
    }
    target = Path(args.metadata)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "nodes": node_meta["node_count"],
        "edges": edge_meta["edge_count"],
        "retained_fraction": edge_meta["retained_fraction"],
        "nt_matched": node_meta["neurotransmitters"].get("matched_nodes"),
    }, indent=2))


if __name__ == "__main__":
    main()
