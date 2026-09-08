"""RSI threshold — mean reversion on an oscillator extreme.

Buy when RSI drops through the oversold line (the selloff is assumed to have
overshot) and sell when it climbs through the overbought line. Between 30 and 70
you simply hold whatever you already had.

That in-between zone is why this needs *events* rather than state: at RSI 50 the
rule says nothing about what your position should be, so it has to be carried
forward from the last entry or exit.

Note the entry is a *crossing*, not a level. "RSI below 30" is true on every bar
of a long slide; "RSI just crossed below 30" fires once, at the point the
condition became true.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import rsi
from backend.app.strategies.signal_utils import (
    cross_above,
    cross_below,
    from_events,
    require_columns,
)

NAME = "RSI Threshold"


@dataclass(frozen=True)
class RsiThresholdParams:
    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0

    def __post_init__(self) -> None:
        if not 0 <= self.oversold < self.overbought <= 100:
            raise ValueError(
                f"need 0 <= oversold < overbought <= 100, got "
                f"oversold={self.oversold}, overbought={self.overbought}"
            )


def generate_signals(
    df: pd.DataFrame,
    params: RsiThresholdParams | None = None,
) -> pd.DataFrame:
    """Return the ``rsi`` series and a 0/1 ``signal`` column."""
    params = params or RsiThresholdParams()
    require_columns(df, ("close",))

    strength = rsi(df["close"], params.period)

    entries = cross_below(strength, params.oversold)
    exits = cross_above(strength, params.overbought)

    return pd.DataFrame(
        {"rsi": strength, "signal": from_events(entries, exits)},
        index=df.index,
    )
