#!/usr/bin/env python3
"""Audit official MaleCNS neurotransmitter predictions over runtime neurons.

The audit is descriptive only. It deliberately does not map transmitter labels
to excitatory/inhibitory signs because that is a neural-dynamics assumption,
not a property of the connectome weight file itself.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def body_column(names: list[str]) -> str:
    for candidate in ("bodyId", "body_id", "body"):
        if candidate in names:
            return candidate
    raise KeyError(f"no body-id column found in {names}")


def runtime_annotation_rows(table: pa.Table) -> pa.Table:
    if "superclass" not in table.column_names:
        raise KeyError("annotations lack superclass")
    superclass = table["superclass"]
    mask = pc.and_(pc.is_valid(superclass), pc.not_equal(superclass, pa.scalar("")))
    if "status" in table.column_names:
        non_glia = pc.fill_null(pc.not_equal(table["status"], pa.scalar("Glia")), True)
        mask = pc.and_(mask, non_glia)
    return table.filter(mask)


def count_values(values: list[Any]) -> dict[str, int]:
    counter = Counter("<null>" if clean(v) is None else str(clean(v)) for v in values)
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def numeric_profile(values: list[Any]) -> dict[str, Any]:
    finite: list[float] = []
    nulls = 0
    for value in values:
        if value is None:
            nulls += 1
            continue
        try:
            f = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(f):
            finite.append(f)
    if not finite:
        return {"non_null_finite": 0, "null_count": nulls}
    arr = np.asarray(finite, dtype=np.float64)
    return {
        "non_null_finite": int(arr.size),
        "null_count": nulls,
        "min": float(arr.min()),
        "p01": float(np.percentile(arr, 1)),
        "p05": float(np.percentile(arr, 5)),
        "median": float(np.median(arr)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("annotations")
    ap.add_argument("neurotransmitters")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    annotations = feather.read_table(args.annotations)
    runtime = runtime_annotation_rows(annotations)
    ann_body_col = body_column(runtime.column_names)
    runtime_rows = runtime.to_pylist()
    runtime_by_body = {int(row[ann_body_col]): row for row in runtime_rows}
    if len(runtime_by_body) != runtime.num_rows:
        raise ValueError("runtime annotation body IDs are not unique")

    nt = feather.read_table(args.neurotransmitters)
    nt_body_col = body_column(nt.column_names)
    nt_rows = nt.to_pylist()
    nt_by_body = {int(row[nt_body_col]): row for row in nt_rows if row.get(nt_body_col) is not None}
    if len(nt_by_body) != len([r for r in nt_rows if r.get(nt_body_col) is not None]):
        raise ValueError("neurotransmitter body IDs are not unique")

    runtime_ids = set(runtime_by_body)
    matched_ids = sorted(runtime_ids & set(nt_by_body))
    unmatched_ids = sorted(runtime_ids - set(nt_by_body))
    nt_only_ids = sorted(set(nt_by_body) - runtime_ids)

    categorical_fields = [
        name for name in (
            "cell_type",
            "predicted_nt",
            "celltype_predicted_nt",
            "ground_truth",
            "consensus_nt",
        ) if name in nt.column_names
    ]
    numeric_fields = [
        name for name in (
            "total_nt_predictions",
            "predicted_nt_confidence",
            "celltype_total_nt_predictions",
            "celltype_predicted_nt_confidence",
        ) if name in nt.column_names
    ]

    categorical: dict[str, Any] = {}
    numeric: dict[str, Any] = {}
    for field in categorical_fields:
        categorical[field] = count_values([nt_by_body[body].get(field) for body in matched_ids])
    for field in numeric_fields:
        numeric[field] = numeric_profile([nt_by_body[body].get(field) for body in matched_ids])

    by_superclass: dict[str, dict[str, Any]] = {}
    class_bodies: dict[str, list[int]] = defaultdict(list)
    for body in matched_ids:
        superclass = clean(runtime_by_body[body].get("superclass")) or "<null>"
        class_bodies[superclass].append(body)
    for superclass, bodies in sorted(class_bodies.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        record: dict[str, Any] = {"matched_bodies": len(bodies)}
        for field in ("consensus_nt", "predicted_nt", "celltype_predicted_nt"):
            if field in nt.column_names:
                record[field] = count_values([nt_by_body[body].get(field) for body in bodies])
        by_superclass[superclass] = record

    unmatched_by_superclass = count_values([
        runtime_by_body[body].get("superclass") for body in unmatched_ids
    ])
    unmatched_by_status = count_values([
        runtime_by_body[body].get("status") for body in unmatched_ids
    ])

    pair_disagreement: dict[str, Any] = {}
    for left, right in (
        ("consensus_nt", "predicted_nt"),
        ("consensus_nt", "celltype_predicted_nt"),
        ("predicted_nt", "celltype_predicted_nt"),
    ):
        if left not in nt.column_names or right not in nt.column_names:
            continue
        comparable = 0
        equal = 0
        disagreement = Counter()
        for body in matched_ids:
            a = clean(nt_by_body[body].get(left))
            b = clean(nt_by_body[body].get(right))
            if a is None or b is None:
                continue
            comparable += 1
            if a == b:
                equal += 1
            else:
                disagreement[(a, b)] += 1
        pair_disagreement[f"{left}__vs__{right}"] = {
            "comparable": comparable,
            "equal": equal,
            "different": comparable - equal,
            "agreement_fraction": equal / comparable if comparable else None,
            "top_disagreements": [
                {left: pair[0], right: pair[1], "count": count}
                for pair, count in disagreement.most_common(50)
            ],
        }

    out = {
        "dataset": "male-cns:v1.0-minconf-0.5",
        "source_files": {
            "annotations": Path(args.annotations).name,
            "neurotransmitters": Path(args.neurotransmitters).name,
        },
        "runtime_node_policy": "official superclass assigned; explicit Glia excluded; null status retained",
        "runtime_neurons": len(runtime_ids),
        "nt_source_rows": nt.num_rows,
        "nt_columns": nt.column_names,
        "coverage": {
            "matched_runtime_neurons": len(matched_ids),
            "unmatched_runtime_neurons": len(unmatched_ids),
            "matched_fraction": len(matched_ids) / len(runtime_ids) if runtime_ids else 0.0,
            "nt_rows_outside_runtime_policy": len(nt_only_ids),
            "unmatched_by_superclass": unmatched_by_superclass,
            "unmatched_by_status": unmatched_by_status,
            "unmatched_body_id_sample": unmatched_ids[:200],
        },
        "categorical_distributions": categorical,
        "numeric_profiles": numeric,
        "by_superclass": by_superclass,
        "prediction_agreement": pair_disagreement,
        "notes": [
            "This audit does not assign synaptic signs.",
            "Connectome weights remain positive structural strengths; transmitter-to-sign mapping belongs to the neural dynamics model.",
            "Unmatched neurons are retained in the runtime graph and require an explicit unknown-transmitter policy before signed simulation."
        ],
    }

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "runtime_neurons": len(runtime_ids),
        "matched": len(matched_ids),
        "unmatched": len(unmatched_ids),
        "matched_fraction": out["coverage"]["matched_fraction"],
        "consensus_nt": categorical.get("consensus_nt"),
        "unmatched_by_superclass": unmatched_by_superclass,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
