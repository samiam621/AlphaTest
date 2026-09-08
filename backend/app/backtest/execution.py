"""How a decision becomes a fill.

One module owns the difference between the execution models, because the choice
changes two things that must agree: which return a position earns, and what
price the trade ledger reports. Splitting that knowledge between the engine and
the ledger is how a backtest ends up with an equity curve and a trade table that
tell different stories.

``close``
    Fill at the close of the bar that produced the signal. A position held
    during bar t earns ``close_t / close_{t-1} - 1``. Standard, and mildly
    optimistic: you traded at a price you only knew once the bar was over.

``next_open``
    Fill at the open of the bar after the signal. The honest version, and it
    needs each bar split at its open:

        gap_t      = open_t / close_{t-1} - 1   carried by the *previous*
                                                position — the order has not
                                                been filled yet
        session_t  = close_t / open_t - 1       carried by the new position

    Multiplying the two legs back together gives exactly the close-to-close
    return whenever the position did not change, so a bar in the middle of a
    trade is accounted identically under both models. Only the entry and exit
    bars differ, which is the entire point.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.signal_utils import lag


@dataclass(frozen=True)
class Fills:
    """What one execution model implies for returns, prices and accounting."""

    name: str
    #: What is held during bar t (through its session).
    position: pd.Series
    #: Per-bar return earned by that position, before costs.
    gross_returns: pd.Series
    #: The price at which a position change taking effect on bar t was filled.
    fill_prices: pd.Series
    #: Which bar that fill physically happened on, relative to the bar the new
    #: position takes effect: -1 for close (yesterday's close), 0 for next_open.
    fill_offset: int
    #: How many bars past the last held one a trade still earns a return on.
    #: Zero for close. One for next_open, where the position is not sold until
    #: the following open and so carries that night's gap.
    exit_return_offset: int


def build(df: pd.DataFrame, signal: pd.Series, execution: str) -> Fills:
    """Apply an execution model to a signal series."""
    close = df["close"].astype(float)

    if execution == "close":
        position = lag(signal).astype(float)
        returns = close.pct_change().fillna(0.0)
        return Fills(
            name=execution,
            position=position,
            gross_returns=position * returns,
            # The change showing up on bar t was traded at the prior close.
            fill_prices=close.shift(1),
            fill_offset=-1,
            exit_return_offset=0,
        )

    if execution == "next_open":
        open_ = df["open"].astype(float)
        gap = (open_ / close.shift(1) - 1).fillna(0.0)
        session = (close / open_ - 1).fillna(0.0)

        # Held through bar t's session, having been filled at its open.
        position = lag(signal).astype(float)
        # Still held overnight into bar t's open, because the order to change
        # only executes at that open.
        prior = lag(signal, 2).astype(float)

        return Fills(
            name=execution,
            position=position,
            gross_returns=(1 + prior * gap) * (1 + position * session) - 1,
            fill_prices=open_,
            fill_offset=0,
            exit_return_offset=1,
        )

    raise NotImplementedError(f"execution={execution!r} is not implemented")
