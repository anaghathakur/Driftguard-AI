"""Reproducible synthetic feature dataset for initial risk-model training."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from apps.api.app.risk.features import FEATURE_NAMES
from apps.api.app.schemas.risk import RiskLevel

DEFAULT_DATASET_SEED = 42
DEFAULT_DATASET_SIZE = 4_000


@dataclass(frozen=True, slots=True)
class SyntheticDataset:
    features: np.ndarray
    labels: np.ndarray
    sha256: str


def generate_synthetic_dataset(
    *, size: int = DEFAULT_DATASET_SIZE, seed: int = DEFAULT_DATASET_SEED
) -> SyntheticDataset:
    if size < 100:
        raise ValueError("Synthetic dataset size must be at least 100")
    rng = np.random.default_rng(seed)
    rows: list[list[float]] = []
    labels: list[str] = []
    for _ in range(size):
        category = int(rng.choice(3, p=[0.42, 0.23, 0.35]))
        is_breaking = float(category == 0)
        is_potential = float(category == 1)
        severity = float(
            rng.beta(3.2, 1.6)
            if is_breaking
            else rng.beta(2.0, 2.2)
            if is_potential
            else rng.beta(1.2, 4.0)
        )
        endpoint_removed = float(is_breaking and rng.random() < 0.10)
        method_removed = float(is_breaking and rng.random() < 0.12)
        auth_change = float(is_breaking and rng.random() < 0.14)
        required_input = float(is_breaking and rng.random() < 0.24)
        input_removed = float((is_breaking or is_potential) and rng.random() < 0.25)
        type_change = float((is_breaking or is_potential) and rng.random() < 0.26)
        response_removed = float((is_breaking or is_potential) and rng.random() < 0.20)
        enum_removed = float(is_breaking and rng.random() < 0.14)
        additive = float(not is_breaking and not is_potential and rng.random() < 0.78)
        match_count = float(np.clip(rng.beta(1.1, 3.0), 0, 1))
        impacted_files = float(np.clip(match_count * rng.uniform(0.4, 1.2), 0, 1))
        high_confidence = float(rng.beta(2.5, 1.5) if match_count else 0)
        subject_depth = float(rng.choice([0, 0.25, 0.5, 0.75, 1.0], p=[0.4, 0.3, 0.17, 0.09, 0.04]))
        row = [
            is_breaking,
            is_potential,
            severity,
            endpoint_removed,
            method_removed,
            auth_change,
            required_input,
            input_removed,
            type_change,
            response_removed,
            enum_removed,
            additive,
            match_count,
            impacted_files,
            high_confidence,
            subject_depth,
        ]
        score = (
            8
            + severity * 42
            + is_breaking * 18
            + is_potential * 7
            + endpoint_removed * 18
            + method_removed * 12
            + auth_change * 16
            + required_input * 11
            + input_removed * 8
            + type_change * 10
            + response_removed * 12
            + enum_removed * 10
            - additive * 12
            + impacted_files * 12
            + high_confidence * 5
            + subject_depth * 3
            + rng.normal(0, 4)
        )
        rows.append(row)
        labels.append(_level_for_synthetic_score(score).value)

    features = np.asarray(rows, dtype=np.float64)
    label_array = np.asarray(labels, dtype=str)
    digest = hashlib.sha256()
    digest.update("|".join(FEATURE_NAMES).encode())
    digest.update(features.tobytes())
    digest.update("|".join(labels).encode())
    return SyntheticDataset(
        features=features,
        labels=label_array,
        sha256=digest.hexdigest(),
    )


def _level_for_synthetic_score(score: float) -> RiskLevel:
    if score < 25:
        return RiskLevel.LOW
    if score < 50:
        return RiskLevel.MEDIUM
    if score < 75:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL
