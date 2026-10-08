"""80 % prediction intervals: settings and split-conformal calibration.

Shared by model/backtest.py (to measure) and model/save_model.py (to train what goes live).
"""

import numpy as np
import pandas as pd

Q_LOW, Q_HIGH = 0.10, 0.90  # 80 % prediction interval
TARGET_COVERAGE = Q_HIGH - Q_LOW
CAL_MONTHS = 3  # calibration window right before the period being forecast


def conformal_offset(y: pd.Series, low: pd.Series, high: pd.Series, coverage: float = TARGET_COVERAGE) -> float:
    """How much to widen [low, high] so it would have covered `coverage` of y (split conformal / CQR).

    Score per hour = how far the real price fell outside the band (negative if inside).
    The offset is that score's (n+1)*coverage-th smallest value. A negative offset narrows the band.
    The uncalibrated quantile models covered only ~70 % in the Oct 2026 backtest, which is why this exists.
    """
    scores = np.sort(np.maximum(low - y, y - high).to_numpy())
    n = len(scores)
    k = min(n, int(np.ceil((n + 1) * coverage)))
    return float(scores[k - 1])
