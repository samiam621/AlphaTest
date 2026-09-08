"""Bollinger band mean reversion — fade a stretch away from the average.

The bands sit a couple of standard deviations either side of a moving average,
so they widen when the market is volatile and tighten when it is calm. A close
below the lower band is a move that is large *relative to how much this market
has been moving lately*, and the bet is that it snaps back.

Entry: close crosses below the lower band.
Exit:  close crosses back above the middle band — the average itself, not the
       upper band. Taking the reversion to the mean is the trade; holding out
       for the opposite extreme is a different, much rarer one.

An *event* rule: between the bands there is no opinion, so position is carried.

Worth knowing: this has no stop. A genuine trend will keep riding the lower
band and the position sits in it the whole way down. TODO: Adding a time or price stop
to the exit condition is the natural next iteration.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import bollinger_bands
from backend.app.strategies.signal_utils import (
    cross_above,
    cross_below,
    from_events,
    require_columns,
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
    require_columns(df, ("close",))

    close = df["close"]
    bands = bollinger_bands(close, params.window, params.num_std)

    entries = cross_below(close, bands["lower"])
    exits = cross_above(close, bands["mid"])

    out = bands.copy()
    out["signal"] = from_events(entries, exits)
    return out
