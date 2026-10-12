"""Explicit claim-level advisory triage; loopback provider by default, never an executor."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from flakydetector.intelligence.triage import propose_triage
from flakydetector.llm import openai_completion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="JSON object: evidence ID -> already-authorized text",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()
    url = urlparse(args.base_url)
    if url.username or url.password or url.scheme not in {"http", "https"}:
        parser.error("Endpoint must be HTTP(S), with no embedded credentials")
    if (url.hostname not in {"127.0.0.1", "localhost", "::1"}) and (
        not args.allow_remote or url.scheme != "https"
    ):
        parser.error("Remote source transmission requires --allow-remote and HTTPS")
    if args.evidence.stat().st_size > 250000:
        parser.error("Evidence input exceeds 250 KB")
    evidence = json.loads(args.evidence.read_text())
    if not isinstance(evidence, dict) or not all(
        (isinstance(k, str) and isinstance(v, str) for k, v in evidence.items())
    ):
        parser.error("Evidence must map IDs to text")
    try:
        result = propose_triage(
            evidence,
            model=args.model,
            complete=openai_completion(
                args.base_url, os.getenv("OPENAI_API_KEY") or "local-no-auth"
            ),
        )
    except Exception as exc:
        # Provider exceptions can contain bodies/keys; never echo the exception text.
        raise SystemExit(f"Advisory rejected ({type(exc).__name__}); no verdict changed") from None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
