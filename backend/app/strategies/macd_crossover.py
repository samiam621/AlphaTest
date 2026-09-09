"""MACD crossover — trend following on the gap between two EMAs.

The MACD line is (fast EMA - slow EMA): positive when the short-term average is
pulling ahead. The signal line is an EMA of that, so it lags it. Long while MACD
is above its signal line, which is the same as saying the histogram is positive.

Compared to a plain moving average crossover this reacts to the *rate* at which
the averages are separating, so it tends to turn earlier — and to whipsaw more
in a flat market.

A *state* rule: MACD-above-signal is the position.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import macd
from backend.app.strategies.signal_utils import from_state, require_columns

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
    params = params or MacdCrossoverParams()
    require_columns(df, ("close",))

    lines = macd(df["close"], params.fast, params.slow, params.signal)

    out = lines.rename(columns={"signal": "signal_line"})
    out["signal"] = from_state(lines["macd"] > lines["signal"])
    return out
