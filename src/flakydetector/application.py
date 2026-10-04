"""One application policy for every transport; deterministic risk is not probability."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Protocol

from flakydetector.analyzer.ast_analyzer import ASTAnalyzer
from flakydetector.analyzer.fixture_graph import resolve_fixtures
from flakydetector.analyzer.log_analyzer import LogAnalyzer
from flakydetector.classifier.feature_extractor import FeatureExtractor
from flakydetector.models.domain import (
    AnalysisDiagnostic,
    AnalysisResponse,
    ASTPattern,
    CodeLocation,
    FixtureInfo,
    FlakyCategory,
    FlakySeverity,
    SourceSnapshot,
    TestAnalysisResult,
    TestDefinition,
)
from flakydetector.utils.config import Settings


def _belongs_to_test(nodeid: object, *, file_path: str, test: TestDefinition) -> bool:
    """Match an attributed log without closing over the analysis loop's variables."""
    if not isinstance(nodeid, str) or "::" not in nodeid:
        return False
    log_path, qualified_name = nodeid.split("::", 1)
    normalized = str(PurePosixPath(log_path.replace("\\", "/")))
    return (
        normalized == str(PurePosixPath(file_path.replace("\\", "/")))
        and qualified_name.split("[", 1)[0] == test.qualified_name
        and test.name != "<module>"
    )


class Classifier(Protocol):
    def predict_single(self, features: Sequence[float]) -> tuple[bool, float]: ...


