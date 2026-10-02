"""Backtest engine: simulates trading a signal over past prices.

Input: price data + a signal from a strategy (1 = hold the stock, 0 = cash, -1 = short).
Output: equity curve (account value over time), list of trades, and stats.
It never imports a strategy, so any new strategy works without changing this file.

Steps inside run():
    1. execution.build   delay the signal by one bar -> position; per-bar returns
    2. costs             charge a fee on every bar where the position changes
    3. equity            starting money * running product of (1 + return)
    4. trades.extract    group the bars into individual trades
    5. metrics.summarize compute Sharpe, drawdown, CAGR, win rate, ...

Why the one-bar delay (avoids "lookahead bias" = using info you couldn't have had yet):
    signal_t     decided using bar t's closing price
    position_t   what we actually hold during bar t = signal_{t-1}
    return_t     position_t * (close_t / close_{t-1} - 1)   (for execution="close")
So a signal on bar t first makes or loses money on bar t+1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.app.backtest import execution as execution_mod
from backend.app.backtest import metrics as metrics_mod
from backend.app.backtest import trades as trades_mod
from backend.app.backtest.config import BacktestConfig, periods_per_year


@dataclass(frozen=True)
class BacktestResult:
    """What main.py needs from one run to build the JSON response."""

    equity: pd.Series
    metrics: dict[str, Any]
    #: One entry per trade, buy to sell (see trades.py).
    trades: list[trades_mod.Trade]


def _validate(df: pd.DataFrame, signal: pd.Series, config: BacktestConfig) -> None:
    """Reject bad input early: missing columns, mismatched rows, NaN or out-of-range signals."""
    if "close" not in df.columns:
        raise ValueError("price data needs a 'close' column to compute returns")
    if config.execution == "next_open" and "open" not in df.columns:
        raise ValueError("execution='next_open' needs an 'open' column")
    if not signal.index.equals(df.index):
        # Signal rows must line up with price rows one-to-one; refuse rather than guess.
        raise ValueError(
            f"signal index does not match the price index "
            f"({len(signal)} signal rows vs {len(df)} price rows)"
        )
    if signal.isna().any():
        raise ValueError(
            f"signal contains {int(signal.isna().sum())} NaN values; a strategy "
            f"must decide flat rather than undecided"
        )
    # -1 = short (bet on price falling), 0 = cash, 1 = fully invested.
    # Bigger than 1 would mean borrowing money, which isn't supported.
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
    """Run one backtest. Called by main.run_backtest."""
    config = config or BacktestConfig()
    _validate(df, signal, config)

    close = df["close"].astype(float)

    # 1. Signal -> position + return per bar. The one-bar delay happens in here.
    fills = execution_mod.build(df, signal, config.execution)
    position, gross_returns = fills.position, fills.gross_returns

    # 2. Fees: turnover = how much the position changed on each bar.
    # Bar 0 counts as a change from 0 to its starting position.
    turnover = position.diff().abs()
    turnover.iloc[0] = abs(position.iloc[0])
    costs = turnover * config.cost_rate

    net_returns = gross_returns - costs

    capital = config.initial_capital
    # 3. Equity grows by compounding each bar: E_t = C * Π_{i=1..t} (1 + r_i)
    # where r_i is the net return on bar i and C is the starting capital.
    equity = capital * (1 + net_returns).cumprod()
    # Gross equity ignores costs: G_t = C * Π_{i=1..t} (1 + g_i). Only used for cost drag.
    gross_equity = capital * (1 + gross_returns).cumprod()

    # 4. Trade list.
    ledger = trades_mod.extract(fills, net_returns, close, config.cost_rate)

    # 5. Stats. The still-open trade is left out of the trade stats, since its
    # result just depends on the day the data ends.
    ppy = periods_per_year(interval)
    summary = metrics_mod.summarize(
        equity,
        position,
        periods_per_year=ppy,
        risk_free_rate=config.risk_free_rate,
        trade_returns=trades_mod.returns(ledger),
    )

    gross_total = metrics_mod.total_return(gross_equity)
    net_total = summary["total_return"]
    # Cost drag = total return lost to fees (return without fees - return with fees).
    summary["cost_drag"] = (
        None if gross_total is None or net_total is None else gross_total - net_total
    )
    # Sum of all position changes. 2.0 = one full buy + sell.
    summary["turnover"] = float(turnover.sum())

    return BacktestResult(equity=equity, metrics=summary, trades=ledger)
