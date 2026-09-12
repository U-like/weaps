from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather


def collect_body_ids(value: Any, *, key: str = "") -> set[int]:
    out: set[int] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            lk = k.lower()
            if lk in {"body_id", "bodyid"} and isinstance(v, int):
                out.add(int(v))
            elif lk == "body_ids" and isinstance(v, list):
                out.update(int(x) for x in v if isinstance(x, int))
            elif lk in {"members", "known"} and isinstance(v, dict):
                out.update(int(x) for x in v.values() if isinstance(x, int))
            elif lk.startswith("unresolved") and isinstance(v, list):
                out.update(int(x) for x in v if isinstance(x, int))
            else:
                out.update(collect_body_ids(v, key=k))
    elif isinstance(value, list) and key.lower().startswith("unresolved"):
        out.update(int(x) for x in value if isinstance(x, int))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract official Janelia annotations for project anchors")
    ap.add_argument("annotations_feather", type=Path)
    ap.add_argument("--anchors", type=Path, default=Path("data/anchors.json"))
    ap.add_argument("--output", type=Path, default=Path("results/anchor_annotations.json"))
    args = ap.parse_args()

    anchor_data = json.loads(args.anchors.read_text(encoding="utf-8"))
    ids = sorted(collect_body_ids(anchor_data))
    if not ids:
        raise ValueError("no body IDs found in anchors file")

    table = feather.read_table(args.annotations_feather, memory_map=True)
    candidates = ["bodyId", "body_id", "body"]
    id_col = next((c for c in candidates if c in table.column_names), None)
    if id_col is None:
        raise ValueError(f"could not find body id column; schema={table.schema}")

    mask = pc.is_in(table[id_col], value_set=pa.array(ids, type=table[id_col].type))
    subset = table.filter(mask)
    rows = subset.to_pylist()
    rows.sort(key=lambda r: int(r[id_col]))
    found = {int(row[id_col]) for row in rows}

    result = {
        "source": args.annotations_feather.name,
        "id_column": id_col,
        "schema": [{"name": f.name, "type": str(f.type)} for f in table.schema],
        "requested_body_ids": ids,
        "matched_count": len(rows),
        "missing_body_ids": sorted(set(ids) - found),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("===MALECNS_ANCHOR_ANNOTATIONS===")
    print(json.dumps(result, indent=2, default=str))
    print("===END_MALECNS_ANCHOR_ANNOTATIONS===")


if __name__ == "__main__":
    main()
