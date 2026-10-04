"""Repository-held-out evaluation; no synthetic-label claims or random clone leakage."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol, cast

from flakydetector.application import AnalyzeService
from flakydetector.classifier.feature_extractor import FeatureExtractor
from flakydetector.dataset.records import DatasetRecord


@dataclass(frozen=True, slots=True, kw_only=True)
class Sample:
    repo: str
    identity: str
    clone_hash: str
    label: int
    features: tuple[float, ...]
    rule_score: float
    root_causes: tuple[str, ...] = ()
    observation: str = "inconclusive"


class NormalizeNames(ast.NodeTransformer):
    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = "function"
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.name = "function"
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> ast.AST:
        node.id = "variable"
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        return ast.copy_location(ast.Constant(value=f"<{type(node.value).__name__}>"), node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.name = "class"
        return self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = "argument"
        return node


def prepare_samples(records: Sequence[DatasetRecord]) -> list[Sample]:
    result: list[Sample] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        if (
            record.provenance_version != 3
            or not record.reviewed
            or not record.review_notes
            or (record.label == 1 and not record.root_causes)
            or record.label is None
            or record.source_code is None
        ):
            raise ValueError(
                "Every training record requires v3 provenance, a reviewed label and matching source snapshot"
            )
        identity = (record.repo, record.nodeid, record.source_hash, record.environment_hash)
        if identity in seen:
            raise ValueError("Duplicate execution identity in dataset")
        seen.add(identity)
        path, name = record.nodeid.split("::", 1)
        name = name.split("[")[0]
        response = AnalyzeService().analyze({**record.context_sources, path: record.source_code})
        if response.status != "ok":
            raise ValueError(
                f"Incomplete static evidence for {record.nodeid}; supply resolved source context"
            )
        test = next(
            (
                r
                for r in response.results
                if r.test_name == name and r.file_path == path and r.result_kind == "test_candidate"
            ),
            None,
        )
        if test is None or test.verdict == "inconclusive":
            raise ValueError(f"Test could not be resolved: {record.nodeid}")
        vector = FeatureExtractor().extract_from_patterns(
            name, path, test.patterns, test.log_anomalies, test.fixtures
        )
        tree = ast.parse(record.source_code)
        body = tree.body
        target: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        for component in name.split("::"):
            node = next(
                (
                    n
                    for n in body
                    if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == component
                ),
                None,
            )
            if node is None:
                raise ValueError(f"Missing clone-analysis target: {record.nodeid}")
            body = node.body
            target = node if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
        if target is None:
            raise ValueError(f"Clone-analysis target is not a function: {record.nodeid}")
        normalized = NormalizeNames().visit(target)
        clone_hash = hashlib.sha256(
            ast.dump(normalized, include_attributes=False).encode()
        ).hexdigest()
        result.append(
            Sample(
                repo=record.repo,
                identity="::".join(identity),
                clone_hash=clone_hash,
                label=record.label,
                features=vector.features,
                rule_score=float(
                    any(
                        p.severity.value in {"high", "critical"} and p.confidence >= 0.5
                        for p in test.patterns
                    )
                ),
                root_causes=record.root_causes,
                observation=record.observation,
            )
        )
    return result


def split_by_repo(
    samples: Sequence[Sample], validation_repos: set[str], test_repos: set[str]
) -> tuple[list[Sample], list[Sample], list[Sample]]:
    if not validation_repos or not test_repos or validation_repos & test_repos:
        raise ValueError("Validation and test repository sets must be nonempty and disjoint")
    splits: tuple[list[Sample], list[Sample], list[Sample]] = ([], [], [])
    for sample in samples:
        index = 2 if sample.repo in test_repos else (1 if sample.repo in validation_repos else 0)
        splits[index].append(sample)
    for split in splits:
        if {s.label for s in split} != {0, 1}:
            raise ValueError("Each split must contain both outcome classes")
    clone_sets = [{s.clone_hash for s in split} for split in splits]
    if any(clone_sets[a] & clone_sets[b] for a, b in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("AST/template clone leakage across repository splits")
    return splits


def metrics(
    labels: Sequence[int], scores: Sequence[float], *, threshold: float = 0.7
) -> dict[str, float]:
    if set(labels) != {0, 1} or len(labels) != len(scores):
        raise ValueError("Metrics require both classes and aligned predictions")
    module = import_module("sklearn.metrics")
    roc_auc = cast(Callable[[Sequence[int], Sequence[float]], float], module.roc_auc_score)
    average_precision = cast(
        Callable[[Sequence[int], Sequence[float]], float], module.average_precision_score
    )
    tp = sum(y == 1 and p >= threshold for y, p in zip(labels, scores, strict=True))
    fp = sum(y == 0 and p >= threshold for y, p in zip(labels, scores, strict=True))
    fn = sum(y == 1 and p < threshold for y, p in zip(labels, scores, strict=True))
    tn = sum(y == 0 and p < threshold for y, p in zip(labels, scores, strict=True))
    return {
        "roc_auc": float(roc_auc(labels, scores)),
        "average_precision": float(average_precision(labels, scores)),
        "precision": tp / max(1, tp + fp),
        "recall": tp / max(1, tp + fn),
        "false_positive_rate": fp / max(1, fp + tn),
        "brier_score_uncalibrated": sum((p - y) ** 2 for y, p in zip(labels, scores, strict=True))
        / len(labels),
        "threshold": threshold,
        "n": float(len(labels)),
    }


class TabularBaseline(Protocol):
    def fit(self, X: list[tuple[float, ...]], y: list[int]) -> object: ...
    def predict_proba(self, X: list[tuple[float, ...]]) -> Sequence[Sequence[float]]: ...


def tabular_scores(train: Sequence[Sample], test: Sequence[Sample]) -> list[float]:
    factory = cast(
        Callable[..., TabularBaseline], import_module("sklearn.tree").DecisionTreeClassifier
    )
    baseline = factory(max_depth=3, min_samples_leaf=2, random_state=42)
    baseline.fit([s.features for s in train], [s.label for s in train])
    return [float(row[1]) for row in baseline.predict_proba([s.features for s in test])]


def recall_by_cause(
    samples: Sequence[Sample], scores: Sequence[float], threshold: float = 0.7
) -> dict[str, float]:
    causes = sorted({cause for s in samples if s.label for cause in s.root_causes})
    return {
        cause: sum(
            p >= threshold
            for s, p in zip(samples, scores, strict=True)
            if s.label and cause in s.root_causes
        )
        / sum(s.label == 1 and cause in s.root_causes for s in samples)
        for cause in causes
    }


def reliability_bins(labels: Sequence[int], scores: Sequence[float]) -> list[dict[str, float]]:
    """Descriptive reliability only; this does not fit or claim a calibrator."""
    bins: list[dict[str, float]] = []
    for index in range(10):
        pairs = [
            (y, p) for y, p in zip(labels, scores, strict=True) if min(9, int(p * 10)) == index
        ]
        if pairs:
            bins.append(
                {
                    "lower": index / 10,
                    "upper": (index + 1) / 10,
                    "n": float(len(pairs)),
                    "mean_score": sum(p for _, p in pairs) / len(pairs),
                    "observed_fraction": sum(y for y, _ in pairs) / len(pairs),
                }
            )
    return bins


def stable_suite_false_positives(
    samples: Sequence[Sample], scores: Sequence[float], threshold: float = 0.7
) -> dict[str, int | float | None]:
    selected = [p for s, p in zip(samples, scores, strict=True) if s.observation == "observed_pass"]
    count = sum(p >= threshold for p in selected)
    return {
        "n": len(selected),
        "false_positives": count,
        "rate": count / len(selected) if selected else None,
    }
