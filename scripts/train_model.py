"""Synthetic dataset generator and CatBoost model trainer."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
from catboost import Pool

# Добавляем корень проекта в путь
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from flakydetector.analyzer.ast_analyzer import ASTAnalyzer
from flakydetector.classifier.feature_extractor import FeatureExtractor
from flakydetector.classifier.catboost_model import FlakyClassifier

# --- 1. Шаблоны для генерации синтетических тестов ---

FLAKY_TEMPLATES = [
    "import time\ndef test_{name}():\n    time.sleep(0.1)\n    assert True",
    "from datetime import datetime\ndef test_{name}():\n    now = datetime.now()\n    assert now.year == 2024",
    "COUNTER = 0\ndef test_{name}():\n    global COUNTER\n    COUNTER += 1\n    assert COUNTER == 1",
    "import requests\ndef test_{name}():\n    res = requests.get('https://example.com')\n    assert res.status_code == 200",
    "def test_{name}():\n    result = 0.1 + 0.2\n    assert result == 0.3",
    "async def test_{name}():\n    import asyncio\n    await asyncio.sleep(0.05)",
]

STABLE_TEMPLATES = [
    "def test_{name}():\n    assert 1 + 1 == 2",
    "def test_{name}():\n    data = [1, 2, 3]\n    assert len(data) == 3",
    "def test_{name}():\n    text = 'hello'\n    assert 'ell' in text",
    "from unittest.mock import patch\n@patch('requests.get')\ndef test_{name}(mock_get):\n    mock_get.return_value.status_code = 200\n    assert True",
    "def test_{name}(tmp_path):\n    d = tmp_path / 'sub'\n    d.mkdir()\n    assert d.exists()",
]


def generate_dataset(n_flaky: int = 50, n_stable: int = 50) -> tuple[list[str], np.ndarray]:
    """Генерирует код и возвращает векторы фичей."""
    analyzer = ASTAnalyzer()
    extractor = FeatureExtractor(analyzer)

    X_list = []
    y_list = []

    # Генерация Flaky
    for i in range(n_flaky):
        template = random.choice(FLAKY_TEMPLATES)
        code = template.format(name=f"flaky_{i}")
        patterns = analyzer.analyze_source(code, f"test_flaky_{i}.py")

        features = extractor.extract_from_patterns(
            test_name=f"test_flaky_{i}",
            file_path=f"test_flaky_{i}.py",
            ast_patterns=patterns,
            log_anomalies=[]
        )
        X_list.append(features.features)
        y_list.append(1)  # 1 = Flaky

    # Генерация Stable
    for i in range(n_stable):
        template = random.choice(STABLE_TEMPLATES)
        code = template.format(name=f"stable_{i}")
        patterns = analyzer.analyze_source(code, f"test_stable_{i}.py")

        features = extractor.extract_from_patterns(
            test_name=f"test_stable_{i}",
            file_path=f"test_stable_{i}.py",
            ast_patterns=patterns,
            log_anomalies=[]
        )
        X_list.append(features.features)
        y_list.append(0)  # 0 = Stable

    return np.array(X_list, dtype=np.float64), np.array(y_list, dtype=np.int32)


if __name__ == "__main__":
    print("🔬 [1/4] Generating synthetic dataset (50 flaky, 50 stable)...")
    X, y = generate_dataset()
    print(f"✅ Dataset generated. Shape: {X.shape}, Flaky ratio: {y.mean():.2f}")

    print("\n🔬 [2/4] Splitting data (80% train, 20% validation)...")
    split_idx = int(len(X) * 0.8)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]

    print("\n🔬 [3/4] Training CatBoost model...")
    clf = FlakyClassifier(
        iterations=500,
        depth=6,
        learning_rate=0.1,
        threshold=0.6  # Чуть снизим порог для чувствительности
    )

    metrics = clf.train(X_train, y_train, X_val, y_val)
    print(f"✅ Training complete. Train AUC: {metrics['train_auc']:.4f}")
    if 'best_score' in metrics:
        print(f"✅ Validation AUC: {metrics['best_score']:.4f}")

    print("\n🔬 [4/4] Saving model...")
    model_path = Path("data/models/flaky_v1.cbm")
    clf.save_model(model_path)

    # Демонстрация Feature Importance
    print("\n📊 Top 5 Feature Importances:")
    importance = clf.get_feature_importance()
    sorted_imp = sorted(importance.items(), key=lambda x: -x[1])[:5]
    for name, score in sorted_imp:
        print(f"  - {name}: {score:.2f}")

    print("\n🚀 Model is ready! Restart uvicorn to load it.")