"""Stochastic oscillator — where the close sits in the recent range.

%K = where the close is within the last ``k_period`` bars' range (0 = at the low, 100 = at the high).
%D = moving average of %K.

Entry: %K crosses above %D while oversold (crossing = timing, oversold zone = context).
Exit:  %K crosses below %D while overbought.

Event rule. Both conditions must be true at once, so it trades rarely. Moving
oversold/overbought closer to 50 makes it trade more.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import stochastic_oscillator as stoch
from backend.app.strategies.signal_utils import (
    cross_above,
    cross_below,
    from_events,
)

NAME = "Stochastic Oscillator"


@dataclass(frozen=True)
class StochasticParams:
    k_period: int = 14
    # 3 = the common "slow" version; 1 = raw %K, much jumpier.
    smooth_k: int = 3
    d_period: int = 3
    oversold: float = 20.0
    overbought: float = 80.0

    def __post_init__(self) -> None:
        if not 0 <= self.oversold < self.overbought <= 100:
            raise ValueError(
                f"need 0 <= oversold < overbought <= 100, got "
                f"oversold={self.oversold}, overbought={self.overbought}"
            )


def generate_signals(
    df: pd.DataFrame,
    params: StochasticParams | None = None,
) -> pd.DataFrame:
    """Return ``k``, ``d`` and a 0/1 ``signal`` column."""
    params = params or StochasticParams()

    lines = stoch(
        df["high"],
        df["low"],
        df["close"],
        k_period=params.k_period,
        smooth_k=params.smooth_k,
        d_period=params.d_period,
    )
    k, d = lines["k"], lines["d"]

    entries = cross_above(k, d) & (k < params.oversold)
    exits = cross_below(k, d) & (k > params.overbought)

    out = lines.copy()
    out["signal"] = from_events(entries, exits)
    return out
