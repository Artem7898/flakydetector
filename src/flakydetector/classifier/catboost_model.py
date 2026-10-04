"""Optional ML adapter with a verified artifact/schema boundary."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from pydantic import Field

from flakydetector.classifier.schema import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, SCHEMA_HASH
from flakydetector.models.domain import ValueModel


class ModelUnavailable(ValueError):
    pass


class ModelManifest(ValueModel):
    model_version: str = Field(default_factory=lambda: str(uuid4()))
    schema_version: str = FEATURE_SCHEMA_VERSION
    schema_hash: str = SCHEMA_HASH
    feature_names: tuple[str, ...] = FEATURE_NAMES
    artifact_sha256: str
    dataset_sha256: str
    evaluation: str = "demo"
    calibrated: bool = False


class CatBoostBackend(Protocol):
    feature_names_: Sequence[str]

    def fit(
        self,
        X: list[list[float]],
        y: list[int],
        *,
        eval_set: tuple[list[list[float]], list[int]] | None = None,
    ) -> object: ...
    def set_feature_names(self, feature_names: list[str]) -> None: ...
    def predict_proba(self, X: list[list[float]]) -> Sequence[Sequence[float]]: ...
    def save_model(self, path: str) -> None: ...
    def load_model(self, path: str) -> None: ...
    def get_feature_importance(self) -> Sequence[float]: ...


def new_backend(**kwargs: object) -> CatBoostBackend:
    try:
        # A single typed boundary around a third-party, incompletely typed package.
        factory = cast(Callable[..., CatBoostBackend], import_module("catboost").CatBoostClassifier)
        return factory(**kwargs)
    except ImportError as exc:
        raise ModelUnavailable("Install flakydetector[ml] to use CatBoost") from exc


class FlakyClassifier:
    def __init__(
        self,
        *,
        iterations: int = 500,
        depth: int = 6,
        learning_rate: float = 0.1,
        threshold: float = 0.7,
    ) -> None:
        self.iterations, self.depth = iterations, depth
        self.learning_rate, self.threshold = learning_rate, threshold
        self.model: CatBoostBackend | None = None
        self.manifest: ModelManifest | None = None

    @property
    def is_trained(self) -> bool:
        return self.model is not None

    @staticmethod
    def _rows(X: Sequence[Sequence[float]]) -> list[list[float]]:
        import math

        rows = [[float(x) for x in row] for row in X]
        if not rows or any(
            len(row) != len(FEATURE_NAMES) or not all(math.isfinite(x) for x in row) for row in rows
        ):
            raise ValueError("Expected nonempty finite rows matching the feature schema")
        return rows

    def train(
        self,
        X: Sequence[Sequence[float]],
        y: Sequence[int],
        X_val: Sequence[Sequence[float]],
        y_val: Sequence[int],
    ) -> None:
        rows, validation = self._rows(X), self._rows(X_val)
        if (
            len(rows) != len(y)
            or len(validation) != len(y_val)
            or set(y) != {0, 1}
            or set(y_val) != {0, 1}
        ):
            raise ValueError(
                "Train and validation must each contain both classes with matching row counts"
            )
        model = new_backend(
            iterations=self.iterations,
            depth=self.depth,
            learning_rate=self.learning_rate,
            loss_function="Logloss",
            eval_metric="AUC",
            random_seed=42,
            early_stopping_rounds=50,
            verbose=False,
            allow_writing_files=False,
        )
        model.fit(rows, list(y), eval_set=(validation, list(y_val)))
        model.set_feature_names(list(FEATURE_NAMES))
        self.model = model

    def predict_single(self, features: Sequence[float]) -> tuple[bool, float]:
        if self.model is None:
            raise ModelUnavailable("No compatible model loaded")
        try:
            score = float(self.model.predict_proba(self._rows([features]))[0][1])
        except Exception as exc:
            raise ModelUnavailable(f"Model prediction failed: {type(exc).__name__}") from exc
        if not 0 <= score <= 1:
            raise ModelUnavailable("Model returned an invalid score")
        return score >= self.threshold, score

    def save_model(self, path: Path, *, dataset_sha256: str, evaluation: str = "demo") -> None:
        if self.model is None:
            raise ModelUnavailable("Model has not been trained")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write the model first; the manifest is the commit marker for readers.
        temporary = path.with_name(path.name + ".tmp")
        self.model.save_model(str(temporary))
        manifest = ModelManifest(
            artifact_sha256=hashlib.sha256(temporary.read_bytes()).hexdigest(),
            dataset_sha256=dataset_sha256,
            evaluation=evaluation,
        )
        temporary.replace(path)
        sidecar = path.with_suffix(path.suffix + ".json")
        temp_manifest = sidecar.with_name(sidecar.name + ".tmp")
        temp_manifest.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        temp_manifest.replace(sidecar)
        self.manifest = manifest

    def load_model(self, path: Path, *, allow_demo: bool = False) -> None:
        sidecar = path.with_suffix(path.suffix + ".json")
        try:
            manifest = ModelManifest.model_validate_json(sidecar.read_text(encoding="utf-8"))
            if (manifest.schema_hash, manifest.schema_version, manifest.feature_names) != (
                SCHEMA_HASH,
                FEATURE_SCHEMA_VERSION,
                FEATURE_NAMES,
            ):
                raise ModelUnavailable(
                    "Feature schema mismatch; retraining requires a validated dataset"
                )
            if not allow_demo and manifest.evaluation != "evaluated":
                raise ModelUnavailable("Demonstration models are disabled in application inference")
            if manifest.calibrated:
                raise ModelUnavailable("This adapter does not implement a calibration artifact")
            if hashlib.sha256(path.read_bytes()).hexdigest() != manifest.artifact_sha256:
                raise ModelUnavailable("Model checksum mismatch")
            model = new_backend(verbose=False)
            model.load_model(str(path))
            if tuple(model.feature_names_) != FEATURE_NAMES:
                raise ModelUnavailable("Model feature names mismatch")
        except ModelUnavailable:
            raise
        except Exception as exc:
            raise ModelUnavailable(
                f"Model artifact unavailable or invalid: {type(exc).__name__}"
            ) from exc
        self.model, self.manifest = model, manifest

    def get_feature_importance(self) -> dict[str, float]:
        if self.model is None:
            raise ModelUnavailable("No compatible model loaded")
        return dict(
            zip(FEATURE_NAMES, map(float, self.model.get_feature_importance()), strict=True)
        )
