"""Bollinger band mean reversion — fade a stretch away from the average.

"Fade" = bet against the move. The bands sit a few standard deviations around
a moving average, so a close below the lower band is an unusually big drop
for this stock right now. The bet is that it bounces back.

Entry: close crosses below the lower band.
Exit:  close crosses back above the middle band (the average).

Event rule: between the bands there's no opinion, so the position carries forward.
No stop-loss: in a real crash it holds all the way down.
TODO: add a time or price stop to the exit.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import bollinger_bands
from backend.app.strategies.signal_utils import (
    cross_above,
    cross_below,
    from_events,
)

NAME = "Bollinger Band Mean Reversion"


@dataclass(frozen=True)
class BollingerMeanReversionParams:
    window: int = 20
    num_std: float = 2.0

    def __post_init__(self) -> None:
        if self.num_std <= 0:
            raise ValueError(f"num_std must be positive, got {self.num_std}")


def generate_signals(
    df: pd.DataFrame,
    params: BollingerMeanReversionParams | None = None,
) -> pd.DataFrame:
    """Return ``lower``/``mid``/``upper`` bands and a 0/1 ``signal`` column."""
    params = params or BollingerMeanReversionParams()

    close = df["close"]
    bands = bollinger_bands(close, params.window, params.num_std)

    entries = cross_below(close, bands["lower"])
    exits = cross_above(close, bands["mid"])

    out = bands.copy()
    out["signal"] = from_events(entries, exits)
    return out
