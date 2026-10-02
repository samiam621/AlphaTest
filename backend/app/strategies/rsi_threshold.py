"""RSI threshold — mean reversion on an oscillator extreme.

"Mean reversion" = betting that a big move will bounce back toward normal.
Buy when RSI crosses below ``oversold`` (fell too far), sell when it crosses
above ``overbought``. In between, keep whatever position we already have.

Event rule: the middle zone says nothing, so the position carries forward.
Uses crossings (fire once), not levels (true on every bar of a long drop).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import rsi
from backend.app.strategies.signal_utils import (
    cross_above,
    cross_below,
    from_events,
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

    strength = rsi(df["close"], params.period)

    entries = cross_below(strength, params.oversold)
    exits = cross_above(strength, params.overbought)

    return pd.DataFrame(
        {"rsi": strength, "signal": from_events(entries, exits)},
        index=df.index,
    )
