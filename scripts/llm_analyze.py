"""Explicit, resumable advisory generation; source is sent only to the chosen endpoint."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlparse

from flakydetector.dataset.records import DatasetRecord
from flakydetector.llm import analyze_dataset, openai_completion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-url", default=os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    )
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "qwen2.5-coder:7b"))
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow sending source/tracebacks to a non-loopback endpoint",
    )
    args = parser.parse_args()
    if (
        urlparse(args.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}
        and not args.allow_remote
    ):
        parser.error("Remote source transmission requires --allow-remote")
    records = [
        DatasetRecord.model_validate_json(line)
        for line in args.input.read_bytes().splitlines()
        if line.strip()
    ]
    ok, errors = analyze_dataset(
        records,
        args.output,
        model=args.model,
        complete=openai_completion(args.base_url, os.getenv("OPENAI_API_KEY") or "local-no-auth"),
    )
    print(f"completed={ok} errors={errors}; explanations are unverified hypotheses")
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
