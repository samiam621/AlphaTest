"""Execution models: at what price and on which bar a trade actually happens.

Called by engine.run. Its output (Fills) is also passed to trades.extract, so
the equity curve and the trade list always agree on prices and timing.

"close"      Trade at the closing price of the bar that produced the signal.
             Return on bar t = position_t * (close_t / close_{t-1} - 1).
             Common, but a bit optimistic: you only know the close once it's over.

"next_open"  Trade at the next bar's opening price (more realistic). Each bar is
             split into two parts:
                 gap_t     = open_t / close_{t-1} - 1   overnight move, earned by the OLD position
                 session_t = close_t / open_t - 1       daytime move, earned by the NEW position
             If the position didn't change, gap * session = the normal close-to-close
             return, so only the buy and sell bars differ between the two models.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.signal_utils import lag


@dataclass(frozen=True)
class Fills:
    """Result of an execution model. engine uses the returns; trades uses the prices."""

    name: str
    #: What we hold during bar t.
    position: pd.Series
    #: Return earned on bar t, before fees.
    gross_returns: pd.Series
    #: Price paid when a position change takes effect on bar t.
    fill_prices: pd.Series
    #: Which bar the trade really happened on, relative to bar t:
    #: -1 for close (the previous close), 0 for next_open (this bar's open).
    fill_offset: int
    #: Extra bars a trade keeps earning after its last held bar. 0 for close.
    #: 1 for next_open: we only sell at the next open, so we still get the overnight move.
    exit_return_offset: int


def build(df: pd.DataFrame, signal: pd.Series, execution: str) -> Fills:
    """Turn a signal into positions, returns and fill prices. This is where the one-bar delay happens."""
    close = df["close"].astype(float)

    if execution == "close":
        position = lag(signal).astype(float)  # position is the signal delayed one bar
        returns = close.pct_change().fillna(0.0)
        return Fills(
            name=execution,
            position=position,
            gross_returns=position * returns,
            # A change that shows up on bar t was traded at the previous bar's close.
            fill_prices=close.shift(1),
            fill_offset=-1,
            exit_return_offset=0,
        )

    if execution == "next_open":
        open_ = df["open"].astype(float)
        gap = (open_ / close.shift(1) - 1).fillna(0.0)
        session = (close / open_ - 1).fillna(0.0)

        # Held during bar t's trading day (bought at its open).
        position = lag(signal).astype(float)
        # Held overnight going into bar t, since the order only fills at that open.
        prior = lag(signal, 2).astype(float)

        return Fills(
            name=execution,
            position=position,
            # Combine both parts: (1 + overnight) * (1 + daytime) - 1.
            gross_returns=(1 + prior * gap) * (1 + position * session) - 1,
            fill_prices=open_,
            fill_offset=0,
            exit_return_offset=1,
        )

    raise NotImplementedError(f"execution={execution!r} is not implemented")
