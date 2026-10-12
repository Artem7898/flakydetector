"""Validate a generated report against the OFFICIAL SARIF schema, not an invented subset.

Run inside a validation environment with jsonschema. Network failures fail the gate.
--schema permits a previously downloaded and reviewed official schema for offline CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

import jsonschema

from flakydetector.application import AnalyzeService
from flakydetector.reporting.sarif import SCHEMA_URI, to_sarif


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path)
    args = parser.parse_args()
    if args.schema:
        raw = args.schema.read_bytes()
    else:
        with urllib.request.urlopen(SCHEMA_URI, timeout=30) as response:
            raw = response.read(500000)
    schema = json.loads(raw)
    if schema.get("title") != "Static Analysis Results Format (SARIF) Version 2.1.0 JSON Schema":
        raise SystemExit("Unexpected schema identity")
    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    validator = validator_class(schema, format_checker=jsonschema.FormatChecker())
    cases = {
        "tests/test_unicode_ñ.py": 'import requests\ndef test_payment():\n    requests.get("https://example.invalid")\n',
        "tests/test_clean.py": "def test_ok():\n    assert 1 == 1\n",
    }
    for sources in (
        cases,
        {"tests/test_bad.py": "def bad(:"},
        {"tests/test_ok.py": "def test_ok(): pass"},
    ):
        validator.validate(to_sarif(AnalyzeService().analyze(sources)))
    print(
        json.dumps(
            {
                "official_schema_sha256": hashlib.sha256(raw).hexdigest(),
                "cases": 3,
                "status": "passed",
            },
        ),
    )


if __name__ == "__main__":
    main()
