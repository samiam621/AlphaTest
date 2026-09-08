from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.app.ingestion.yfinance_source import (
    VALID_INTERVALS,
    VALID_PERIODS,
    get_yf_data,
    to_records,
)

app = FastAPI(title="Trading Backtester")

# No trailing slashes — CORS origins are matched exactly, so "http://localhost:5173/"
# would never match the browser's "http://localhost:5173" Origin header.
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/api/data")
def get_data(
    ticker: str = Query(..., description="Symbol to backtest, e.g. AAPL"),
    start: str | None = Query(None, description="Start date, YYYY-MM-DD"),
    end: str | None = Query(None, description="End date (inclusive), YYYY-MM-DD"),
    period: str | None = Query(
        None, description=f"Shorthand range instead of start/end: {', '.join(VALID_PERIODS)}"
    ),
    interval: str = Query("1d", description=f"Bar size: {', '.join(VALID_INTERVALS)}"),
    auto_adjust: bool = Query(True, description="Split/dividend adjusted prices"),
    prepost: bool = Query(False, description="Include pre/post market bars"),
):
    """OHLCV bars for the parameters the user picked in the UI."""
    try:
        df = get_yf_data(
            ticker=ticker,
            start=start,
            end=end,
            period=period,
            interval=interval,
            auto_adjust=auto_adjust,
            prepost=prepost,
        )
    except ValueError as exc:
        # Bad ticker, bad dates, unsupported interval — the user's input, not our bug.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    bars = to_records(df)
    return {
        "ticker": ticker.strip().upper(),
        "interval": interval,
        "start": bars[0]["date"],
        "end": bars[-1]["date"],
        "count": len(bars),
        "bars": bars,
    }
