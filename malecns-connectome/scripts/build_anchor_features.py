from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc


def anchor_ids(path: Path) -> np.ndarray:
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = []
    for spec in data["limb_families"].values():
        if spec.get("status") == "confirmed-six-channel":
            ids.extend(int(v) for v in spec["members"].values())
    return np.array(sorted(set(ids)), dtype=np.int64)


def mix64(x: np.ndarray) -> np.ndarray:
    """Vectorized SplitMix64 finalizer for deterministic CountSketch coordinates."""
    z = np.asarray(x, dtype=np.uint64).copy()
    z ^= z >> np.uint64(30)
    z *= np.uint64(0xBF58476D1CE4E5B9)
    z ^= z >> np.uint64(27)
    z *= np.uint64(0x94D049BB133111EB)
    z ^= z >> np.uint64(31)
    return z


def accumulate_channel(
    target_rows: np.ndarray,
    partner_ids: np.ndarray,
    weights: np.ndarray,
    out: np.ndarray,
    *,
    bins: int,
    salt: int,
) -> None:
    if len(target_rows) == 0:
        return
    h = mix64(np.asarray(partner_ids, dtype=np.uint64) ^ np.uint64(salt))
    cols = np.asarray(h % np.uint64(bins), dtype=np.int64)
    signs = np.where(((h >> np.uint64(63)) & np.uint64(1)) == 0, 1.0, -1.0)
    np.add.at(out, (target_rows, cols), np.asarray(weights, dtype=np.float64) * signs)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build direct in/out CountSketch features for limb anchors")
    ap.add_argument("graph_feather", type=Path)
    ap.add_argument("--anchors", type=Path, default=Path("data/anchors.json"))
    ap.add_argument("--bins", type=int, default=65536)
    ap.add_argument("--min-weight", type=int, default=1)
    ap.add_argument("--output", type=Path, default=Path("data/anchor_connectivity_features.npz"))
    args = ap.parse_args()

    ids = anchor_ids(args.anchors)
    if len(ids) == 0:
        raise ValueError("no confirmed six-channel anchors")
    row_of = {int(body): i for i, body in enumerate(ids)}
    incoming = np.zeros((len(ids), args.bins), dtype=np.float64)
    outgoing = np.zeros((len(ids), args.bins), dtype=np.float64)

    source = pa.memory_map(str(args.graph_feather), "r")
    reader = ipc.open_file(source)
    names = set(reader.schema.names)
    required = {"body_pre", "body_post", "weight"}
    if not required.issubset(names):
        raise ValueError(f"graph must contain {sorted(required)}; found {reader.schema.names}")

    total = 0
    used = 0
    for batch_i in range(reader.num_record_batches):
        batch = reader.get_batch(batch_i)
        pre = batch.column(reader.schema.get_field_index("body_pre")).to_numpy(zero_copy_only=False)
        post = batch.column(reader.schema.get_field_index("body_post")).to_numpy(zero_copy_only=False)
        weight = batch.column(reader.schema.get_field_index("weight")).to_numpy(zero_copy_only=False)
        total += len(weight)
        keep = weight >= args.min_weight
        if not np.all(keep):
            pre, post, weight = pre[keep], post[keep], weight[keep]

        # Membership over only 12-18 anchors is faster and much smaller than constructing
        # a dense map over the ~88M raw segment IDs.
        pre_mask = np.isin(pre, ids)
        if np.any(pre_mask):
            p = pre[pre_mask]
            rows = np.fromiter((row_of[int(x)] for x in p), dtype=np.int64, count=len(p))
            accumulate_channel(rows, post[pre_mask], weight[pre_mask], outgoing, bins=args.bins, salt=0xA5A5A5A5)
            used += int(np.sum(pre_mask))

        post_mask = np.isin(post, ids)
        if np.any(post_mask):
            p = post[post_mask]
            rows = np.fromiter((row_of[int(x)] for x in p), dtype=np.int64, count=len(p))
            accumulate_channel(rows, pre[post_mask], weight[post_mask], incoming, bins=args.bins, salt=0x5A5A5A5A)
            used += int(np.sum(post_mask))

        if (batch_i + 1) % 100 == 0 or batch_i + 1 == reader.num_record_batches:
            print(f"batches {batch_i + 1}/{reader.num_record_batches}; rows={total:,}; anchor-edge-incidences={used:,}", flush=True)

    # Keep direction as separate coordinates. Absolute value prevents signed CountSketch
    # cancellation from becoming an accidental biological sign; sign is only collision control.
    features = np.concatenate([np.abs(outgoing), np.abs(incoming)], axis=1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        body_ids=ids,
        features=features,
        outgoing_bins=outgoing,
        incoming_bins=incoming,
        bins=np.array(args.bins, dtype=np.int64),
        min_weight=np.array(args.min_weight, dtype=np.int64),
    )
    print(f"wrote {args.output}: body_ids={len(ids)}, feature_dim={features.shape[1]}")


if __name__ == "__main__":
    main()
