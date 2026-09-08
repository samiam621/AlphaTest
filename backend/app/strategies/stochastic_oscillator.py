"""Stochastic oscillator — where the close sits in the recent range.

%K reads 0 when a bar closes at the bottom of the last ``k_period`` bars' range
and 100 at the top. %D is a moving average of %K, so %K crossing above %D means
the close is pushing up through its own recent tendency.

Entry: %K crosses above %D **while still oversold**. The crossing supplies the
       timing, the zone supplies the context — a %K/%D cross in the middle of
       the range is noise, so both halves are required.
Exit:  %K crosses below %D while overbought.

An *event* rule, and a demanding one: both conditions need a crossing and a
zone at the same time, so it trades rarely and will hold through the middle of
the range waiting for an overbought cross. Widening ``oversold``/``overbought``
toward 50 loosens that considerably.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import stochastic_oscillator as stoch
from backend.app.strategies.signal_utils import (
    cross_above,
    cross_below,
    from_events,
    require_columns,
)

NAME = "Stochastic Oscillator"


@dataclass(frozen=True)
class StochasticParams:
    k_period: int = 14
    # 3 gives the "slow" stochastic; 1 leaves %K raw and much jumpier.
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
    require_columns(df, ("high", "low", "close"))

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
