"""Extract dynamic features from real execution traces and build a hybrid dataset."""

from __future__ import annotations
import sys

import sqlite3
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from flakydetector.analyzer.ast_analyzer import ASTAnalyzer
from flakydetector.classifier.feature_extractor import FeatureExtractor
from flakydetector.classifier.catboost_model import FlakyDetector


def extract_dynamic_features(source_dir: str, db_path: str = "data/raw/traces.db") -> tuple[np.ndarray, np.ndarray, int]:
    """Extract dynamic features from the trace database."""
    source_path = Path(source_dir)
    db_path_path = Path(db_path)

    if not db_path_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path_path}. Run pytest-flaky-trail first."
        )

    conn = sqlite3.connect(str(db_path_path))
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("""
        SELECT test_name, status, prev_test_failed, prev_test_name, prev_time_ms
        FROM test_runs
        ORDER BY rowid
    """)
    rows = cursor.fetchall()

    analyzer = ASTAnalyzer()
    extractor = FeatureExtractor(analyzer)
    X_dynamic_list = []
    y_list = []
    missing_code_files: set[str] = set()

    for row in rows:
        test_name = row["test_name"]
        prev_failed = bool(row["prev_test_failed"])
        prev_name = row["prev_test_name"]

        # Dynamic Feature 1: Did the previous test fail?
        f1 = 1.0 if prev_failed else 0.0

        # Dynamic Feature 2: Did the previous test have shared scope?
        f2 = 0.0
        if prev_name:
            for p in source_path.rglob("**/test_*.py"):
                try:
                    content = p.read_text(encoding="utf-strict", errors="ignore")
                    if f"def {prev_name}" in content:
                        _, fixtures = analyzer.analyze_source(content, str(p))
                        f2 = 1.0 if any(f.scope in ("module", "session") for f in fixtures) else 0.0
                        break
                except Exception:
                    pass

        # Dynamic Feature 3: Time delta
        f3 = float(row["prev_time_ms"]) / 1000.0 if row["prev_time_ms"] else 0.0

        if test_name not in missing_code_files:
            try:
                for p in source_path.rglob("**/test_*.py"):
                    content = p.read_text(encoding="utf-strict", errors="ignore")
                    if f"def {test_name}" in content:
                        patterns, fixtures = analyzer.analyze_source(content, str(p))
                        features = extractor.extract_from_patterns(
                            test_name=test_name,
                            file_path=str(p),
                            ast_patterns=patterns,
                            log_anomalies=[],
                            fixtures=fixtures,
                        )

                        # Concatenate 42D static + 3 dynamic features
                        dynamic_feats = np.array([f1, f2, f3], dtype=np.float64)
                        hybrid_features = np.concatenate([features.features, dynamic_feats])

                        # Label: Failed right after a failure = 1.0, else 0.0
                        is_flaky = 1.0 if (row["status"] == "failed" and prev_failed) else 0.0

                        X_dynamic_list.append(hybrid_features)
                        y_list.append(is_flaky)
                        break
            except Exception:
                missing_code_files.add(test_name)

    if not X_dynamic_list:
        print("❌ No matching test files found in the source directory.")
        return np.array([]), np.array([]), 0

    X = np.array(X_dynamic_list, dtype=np.float64)
    y = np.array(y_list, dtype=np.float64)
    return X, y, len(y_list)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build hybrid dataset from real execution traces.")
    parser.add_argument("--source-dir", type=str, required=True, help="Path to the target repository")
    parser.add_argument("--db-path", type=str, default="data/raw/traces.db", help="Path to the generated traces.db file")

    args = parser.parse_args()

    try:
        X, y, n_samples = extract_dynamic_features(args.source_dir, args.db_path)
        print(f"✅ Real dataset extracted: {n_samples} valid samples.")
        print(f"📊 Feature dimensionality: {X.shape[1]} (42 static + 3 dynamic)")
        print(f"Flaky rate in traced data: {y.mean():.2%}")

        if n_samples > 30:
            print("\n🔬 Training hybrid 45D model on REAL data...")
            clf = FlakyDetector(iterations=500, depth=6, learning_rate=0.1)

            split_idx = int(len(X) * 0.8)
            metrics = clf.train(X[:split_idx], y[:split_idx], X[split_idx:], y[split_idx:])

            model_path = Path("data/models/flaky_v3_45d_real.cbm")
            clf.save_model(model_path)
            print(f"✅ Real model saved to {model_path}")
        else:
            print("\n⚠️ Not enough data points for ML training (need >30). Run more tests!")

    except Exception as e:
        print(f"❌ Error: {e}")