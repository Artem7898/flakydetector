"""Source-free CLI reports; 0=policy pass, 1=risk policy, 2=operational/incomplete."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from flakydetector.application import AnalyzeService
from flakydetector.classifier.catboost_model import FlakyClassifier, ModelUnavailable
from flakydetector.input import InputError, decode, directory_bundle, zip_bundle
from flakydetector.models.domain import FlakySeverity
from flakydetector.reporting.baseline import Baseline, compare, create_baseline, policy_exit
from flakydetector.reporting.sarif import to_sarif
from flakydetector.security.auth import SCOPES, Principal
from flakydetector.security.projection import project_response
from flakydetector.utils.config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--format", choices=["text", "json", "sarif"], default="text")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on", choices=["none", *FlakySeverity], default="high")
    parser.add_argument("--fail-on-critical", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--use-ml", action="store_true")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-revision")
    parser.add_argument("--new-only", action="store_true")
    parser.add_argument("--write-baseline", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--accepted-by")
    parser.add_argument("--include-source", action="store_true")
    parser.add_argument("--confirm-source", action="store_true")
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-annotations", action="store_true")
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="Analyze in a killable Linux child process",
    )
    args = parser.parse_args(argv)
    try:
        if args.include_source and (not args.confirm_source):
            raise ValueError("Source export requires --confirm-source")
        if args.include_source and args.format == "sarif":
            raise ValueError("SARIF is always source-free")
        settings = replace(
            Settings.from_env(), source_mode="redacted" if args.include_source else "disabled"
        )
        if args.model:
            settings = replace(settings, model_path=args.model)
        service = AnalyzeService(settings)
        if args.use_ml and settings.model_path and (not args.isolated):
            model = FlakyClassifier()
            try:
                model.load_model(settings.model_path)
                service.classifier = model
                service.model_version = model.manifest.model_version if model.manifest else None
            except ModelUnavailable:
                service.degraded_reason = "Configured model unavailable/incompatible"
        path = args.path.resolve()
        project_root = (
            args.project_root
            or (
                Path.cwd()
                if path.is_relative_to(Path.cwd())
                else path
                if path.is_dir()
                else path.parent
            )
        ).resolve()
        if not path.is_relative_to(project_root):
            raise ValueError("Analysis path must be inside --project-root")
        scope = path.relative_to(project_root).as_posix()
        diagnostics = ()
        if path.is_dir():
            bundle = directory_bundle(path, settings)
            prefix = path.relative_to(project_root)
            sources = {(prefix / k).as_posix(): v for k, v in bundle.sources.items()}
            diagnostics = bundle.diagnostics
        elif path.suffix == ".zip":
            with path.open("rb") as stream:
                bundle = zip_bundle(stream.read(settings.max_archive_bytes + 1), settings)
            sources = bundle.sources
            diagnostics = bundle.diagnostics
        else:
            with path.open("rb") as stream:
                code = decode(
                    stream.read(settings.max_file_bytes + 1), scope, settings.max_file_bytes
                )
            sources = {scope: code}
        if args.isolated:
            import asyncio

            from flakydetector.models.domain import AnalysisResponse
            from flakydetector.workers.supervisor import ProcessSupervisor, WorkerFailure

            try:
                response = AnalysisResponse.model_validate(
                    asyncio.run(
                        ProcessSupervisor(settings).run(
                            {
                                "operation": "analyze",
                                "sources": sources,
                                "diagnostics": [d.model_dump(mode="json") for d in diagnostics],
                                "use_ml": args.use_ml,
                            },
                        ),
                    ),
                )
            except WorkerFailure as exc:
                raise ValueError("Isolated analysis failed") from exc
        else:
            response = service.analyze(sources, diagnostics=diagnostics, use_ml=args.use_ml)
        absent = ()
        if args.baseline:
            if not args.baseline_revision:
                raise ValueError("--baseline-revision is required; trust the base, not PR content")
            if args.baseline.stat().st_size > 10000000:
                raise ValueError("Baseline too large")
            baseline = Baseline.model_validate_json(args.baseline.read_text())
            response, absent = compare(
                response, baseline, expected_revision=args.baseline_revision, scope=scope
            )
        elif args.new_only:
            raise ValueError("--new-only requires an explicitly trusted baseline")
        if args.write_baseline:
            if not args.revision or not args.accepted_by:
                raise ValueError("Baseline acceptance requires --revision and --accepted-by")
            baseline = create_baseline(
                response, revision=args.revision, scope=scope, accepted_by=args.accepted_by
            )
            args.write_baseline.parent.mkdir(parents=True, exist_ok=True)
            args.write_baseline.write_text(baseline.model_dump_json(indent=2) + "\n")
        projected = project_response(
            response,
            settings,
            Principal("cli", frozenset({"local"}), SCOPES),
            "local",
            include_source=args.include_source,
        )
        if args.format == "sarif":
            output = json.dumps(to_sarif(projected), indent=2, ensure_ascii=False)
        elif args.format == "json":
            output = projected.model_dump_json(indent=2)
        else:
            output = f"Status: {projected.status}; static candidates: {projected.test_candidates}; unique findings: {len(projected.findings)}\n"
            output += "\n".join(
                (
                    f"{f.location.file_path}:{f.location.line_start}: {f.rule_id} {f.severity} [{f.baseline_state}] {f.title}"
                    for f in projected.findings
                ),
            )
            output += "\nStatic risk is not observed runtime flakiness."
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        if args.summary:
            summary = f"## FlakyDetector\n\nAnalysis: **{projected.status}**. Static candidates: {projected.test_candidates}. Unique findings: {len(projected.findings)}.\n\n"
            for state in ("new", "worsened", "existing"):
                summary += (
                    f"- {state}: {sum(f.baseline_state == state for f in projected.findings)}\n"
                )
            summary += f"- resolved: {sum(f.baseline_state == 'resolved' for f in absent)}\n- inconclusive disappearances: {sum(f.baseline_state == 'inconclusive' for f in absent)}\n"
            summary += "\nSource code is not included. Static findings do not establish runtime flakiness or causation.\n"
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(summary)
        if args.github_annotations:
            for f in projected.findings[:50]:
                uri = (
                    f.location.file_path.replace("%", "%25").replace(",", "%2C").replace(":", "%3A")
                )
                print(
                    f"::warning file={uri},line={f.location.line_start},title={f.rule_id}::{f.title}. Static risk only.",
                    file=sys.stderr,
                )
        for d in response.diagnostics:
            print(f"{d.code}: analysis coverage requires review", file=sys.stderr)
        return policy_exit(
            response,
            fail_on="critical" if args.fail_on_critical else args.fail_on,
            new_only=args.new_only,
        )
    except (InputError, OSError, ValueError, ModelUnavailable) as exc:
        # No source values in ordinary CLI errors. Codes/constraints are described in docs.
        print(
            f"Analysis/policy input rejected ({type(exc).__name__}); check paths, baseline and options.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
