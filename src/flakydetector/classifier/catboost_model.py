"""CatBoost-based flaky test classifier."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from catboost import CatBoostClassifier, Pool
from numpy.typing import NDArray

from flakydetector.classifier.feature_extractor import FEATURE_NAMES, FeatureExtractor
from flakydetector.models.domain import FlakyTestReport, FlakyCategory, FlakySeverity
from flakydetector.utils.logger import get_logger

logger = get_logger(__name__)


class FlakyClassifier:
    """CatBoost classifier for flaky test detection."""

    def __init__(
            self,
            iterations: int = 1000,
            depth: int = 8,
            learning_rate: float = 0.05,
            threshold: float = 0.7,
            feature_extractor: FeatureExtractor | None = None,
    ) -> None:
        self._iterations = iterations
        self._depth = depth
        self._learning_rate = learning_rate
        self._threshold = threshold
        self._feature_extractor = feature_extractor or FeatureExtractor()

        self._model: CatBoostClassifier | None = None
        self._is_trained = False

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    def train(
            self,
            X: NDArray[np.float64],
            y: NDArray[np.int32],
            X_val: NDArray[np.float64] | None = None,
            y_val: NDArray[np.int32] | None = None,
            verbose: int = 100,
    ) -> dict[str, float]:
        """Train the classifier."""
        logger.info(
            "training_start",
            n_samples=X.shape[0],
            n_features=X.shape[1],
            n_positive=y.sum(),
        )

        train_pool = Pool(X, y, feature_names=FEATURE_NAMES)
        eval_pool = Pool(X_val, y_val, feature_names=FEATURE_NAMES) if X_val is not None else None

        self._model = CatBoostClassifier(
            iterations=self._iterations,
            depth=self._depth,
            learning_rate=self._learning_rate,
            loss_function="Logloss",
            eval_metric="AUC",
            auto_class_weights="Balanced",
            random_seed=42,
            verbose=verbose,
            early_stopping_rounds=50,
            l2_leaf_reg=3.0,
            min_data_in_leaf=5,
        )

        self._model.fit(train_pool, eval_set=eval_pool)
        self._is_trained = True

        # Get metrics safely (handles early stopping on iteration 0)
        best_score = self._model.get_best_score() or {}
        learn_metrics = best_score.get("learn", {})
        val_metrics = best_score.get("validation", {})

        metrics: dict[str, float] = {
            "train_auc": learn_metrics.get("AUC", 0.0),
            "best_iteration": self._model.get_best_iteration(),
        }

        if eval_pool is not None:
            metrics["best_score"] = val_metrics.get("AUC", 0.0)
        logger.info("training_complete", metrics=metrics)
        return metrics

    def predict(
            self,
            X: NDArray[np.float64],
            return_probabilities: bool = True,
    ) -> tuple[NDArray[np.bool_], NDArray[np.float64]]:
        """Predict flaky labels."""
        if not self._is_trained or self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")

        probabilities = self._model.predict_proba(X)[:, 1]
        predictions = probabilities >= self._threshold

        return predictions, probabilities

    def predict_single(
            self,
            features: NDArray[np.float64],
    ) -> tuple[bool, float]:
        """Predict for a single test."""
        predictions, probabilities = self.predict(features.reshape(1, -1))
        return bool(predictions[0]), float(probabilities[0])

    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance scores."""
        if not self._is_trained or self._model is None:
            raise RuntimeError("Model not trained.")

        importances = self._model.get_feature_importance()
        return dict(zip(FEATURE_NAMES, importances))

    def save_model(self, path: Path) -> None:
        """Save model to disk."""
        if not self._is_trained or self._model is None:
            raise RuntimeError("Model not trained.")

        path.parent.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path))
        logger.info("model_saved", path=str(path))

    def load_model(self, path: Path) -> None:
        """Load model from disk."""
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        self._model = CatBoostClassifier()
        self._model.load_model(str(path))
        self._is_trained = True
        logger.info("model_loaded", path=str(path))

    def get_model_params(self) -> dict[str, Any]:
        """Get model hyperparameters."""
        return {
            "iterations": self._iterations,
            "depth": self._depth,
            "learning_rate": self._learning_rate,
            "threshold": self._threshold,
            "is_trained": self._is_trained,
            "n_features": len(FEATURE_NAMES),
        }