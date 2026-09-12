#!/usr/bin/env python3
"""Create compact physical-channel summaries from generated MaleCNS I/O masks."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

import pyarrow.feather as feather


def norm(value: Any) -> str:
    if value is None:
        return "unknown"
    text = str(value).strip()
    return text if text else "unknown"


def summarize(path: str) -> dict[str, Any]:
    rows = feather.read_table(path).to_pylist()

    def counts(field: str) -> dict[str, int]:
        c = Counter(norm(row.get(field)) for row in rows)
        return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))

    combo = Counter(
        (
            norm(row.get("nerve")),
            norm(row.get("side")),
            norm(row.get("neuromere")),
            norm(row.get("class")),
            norm(row.get("subclass")),
        )
        for row in rows
    )
    return {
        "rows": len(rows),
        "unique_bodies": len({int(row["body_id"]) for row in rows}),
        "nerve_counts": counts("nerve"),
        "side_counts": counts("side"),
        "neuromere_counts": counts("neuromere"),
        "class_counts": counts("class"),
        "subclass_counts": counts("subclass"),
        "physical_combinations": [
            {
                "nerve": key[0],
                "side": key[1],
                "neuromere": key[2],
                "class": key[3],
                "subclass": key[4],
                "count": count,
            }
            for key, count in sorted(combo.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }


def compact(section: dict[str, Any]) -> dict[str, Any]:
    return {
        key: section[key]
        for key in (
            "rows",
            "unique_bodies",
            "nerve_counts",
            "side_counts",
            "neuromere_counts",
            "class_counts",
            "subclass_counts",
        )
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensory", required=True)
    ap.add_argument("--motor", required=True)
    ap.add_argument("--diagnostic", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--core-output")
    args = ap.parse_args()

    out = {
        "sensory": summarize(args.sensory),
        "motor": summarize(args.motor),
        "diagnostic": summarize(args.diagnostic),
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    core = {
        "sensory": compact(out["sensory"]),
        "motor": compact(out["motor"]),
        "diagnostic": {
            "rows": out["diagnostic"]["rows"],
            "unique_bodies": out["diagnostic"]["unique_bodies"],
            "side_counts": out["diagnostic"]["side_counts"],
            "neuromere_counts": out["diagnostic"]["neuromere_counts"],
        },
    }
    if args.core_output:
        core_path = Path(args.core_output)
        core_path.parent.mkdir(parents=True, exist_ok=True)
        core_path.write_text(json.dumps(core, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(core, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
