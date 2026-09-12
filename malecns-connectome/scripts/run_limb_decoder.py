from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from malecns.limb_decoder import leave_one_family_out, permutation_null


def load_anchors(path: Path) -> dict[str, dict[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    families = {}
    for name, spec in data["limb_families"].items():
        if spec.get("status") == "confirmed-six-channel":
            families[name] = {k: int(v) for k, v in spec["members"].items()}
    return families


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("features_npz", type=Path, help="NPZ with body_ids[N] and features[N,D]")
    ap.add_argument("--anchors", type=Path, default=Path("data/anchors.json"))
    ap.add_argument("--permutations", type=int, default=256)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--output", type=Path, default=Path("results/limb_decoder.json"))
    args = ap.parse_args()

    z = np.load(args.features_npz)
    body_ids = np.asarray(z["body_ids"], dtype=np.int64)
    features = np.asarray(z["features"], dtype=np.float64)
    if features.ndim != 2 or len(body_ids) != len(features):
        raise ValueError("NPZ must contain aligned body_ids[N] and features[N,D]")

    feature_map = {int(body): features[i] for i, body in enumerate(body_ids)}
    families = load_anchors(args.anchors)
    required = {body for members in families.values() for body in members.values()}
    missing = sorted(required.difference(feature_map))
    if missing:
        raise KeyError(f"feature matrix is missing {len(missing)} anchor bodies: {missing}")

    observed = leave_one_family_out(feature_map, families)
    null = permutation_null(
        feature_map,
        families,
        repeats=args.permutations,
        seed=args.seed,
    )
    observed_accuracy = float(np.mean([v["accuracy_non_abstain"] for v in observed.values()]))
    p = float((1 + np.sum(null >= observed_accuracy)) / (len(null) + 1))

    result = {
        "families": observed,
        "observed_mean_non_abstain_accuracy": observed_accuracy,
        "permutation_null": {
            "repeats": int(len(null)),
            "mean": float(np.mean(null)),
            "std": float(np.std(null)),
            "p_ge_observed": p,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
