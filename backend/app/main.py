from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.ingestion.yfinance_source import (
    VALID_INTERVALS,
    VALID_PERIODS,
    get_yf_data,
    to_records,
)
from backend.app.strategies import registry
from backend.app.strategies.signal_utils import lag

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


@app.get("/api/strategies")
def list_strategies():
    """Every strategy and its parameter schema.

    The UI calls this once to build its strategy picker and the parameter form
    that goes with it, so the form's fields and defaults come from the strategy
    dataclasses rather than being duplicated in the frontend.
    """
    return {"strategies": registry.catalogue()}


class BacktestRequest(BaseModel):
    """A strategy run: the same data selection as /api/data, plus the rule."""

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


@app.post("/api/backtest")
def run_backtest(req: BacktestRequest):
    """Run one strategy over one ticker and return the bars it decided on.

    Each bar carries the strategy's indicator values, the ``signal`` it decided
    on using that bar's close, and the ``position`` that signal can actually be
    traded at — one bar later, because the close used to make the decision had
    already happened by the time you saw it.
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    signals = signals.copy()
    signals["position"] = lag(signals["signal"])
    bars = to_records(df.join(signals))

    return {
        "ticker": req.ticker.strip().upper(),
        "interval": req.interval,
        "strategy": {"slug": strategy.slug, "name": strategy.name},
        # Echo the full resolved parameter set, not just what was sent, so the
        # response says exactly what was run.
        "params": registry.params_as_dict(params),
        "start": bars[0]["date"],
        "end": bars[-1]["date"],
        "count": len(bars),
        "trades": int((signals["signal"].diff() == 1).sum()),
        "bars": bars,
    }
