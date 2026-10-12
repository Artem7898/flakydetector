"""Static change impact explains scope; it never authorizes skipping runtime tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flakydetector.input import directory_bundle
from flakydetector.intelligence.impact import impact_report
from flakydetector.utils.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--changed", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = directory_bundle(args.root, Settings())
    report = impact_report(bundle.sources, args.changed)
    if bundle.diagnostics:
        report["full_scan_recommended"] = True
        report["analysis_status"] = "partial"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
