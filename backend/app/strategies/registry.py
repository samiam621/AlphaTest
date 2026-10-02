"""Strategy lookup table: maps a name like "rsi_threshold" to its strategy module.

main.py only reaches strategies through this file:
    get(slug)     -> one Strategy, used by POST /api/backtest
    catalogue()   -> every strategy + its settings, for GET /api/strategies
Adding a strategy = write the module, then add one _register(...) line below.

The UI form for each strategy is generated from its params dataclass (via
params.describe), so defaults are only defined once, in Python.
"""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from types import ModuleType
from typing import Any, Callable, Mapping

import pandas as pd

from backend.app import params as params_mod

from backend.app.strategies import (
    bollinger_band_mean_reversion,
    donchian_channel_breakout,
    macd_crossover,
    moving_average_crossover,
    roc_momentum,
    rsi_threshold,
    stochastic_oscillator,
    buy_and_hold,
)

@dataclass(frozen=True)
class Strategy:
    """One registered strategy: its name, its settings class, and its signal function."""

    slug: str
    name: str
    description: str
    params_class: type
    generate_signals: Callable[..., pd.DataFrame]

    def run(self, df: pd.DataFrame, values: Mapping[str, Any] | None = None):
        """Check the user's settings, then generate signals. Returns (signals DataFrame, settings)."""
        params = params_mod.build(self.params_class, values, self.slug)
        return self.generate_signals(df, params), params

    def as_dict(self) -> dict[str, Any]:
        """This strategy's entry in the list sent to the UI (settings come from params.describe)."""
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "params": params_mod.describe(self.params_class),
        }


def _summary(module: ModuleType) -> str:
    """First line of the module's docstring; shown under the strategy picker in the UI."""
    doc = (module.__doc__ or "").strip()
    return doc.splitlines()[0] if doc else ""


def _register(module: ModuleType, params_class: type) -> Strategy:
    """Build a Strategy from a module's NAME, docstring and generate_signals()."""
    if not is_dataclass(params_class):
        raise TypeError(f"{params_class.__name__} must be a dataclass")
    # Slug = file name, so ?strategy=rsi_threshold points to rsi_threshold.py.
    slug = module.__name__.rsplit(".", 1)[-1]
    return Strategy(
        slug=slug,
        name=module.NAME,
        description=_summary(module),
        params_class=params_class,
        generate_signals=module.generate_signals,
    )


# One line per strategy; this is also the order shown in the UI.
# Trend-following first, then mean-reversion, then buy-and-hold as the baseline.
_STRATEGIES: tuple[Strategy, ...] = (
    _register(moving_average_crossover, moving_average_crossover.MovingAverageCrossoverParams),
    _register(macd_crossover, macd_crossover.MacdCrossoverParams),
    _register(roc_momentum, roc_momentum.RocMomentumParams),
    _register(donchian_channel_breakout, donchian_channel_breakout.DonchianBreakoutParams),
    _register(rsi_threshold, rsi_threshold.RsiThresholdParams),
    _register(bollinger_band_mean_reversion, bollinger_band_mean_reversion.BollingerMeanReversionParams),
    _register(stochastic_oscillator, stochastic_oscillator.StochasticParams),
    _register(buy_and_hold, buy_and_hold.BuyAndHoldParams),
)

REGISTRY: dict[str, Strategy] = {s.slug: s for s in _STRATEGIES}
SLUGS: tuple[str, ...] = tuple(REGISTRY)


def get(slug: str) -> Strategy:
    """Find a strategy by name (case-insensitive). Raises ValueError listing the valid names."""
    key = (slug or "").strip().lower()
    if key not in REGISTRY:
        raise ValueError(
            f"unknown strategy {slug!r}; pick one of {', '.join(SLUGS)}"
        )
    return REGISTRY[key]


def catalogue() -> list[dict[str, Any]]:
    """Every strategy and its settings, for GET /api/strategies."""
    return [s.as_dict() for s in _STRATEGIES]
