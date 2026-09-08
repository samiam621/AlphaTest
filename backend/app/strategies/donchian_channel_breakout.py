"""Donchian channel breakout — the Turtle rule.

Buy when the close takes out the highest high of the last `entry_window` bars,
exit when it gives back the lowest low of the last `exit_window` bars. The
exit window is shorter, so the position gets out faster than it got in.

This is the opposite bet to the Bollinger strategy: a move to a new extreme is
treated as the start of something rather than as an overshoot to fade.

The one detail that matters: the channel is compared **as it stood before the
current bar** (``.shift(1)``). Without the shift, today's high is inside the
window used to compute today's channel top, so the close can essentially never
exceed it and the strategy quietly never trades.

An *event* rule.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import donchian_channel
from backend.app.strategies.signal_utils import from_events, require_columns

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
    """Return the breakout levels actually used, plus a 0/1 ``signal`` column.

    ``entry_high`` and ``exit_low`` are the shifted levels the rule compared
    against, so a chart of them lines up exactly with where the trades fired.
    """
    params = params or DonchianBreakoutParams()
    require_columns(df, ("high", "low", "close"))

    close = df["close"]
    entry_high = donchian_channel(df["high"], df["low"], params.entry_window)["upper"].shift(1)
    exit_low = donchian_channel(df["high"], df["low"], params.exit_window)["lower"].shift(1)

    # Plain comparisons rather than crossings: a breakout that stays broken out
    # keeps re-firing the entry, which is a no-op while already long.
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
