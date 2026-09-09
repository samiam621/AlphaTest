"""The catalogue of strategies the API can run.

One place that maps a URL-safe slug to a strategy module, so ``main.py`` never
imports a strategy directly and adding a new one is a single line in
``_STRATEGIES`` below rather than an edit to the API layer.

Everything the frontend needs to render a parameter form — field names, types,
defaults, and any fixed set of choices — is read off the strategy's params
dataclass by introspection. There is no second copy of the schema to keep in
sync: change a default in the strategy file and the UI picks it up.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
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
)

class UnknownStrategyError(ValueError):
    """Raised when a slug doesn't match anything in the registry."""


@dataclass(frozen=True)
class Strategy:
    """A registered strategy: its identity, its params class, and its rule."""

    slug: str
    name: str
    description: str
    params_class: type
    generate_signals: Callable[..., pd.DataFrame]

    def param_specs(self) -> list[dict[str, Any]]:
        """Describe this strategy's tunable inputs, for rendering a form."""
        return params_mod.describe(self.params_class)

    def build_params(self, values: Mapping[str, Any] | None = None):
        """Turn a dict of user input into a validated params object."""
        return params_mod.build(self.params_class, values, self.slug)

    def run(self, df: pd.DataFrame, values: Mapping[str, Any] | None = None):
        """Build params from user input and generate signals. Returns both."""
        params = self.build_params(values)
        return self.generate_signals(df, params), params

    def as_dict(self) -> dict[str, Any]:
        """The catalogue entry the frontend consumes."""
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "params": self.param_specs(),
        }


def _summary(module: ModuleType) -> str:
    """First line of the module docstring — the one-liner for the UI."""
    doc = (module.__doc__ or "").strip()
    return doc.splitlines()[0] if doc else ""


def _register(module: ModuleType, params_class: type) -> Strategy:
    """Build a registry entry from a strategy module's own metadata."""
    if not is_dataclass(params_class):
        raise TypeError(f"{params_class.__name__} must be a dataclass")
    # The slug is the module's filename, so a URL like ?strategy=rsi_threshold
    # points at exactly the file a reader would go looking for.
    slug = module.__name__.rsplit(".", 1)[-1]
    return Strategy(
        slug=slug,
        name=module.NAME,
        description=_summary(module),
        params_class=params_class,
        generate_signals=module.generate_signals,
    )


# Add a strategy by adding a line here. Order is the order the UI lists them in:
# trend followers first, then the mean-reversion rules.
_STRATEGIES: tuple[Strategy, ...] = (
    _register(moving_average_crossover, moving_average_crossover.MovingAverageCrossoverParams),
    _register(macd_crossover, macd_crossover.MacdCrossoverParams),
    _register(roc_momentum, roc_momentum.RocMomentumParams),
    _register(donchian_channel_breakout, donchian_channel_breakout.DonchianBreakoutParams),
    _register(rsi_threshold, rsi_threshold.RsiThresholdParams),
    _register(bollinger_band_mean_reversion, bollinger_band_mean_reversion.BollingerMeanReversionParams),
    _register(stochastic_oscillator, stochastic_oscillator.StochasticParams),
)

REGISTRY: dict[str, Strategy] = {s.slug: s for s in _STRATEGIES}
SLUGS: tuple[str, ...] = tuple(REGISTRY)


def get(slug: str) -> Strategy:
    """Look up a strategy, or explain what the valid options were."""
    key = (slug or "").strip().lower()
    if key not in REGISTRY:
        raise UnknownStrategyError(
            f"unknown strategy {slug!r}; pick one of {', '.join(SLUGS)}"
        )
    return REGISTRY[key]


def catalogue() -> list[dict[str, Any]]:
    """Every strategy and its parameter schema, for the UI to render a form."""
    return [s.as_dict() for s in _STRATEGIES]


def params_as_dict(params) -> dict[str, Any]:
    """The parameters a run actually used, defaults included, for echoing back."""
    return asdict(params)
