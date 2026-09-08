"""Moving average crossover
Long whenever the fast average is above the slow one. The fast average reacts
to recent bars sooner, so it sits above the slow one while price is trending up
and below it while trending down.

This is a *state* rule: the condition and the position are the same thing, so
there is nothing to remember between bars. Crossovers are just where the state
happens to flip.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backend.app.strategies.indicators import ema, sma
from backend.app.strategies.signal_utils import from_state, require_columns

NAME = "Moving Average Crossover"


@dataclass(frozen=True)
class MovingAverageCrossoverParams:
    fast: int = 20
    slow: int = 50
    # "sma" weights every bar in the window equally; "ema" leans on recent bars
    # and so turns a few bars sooner, at the cost of more whipsaws.
    # The metadata is what tells the registry to offer a dropdown rather than a
    # free-text box; __post_init__ below is what actually enforces it.
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
    """Return the two averages plus a 0/1 ``signal`` column, indexed like ``df``."""
    params = params or MovingAverageCrossoverParams()
    require_columns(df, ("close",))

    average = sma if params.ma_type == "sma" else ema
    fast = average(df["close"], params.fast)
    slow = average(df["close"], params.slow)

    # Both averages are NaN until the slow window fills, and NaN comparisons are
    # False, so the warm-up bars come out flat rather than accidentally long.
    return pd.DataFrame(
        {"fast": fast, "slow": slow, "signal": from_state(fast > slow)},
        index=df.index,
    )
