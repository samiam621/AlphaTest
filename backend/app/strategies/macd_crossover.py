"""MACD crossover — trend following on the gap between two EMAs.

"Trend following" = betting that a move in one direction will keep going.
MACD = fast EMA - slow EMA; the signal line is an EMA of MACD, so it lags behind.
Hold while MACD is above its signal line. Reacts sooner than a moving average
crossover, but gives more false signals in sideways markets.

State rule.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import macd
from backend.app.strategies.signal_utils import from_state

NAME = "MACD Crossover"


@dataclass(frozen=True)
class MacdCrossoverParams:
    fast: int = 12
    slow: int = 26
    signal: int = 9

    def __post_init__(self) -> None:
        if self.fast >= self.slow:
            raise ValueError(f"fast ({self.fast}) must be shorter than slow ({self.slow})")


def generate_signals(
    df: pd.DataFrame,
    params: MacdCrossoverParams | None = None,
) -> pd.DataFrame:
    """Return macd / signal_line / hist plus a 0/1 ``signal`` column."""
    params = params or MacdCrossoverParams()

    lines = macd(df["close"], params.fast, params.slow, params.signal)

    # Rename MACD's "signal" line so it doesn't clash with our 0/1 "signal" column.
    out = lines.rename(columns={"signal": "signal_line"})
    out["signal"] = from_state(lines["macd"] > lines["signal"])
    return out
