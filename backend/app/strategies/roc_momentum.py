"""Rate-of-change momentum — buy what has been going up.

Hold while the price is more than ``threshold`` percent above where it was
``period`` bars ago. No averages, no smoothing: it is the bluntest statement of
momentum there is, which makes it a useful control to benchmark the others
against.

Raising the threshold above 0 demands the trend actually be worth something
before taking the trade, and cuts down on flip-flopping around flat markets.

A *state* rule.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import roc
from backend.app.strategies.signal_utils import from_state, require_columns

NAME = "ROC Momentum"


@dataclass(frozen=True)
class RocMomentumParams:
    period: int = 12
    # Percent, so 2.0 means "only hold if up more than 2% over the period".
    threshold: float = 0.0


def generate_signals(
    df: pd.DataFrame,
    params: RocMomentumParams | None = None,
) -> pd.DataFrame:
    """Return the ``roc`` series and a 0/1 ``signal`` column."""
    params = params or RocMomentumParams()
    require_columns(df, ("close",))

    momentum = roc(df["close"], params.period)
    return pd.DataFrame(
        {"roc": momentum, "signal": from_state(momentum > params.threshold)},
        index=df.index,
    )
