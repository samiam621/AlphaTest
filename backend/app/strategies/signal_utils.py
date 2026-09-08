

import numpy as np
import pandas as pd

def from_state(condition: pd.Series) -> pd.Series:
    return condition.astype(int)

def from_events(entries:pd.Series, exits: pd.Series) -> pd.Series:
    raw= pd.Series(np.nan, index=entries.index)
    raw[entries]=1
    raw[exits] = 0 #if entries and exit on same bar, exit wins
    return raw.ffill().fillna(0).astype(int)

def cross_above(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """True only on the bar where ``a`` goes from at-or-below ``b`` to above it.

    The previous-bar half is the whole point: "RSI is below 30" is true on every
    bar of a selloff, but "RSI just crossed below 30" is true once. Comparisons
    against NaN are False, so no crossing is reported during an indicator's
    warm-up.
    """
    prev_a, prev_b = a.shift(1), b.shift(1) if isinstance(b, pd.Series) else b
    return (a > b) & (prev_a <= prev_b)


def cross_below(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """True only on the bar where ``a`` goes from at-or-above ``b`` to below it."""
    prev_a, prev_b = a.shift(1), b.shift(1) if isinstance(b, pd.Series) else b
    return (a < b) & (prev_a >= prev_b)


def require_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    """Fail loudly if the price frame is missing something the strategy needs."""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(
            f"price data is missing required column(s): {', '.join(missing)}; "
            f"got {', '.join(map(str, df.columns))}"
        )


def lag(signal: pd.Series, bars: int = 1) -> pd.Series:
    """Delay a signal so it is acted on *after* the bar that produced it.

    Strategies return the position they decided on using a bar's close. You
    could not have traded that close, so the backtest engine — not the strategy —
    shifts the series before pairing it with returns. Skipping this is the
    classic lookahead bug that makes every strategy look profitable.
    """
    return signal.shift(bars).fillna(0).astype(int)
