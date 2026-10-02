"""Backtest settings (BacktestConfig) and how many bars make up one year.

The bars-per-year number turns per-bar stats into yearly ones ("annualising"),
e.g. daily volatility -> yearly volatility. It comes from INTERVALS in yfinance_source.py.
Used by main.py (build_config, describe_config) and engine.py (periods_per_year).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.app import params as params_mod
from backend.app.ingestion.yfinance_source import INTERVALS

# See execution.py.
EXECUTION_MODELS = ("close", "next_open")


def periods_per_year(interval: str) -> float:
    """Bars per year for a bar size. Assumes regular market hours only."""
    try:
        return INTERVALS[interval][1]
    except KeyError:
        raise ValueError(
            f"cannot annualise {interval!r} bars; known intervals are "
            f"{', '.join(INTERVALS)}"
        ) from None


@dataclass(frozen=True)
class BacktestConfig:
    """Settings the user picks before a run: starting money, fees, when trades fill, risk-free rate."""

    initial_capital: float = 10_000.0

    # Trading fee per buy or sell, in basis points (1 bp = 0.01%).
    commission_bps: float = 0.0

    # "close":     trade at the closing price of the bar that gave the signal (common, a bit optimistic).
    # "next_open": trade at the next bar's opening price (more realistic). See execution.py.
    execution: str = field(default="close", metadata={"choices": EXECUTION_MODELS})

    # Yearly return of a "safe" investment, as a decimal (~US 10-year Treasury).
    # Sharpe/Sortino measure how much the strategy beats this.
    risk_free_rate: float = 0.04841

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError(
                f"initial_capital must be positive, got {self.initial_capital}"
            )
        bps = self.commission_bps
        if bps < 0:
            raise ValueError(f"commission_bps cannot be negative, got {bps}")
        if bps > 1_000:  # 10% per side: almost certainly a % typed as bps
            raise ValueError(
                f"commission_bps is {bps} bps ({bps / 100:.1f}% per side) — that "
                f"looks like a percentage entered as basis points"
            )
        if self.execution not in EXECUTION_MODELS:
            raise ValueError(
                f"execution must be one of {', '.join(EXECUTION_MODELS)}, "
                f"got {self.execution!r}"
            )
        # Must be a decimal: 0.04 = 4%. A value like 4 is a unit mix-up.
        if not -1 < self.risk_free_rate < 1:
            raise ValueError(
                f"risk_free_rate is a decimal, not a percentage — got "
                f"{self.risk_free_rate}, did you mean {self.risk_free_rate / 100}?"
            )

    @property
    def cost_rate(self) -> float:
        """Fee per buy or sell as a fraction (e.g. 10 bps -> 0.001). Used by engine and trades."""
        return self.commission_bps / 10_000


def build_config(values: Mapping[str, Any] | None = None) -> BacktestConfig:
    """Request JSON -> validated BacktestConfig (same rules as strategy params)."""
    return params_mod.build(BacktestConfig, values, "config")


def describe_config() -> list[dict[str, Any]]:
    """BacktestConfig schema for the UI's settings form."""
    return params_mod.describe(BacktestConfig)
