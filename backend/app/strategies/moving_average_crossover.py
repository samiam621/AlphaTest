"""Moving average crossover
Hold while the fast (short-window) average is above the slow (long-window) one.
The fast average reacts to new prices sooner, so it's on top during uptrends
and below during downtrends.

State rule: the condition itself is the position; nothing to remember between bars.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backend.app.strategies.indicators import ema, sma
from backend.app.strategies.signal_utils import from_state

NAME = "Moving Average Crossover"


@dataclass(frozen=True)
class MovingAverageCrossoverParams:
    fast: int = 20
    slow: int = 50
    # "sma" weights all bars equally; "ema" favours recent bars (reacts sooner,
    # but gives more false signals). "choices" makes the UI show a dropdown.
    ma_type: str = field(default="sma", metadata={"choices": ("sma", "ema")})

    def __post_init__(self) -> None:
        if self.fast >= self.slow:
            raise ValueError(
                f"fast ({self.fast}) must be shorter than slow ({self.slow}) — "
                f"otherwise the 'fast' average is the slower of the two"
            )
        if self.ma_type not in ("sma", "ema"):
            raise ValueError(f"ma_type must be 'sma' or 'ema', got {self.ma_type!r}")


def generate_signals(
    df: pd.DataFrame,
    params: MovingAverageCrossoverParams | None = None,
) -> pd.DataFrame:
    """Return the two averages plus a 0/1 ``signal`` column."""
    params = params or MovingAverageCrossoverParams()

    average = sma if params.ma_type == "sma" else ema
    fast = average(df["close"], params.fast)
    slow = average(df["close"], params.slow)

    # While either average is still NaN (warm-up), the comparison is False, so those bars stay 0.
    return pd.DataFrame(
        {"fast": fast, "slow": slow, "signal": from_state(fast > slow)},
        index=df.index,
    )
