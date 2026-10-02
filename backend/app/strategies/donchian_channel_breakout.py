"""Donchian channel breakout — the Turtle rule.

Buy when the close goes above the highest high of the last ``entry_window`` bars;
sell when it drops below the lowest low of the last ``exit_window`` bars (a
shorter window, so it exits faster than it enters). Opposite idea to Bollinger:
a new high is treated as the start of a trend, not a move to fade.

Key detail: compare to the channel from the PREVIOUS bar (``.shift(1)``).
Otherwise today's high is part of today's channel, so the close can never
beat it and the strategy never trades.

Event rule.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import donchian_channel
from backend.app.strategies.signal_utils import from_events

NAME = "Donchian Channel Breakout"


@dataclass(frozen=True)
class DonchianBreakoutParams:
    entry_window: int = 20
    exit_window: int = 10

    def __post_init__(self) -> None:
        if self.exit_window > self.entry_window:
            raise ValueError(
                f"exit_window ({self.exit_window}) should not be longer than "
                f"entry_window ({self.entry_window}) — the exit is meant to be "
                f"the quicker of the two"
            )


def generate_signals(
    df: pd.DataFrame,
    params: DonchianBreakoutParams | None = None,
) -> pd.DataFrame:
    """Return the breakout levels used (already shifted) plus a 0/1 ``signal`` column."""
    params = params or DonchianBreakoutParams()

    close = df["close"]
    entry_high = donchian_channel(df["high"], df["low"], params.entry_window)["upper"].shift(1)
    exit_low = donchian_channel(df["high"], df["low"], params.exit_window)["lower"].shift(1)

    # Plain comparisons, not crossings: repeating an entry while already holding does nothing.
    entries = close > entry_high
    exits = close < exit_low

    return pd.DataFrame(
        {
            "entry_high": entry_high,
            "exit_low": exit_low,
            "signal": from_events(entries, exits),
        },
        index=df.index,
    )
