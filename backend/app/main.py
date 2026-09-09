import os
from dataclasses import asdict

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.backtest import engine, metrics, trades as trades_mod
from backend.app.backtest.config import build_config, describe_config
from backend.app.ingestion.yfinance_source import (
    VALID_INTERVALS,
    VALID_PERIODS,
    get_yf_data,
    to_records,
)
from backend.app.strategies import registry

app = FastAPI(title="AlphaTest")

# No trailing slashes
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    ""
]


origins += [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/api/health")
def health():
    """Liveness probe for the host's health check, and a cheap keep-warm ping."""
    return {"status": "ok"}


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


@app.get("/api/strategies")
def list_strategies():
    """Every strategy and its parameter schema.

    The UI calls this once to build its strategy picker and the parameter form
    that goes with it, so the form's fields and defaults come from the strategy
    dataclasses rather than being duplicated in the frontend.
    """
    return {"strategies": registry.catalogue()}


class BacktestRequest(BaseModel):
    """A strategy run: data selection, the rule, and the trading assumptions."""

    ticker: str
    start: str | None = None
    end: str | None = None
    period: str | None = None
    interval: str = "1d"
    auto_adjust: bool = True
    prepost: bool = False

    strategy: str = Field(..., description=f"One of: {', '.join(registry.SLUGS)}")
    # Whatever the user changed from the defaults. Anything left out keeps the
    # strategy's own default, so the frontend can send only the edited fields.
    params: dict = Field(default_factory=dict)
    # Capital and cost assumptions; same partial-override rules as params.
    config: dict = Field(default_factory=dict)

    # The bar-by-bar frame is the largest part of the response by far and the
    # metrics view does not need it. Ten years of hourly bars with indicator
    # columns runs to megabytes.
    include_bars: bool = True


@app.get("/api/backtest/config")
def backtest_config_schema():
    """Defaults and types for the trading assumptions, for the settings form."""
    return {"config": describe_config()}


@app.post("/api/backtest")
def run_backtest(req: BacktestRequest):
    """Run one strategy over one ticker and report how it would have done.

    The response has four parts: ``metrics`` (headline performance, including a
    buy-and-hold benchmark), ``equity`` (the curve, for charting), ``trades``
    (the round-trip ledger) and optionally ``bars`` (per-bar indicator values
    and positions).
    """
    try:
        strategy = registry.get(req.strategy)
    except registry.UnknownStrategyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        df = get_yf_data(
            ticker=req.ticker,
            start=req.start,
            end=req.end,
            period=req.period,
            interval=req.interval,
            auto_adjust=req.auto_adjust,
            prepost=req.prepost,
        )
        # Bad parameter names, un-coercible values, and the dataclasses' own
        # rules (fast < slow, thresholds in order) all surface as ValueError.
        signals, params = strategy.run(df, req.params)
        config = build_config(req.config)
        result = engine.run(df, signals["signal"], config, interval=req.interval)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        # A valid request for something not built yet — not the user's mistake.
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    curve = to_records(
        pd.DataFrame(
            {
                "equity": result.equity,
                "benchmark": result.benchmark_equity,
                # Saves the UI recomputing a running maximum to draw the
                # underwater chart.
                "drawdown": metrics.drawdown_series(result.equity),
            }
        )
    )

    response = {
        "ticker": req.ticker.strip().upper(),
        "interval": req.interval,
        "strategy": {"slug": strategy.slug, "name": strategy.name},
        # Echo the fully resolved settings, not just what was sent, so the
        # response states exactly what was run.
        "params": registry.params_as_dict(params),
        "config": asdict(config),
        "start": curve[0]["date"],
        "end": curve[-1]["date"],
        "count": len(curve),
        "metrics": result.metrics,
        "equity": curve,
        "trades": trades_mod.to_records(result.trades),
    }

    if req.include_bars:
        bars = signals.copy()
        bars["position"] = result.position
        response["bars"] = to_records(df.join(bars))

    return response
