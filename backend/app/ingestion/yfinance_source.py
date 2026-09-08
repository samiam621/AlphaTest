"""Price data ingestion from Yahoo Finance.

User selects one of the rule-based strategies and sets its parameters — ticker, date range, and
strategy-specific inputs 

This handles the ticker, the date range and the bar size. 
Strategy-specific inputs are handled by the strategy layer

"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

# Bar sizes Yahoo will serve, mapped to how far back that bar size is available.
# None means "full history". Anything intraday is capped by Yahoo, so we check
# the user's date range against these before spending a request.
INTERVAL_MAX_LOOKBACK = {
    "1m": timedelta(days=30),
    "2m": timedelta(days=60),
    "5m": timedelta(days=60),
    "15m": timedelta(days=60),
    "30m": timedelta(days=60),
    "60m": timedelta(days=730),
    "90m": timedelta(days=60),
    "1h": timedelta(days=730),
    "1d": None,
    "5d": None,
    "1wk": None,
    "1mo": None,
    "3mo": None,
}

VALID_INTERVALS = tuple(INTERVAL_MAX_LOOKBACK)

# Shorthand ranges the user can pick instead of typing two dates.
VALID_PERIODS = (
    "1d", "5d", "1mo", "3mo", "6mo",
    "1y", "2y", "5y", "10y", "ytd", "max",
)

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class PriceRequest:
    """The data-selection parameters a user sets in the UI.

    Either give ``start``/``end``, or give ``period``. If neither is set the
    fetch defaults to one year of daily bars.
    """

    ticker: str
    start: date | str | None = None
    end: date | str | None = None
    period: str | None = None
    interval: str = "1d"
    # Split/dividend adjusted bars — what you almost always want to backtest on.
    auto_adjust: bool = True
    # Include pre/post market bars (intraday intervals only).
    prepost: bool = False


def _coerce_date(value: date | str | None, field: str) -> date | None:
    """Accept an ISO string or a date/datetime from the request body."""
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


def _validate(req: PriceRequest) -> tuple[date | None, date | None]:
    """Check the user's parameters before hitting the network."""
    if not req.ticker or not req.ticker.strip():
        raise ValueError("ticker is required")

    if req.interval not in INTERVAL_MAX_LOOKBACK:
        raise ValueError(
            f"interval {req.interval!r} is not supported; "
            f"pick one of {', '.join(VALID_INTERVALS)}"
        )

    if req.period is not None and req.period not in VALID_PERIODS:
        raise ValueError(
            f"period {req.period!r} is not supported; "
            f"pick one of {', '.join(VALID_PERIODS)}"
        )

    if req.period is not None and (req.start is not None or req.end is not None):
        raise ValueError("set either period or start/end, not both")

    start = _coerce_date(req.start, "start")
    end = _coerce_date(req.end, "end")

    if start is not None and end is not None and start >= end:
        raise ValueError(f"start ({start}) must be before end ({end})")

    today = datetime.now(timezone.utc).date()
    if start is not None and start > today:
        raise ValueError(f"start ({start}) is in the future")

    # Yahoo only keeps intraday bars for a limited window, so a user asking for
    # 1-minute bars from 2015 gets told why instead of an empty chart.
    max_lookback = INTERVAL_MAX_LOOKBACK[req.interval]
    if max_lookback is not None and start is not None:
        earliest = today - max_lookback
        if start < earliest:
            raise ValueError(
                f"{req.interval} bars only go back to {earliest} "
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
    """Fetch OHLCV bars for the parameters the user set.
    """
    return fetch(
        PriceRequest(
            ticker=ticker,
            start=start,
            end=end,
            period=period,
            interval=interval,
            auto_adjust=auto_adjust,
            prepost=prepost,
        )
    )


def fetch(req: PriceRequest) -> pd.DataFrame:
    """Same as :func:`get_yf_data`, but takes an already-built request."""
    start, end = _validate(req)
    symbol = req.ticker.strip().upper()

    params = {
        "interval": req.interval,
        "auto_adjust": req.auto_adjust,
        "prepost": req.prepost,
        # Dividends/splits come back as extra columns we drop below.
        "actions": False,
        "raise_errors": True,
    }

    if req.period is not None:
        params["period"] = req.period
    elif start is None and end is None:
        # 1yr default backtest window.
        params["period"] = "1y"
    else:
        params["start"] = start
        # yfinance treats end as exclusive, so bump it to include the user's
        # last day.
        params["end"] = end + timedelta(days=1) if end is not None else None

    try:
        history = yf.Ticker(symbol).history(**params)
    except Exception as exc:
        raise ValueError(f"could not fetch {symbol} from Yahoo Finance: {exc}") from exc

    if history is None or history.empty:
        raise ValueError(
            f"no {req.interval} data for {symbol} in the requested range — "
            f"check the ticker symbol and the dates"
        )

    return _normalize(history)


def _normalize(history: pd.DataFrame) -> pd.DataFrame:
    """Lowercase the columns, keep OHLCV, drop rows with no price."""
    df = history.rename(columns=str.lower)
    df = df[[c for c in OHLCV_COLUMNS if c in df.columns]].copy()
    df.index.name = "date"
    df = df.dropna(subset=[c for c in ("open", "high", "low", "close") if c in df])
    return df.sort_index()


def to_records(df: pd.DataFrame) -> list[dict]:
    """JSON-serialisable rows for the API response."""
    out = df.reset_index()
    out["date"] = out["date"].apply(lambda ts: ts.isoformat())
    return out.to_dict(orient="records")
