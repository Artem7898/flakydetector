"""Publish a new index only after all validated explanations are indexed."""

from __future__ import annotations

import argparse
from pathlib import Path

from flakydetector.llm import AdvisoryRecord
from flakydetector.rag import RagIndex


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = [
        AdvisoryRecord.model_validate_json(line)
        for line in args.input.read_bytes().splitlines()
        if line.strip()
    ]
    print(RagIndex(args.output).rebuild(records).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