class AnalyzeService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        classifier: Classifier | None = None,
        model_version: str | None = None,
        degraded_reason: str | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.analyzer = ASTAnalyzer(self.settings.max_file_bytes, self.settings.max_ast_nodes)
        self.classifier = classifier
        self.model_version = model_version
        self.degraded_reason = degraded_reason

    def analyze(
        self,
        sources: Mapping[str, str],
        *,
        log_content: str = "",
        use_ml: bool = False,
        diagnostics: Sequence[AnalysisDiagnostic] = (),
    ) -> AnalysisResponse:
        parsed = {
            name: self.analyzer.analyze_source(code, name) for name, code in sorted(sources.items())
        }
        targets = {
            name: item for name, item in parsed.items() if PurePosixPath(name).name != "conftest.py"
        }
        all_diagnostics = [*diagnostics, *(d for s in parsed.values() for d in s.diagnostics)]
        logs = LogAnalyzer().analyze_log(log_content)
        results: list[TestAnalysisResult] = []
        assigned_logs: set[int] = set()
        for name, source in targets.items():
            definitions: list[FixtureInfo] = []
            for ancestor in reversed(PurePosixPath(name).parents):
                config = parsed.get(str(ancestor / "conftest.py"))
                if config:
                    definitions.extend(config.fixtures)
            definitions.extend(source.fixtures)
            tests = source.tests or (TestDefinition(name="<module>", line=1),)
            assigned: set[str] = set()
            for test in tests:
                selection = resolve_fixtures(test, definitions, name)
                fixture_functions = {
                    (f.file_path, f.function_name, f.class_name) for f in selection.fixtures
                }
                selected = [
                    p
                    for p in source.patterns
                    if test.name == "<module>"
                    or (
                        p.location.function_name is not None
                        and p.location.function_name.split(".")[0] == test.name
                        and p.location.class_name == test.class_name
                    )
                ]
                for definition_source in parsed.values():
                    for pattern in definition_source.patterns:
                        if (
                            pattern.location.file_path,
                            pattern.location.function_name,
                            pattern.location.class_name,
                        ) in fixture_functions and pattern not in selected:
                            selected.append(pattern)
                assigned.update(
                    p.model_dump_json() for p in selected if p.location.file_path == name
                )
                for f in selection.fixtures:
                    if f.scope in {"module", "session", "class"} and f.returns_mutable_literal:
                        selected.append(
                            ASTPattern(
                                pattern_type="shared_fixture_state",
                                category=FlakyCategory.GLOBAL_STATE,
                                severity=FlakySeverity.MEDIUM,
                                description="A used shared fixture exposes a mutable value; mutation may leak between tests",
                                confidence=0.7,
                                code_snippet="\n".join(
                                    sources.get(f.file_path, "").splitlines()[
                                        max(0, f.line - 2) : f.line + 5
                                    ]
                                ),
                                location=CodeLocation(
                                    file_path=f.file_path,
                                    line_start=max(1, f.line),
                                    function_name=f.function_name,
                                    class_name=f.class_name,
                                ),
                                fix_suggestion="Use function scope or explicitly isolate/restore mutations",
                            )
                        )
                # Only a full, matching nodeid belongs to this static definition.
                # Do not guess from basenames, bare function names, proximity or file count.
                related_logs = [
                    log
                    for log in logs
                    if _belongs_to_test(log.metadata.get("test_name"), file_path=name, test=test)
                ]
                assigned_logs.update(id(log) for log in related_logs)
                ds = (*source.diagnostics, *selection.diagnostics)
                all_diagnostics.extend(selection.diagnostics)
                weighted = [
                    p.confidence
                    * {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1}[p.severity.value]
                    for p in selected
                ]
                weighted.extend(log.confidence * 0.75 for log in related_logs)
                score = max(weighted, default=0.0) if source.ok else None
                backend, model_score = "rules", None
                ml_risk = False
                if use_ml and self.classifier is not None and source.ok:
                    features = FeatureExtractor().extract_from_patterns(
                        test.qualified_name, name, selected, related_logs, selection.fixtures
                    )
                    ml_risk, model_score = self.classifier.predict_single(features.features)
                    backend = "ml"
                verdict = (
                    "inconclusive"
                    if ds
                    else (
                        "risk_detected"
                        if any(p.confidence >= 0.5 for p in selected) or related_logs or ml_risk
                        else "no_known_risk"
                    )
                )
                results.append(
                    TestAnalysisResult(
                        result_kind="module" if test.name == "<module>" else "test_candidate",
                        test_name=test.qualified_name,
                        file_path=name,
                        verdict=verdict,
                        risk_score=score,
                        patterns=tuple(selected),
                        fixtures=selection.fixtures,
                        log_anomalies=tuple(related_logs),
                        diagnostics=ds,
                        backend_used=backend,
                        model_score=model_score,
                        recommendations=tuple(
                            dict.fromkeys(p.fix_suggestion for p in selected if p.fix_suggestion)
                        ),
                    )
                )
            unassigned = tuple(p for p in source.patterns if p.model_dump_json() not in assigned)
            if unassigned and source.tests:
                results.append(
                    TestAnalysisResult(
                        result_kind="helper",
                        test_name="<unattributed helpers>",
                        file_path=name,
                        verdict="inconclusive",
                        patterns=unassigned,
                        diagnostics=(
                            AnalysisDiagnostic(
                                code="unattributed_helper",
                                message="Helper findings require call-graph or runtime evidence",
                                file_path=name,
                                level="warning",
                            ),
                        ),
                    )
                )
        unassigned_logs = tuple(log for log in logs if id(log) not in assigned_logs)
        if unassigned_logs:
            diagnostic = AnalysisDiagnostic(
                code="unattributed_log",
                message="Log evidence could not be attributed to a selected test",
                level="warning",
            )
            results.append(
                TestAnalysisResult(
                    result_kind="unattributed_log",
                    test_name="<unattributed logs>",
                    file_path="<logs>",
                    verdict="inconclusive",
                    log_anomalies=unassigned_logs,
                    diagnostics=(diagnostic,),
                )
            )
        for result in results:
            all_diagnostics.extend(d for d in result.diagnostics if d not in all_diagnostics)
        no_tests = not any(source.tests for source in targets.values())
        if no_tests:
            all_diagnostics.append(
                AnalysisDiagnostic(
                    code="no_tests",
                    message="No statically discoverable test functions; analysis coverage is empty",
                )
            )
            results = [
                r.model_copy(update={"verdict": "inconclusive", "risk_score": None})
                for r in results
            ]
        if not targets:
            all_diagnostics.append(
                AnalysisDiagnostic(code="empty_scan", message="No test files were selected")
            )
        errors = any(d.level == "error" for d in all_diagnostics)
        valid_files = sum(source.ok for source in targets.values())
        degraded = (
            (self.degraded_reason or "No compatible model configured")
            if use_ml and self.classifier is None
            else None
        )
        status = (
            "error"
            if no_tests or not targets or (errors and not valid_files)
            else ("partial" if all_diagnostics or degraded else "ok")
        )
        evidence_links = sum(len(r.patterns) + len(r.log_anomalies) for r in results)
        unique_risks = {
            (p.location.file_path, p.location.line_start, p.pattern_type)
            for r in results
            for p in r.patterns
            if p.confidence >= 0.5
        }
        return AnalysisResponse(
            status=status,
            request_fingerprint=hashlib.sha256(
                json.dumps(
                    {
                        "sources": dict(sorted(sources.items())),
                        "log": log_content,
                        "use_ml": use_ml,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            source_snapshots=tuple(
                SourceSnapshot(
                    file_path=name, content=code, sha256=hashlib.sha256(code.encode()).hexdigest()
                )
                for name, code in sorted(sources.items())
            ),
            total_files_analyzed=valid_files,
            total_patterns_found=evidence_links,
            files_selected=len(targets),
            files_parsed=valid_files,
            files_rejected=len(targets) - valid_files,
            context_files_selected=len(parsed) - len(targets),
            test_candidates=sum(len(source.tests) for source in targets.values()),
            unique_risk_locations=len(unique_risks),
            tests_with_risk=sum(
                r.result_kind == "test_candidate"
                and (any(p.confidence >= 0.5 for p in r.patterns) or bool(r.log_anomalies))
                for r in results
            ),
            evidence_links=evidence_links,
            diagnostic_groups=sum(r.result_kind != "test_candidate" for r in results),
            results=tuple(results),
            diagnostics=tuple(all_diagnostics),
            model_version=self.model_version if use_ml else None,
            degraded_reason=degraded,
        )
