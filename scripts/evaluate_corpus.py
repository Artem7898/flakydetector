"""Evaluate reviewed static corpus or explicitly labeled synthetic regressions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flakydetector.intelligence.corpus import CorpusCase, evaluate_corpus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic-regression", action="store_true")
    args = parser.parse_args()
    if args.input.stat().st_size > 20000000:
        parser.error("Corpus file exceeds 20 MB")
    cases = [
        CorpusCase.model_validate_json(line)
        for line in args.input.read_text().splitlines()
        if line.strip()
    ]
    report = evaluate_corpus(cases, independent=not args.synthetic_regression)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
