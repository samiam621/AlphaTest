"""FastAPI entry point: the HTTP layer between the React UI and the backtester.

Flow of POST /api/backtest (the main endpoint):
    registry.get(slug)          find the strategy by name          strategies/registry.py
    get_yf_data(...)            download price bars from Yahoo     ingestion/yfinance_source.py
    strategy.run(df, params)    indicators -> buy/sell signal      strategies/*.py
    build_config(config)        money, fees, fill settings         backtest/config.py
    engine.run(df, signal, ...) simulate -> equity, trades, stats  backtest/engine.py
    -> JSON response

A "bar" = one row of price data (open, high, low, close, volume) for one time
step, e.g. one day. OHLCV is short for those five columns.
"""

import os
from dataclasses import asdict

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.backtest import engine, metrics, trades as trades_mod
from backend.app.backtest.config import build_config, describe_config
from backend.app.ingestion.yfinance_source import get_yf_data, to_records
from backend.app.strategies import registry

app = FastAPI(title="AlphaTest")

# Browser origins allowed to call this API (CORS): the local Vite dev server,
# plus any listed in the CORS_ORIGINS env var (comma-separated, no trailing slash).
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
    """Health check that Render pings (healthCheckPath in render.yaml)."""
    return {"status": "ok"}


@app.get("/api/strategies")
def list_strategies():
    """Every strategy and its param schema. The UI builds its strategy picker and form from this."""
    return {"strategies": registry.catalogue()}


class BacktestRequest(BaseModel):
    """Body of POST /api/backtest: which data, which strategy, and the trading settings."""

    ticker: str
    start: str | None = None
    end: str | None = None
    period: str | None = None
    interval: str = "1d"
    auto_adjust: bool = True
    prepost: bool = False

    strategy: str = Field(..., description=f"One of: {', '.join(registry.SLUGS)}")
    # Only the params the user changed; anything missing uses the strategy's default.
    params: dict = Field(default_factory=dict)
    # Same idea for BacktestConfig (capital, commission, execution, risk-free rate).
    config: dict = Field(default_factory=dict)


@app.get("/api/backtest/config")
def backtest_config_schema():
    """BacktestConfig fields and defaults, so the UI can render the settings form."""
    return {"config": describe_config()}


@app.post("/api/backtest")
def run_backtest(req: BacktestRequest):
    """Run one strategy on one ticker. This is the endpoint the UI calls for each run.

    Returns ``metrics`` (headline stats), ``equity`` (curve + drawdown, for charts)
    and ``trades`` (one row per trade, for the Trade Log).
    """
    try:
        # Unknown strategy, bad ticker/dates, bad param names or types, and rule
        # violations (e.g. fast >= slow) all raise ValueError -> 400 with a readable message.
        strategy = registry.get(req.strategy)
        df = get_yf_data(
            ticker=req.ticker,
            start=req.start,
            end=req.end,
            period=req.period,
            interval=req.interval,
            auto_adjust=req.auto_adjust,
            prepost=req.prepost,
        )
        signals, params = strategy.run(df, req.params)
        config = build_config(req.config)
        result = engine.run(df, signals["signal"], config, interval=req.interval)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        # Valid request for something not supported yet -> 501.
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    curve = to_records(
        pd.DataFrame(
            {
                "equity": result.equity,
                # Precomputed so the UI can draw the drawdown chart directly.
                "drawdown": metrics.drawdown_series(result.equity),
            }
        )
    )

    return {
        "ticker": req.ticker.strip().upper(),
        "interval": req.interval,
        "strategy": {"slug": strategy.slug, "name": strategy.name},
        # Echo the resolved settings (defaults filled in) so the response shows exactly what ran.
        "params": asdict(params),
        "config": asdict(config),
        "start": curve[0]["date"],
        "end": curve[-1]["date"],
        "count": len(curve),
        "metrics": result.metrics,
        "equity": curve,
        "trades": trades_mod.to_records(result.trades),
    }
