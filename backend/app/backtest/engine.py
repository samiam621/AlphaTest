"""Turn a position series into an equity curve.

The engine takes a price frame and a position series and knows nothing about
where the positions came from — no strategy is imported here. That keeps it
testable against hand-written signals, and means any strategy added later works
without touching this file.

The timing convention, which is the whole ballgame:

    signal_t     the strategy's decision, made from bar t's close
    position_t   what is held *during* bar t, which is signal_{t-1}
    return_t     close_t / close_{t-1} - 1

So ``position_t * return_t`` is the money made on bar t, and a signal on bar t
first earns on bar t+1. Under ``execution="close"`` this means the fill happened
at the close of bar t — the price that produced the decision. That is the
standard assumption and it is mildly optimistic; ``execution="next_open"``
(planned) is the honest version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.app.backtest import execution as execution_mod
from backend.app.backtest import metrics as metrics_mod
from backend.app.backtest import trades as trades_mod
from backend.app.backtest.config import BacktestConfig, periods_per_year


@dataclass(frozen=True)
class BacktestResult:
    """Everything one run produced. Series stay as pandas for the API to shape."""

    equity: pd.Series
    #: What the same money would have done just holding the asset. Cost-free,
    #: and always close-to-close from the first bar whatever the execution
    #: model: it is the "why bother" baseline, not a competing strategy.
    benchmark_equity: pd.Series
    #: The curve without trading costs — the gap to ``equity`` is the cost drag.
    gross_equity: pd.Series
    position: pd.Series
    gross_returns: pd.Series
    net_returns: pd.Series
    costs: pd.Series
    metrics: dict[str, Any]
    config: BacktestConfig
    interval: str
    #: Round-trip ledger, one entry per completed (or still-open) trade.
    trades: list[trades_mod.Trade] = field(default_factory=list)


def _validate(df: pd.DataFrame, signal: pd.Series, config: BacktestConfig) -> None:
    if "close" not in df.columns:
        raise ValueError("price data needs a 'close' column to compute returns")
    if config.execution == "next_open" and "open" not in df.columns:
        raise ValueError("execution='next_open' needs an 'open' column")
    if not signal.index.equals(df.index):
        # Reindexing silently would introduce NaN positions and quietly flatten
        # part of the backtest, which is far worse than refusing to run.
        raise ValueError(
            f"signal index does not match the price index "
            f"({len(signal)} signal rows vs {len(df)} price rows)"
        )
    if signal.isna().any():
        raise ValueError(
            f"signal contains {int(signal.isna().sum())} NaN values; a strategy "
            f"must decide flat rather than undecided"
        )
    # Long/flat today, but shorts (-1) and fractional sizing work unchanged.
    # Anything beyond +-1 implies borrowing, which there is no margin model for.
    if (signal.abs() > 1).any():
        raise ValueError(
            "signal values must be between -1 and 1; leverage is not modelled"
        )


def run(
    df: pd.DataFrame,
    signal: pd.Series,
    config: BacktestConfig | None = None,
    interval: str = "1d",
) -> BacktestResult:
    """Run one backtest over a price frame and a signal series.

    ``signal`` is the strategy's per-bar decision. The one-bar delay that turns
    it into a tradable position happens here, not in the strategy, so no
    strategy can forget it.
    """
    config = config or BacktestConfig()
    _validate(df, signal, config)

    close = df["close"].astype(float)

    # The execution model decides what each position earns and at what price it
    # was filled. Everything below is the same arithmetic either way.
    fills = execution_mod.build(df, signal, config.execution)
    position, gross_returns = fills.position, fills.gross_returns

    # Trading costs land on the bar where the position changed — the same bar
    # the fill happened on.
    turnover = position.diff().abs()
    turnover.iloc[0] = abs(position.iloc[0])
    costs = turnover * config.cost_rate

    net_returns = gross_returns - costs

    capital = config.initial_capital
    equity = capital * (1 + net_returns).cumprod()
    gross_equity = capital * (1 + gross_returns).cumprod()
    benchmark_equity = capital * close / close.iloc[0]

    ledger = trades_mod.extract(fills, net_returns, close, config.cost_rate)

    ppy = periods_per_year(interval)
    summary = metrics_mod.summarize(
        equity,
        position,
        periods_per_year=ppy,
        risk_free_rate=config.risk_free_rate,
        # The open trade is excluded: its "result" is just wherever the data
        # ended, and counting it would make the win rate depend on the run date.
        trade_returns=trades_mod.returns(ledger),
        benchmark_equity=benchmark_equity,
    )

    gross_total = metrics_mod.total_return(gross_equity)
    net_total = summary["total_return"]
    summary["gross_total_return"] = gross_total
    # Exactly what costs took off the top, rather than an estimate summed from
    # per-bar fractions that ignores compounding.
    summary["cost_drag"] = (
        None if gross_total is None or net_total is None else gross_total - net_total
    )
    # Total position turnover: 2.0 is one full round trip.
    summary["turnover"] = float(turnover.sum())

    return BacktestResult(
        equity=equity,
        benchmark_equity=benchmark_equity,
        gross_equity=gross_equity,
        position=position,
        gross_returns=gross_returns,
        net_returns=net_returns,
        costs=costs,
        metrics=summary,
        config=config,
        interval=interval,
        trades=ledger,
    )
