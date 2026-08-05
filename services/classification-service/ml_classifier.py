"""
ML Classifier for the Classification Service.

Wraps a Scikit-learn gradient-boosted classifier that predicts lifecycle status
from a five-element feature vector.

Feature vector (in order):
  [traffic_recency, spec_presence, deprecated_flag, owner_present, traffic_trend]

If the model artifact is not found on disk, inference silently falls back to
the rule-based result (caller is responsible for the fallback).
"""

import os
import pickle
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from sentinel_shared.models import LifecycleStatus

logger = logging.getLogger(__name__)

# Default path for the pre-trained model artifact
DEFAULT_MODEL_PATH = os.environ.get(
    "CLASSIFICATION_MODEL_PATH",
    "/models/lifecycle_classifier.pkl",
)

# Ordered label list — must match the training label encoding
_LABELS = [
    LifecycleStatus.ACTIVE,
    LifecycleStatus.DEPRECATED,
    LifecycleStatus.ORPHANED,
    LifecycleStatus.ZOMBIE,
]

# Sentinel value used when traffic_recency_days is None (no traffic ever)
_NO_TRAFFIC_SENTINEL = 999.0


@dataclass
class MLClassificationResult:
    """Result of ML model inference."""

    ml_status: LifecycleStatus
    ml_confidence: float


def _build_feature_vector(
    traffic_recency_days: Optional[float],
    spec_presence: bool,
    deprecated_flag: bool,
    owner_present: bool,
    traffic_trend: float = 0.0,
) -> np.ndarray:
    """
    Build the five-element feature vector for the ML model.

    Args:
        traffic_recency_days: Days since last traffic. None → sentinel 999.
        spec_presence: Whether endpoint is in a spec/gateway.
        deprecated_flag: Whether endpoint is marked deprecated.
        owner_present: Whether an owning team is recorded.
        traffic_trend: Trend in traffic volume (positive = increasing).

    Returns:
        1-D numpy array of shape (5,).
    """
    recency = (
        float(traffic_recency_days)
        if traffic_recency_days is not None
        else _NO_TRAFFIC_SENTINEL
    )
    return np.array(
        [
            recency,
            float(spec_presence),
            float(deprecated_flag),
            float(owner_present),
            float(traffic_trend),
        ],
        dtype=np.float64,
    )


class MLClassifier:
    """
    Gradient-boosted lifecycle classifier backed by a Scikit-learn model.

    The model artifact is loaded lazily on first call to ``predict``.
    If the artifact is absent or fails to load, ``predict`` returns None
    and the caller should fall back to the rule-based result.
    """

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH) -> None:
        self._model_path = model_path
        self._model = None
        self._load_attempted = False

    def _load_model(self) -> None:
        """Attempt to load the model artifact from disk (once)."""
        if self._load_attempted:
            return
        self._load_attempted = True
        if not os.path.exists(self._model_path):
            logger.warning(
                "ml_model_not_found",
                extra={"path": self._model_path},
            )
            return
        try:
            with open(self._model_path, "rb") as fh:
                self._model = pickle.load(fh)  # noqa: S301
            logger.info("ml_model_loaded", extra={"path": self._model_path})
        except Exception as exc:
            logger.error(
                "ml_model_load_failed",
                extra={"path": self._model_path, "error": str(exc)},
            )
            self._model = None

    def predict(
        self,
        traffic_recency_days: Optional[float],
        spec_presence: bool,
        deprecated_flag: bool,
        owner_present: bool,
        traffic_trend: float = 0.0,
    ) -> Optional[MLClassificationResult]:
        """
        Run inference and return an MLClassificationResult, or None on failure.

        Returns None when:
        - The model artifact is not found on disk.
        - The model fails to load.
        - An exception occurs during inference.

        Args:
            traffic_recency_days: Days since last traffic. None = no traffic ever.
            spec_presence: Whether endpoint is in a spec/gateway.
            deprecated_flag: Whether endpoint is marked deprecated.
            owner_present: Whether an owning team is recorded.
            traffic_trend: Trend in traffic volume.

        Returns:
            MLClassificationResult or None.
        """
        self._load_model()
        if self._model is None:
            return None

        try:
            features = _build_feature_vector(
                traffic_recency_days,
                spec_presence,
                deprecated_flag,
                owner_present,
                traffic_trend,
            ).reshape(1, -1)

            predicted_index = int(self._model.predict(features)[0])
            probabilities = self._model.predict_proba(features)[0]
            confidence = float(probabilities[predicted_index])

            # Map predicted index to LifecycleStatus
            if 0 <= predicted_index < len(_LABELS):
                ml_status = _LABELS[predicted_index]
            else:
                logger.warning(
                    "ml_unknown_label_index",
                    extra={"index": predicted_index},
                )
                return None

            return MLClassificationResult(
                ml_status=ml_status,
                ml_confidence=confidence,
            )
        except Exception as exc:
            logger.error(
                "ml_inference_failed",
                extra={"error": str(exc)},
            )
            return None
