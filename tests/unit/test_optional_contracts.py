from __future__ import annotations

import hashlib
import json

import pytest

from flakydetector.ci_integration.trap_shared_state import SharedStateTrap
from flakydetector.classifier.catboost_model import FlakyClassifier, ModelManifest, ModelUnavailable
from flakydetector.classifier.schema import FEATURE_NAMES
from flakydetector.dataset.benchmark import Sample, metrics, prepare_samples, split_by_repo
from flakydetector.dataset.records import DatasetRecord
from flakydetector.llm import analyze_dataset, analyze_record, build_prompt
from flakydetector.rag import RagIndex, RagUnavailable


def record(**overrides):
    return DatasetRecord(
        provenance_version=3,
        repo="example/repo",
        nodeid="test_a.py::test_a",
        source_hash="source",
        environment_hash="env",
        passed=9,
        failed=1,
        ignored=2,
        runs_total=10,
        observation="observed_flaky",
        label=1,
        source_code="def test_a(): pass",
        **overrides,
    )


def completion(**kwargs):
    assert kwargs["model"] == "test-model"
    return json.dumps(
        {
            "root_cause_hypothesis": "Needs controlled repeated runs",
            "explanation": "Source alone is insufficient",
            "fix_strategy": "Inspect execution evidence",
            "evidence_ids": ["source"],
            "fixed_code": "def test_a(): pass",
        }
    )


def test_failure_count_prompt_and_stable_traceback_order():
    prompt, ids = build_prompt(record(sample_tracebacks=("second", "first", "second")))
    payload = json.loads(prompt)
    assert payload["observations"]["failed"] == 1
    assert payload["observations"]["comparable_attempts"] == 10
    assert payload["evidence"]["traceback:0"] == "second"
    assert ids == {"source", "traceback:0", "traceback:1"}


def test_llm_validates_evidence_and_does_not_execute_code(tmp_path):
    result = analyze_record(record(), model="test-model", complete=completion)
    assert result.status == "ok"

    def invalid(**_):
        return completion(model="test-model").replace('"source"', '"invented"')

    assert analyze_record(record(), model="test-model", complete=invalid).status == "error"

    def syntax(**_):
        return completion(model="test-model").replace("def test_a(): pass", "def broken(:")

    assert analyze_record(record(), model="test-model", complete=syntax).status == "error"
    output = tmp_path / "advice.jsonl"
    assert analyze_dataset([record()], output, model="test-model", complete=completion) == (1, 0)
    assert analyze_dataset([record()], output, model="test-model", complete=completion) == (0, 0)
    assert len(output.read_text().splitlines()) == 1


def test_llm_fixed_code_is_never_executed(tmp_path):
    marker = tmp_path / "unexpected_execution.txt"

    def proposed_fix(**kwargs):
        payload = json.loads(completion(**kwargs))
        payload["fixed_code"] = (
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        )
        return json.dumps(payload)

    result = analyze_record(
        record(),
        model="test-model",
        complete=proposed_fix,
    )

    # The code is syntactically valid: the failure of the parser should not
    # mask erroneous execution of the model result.
    assert result.status == "ok"
    assert not marker.exists()


def test_llm_provider_error_visible_without_response_secrets():
    def broken(**_):
        raise RuntimeError("private response content")

    result = analyze_record(record(), model="test-model", complete=broken)
    assert result.status == "error" and result.error == "RuntimeError"
    assert "private" not in result.model_dump_json()


class FakeCollection:
    def __init__(self):
        self.data = {}
        self.fail = False

    def add(self, *, ids, documents, metadatas):
        if self.fail:
            raise RuntimeError("index write failed")
        self.data[ids[0]] = metadatas[0]

    def count(self):
        return len(self.data)

    def query(self, **_):
        return {
            "ids": [list(self.data)],
            "metadatas": [list(self.data.values())],
            "distances": [[0.25] * len(self.data)],
        }


class FakeClient:
    def __init__(self):
        self.collections = {}
        self.fail_next = False

    def create_collection(self, name, **kwargs):
        assert kwargs["configuration"]["hnsw"]["space"] == "cosine"
        collection = FakeCollection()
        collection.fail = self.fail_next
        self.collections[name] = collection
        return collection

    def get_collection(self, name, **_):
        return self.collections[name]


def test_rag_atomic_switch_and_real_metadata(tmp_path):
    client = FakeClient()
    index = RagIndex(tmp_path, client=client, version="test")
    advisory = analyze_record(record(), model="test-model", complete=completion)
    manifest = index.rebuild([advisory])
    hit = index.search("why")["results"][0]
    assert hit["explanation"] == advisory.analysis.explanation
    assert hit["distance"] == 0.25 and "similarity_score" not in hit
    client.fail_next = True
    with pytest.raises(RagUnavailable):
        index.rebuild([advisory])
    assert json.loads((tmp_path / "active.json").read_text())["collection"] == manifest.collection
    assert index.search("why")["results"]
    with pytest.raises(RagUnavailable):
        index.rebuild([])


def test_shared_state_trap_mapping_delete_reset():
    target = {"a": 1}
    trap = SharedStateTrap(target)
    trap["b"] = 2
    assert target == dict(trap) == {"a": 1, "b": 2}
    del trap["a"]
    assert "a" not in target
    assert [m.operation for m in trap.get_mutations()] == ["set", "delete"]
    trap.reset()
    assert target == {"a": 1} and not trap.has_mutations()


def test_model_roundtrip_is_explicit_demo_not_production(tmp_path):
    model = FlakyClassifier(iterations=3, depth=2)
    positive = [1.0] + [0.0] * (len(FEATURE_NAMES) - 1)
    negative = [0.0] * len(FEATURE_NAMES)
    model.train([negative, positive] * 3, [0, 1] * 3, [negative, positive], [0, 1])
    path = tmp_path / "demo.cbm"
    model.save_model(path, dataset_sha256="unit-test-fixture")
    reloaded = FlakyClassifier()
    with pytest.raises(ModelUnavailable, match="Demonstration"):
        reloaded.load_model(path)
    reloaded.load_model(path, allow_demo=True)
    assert reloaded.predict_single(positive) == model.predict_single(positive)
    assert tuple(reloaded.get_feature_importance()) == FEATURE_NAMES
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(ModelUnavailable, match="checksum"):
        FlakyClassifier().load_model(path, allow_demo=True)


@pytest.mark.parametrize("old_schema", ["1.0.0", "2.0.0"])
def test_old_schema_and_missing_models_rejected(tmp_path, old_schema):
    with pytest.raises(ModelUnavailable):
        FlakyClassifier().load_model(tmp_path / "missing")
    path = tmp_path / "model.cbm"
    path.write_bytes(b"not a model")
    manifest = ModelManifest(
        schema_version=old_schema,
        artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        dataset_sha256="test",
        evaluation="evaluated",
    )
    path.with_suffix(".cbm.json").write_text(manifest.model_dump_json())
    with pytest.raises(ModelUnavailable, match="schema"):
        FlakyClassifier().load_model(path)


def test_monoclass_training_is_blocked():
    model = FlakyClassifier()
    with pytest.raises(ValueError, match="both classes"):
        model.train([[0.0] * 42, [1.0] * 42], [0, 1], [[0.0] * 42], [0])


def samples():
    return [
        Sample(
            repo=repo,
            identity=f"{repo}{label}",
            clone_hash=f"{repo}{label}",
            label=label,
            features=(float(label),) * 42,
            rule_score=float(label),
        )
        for repo in ["train", "validation", "test"]
        for label in [0, 1]
    ]


def test_repo_split_and_clone_leakage():
    items = samples()
    train, val, test = split_by_repo(items, {"validation"}, {"test"})
    assert {s.repo for s in train} == {"train"}
    assert {s.repo for s in val} == {"validation"}
    assert {s.repo for s in test} == {"test"}
    items[-1] = Sample(
        repo="test",
        identity="clone",
        clone_hash=items[0].clone_hash,
        label=1,
        features=(1.0,) * 42,
        rule_score=1,
    )
    with pytest.raises(ValueError, match="clone"):
        split_by_repo(items, {"validation"}, {"test"})
    with pytest.raises(ValueError, match="both"):
        split_by_repo(samples()[:-1], {"validation"}, {"test"})


def test_unreviewed_labels_blocked_and_metrics_explicit():
    with pytest.raises(ValueError, match="reviewed"):
        prepare_samples([record()])
    result = metrics([0, 0, 1, 1], [0.1, 0.9, 0.8, 0.2])
    assert result["precision"] == result["recall"] == result["false_positive_rate"] == 0.5
    assert "brier_score_uncalibrated" in result


def test_reviewed_train_features_equal_serving_and_clone_normalization():
    from flakydetector.application import AnalyzeService
    from flakydetector.classifier.feature_extractor import FeatureExtractor

    first = record(
        reviewed=True,
        review_notes="Reviewed repeated failures independently",
        root_causes=("external_service",),
    )
    first = first.model_copy(
        update={"source_code": 'import requests\ndef test_a():\n    requests.get("url1")\n'}
    )
    second = first.model_copy(
        update={
            "repo": "another/repo",
            "nodeid": "test_b.py::test_b",
            "source_code": 'import requests\ndef test_b():\n    requests.get("url2")\n',
        }
    )
    samples_ = prepare_samples([first, second])
    response = AnalyzeService().analyze({"test_a.py": first.source_code})
    test = response.results[0]
    served = FeatureExtractor().extract_from_patterns(
        "test_a", "test_a.py", test.patterns, test.log_anomalies, test.fixtures
    )
    assert samples_[0].features == served.features
    assert samples_[0].clone_hash == samples_[1].clone_hash
    assert samples_[0].rule_score == 1


def test_reliability_bins_and_stable_suite_are_not_calibration_claims():
    from flakydetector.dataset.benchmark import (
        reliability_bins,
        stable_suite_false_positives,
        tabular_scores,
    )

    bins = reliability_bins([0, 1], [0.2, 0.8])
    assert sum(b["n"] for b in bins) == 2
    assert bins[0]["observed_fraction"] == 0
    assert len(tabular_scores(samples()[:4], samples()[4:])) == 2
    stable = Sample(
        repo="repo",
        identity="one",
        clone_hash="one",
        label=0,
        features=(0.0,) * 42,
        rule_score=0,
        observation="observed_pass",
    )
    assert stable_suite_false_positives([stable], [0.8]) == {
        "n": 1,
        "false_positives": 1,
        "rate": 1.0,
    }


def test_inconsistent_dataset_counts_rejected():
    from pydantic import ValidationError

    payload = record().model_dump()
    payload["runs_total"] = 100
    with pytest.raises(ValidationError):
        DatasetRecord.model_validate(payload)


def test_prediction_error_is_explicit_model_unavailability():
    class Broken:
        def predict_proba(self, _):
            raise RuntimeError("invalid model state")

    model = FlakyClassifier()
    model.model = Broken()
    with pytest.raises(ModelUnavailable, match="prediction failed"):
        model.predict_single([0.0] * 42)
