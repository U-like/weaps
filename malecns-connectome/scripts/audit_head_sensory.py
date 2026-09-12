#!/usr/bin/env python3
"""Audit optic-lobe and central-brain sensory annotations for body I/O design.

The goal is to discover usable *official* coordinate/modality fields before we
construct virtual eye, antenna, taste or other head-sensor ports. No missing
anatomy is inferred here.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather


def scalar(value: Any) -> Any:
    return value.as_py() if hasattr(value, "as_py") else value


def clean(value: Any) -> str:
    if value is None:
        return "<null>"
    text = str(value).strip()
    return text if text else "<empty>"


def value_counts(column: pa.ChunkedArray, limit: int = 300) -> list[dict[str, Any]]:
    valid = pc.drop_null(column)
    if len(valid) == 0:
        return []
    counts = pc.value_counts(valid).to_pylist()
    counts.sort(key=lambda x: (-int(x["counts"]), str(x["values"])))
    return [
        {"value": scalar(item["values"]), "count": int(item["counts"])}
        for item in counts[:limit]
    ]


def profile_field(table: pa.Table, name: str) -> dict[str, Any]:
    if name not in table.column_names:
        return {"present": False}
    col = table[name]
    out: dict[str, Any] = {
        "present": True,
        "type": str(col.type),
        "rows": table.num_rows,
        "null_count": int(col.null_count),
        "non_null_count": int(table.num_rows - col.null_count),
        "unique_non_null": int(pc.count_distinct(col).as_py()),
    }
    if pa.types.is_integer(col.type) or pa.types.is_floating(col.type):
        valid = pc.drop_null(col)
        if len(valid):
            out["min"] = scalar(pc.min(valid))
            out["max"] = scalar(pc.max(valid))
    else:
        out["top_values"] = value_counts(col, 300)
    return out


def combinations(table: pa.Table, fields: list[str], limit: int = 500) -> list[dict[str, Any]]:
    actual = [field for field in fields if field in table.column_names]
    counter: Counter[tuple[str, ...]] = Counter()
    for row in table.select(actual).to_pylist():
        counter[tuple(clean(row.get(field)) for field in actual)] += 1
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [
        {**{field: key[i] for i, field in enumerate(actual)}, "count": int(count)}
        for key, count in items
    ]


def body_column(names: list[str]) -> str:
    for candidate in ("bodyId", "body_id", "body"):
        if candidate in names:
            return candidate
    raise KeyError("no body-id column")


def subset(table: pa.Table, superclass: str) -> pa.Table:
    return table.filter(pc.equal(table["superclass"], pa.scalar(superclass)))


def samples(table: pa.Table, fields: list[str], limit: int = 50) -> list[dict[str, Any]]:
    actual = [f for f in fields if f in table.column_names]
    return table.select(actual).slice(0, limit).to_pylist()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("annotations")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    table = feather.read_table(args.annotations)
    body = body_column(table.column_names)
    ol = subset(table, "ol_sensory")
    cb = subset(table, "cb_sensory")

    ol_fields = [
        "type", "class", "rootSide", "somaSide", "assignedOlHex1",
        "assignedOlHex2", "status", "receptorType",
    ]
    cb_fields = [
        "type", "class", "subclass", "entryNerve", "rootSide", "status",
        "receptorType",
    ]

    out = {
        "source_file": Path(args.annotations).name,
        "optic_lobe_sensory": {
            "superclass": "ol_sensory",
            "rows": ol.num_rows,
            "profiles": {field: profile_field(ol, field) for field in ol_fields},
            "type_root_hex_combinations": combinations(
                ol,
                ["type", "rootSide", "assignedOlHex1", "assignedOlHex2", "status"],
                500,
            ),
            "sample_rows": samples(
                ol,
                [body, "type", "class", "rootSide", "assignedOlHex1", "assignedOlHex2", "status"],
                60,
            ),
        },
        "central_brain_sensory": {
            "superclass": "cb_sensory",
            "rows": cb.num_rows,
            "profiles": {field: profile_field(cb, field) for field in cb_fields},
            "nerve_class_subclass_side_combinations": combinations(
                cb,
                ["entryNerve", "class", "subclass", "rootSide", "status"],
                500,
            ),
            "sample_rows": samples(
                cb,
                [body, "type", "class", "subclass", "entryNerve", "rootSide", "receptorType", "status"],
                60,
            ),
        },
        "notes": [
            "assignedOlHex1/assignedOlHex2 are audited as official fields; no interpretation is imposed until their observed schema/values are known.",
            "cb_sensory semantic channels should be derived from observed nerve/class/subclass combinations, not superclass alone.",
            "Rows with null status remain visible because status completeness is separate from official superclass assignment."
        ],
    }

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    print(json.dumps({
        "ol_sensory_rows": ol.num_rows,
        "cb_sensory_rows": cb.num_rows,
        "ol_hex1": out["optic_lobe_sensory"]["profiles"]["assignedOlHex1"],
        "ol_hex2": out["optic_lobe_sensory"]["profiles"]["assignedOlHex2"],
        "cb_class": out["central_brain_sensory"]["profiles"]["class"],
        "cb_entry_nerve": out["central_brain_sensory"]["profiles"]["entryNerve"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
