"""Technical indicators: formulas traders run on price history (moving averages, RSI, MACD, ...).

Pure math used by the strategy files: prices in, indicator series out.
Two rules:
* Output has the same index (dates) as the input, so it lines up with the prices.
* The first few bars stay NaN until there's enough data ("warm-up"). A 20-bar
  average doesn't exist on bar 3; filling it in would let the backtest trade
  on numbers that couldn't exist yet.
Indicators with several lines return a DataFrame with named columns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _window(value: int, name: str) -> int:
    """Check a window length (number of bars) is a positive whole number."""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive whole number of bars, got {value!r}")
    return int(value)


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average: plain average of the last ``window`` values."""
    window = _window(window, "window")
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average: like SMA but recent bars count more (weight 2/(span+1))."""
    span = _window(span, "span")
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index), 0-100: compares average gains to average losses.

    Above 70 = "overbought" (rose a lot), below 30 = "oversold" (fell a lot).
    Uses Wilder's smoothing, a type of exponential average.
    """
    period = _window(period, "period")

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    out = 100 - (100 / (1 + avg_gain / avg_loss))

    # No losses = divide by zero. Standard answer: 100 if it only went up,
    # 50 (neutral) if the price never moved.
    out = out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    out = out.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return out


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD: fast EMA - slow EMA, plus a "signal" line (EMA of MACD) and their gap ("hist").

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
    """Bollinger Bands: a moving average with bands ``num_std`` standard deviations above and below.

    Bands widen when prices are jumpy, narrow when calm. Columns: ``lower``, ``mid``, ``upper``.
    """
    window = _window(window, "window")
    if num_std <= 0:
        raise ValueError(f"num_std must be positive, got {num_std!r}")

    mid = sma(close, window)
    # ddof=0 (population std dev) is the standard Bollinger definition.
    spread = close.rolling(window=window, min_periods=window).std(ddof=0) * num_std
    return pd.DataFrame({"lower": mid - spread, "mid": mid, "upper": mid + spread})


def donchian_channel(high: pd.Series, low: pd.Series, window: int = 20) -> pd.DataFrame:
    """Donchian Channel: highest high and lowest low of the last ``window`` bars.

    Columns: ``lower``, ``mid``, ``upper``. Includes the current bar, so the
    breakout strategy shifts it back one bar before comparing.
    """
    window = _window(window, "window")
    upper = high.rolling(window=window, min_periods=window).max()
    lower = low.rolling(window=window, min_periods=window).min()
    return pd.DataFrame({"lower": lower, "mid": (upper + lower) / 2, "upper": upper})


def roc(close: pd.Series, period: int = 12) -> pd.Series:
    """Rate of change: % price change compared to ``period`` bars ago."""
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
    """Stochastic oscillator, 0-100: where the close sits between the recent low (0) and high (100).

    Columns: ``k`` (smoothed %K) and ``d`` (moving average of %K).
    smooth_k=3 is the common "slow" version; smooth_k=1 is the raw "fast" one.
    """
    k_period = _window(k_period, "k_period")
    smooth_k = _window(smooth_k, "smooth_k")
    d_period = _window(d_period, "d_period")

    lowest = low.rolling(window=k_period, min_periods=k_period).min()
    highest = high.rolling(window=k_period, min_periods=k_period).max()
    span = highest - lowest

    raw_k = 100 * (close - lowest) / span
    # Flat range (high == low) would divide by zero; call it 50 (neutral).
    raw_k = raw_k.mask(span == 0, 50.0)

    k = raw_k.rolling(window=smooth_k, min_periods=smooth_k).mean()
    return pd.DataFrame({"k": k, "d": k.rolling(window=d_period, min_periods=d_period).mean()})
