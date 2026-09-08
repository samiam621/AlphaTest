"""Indicator math.

Pure functions: prices in, indicator series out. Nothing in here knows about
positions, entries or exits — that lives in the strategy modules.

Two rules every function follows:

* the result keeps the caller's index, so it lines up with the bars it came from
* the warm-up period stays NaN instead of being filled with a half-computed
  value. A 20-day SMA does not exist on day 3, and pretending it does is how a
  backtest ends up trading on numbers a live system would never have had.

Indicators with more than one output return a DataFrame with named columns
rather than a tuple, so a strategy can join them straight onto its output.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _window(value: int, name: str) -> int:
    """Windows are bar counts — reject anything that isn't a positive whole number."""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive whole number of bars, got {value!r}")
    return int(value)


def sma(series: pd.Series, window: int) -> pd.Series:
    """simple moving average"""
    window = _window(window, "window")
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """exponential moving average with the standard 2/(span+1) smoothing.
    """
    span = _window(span, "span")
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index, 0-100, using Wilder's smoothing.
    """
    period = _window(period, "period")

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    out = 100 - (100 / (1 + avg_gain / avg_loss))

    # A stretch with no down bars divides by zero. Textbook RSI is 100 there
    # (pure gains), and 50 — neutral — if the price simply never moved.
    out = out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    out = out.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return out


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD line, its signal line, and the histogram between them.

    Columns: ``macd``, ``signal``, ``hist``.
    """
    fast = _window(fast, "fast")
    slow = _window(slow, "slow")
    signal = _window(signal, "signal")
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be shorter than slow ({slow})")

    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line.dropna(), signal).reindex(close.index)
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": macd_line - signal_line}
    )


def bollinger_bands(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    """Moving average with bands ``num_std`` standard deviations either side.

    Columns: ``lower``, ``mid``, ``upper``.
    """
    window = _window(window, "window")
    if num_std <= 0:
        raise ValueError(f"num_std must be positive, got {num_std!r}")

    mid = sma(close, window)
    # ddof=0 (population) is what Bollinger defined and what charts draw;
    # pandas defaults to ddof=1, which would give slightly wider bands.
    spread = close.rolling(window=window, min_periods=window).std(ddof=0) * num_std
    return pd.DataFrame({"lower": mid - spread, "mid": mid, "upper": mid + spread})


def donchian_channel(high: pd.Series, low: pd.Series, window: int = 20) -> pd.DataFrame:
    """Highest high and lowest low of the last ``window`` bars.

    Columns: ``lower``, ``mid``, ``upper``. The window *includes* the current
    bar, which is what you want to plot. A breakout rule must compare against
    the channel as it stood before the current bar — see the shift in
    ``donchian_channel_breakout``.
    """
    window = _window(window, "window")
    upper = high.rolling(window=window, min_periods=window).max()
    lower = low.rolling(window=window, min_periods=window).min()
    return pd.DataFrame({"lower": lower, "mid": (upper + lower) / 2, "upper": upper})


def roc(close: pd.Series, period: int = 12) -> pd.Series:
    """Rate of change over ``period`` bars, in percent."""
    period = _window(period, "period")
    return 100 * (close / close.shift(period) - 1)


def stochastic_oscillator(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    smooth_k: int = 3,
    d_period: int = 3,
) -> pd.DataFrame:
    """Where the close sits inside the recent high-low range, 0-100.

    Columns: ``k`` (smoothed %K) and ``d`` (its moving average). The default
    ``smooth_k=3`` gives the "slow" stochastic; pass ``smooth_k=1`` for fast.
    """
    k_period = _window(k_period, "k_period")
    smooth_k = _window(smooth_k, "smooth_k")
    d_period = _window(d_period, "d_period")

    lowest = low.rolling(window=k_period, min_periods=k_period).min()
    highest = high.rolling(window=k_period, min_periods=k_period).max()
    span = highest - lowest

    raw_k = 100 * (close - lowest) / span
    # A perfectly flat window has no range to be positioned in; call it neutral
    # instead of letting the divide-by-zero through as inf.
    raw_k = raw_k.mask(span == 0, 50.0)

    k = raw_k.rolling(window=smooth_k, min_periods=smooth_k).mean()
    return pd.DataFrame({"k": k, "d": k.rolling(window=d_period, min_periods=d_period).mean()})
