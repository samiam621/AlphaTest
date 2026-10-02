"""Helpers for turning indicator conditions into a 0/1 signal (1 = hold, 0 = cash).

Strategies use from_state / from_events / cross_above / cross_below.
lag() is used by the engine (execution.build), not by strategies.
"""

import numpy as np
import pandas as pd

def from_state(condition: pd.Series) -> pd.Series:
    """State rule: hold whenever the condition is True (True -> 1, False -> 0)."""
    return condition.astype(int)

def from_events(entries:pd.Series, exits: pd.Series) -> pd.Series:
    """Event rule: go to 1 on an entry bar, back to 0 on an exit bar, keep the last value in between."""
    raw= pd.Series(np.nan, index=entries.index)
    raw[entries]=1
    raw[exits] = 0 #if entries and exit on same bar, exit wins
    return raw.ffill().fillna(0).astype(int)

def cross_above(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """True only on the bar where ``a`` moves from <= ``b`` to > ``b``.

    A one-time event, not a level: "RSI is below 30" is true for many bars,
    "RSI just crossed below 30" is true once. NaN compares as False, so no
    crosses fire while an indicator is still warming up.
    """
    prev_a, prev_b = a.shift(1), b.shift(1) if isinstance(b, pd.Series) else b
    return (a > b) & (prev_a <= prev_b)


def cross_below(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """True only on the bar where ``a`` moves from >= ``b`` to < ``b``."""
    prev_a, prev_b = a.shift(1), b.shift(1) if isinstance(b, pd.Series) else b
    return (a < b) & (prev_a >= prev_b)


def lag(signal: pd.Series, bars: int = 1) -> pd.Series:
    """Shift the signal forward by ``bars`` so it's acted on AFTER the bar that produced it.

    A signal made from today's close can't trade at a price you didn't know yet.
    Skipping this is "lookahead bias", the classic bug that makes every strategy
    look profitable. Called by execution.build, so no strategy can forget it.
    """
    return signal.shift(bars).fillna(0).astype(int)
