"""CLI adapter. Exit 0=policy passed, 1=risk threshold, 2=incomplete/error."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from flakydetector.application import AnalyzeService
from flakydetector.classifier.catboost_model import FlakyClassifier, ModelUnavailable
from flakydetector.input import InputError, decode, directory_bundle, zip_bundle
from flakydetector.models.domain import SEVERITY_RANK, FlakySeverity
from flakydetector.utils.config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explainable test-risk analysis; no source execution"
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--fail-on", choices=["none", *FlakySeverity], default="high")
    parser.add_argument("--fail-on-critical", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--use-ml", action="store_true")
    parser.add_argument("--model", type=Path)
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.model is not None:
        settings = replace(settings, model_path=args.model)
    service = AnalyzeService(settings)
    if args.use_ml and settings.model_path:
        model = FlakyClassifier()
        try:
            model.load_model(settings.model_path)
            service.classifier = model
            service.model_version = model.manifest.model_version if model.manifest else None
        except ModelUnavailable as exc:
            service.degraded_reason = str(exc)
    try:
        if args.path.is_dir():
            bundle = directory_bundle(args.path, settings)
            response = service.analyze(
                bundle.sources, diagnostics=bundle.diagnostics, use_ml=args.use_ml
            )
        elif args.path.suffix == ".zip":
            with args.path.open("rb") as stream:
                bundle = zip_bundle(stream.read(settings.max_archive_bytes + 1), settings)
            response = service.analyze(
                bundle.sources, diagnostics=bundle.diagnostics, use_ml=args.use_ml
            )
        else:
            with args.path.open("rb") as stream:
                source = decode(
                    stream.read(settings.max_file_bytes + 1),
                    args.path.name,
                    settings.max_file_bytes,
                )
            response = service.analyze({args.path.name: source}, use_ml=args.use_ml)
    except (InputError, OSError, ModelUnavailable) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(response.model_dump_json(indent=2))
    else:
        print(
            f"Status: {response.status}; files: {response.total_files_analyzed}; findings: {response.total_patterns_found}"
        )
        for result in response.results:
            print(
                f"{result.file_path}::{result.test_name}: {result.verdict} (risk score: {result.risk_score})"
            )
            for pattern in result.patterns:
                print(
                    f"  {pattern.location.location_string}: {pattern.severity} {pattern.pattern_type}"
                )
        for diagnostic in response.diagnostics:
            print(f"  {diagnostic.code}: {diagnostic.message}", file=sys.stderr)
        if response.degraded_reason:
            print(f"  ML unavailable: {response.degraded_reason}", file=sys.stderr)
    if response.status != "ok":
        return 2
    threshold = "critical" if args.fail_on_critical else args.fail_on
    if threshold != "none":
        rank = SEVERITY_RANK[FlakySeverity(threshold)]
        if any(
            SEVERITY_RANK[p.severity] >= rank and p.confidence >= 0.5
            for r in response.results
            for p in (*r.patterns, *r.log_anomalies)
        ):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
