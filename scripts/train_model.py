"""Explicit reviewed-data training. Running without a dataset never trains a model."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from flakydetector.classifier.catboost_model import FlakyClassifier
from flakydetector.classifier.schema import FEATURE_SCHEMA_VERSION, SCHEMA_HASH
from flakydetector.dataset.benchmark import (
    metrics,
    prepare_samples,
    recall_by_cause,
    reliability_bins,
    split_by_repo,
    stable_suite_false_positives,
    tabular_scores,
)
from flakydetector.dataset.records import DatasetRecord


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--validation-repo", action="append", required=True)
    parser.add_argument("--test-repo", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--min-precision", type=float, default=0.9)
    parser.add_argument("--min-recall", type=float, default=0.5)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    records = [DatasetRecord.model_validate_json(line) for line in raw.splitlines() if line.strip()]
    train, validation, test = split_by_repo(
        prepare_samples(records), set(args.validation_repo), set(args.test_repo)
    )
    classifier = FlakyClassifier()
    classifier.train(
        [s.features for s in train],
        [s.label for s in train],
        [s.features for s in validation],
        [s.label for s in validation],
    )
    labels = [s.label for s in test]
    predictions = [classifier.predict_single(s.features)[1] for s in test]
    ml_metrics = metrics(labels, predictions)
    report = {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "schema_hash": SCHEMA_HASH,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "seed": 42,
        "split_identities": {
            n: [s.identity for s in split]
            for n, split in [("train", train), ("validation", validation), ("test", test)]
        },
        "model": ml_metrics,
        "rule_baseline": metrics(labels, [s.rule_score for s in test]),
        "constant_baseline": metrics(
            labels, [sum(s.label for s in train) / len(train)] * len(test)
        ),
        "tabular_baseline": metrics(labels, tabular_scores(train, test)),
        "recall_by_cause": recall_by_cause(test, predictions),
        "analysis_coverage": {
            "accepted": len(records),
            "submitted": len(records),
            "policy": "Reject entire benchmark if any record cannot be analyzed",
        },
        "reliability_bins_uncalibrated": reliability_bins(labels, predictions),
        "stable_suite": stable_suite_false_positives(test, predictions),
        "calibrated": False,
        "uncertainty": "No confidence intervals inferred from a small holdout; use multiple independent repository holdouts.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if ml_metrics["precision"] < args.min_precision or ml_metrics["recall"] < args.min_recall:
        raise SystemExit("Quality gate failed: report saved, inference model not published")
    classifier.save_model(
        args.output, dataset_sha256=hashlib.sha256(raw).hexdigest(), evaluation="evaluated"
    )


if __name__ == "__main__":
    main()
