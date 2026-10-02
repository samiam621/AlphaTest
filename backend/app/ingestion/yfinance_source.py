"""Downloads price data from Yahoo Finance (via the yfinance library).

Called by main.py: get_yf_data() fetches the bars, to_records() turns them into JSON.
Checks the ticker, dates and bar size first, so a bad request gets a clear
error message instead of an empty chart.
"""

import math
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

# A US trading year: 252 days of 390-minute sessions (09:30-16:00).
TRADING_DAYS_PER_YEAR = 252
SESSION_MINUTES = 390
MINUTES_PER_YEAR = TRADING_DAYS_PER_YEAR * SESSION_MINUTES

# Every allowed bar size -> (how far back Yahoo keeps it, bars per year).
# Lookback None = all history; Yahoo only keeps minute/hour bars for a limited time.
# Bars per year turns per-bar stats into yearly ones (see backtest/config.py).
INTERVALS: dict[str, tuple[timedelta | None, float]] = {
    "1m": (timedelta(days=30), MINUTES_PER_YEAR),
    "2m": (timedelta(days=60), MINUTES_PER_YEAR / 2),
    "5m": (timedelta(days=60), MINUTES_PER_YEAR / 5),
    "15m": (timedelta(days=60), MINUTES_PER_YEAR / 15),
    "30m": (timedelta(days=60), MINUTES_PER_YEAR / 30),
    "60m": (timedelta(days=730), MINUTES_PER_YEAR / 60),
    "90m": (timedelta(days=60), MINUTES_PER_YEAR / 90),
    "1h": (timedelta(days=730), MINUTES_PER_YEAR / 60),
    "1d": (None, TRADING_DAYS_PER_YEAR),
    "5d": (None, TRADING_DAYS_PER_YEAR / 5),
    "1wk": (None, 52.0),
    "1mo": (None, 12.0),
    "3mo": (None, 4.0),
}

VALID_INTERVALS = tuple(INTERVALS)

# Preset date ranges the user can pick instead of typing start/end dates.
VALID_PERIODS = (
    "1d", "5d", "1mo", "3mo", "6mo",
    "1y", "2y", "5y", "10y", "ytd", "max",
)

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


def _coerce_date(value: date | str | None, field: str) -> date | None:
    """Parse a 'YYYY-MM-DD' string into a date (dates pass straight through)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{field} must be a YYYY-MM-DD date, got {value!r}")


def _validate(
    ticker: str,
    start: date | str | None,
    end: date | str | None,
    period: str | None,
    interval: str,
) -> tuple[date | None, date | None]:
    """Check the request before calling Yahoo. Returns start/end as dates; raises ValueError if invalid."""
    if not ticker or not ticker.strip():
        raise ValueError("ticker is required")

    if interval not in INTERVALS:
        raise ValueError(
            f"interval {interval!r} is not supported; "
            f"pick one of {', '.join(VALID_INTERVALS)}"
        )

    if period is not None and period not in VALID_PERIODS:
        raise ValueError(
            f"period {period!r} is not supported; "
            f"pick one of {', '.join(VALID_PERIODS)}"
        )

    if period is not None and (start is not None or end is not None):
        raise ValueError("set either period or start/end, not both")

    start = _coerce_date(start, "start")
    end = _coerce_date(end, "end")

    if start is not None and end is not None and start >= end:
        raise ValueError(f"start ({start}) must be before end ({end})")

    today = datetime.now(timezone.utc).date()
    if start is not None and start > today:
        raise ValueError(f"start ({start}) is in the future")

    # e.g. 1-minute bars from 2015 don't exist on Yahoo; say so instead of returning nothing.
    max_lookback = INTERVALS[interval][0]
    if max_lookback is not None and start is not None:
        earliest = today - max_lookback
        if start < earliest:
            raise ValueError(
                f"{interval} bars only go back to {earliest} "
                f"({max_lookback.days} days); requested start was {start}. "
                f"Use a later start date or a larger interval."
            )

    return start, end


def get_yf_data(
    ticker: str,
    start: date | str | None = None,
    end: date | str | None = None,
    period: str | None = None,
    interval: str = "1d",
    auto_adjust: bool = True,
    prepost: bool = False,
) -> pd.DataFrame:
    """Validate -> download from Yahoo -> clean up. Returns one row per bar.

    Give start/end OR period; if neither, the last 1 year.
    auto_adjust: prices adjusted for stock splits and dividends (what you want for backtests).
    prepost: include pre/after-market bars (only for minute/hour bars).
    """
    start, end = _validate(ticker, start, end, period, interval)
    symbol = ticker.strip().upper()

    params = {
        "interval": interval,
        "auto_adjust": auto_adjust,
        "prepost": prepost,
        # Don't return dividend/split columns.
        "actions": False,
        "raise_errors": True,
    }

    if period is not None:
        params["period"] = period
    elif start is None and end is None:
        # No range given: default to the last 1 year.
        params["period"] = "1y"
    else:
        params["start"] = start
        # yfinance excludes the end date, so add a day to include it.
        params["end"] = end + timedelta(days=1) if end is not None else None

    try:
        history = yf.Ticker(symbol).history(**params)
    except Exception as exc:
        raise ValueError(f"could not fetch {symbol} from Yahoo Finance: {exc}") from exc

    if history is None or history.empty:
        raise ValueError(
            f"no {interval} data for {symbol} in the requested range — "
            f"check the ticker symbol and the dates"
        )

    return _normalize(history)


def _normalize(history: pd.DataFrame) -> pd.DataFrame:
    """Lowercase column names, keep only OHLCV, drop rows with no price, sort by date."""
    df = history.rename(columns=str.lower)
    df = df[[c for c in OHLCV_COLUMNS if c in df.columns]].copy()
    df.index.name = "date"
    df = df.dropna(subset=[c for c in ("open", "high", "low", "close") if c in df])
    return df.sort_index()


def to_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> list of dicts for JSON. NaN becomes None, because JSON has no NaN
    and the browser would reject the response.
    """
    out = df.reset_index()
    out["date"] = out["date"].apply(lambda ts: ts.isoformat())
    return [
        {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()}
        for row in out.to_dict(orient="records")
    ]
