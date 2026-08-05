"""Train and compare versioned local risk classifiers on synthetic data."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from apps.api.app.risk.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from apps.api.app.risk.synthetic import (
    DEFAULT_DATASET_SEED,
    DEFAULT_DATASET_SIZE,
    generate_synthetic_dataset,
)

MODEL_VERSION = "1.0.0"
DEFAULT_OUTPUT_DIRECTORY = Path("apps/api/models/risk") / f"v{MODEL_VERSION}"


def train_models(
    *,
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
    dataset_size: int = DEFAULT_DATASET_SIZE,
    seed: int = DEFAULT_DATASET_SEED,
) -> dict[str, Any]:
    dataset = generate_synthetic_dataset(size=dataset_size, seed=seed)
    x_train, x_test, y_train, y_test = train_test_split(
        dataset.features,
        dataset.labels,
        test_size=0.25,
        random_state=seed,
        stratify=dataset.labels,
    )
    candidates = {
        "logistic_regression": Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=2_000,
                        class_weight="balanced",
                        random_state=seed,
                    ),
                ),
            ]
        ),
        "random_forest": Pipeline(
            [
                (
                    "classifier",
                    RandomForestClassifier(
                        n_estimators=250,
                        max_depth=12,
                        min_samples_leaf=2,
                        class_weight="balanced",
                        random_state=seed,
                        n_jobs=1,
                    ),
                )
            ]
        ),
    }
    metrics: dict[str, dict[str, float]] = {}
    trained: dict[str, Pipeline] = {}
    for name, candidate in candidates.items():
        candidate.fit(x_train, y_train)
        predicted = candidate.predict(x_test)
        metrics[name] = {
            "accuracy": round(float(accuracy_score(y_test, predicted)), 6),
            "balanced_accuracy": round(
                float(balanced_accuracy_score(y_test, predicted)), 6
            ),
            "macro_f1": round(
                float(f1_score(y_test, predicted, average="macro")), 6
            ),
        }
        trained[name] = candidate

    selected_name = max(
        metrics,
        key=lambda name: (
            metrics[name]["macro_f1"],
            metrics[name]["balanced_accuracy"],
            name == "logistic_regression",
        ),
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    artifact_path = output_directory / "risk_model.joblib"
    joblib.dump(
        {
            "model": trained[selected_name],
            "feature_names": list(FEATURE_NAMES),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "model_version": MODEL_VERSION,
            "model_name": selected_name,
        },
        artifact_path,
        compress=3,
    )
    artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    metadata = {
        "model_version": MODEL_VERSION,
        "model_name": selected_name,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "dataset": {
            "kind": "synthetic",
            "size": dataset_size,
            "seed": seed,
            "sha256": dataset.sha256,
            "class_distribution": {
                label: int((dataset.labels == label).sum())
                for label in sorted(set(dataset.labels))
            },
        },
        "split": {"test_fraction": 0.25, "random_state": seed, "stratified": True},
        "metrics": metrics,
        "selection_metric": "macro_f1",
        "artifact_sha256": artifact_sha256,
        "trained_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "limitations": [
            "Training labels are synthetic and do not establish production accuracy.",
            "Metrics measure held-out synthetic data only.",
            "The deterministic rule baseline remains visible and is used as fallback.",
        ],
    }
    metadata_path = output_directory / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--dataset-size", type=int, default=DEFAULT_DATASET_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_DATASET_SEED)
    arguments = parser.parse_args()
    metadata = train_models(
        output_directory=arguments.output,
        dataset_size=arguments.dataset_size,
        seed=arguments.seed,
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
