"""Rate-of-change momentum — buy what has been going up.

Hold while the price is more than ``threshold`` % above where it was ``period``
bars ago. The simplest momentum rule, so it's a good baseline. A threshold
above 0 avoids flipping in and out when the price is flat.

State rule.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.indicators import roc
from backend.app.strategies.signal_utils import from_state

NAME = "ROC Momentum"


@dataclass(frozen=True)
class RocMomentumParams:
    period: int = 12
    # In percent: 2.0 means "only hold if up more than 2% over the period".
    threshold: float = 0.0


def generate_signals(
    df: pd.DataFrame,
    params: RocMomentumParams | None = None,
) -> pd.DataFrame:
    """Return the ``roc`` series and a 0/1 ``signal`` column."""
    params = params or RocMomentumParams()

    momentum = roc(df["close"], params.period)
    return pd.DataFrame(
        {"roc": momentum, "signal": from_state(momentum > params.threshold)},
        index=df.index,
    )
