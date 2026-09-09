"""Backtest settings, and the bar-size arithmetic that annualising depends on.

Nothing here touches prices. It holds the knobs a user turns before a run, plus
the interval -> bars-per-year table that every annualised metric needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.app import params as params_mod
from backend.app.ingestion.yfinance_source import VALID_INTERVALS

# Trading days in a year, and the length of a regular US equity session. Every
# intraday figure below is derived from these two rather than written out, so
# the relationship between them stays visible.
TRADING_DAYS_PER_YEAR = 252
SESSION_MINUTES = 390  # 09:30-16:00

#: How many bars of a given size a year contains. Sharpe, volatility and CAGR
#: are all "per year" numbers, and getting this wrong silently scales them by a
#: constant — a 1-hour Sharpe annualised at 252 is off by a factor of ~2.5.
PERIODS_PER_YEAR: dict[str, float] = {
    "1m": TRADING_DAYS_PER_YEAR * SESSION_MINUTES,
    "2m": TRADING_DAYS_PER_YEAR * SESSION_MINUTES / 2,
    "5m": TRADING_DAYS_PER_YEAR * SESSION_MINUTES / 5,
    "15m": TRADING_DAYS_PER_YEAR * SESSION_MINUTES / 15,
    "30m": TRADING_DAYS_PER_YEAR * SESSION_MINUTES / 30,
    "60m": TRADING_DAYS_PER_YEAR * SESSION_MINUTES / 60,
    "90m": TRADING_DAYS_PER_YEAR * SESSION_MINUTES / 90,
    "1h": TRADING_DAYS_PER_YEAR * SESSION_MINUTES / 60,
    "1d": TRADING_DAYS_PER_YEAR,
    "5d": TRADING_DAYS_PER_YEAR / 5,
    "1wk": 52.0,
    "1mo": 12.0,
    "3mo": 4.0,
}

# The two tables have to agree: an interval the user can fetch but not annualise
# would fail at request time instead of here. Fail at import instead.
_missing = set(VALID_INTERVALS) - set(PERIODS_PER_YEAR)
if _missing:
    raise RuntimeError(
        f"PERIODS_PER_YEAR is missing interval(s) {sorted(_missing)} that "
        f"yfinance_source will happily fetch"
    )

EXECUTION_MODELS = ("close", "next_open")


def periods_per_year(interval: str) -> float:
    """Bars per year for a bar size, for annualising returns and volatility.

    Intraday figures assume a regular session — ``prepost=True`` bars are more
    numerous than this says, which slightly overstates annualised numbers.
    """
    try:
        return PERIODS_PER_YEAR[interval]
    except KeyError:
        raise ValueError(
            f"cannot annualise {interval!r} bars; known intervals are "
            f"{', '.join(PERIODS_PER_YEAR)}"
        ) from None


@dataclass(frozen=True)
class BacktestConfig:
    """What the user sets before a run — capital, costs, and fill assumptions."""

    initial_capital: float = 10_000.0

    # Per side, in basis points (1 bp = 0.01%). A round trip pays both of these
    # twice: once getting in, once getting out.
    commission_bps: float = 0.0
    # The gap between the price you modelled and the price you got. Kept apart
    # from commission because they are worth tuning independently.
    slippage_bps: float = 0.0

    # "close"     — fill at the close of the bar that produced the signal.
    #               Standard, and slightly optimistic: you are trading at a
    #               price you only knew once the bar was over.
    # "next_open" — fill at the next bar's open. More honest about what was
    #               actually reachable.
    execution: str = field(default="close", metadata={"choices": EXECUTION_MODELS})

    # risk_free_rate of U.S 10 year treasury as default
    risk_free_rate: float = 0.04841

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError(
                f"initial_capital must be positive, got {self.initial_capital}"
            )
        for name in ("commission_bps", "slippage_bps"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} cannot be negative, got {value}")
            if value > 1_000:  # 10% per side
                raise ValueError(
                    f"{name} is {value} bps ({value / 100:.1f}% per side) — that "
                    f"looks like a percentage entered as basis points"
                )
        if self.execution not in EXECUTION_MODELS:
            raise ValueError(
                f"execution must be one of {', '.join(EXECUTION_MODELS)}, "
                f"got {self.execution!r}"
            )
        # 0.04 is 4%; 4 would be 400% and is almost certainly a unit mix-up.
        if not -1 < self.risk_free_rate < 1:
            raise ValueError(
                f"risk_free_rate is a decimal, not a percentage — got "
                f"{self.risk_free_rate}, did you mean {self.risk_free_rate / 100}?"
            )

    @property
    def cost_rate(self) -> float:
        """Cost of one side of a trade, as a fraction of the traded value."""
        return (self.commission_bps + self.slippage_bps) / 10_000


def build_config(values: Mapping[str, Any] | None = None) -> BacktestConfig:
    """Build a config from partial user input, the way strategy params are built.

    Unknown keys are rejected and values are coerced before ``__post_init__``
    gets to enforce the ranges.
    """
    return params_mod.build(BacktestConfig, values, "config")


def describe_config() -> list[dict[str, Any]]:
    """The config schema, so a UI can render the settings form from one source."""
    return params_mod.describe(BacktestConfig)
