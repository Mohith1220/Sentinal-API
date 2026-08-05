"""
PyTorch LSTM baseline model for anomaly detection.

Defines the LSTM architecture and provides train/predict functions.
"""

import io
import pickle
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# LSTM Model Architecture
# ---------------------------------------------------------------------------


class LSTMBaselineModel(nn.Module):
    """
    LSTM baseline model for time-series anomaly detection.

    Architecture:
    - Input: hourly request counts (sequence length configurable)
    - Hidden size: 64
    - Layers: 2
    - Output: predicted next-hour request count
    """

    def __init__(self, input_size: int = 1, hidden_size: int = 64, num_layers: int = 2):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.

        Args:
            x: Input tensor of shape (batch_size, sequence_length, input_size)

        Returns:
            Output tensor of shape (batch_size, 1)
        """
        # LSTM output: (batch_size, sequence_length, hidden_size)
        lstm_out, _ = self.lstm(x)
        # Take the last time step
        last_out = lstm_out[:, -1, :]
        # Fully connected layer
        out = self.fc(last_out)
        return out


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train_baseline(
    hourly_counts: list[float],
    history_days: int = 7,
    sequence_length: int = 24,
    epochs: int = 50,
) -> bytes:
    """
    Train an LSTM baseline model on hourly request counts.

    Args:
        hourly_counts: List of hourly request counts (at least history_days * 24 values).
        history_days: Number of days of history to use for training.
        sequence_length: Number of hours in each input sequence (default 24 = 1 day).
        epochs: Number of training epochs.

    Returns:
        Serialized model artifact (bytes) suitable for storage in the database.
    """
    if len(hourly_counts) < history_days * 24:
        raise ValueError(
            f"Insufficient data: need at least {history_days * 24} hourly counts, "
            f"got {len(hourly_counts)}"
        )

    # Prepare training data: sliding windows of sequence_length hours
    X, y = [], []
    for i in range(len(hourly_counts) - sequence_length):
        X.append(hourly_counts[i : i + sequence_length])
        y.append(hourly_counts[i + sequence_length])

    X = np.array(X, dtype=np.float32).reshape(-1, sequence_length, 1)
    y = np.array(y, dtype=np.float32).reshape(-1, 1)

    X_tensor = torch.from_numpy(X)
    y_tensor = torch.from_numpy(y)

    # Initialize model
    model = LSTMBaselineModel(input_size=1, hidden_size=64, num_layers=2)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    # Training loop
    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad()
        outputs = model(X_tensor)
        loss = criterion(outputs, y_tensor)
        loss.backward()
        optimizer.step()

        if (epoch + 1) % 10 == 0:
            logger.debug("training_epoch", epoch=epoch + 1, loss=loss.item())

    # Serialize model
    buffer = io.BytesIO()
    torch.save(model.state_dict(), buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------


def predict_deviation(
    model_artifact: bytes,
    current_window: list[float],
    sequence_length: int = 24,
) -> tuple[float, float]:
    """
    Predict the expected next-hour count and compute deviation.

    Args:
        model_artifact: Serialized model state dict (bytes).
        current_window: List of recent hourly counts (length = sequence_length).
        sequence_length: Number of hours in the input sequence.

    Returns:
        Tuple of (predicted_value, observed_value).
        The caller computes deviation_sigma = (observed - predicted) / stddev.
    """
    if len(current_window) < sequence_length + 1:
        raise ValueError(
            f"current_window must have at least {sequence_length + 1} values "
            f"(sequence + observed), got {len(current_window)}"
        )

    # Load model
    model = LSTMBaselineModel(input_size=1, hidden_size=64, num_layers=2)
    buffer = io.BytesIO(model_artifact)
    model.load_state_dict(torch.load(buffer, weights_only=True))
    model.eval()

    # Prepare input: last sequence_length hours
    X = np.array(current_window[:sequence_length], dtype=np.float32).reshape(
        1, sequence_length, 1
    )
    X_tensor = torch.from_numpy(X)

    # Predict
    with torch.no_grad():
        predicted = model(X_tensor).item()

    # Observed value is the next hour (index sequence_length)
    observed = current_window[sequence_length]

    return predicted, observed


# ---------------------------------------------------------------------------
# Cold-start baseline (cluster aggregate)
# ---------------------------------------------------------------------------


def create_cluster_baseline(
    cluster_hourly_counts: list[list[float]],
    sequence_length: int = 24,
    epochs: int = 50,
) -> bytes:
    """
    Train a cluster-level baseline from multiple endpoints' hourly counts.

    Args:
        cluster_hourly_counts: List of hourly count lists, one per endpoint in the cluster.
        sequence_length: Number of hours in each input sequence.
        epochs: Number of training epochs.

    Returns:
        Serialized model artifact (bytes).
    """
    # Concatenate all cluster data
    all_counts = []
    for counts in cluster_hourly_counts:
        all_counts.extend(counts)

    if len(all_counts) < sequence_length + 1:
        raise ValueError(
            f"Insufficient cluster data: need at least {sequence_length + 1} hourly counts"
        )

    return train_baseline(
        hourly_counts=all_counts,
        history_days=len(all_counts) // 24,
        sequence_length=sequence_length,
        epochs=epochs,
    )
