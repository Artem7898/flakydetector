"""Export execution evidence; legacy ledger rows remain inconclusive without v3 provenance."""

from __future__ import annotations

import argparse
from pathlib import Path

from flakydetector.dataset.records import export_records, write_dataset
from flakydetector.dataset.records import extract_function_source as extract_function_source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-runs", type=int, default=5)
    args = parser.parse_args()
    write_dataset(export_records(args.db, args.source_root, min_runs=args.min_runs), args.output)


if __name__ == "__main__":
    main()
