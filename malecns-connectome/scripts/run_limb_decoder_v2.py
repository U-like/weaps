from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from malecns.limb_decoder_v2 import leave_one_family_out, permutation_null


def load_families(path: Path) -> dict[str, dict[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: {label: int(body) for label, body in spec["members"].items()}
        for name, spec in data["limb_families"].items()
        if spec.get("status") == "confirmed-six-channel"
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Cross-family MaleCNS limb decoder evaluation")
    ap.add_argument("features_npz", type=Path)
    ap.add_argument("--anchors", type=Path, default=Path("data/anchors.json"))
    ap.add_argument("--permutations", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--output", type=Path, default=Path("results/limb_decoder_v2.json"))
    args = ap.parse_args()

    z = np.load(args.features_npz)
    body_ids = np.asarray(z["body_ids"], dtype=np.int64)
    features = np.asarray(z["features"], dtype=np.float64)
    if features.ndim != 2 or len(body_ids) != len(features):
        raise ValueError("NPZ must contain aligned body_ids[N] and features[N,D]")

    feature_map = {int(body): features[i] for i, body in enumerate(body_ids)}
    families = load_families(args.anchors)
    if len(families) < 2:
        raise ValueError("at least two confirmed six-channel families are required")
    required = {body for members in families.values() for body in members.values()}
    missing = sorted(required.difference(feature_map))
    if missing:
        raise KeyError(f"feature matrix is missing anchor bodies: {missing}")

    observed = leave_one_family_out(feature_map, families)
    observed_forced = float(np.mean([v["forced_accuracy"] for v in observed.values()]))
    observed_side = float(np.mean([v["side_accuracy"] for v in observed.values()]))
    observed_segment = float(np.mean([v["segment_accuracy"] for v in observed.values()]))
    observed_coverage = float(np.mean([v["coverage"] for v in observed.values()]))

    null = permutation_null(feature_map, families, repeats=args.permutations, seed=args.seed)
    p = float((1 + np.sum(null >= observed_forced)) / (len(null) + 1))

    result = {
        "method": {
            "primary_metric": "leave-one-cell-type-out six-way forced_accuracy",
            "null": "independent within-family permutation of T1/T2/T3 x L/R labels",
            "abstain_note": "ABSTAIN/coverage is reported separately and is not used for the significance test"
        },
        "confirmed_families": sorted(families),
        "feature_shape": [int(features.shape[0]), int(features.shape[1])],
        "families": observed,
        "summary": {
            "observed_mean_forced_accuracy": observed_forced,
            "observed_mean_side_accuracy": observed_side,
            "observed_mean_segment_accuracy": observed_segment,
            "observed_mean_coverage": observed_coverage,
            "chance_six_way": 1.0 / 6.0,
            "chance_side": 0.5,
            "chance_segment": 1.0 / 3.0
        },
        "permutation_null": {
            "repeats": int(len(null)),
            "mean": float(np.mean(null)),
            "std": float(np.std(null)),
            "p_ge_observed": p,
            "q50": float(np.quantile(null, 0.50)),
            "q95": float(np.quantile(null, 0.95)),
            "q99": float(np.quantile(null, 0.99)),
            "max": float(np.max(null))
        }
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("===MALECNS_LIMB_DECODER_V2===")
    print(json.dumps(result, indent=2))
    print("===END_MALECNS_LIMB_DECODER_V2===")


if __name__ == "__main__":
    main()
