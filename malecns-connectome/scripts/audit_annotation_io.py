#!/usr/bin/env python3
"""Audit official MaleCNS annotations for simulation I/O construction.

The script intentionally does not invent biological labels. It reports the
exact Feather schema, value distributions and compact summaries of explicit
high-level I/O superclasses from the official annotation table.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather

INTERESTING = {
    "status",
    "superclass",
    "class",
    "subclass",
    "type",
    "systematicType",
    "somaSide",
    "somaNeuromere",
    "rootSide",
    "rootNeuropil",
    "hemilineage",
    "mancType",
    "flywireType",
}

IO_SUPERCLASSES = {
    "vnc_sensory": "input",
    "vnc_motor": "output",
    "ascending_neuron": "diagnostic",
    "descending_neuron": "diagnostic",
}


def scalar(value: Any) -> Any:
    if hasattr(value, "as_py"):
        return value.as_py()
    return value


def value_counts(column: pa.ChunkedArray, limit: int = 200) -> list[dict[str, Any]]:
    clean = pc.drop_null(column)
    if len(clean) == 0:
        return []
    counts = pc.value_counts(clean).to_pylist()
    counts.sort(key=lambda x: (-int(x["counts"]), str(x["values"])))
    return [{"value": scalar(x["values"]), "count": int(x["counts"])} for x in counts[:limit]]


def body_column(names: list[str]) -> str:
    for candidate in ("bodyId", "body_id", "body"):
        if candidate in names:
            return candidate
    raise KeyError(f"no body-id column found in {names}")


def summarize_superclass(
    table: pa.Table,
    superclass: str,
    body_col: str,
    *,
    sample_rows: int = 40,
) -> dict[str, Any]:
    mask = pc.equal(table["superclass"], pa.scalar(superclass))
    sub = table.filter(mask)
    fields = [
        body_col,
        "type",
        "systematicType",
        "class",
        "subclass",
        "somaSide",
        "somaNeuromere",
        "rootSide",
        "rootNeuropil",
        "status",
    ]
    fields = [f for f in fields if f in sub.column_names]

    breakdown: dict[str, Any] = {}
    for field in ("class", "subclass", "somaSide", "somaNeuromere", "rootSide", "rootNeuropil", "status"):
        if field in sub.column_names:
            breakdown[field] = value_counts(sub[field], 200)

    sample: list[dict[str, Any]] = []
    if fields and sub.num_rows:
        for row in sub.select(fields).slice(0, sample_rows).to_pylist():
            sample.append({k: scalar(v) for k, v in row.items()})

    return {
        "count": sub.num_rows,
        "fields": fields,
        "breakdown": breakdown,
        "sample_rows": sample,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("annotations")
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-values", type=int, default=200)
    args = ap.parse_args()

    table = feather.read_table(args.annotations)
    names = table.column_names
    body_col = body_column(names)

    schema = [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
            "null_count": int(table[field.name].null_count),
        }
        for field in table.schema
    ]

    distributions: dict[str, Any] = {}
    for name in names:
        col = table[name]
        t = col.type
        is_text = pa.types.is_string(t) or pa.types.is_large_string(t) or pa.types.is_dictionary(t)
        if name in INTERESTING or is_text:
            try:
                distributions[name] = {
                    "unique_non_null": int(pc.count_distinct(col).as_py()),
                    "top_values": value_counts(col, args.max_values),
                }
            except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
                pass

    io_groups: dict[str, Any] = {}
    if "superclass" in names:
        for superclass, direction in IO_SUPERCLASSES.items():
            group = summarize_superclass(table, superclass, body_col)
            group["direction"] = direction
            io_groups[superclass] = group

    out = {
        "source_file": Path(args.annotations).name,
        "rows": table.num_rows,
        "columns": table.num_columns,
        "body_id_column": body_col,
        "schema": schema,
        "distributions": distributions,
        "io_superclasses": io_groups,
        "notes": [
            "I/O groups are selected only by exact superclass labels found in the official annotations.",
            "Superclass rows remain candidates until semantic port grouping and path validation are complete.",
            "No unknown/unclassified neuron is assigned an I/O role by this audit.",
            "Only compact samples are tracked here; body-ID masks are generated separately from the source Feather.",
        ],
    }

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "rows": table.num_rows,
        "columns": table.num_columns,
        "body_id_column": body_col,
        "io_counts": {k: v["count"] for k, v in io_groups.items()},
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
