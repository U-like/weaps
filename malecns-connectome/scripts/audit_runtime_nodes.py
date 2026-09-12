#!/usr/bin/env python3
"""Audit candidate node policies for the stateful MaleCNS runtime graph."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

import pyarrow.feather as feather


def norm(value: Any) -> str:
    if value is None:
        return "<null>"
    text = str(value).strip()
    return text if text else "<empty>"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("annotations")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    table = feather.read_table(args.annotations)
    rows = table.to_pylist()
    body_col = "bodyId" if "bodyId" in table.column_names else "body_id"

    status = Counter(norm(row.get("status")) for row in rows)
    superclass = Counter(norm(row.get("superclass")) for row in rows)
    joint = Counter((norm(row.get("status")), norm(row.get("superclass"))) for row in rows)

    with_body = [row for row in rows if row.get(body_col) is not None]
    assigned_superclass = [
        row for row in with_body
        if norm(row.get("superclass")) not in {"<null>", "<empty>"}
    ]
    traced = [row for row in with_body if norm(row.get("status")) == "Traced"]
    traced_assigned = [
        row for row in traced
        if norm(row.get("superclass")) not in {"<null>", "<empty>"}
    ]

    # Glia must never silently become neural state just because it appears in
    # an annotation table.  Keep this broader policy count only as an audited
    # comparison, not as an automatic selection.
    assigned_non_glia = [
        row for row in assigned_superclass
        if norm(row.get("status")).lower() != "glia"
        and norm(row.get("superclass")).lower() != "glia"
    ]

    out = {
        "source_file": Path(args.annotations).name,
        "rows": table.num_rows,
        "unique_body_ids": len({int(row[body_col]) for row in with_body}),
        "missing_body_id_rows": table.num_rows - len(with_body),
        "status_counts": dict(sorted(status.items(), key=lambda kv: (-kv[1], kv[0]))),
        "superclass_counts": dict(sorted(superclass.items(), key=lambda kv: (-kv[1], kv[0]))),
        "status_superclass_counts": [
            {"status": key[0], "superclass": key[1], "count": count}
            for key, count in sorted(joint.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "policy_counts": {
            "all_annotated_with_body_id": len(with_body),
            "status_traced": len(traced),
            "assigned_superclass": len(assigned_superclass),
            "status_traced_and_assigned_superclass": len(traced_assigned),
            "assigned_superclass_excluding_explicit_glia": len(assigned_non_glia),
        },
        "policy_notes": {
            "conservative_initial_runtime": "status == Traced AND superclass is assigned",
            "broader_candidate": "superclass is assigned and explicit glia are excluded",
            "decision_rule": "Do not finalize node policy until counts and excluded categories are reviewed; raw segmentation objects are never stateful neurons by default."
        },
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "rows": out["rows"],
        "unique_body_ids": out["unique_body_ids"],
        "policy_counts": out["policy_counts"],
        "status_counts": out["status_counts"],
    }, indent=2))


if __name__ == "__main__":
    main()
