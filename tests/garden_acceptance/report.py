"""Print the machine-readable §7.8.13 audit matrix as a compact table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


MATRIX = Path(__file__).with_name("gate_matrix.json")


def load_matrix() -> dict:
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit canonical JSON")
    args = parser.parse_args()
    matrix = load_matrix()
    if args.json:
        print(json.dumps(matrix, sort_keys=True, separators=(",", ":")))
        return
    print("Gate  Status   Name")
    for row in matrix["gates"]:
        print(f"{row['gate']:>4}  {row['status']:<7}  {row['name']}")
        if row["blocker"]:
            print(f"      blocker: {row['blocker']}")


if __name__ == "__main__":
    main()
