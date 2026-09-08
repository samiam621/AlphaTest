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

from dataclasses import MISSING, asdict, dataclass, fields, is_dataclass
from types import ModuleType
from typing import Any, Callable, Mapping, get_type_hints

import pandas as pd

from backend.app.strategies import (
    bollinger_band_mean_reversion,
    donchian_channel_breakout,
    macd_crossover,
    moving_average_crossover,
    roc_momentum,
    rsi_threshold,
    stochastic_oscillator,
)

# Python type -> the name the frontend uses to pick an input widget.
_TYPE_NAMES = {int: "int", float: "float", str: "str", bool: "bool"}


class UnknownStrategyError(ValueError):
    """Raised when a slug doesn't match anything in the registry."""


@dataclass(frozen=True)
class ParamSpec:
    """One tunable input, described well enough for a UI to render it."""

    name: str
    type: str
    default: Any
    choices: tuple[str, ...] | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {"name": self.name, "type": self.type, "default": self.default}
        if self.choices is not None:
            out["choices"] = list(self.choices)
        return out


@dataclass(frozen=True)
class Strategy:
    """A registered strategy: its identity, its params class, and its rule."""

    slug: str
    name: str
    description: str
    params_class: type
    generate_signals: Callable[..., pd.DataFrame]

    def param_specs(self) -> list[ParamSpec]:
        """Describe the params dataclass field by field."""
        # get_type_hints resolves the annotations, which are plain strings in
        # these modules because they all use `from __future__ import annotations`.
        hints = get_type_hints(self.params_class)
        specs = []
        for f in fields(self.params_class):
            if f.default is MISSING:
                raise TypeError(
                    f"{self.params_class.__name__}.{f.name} has no default; every "
                    f"strategy parameter needs one so the UI can prefill the form"
                )
            hint = hints.get(f.name, str)
            specs.append(
                ParamSpec(
                    name=f.name,
                    type=_TYPE_NAMES.get(hint, "str"),
                    default=f.default,
                    choices=f.metadata.get("choices"),
                )
            )
        return specs

    def build_params(self, values: Mapping[str, Any] | None = None):
        """Turn a dict of user input into a validated params object.

        Unknown keys are rejected rather than ignored: a typo'd parameter name
        would otherwise silently run the strategy on its defaults and look like
        the setting simply had no effect.
        """
        values = dict(values or {})
        hints = get_type_hints(self.params_class)
        known = {f.name for f in fields(self.params_class)}

        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(
                f"{self.slug} has no parameter(s) {', '.join(unknown)}; "
                f"valid parameters are {', '.join(sorted(known))}"
            )

        coerced = {
            name: _coerce(value, hints.get(name, str), name, self.slug)
            for name, value in values.items()
            if value is not None  # an omitted field falls through to its default
        }
        # The dataclass's own __post_init__ does the real validation (fast < slow,
        # thresholds in order, and so on) and raises ValueError from here.
        return self.params_class(**coerced)

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
            "params": [spec.as_dict() for spec in self.param_specs()],
        }


def _coerce(value: Any, expected: type, name: str, slug: str) -> Any:
    """Convert a JSON/query-string value to the type the dataclass expects.

    A JSON body already arrives correctly typed, but a query string makes every
    value a string, so ``period="14"`` has to become ``14`` before the strategy
    tries arithmetic with it.
    """
    # bool is a subclass of int, so it has to be handled before the int branch
    # or True would quietly become the window length 1.
    if expected is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValueError(f"{slug}.{name} must be true or false, got {value!r}")

    if expected is int:
        if isinstance(value, bool):
            raise ValueError(f"{slug}.{name} must be a whole number, got {value!r}")
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                pass
        raise ValueError(f"{slug}.{name} must be a whole number, got {value!r}")

    if expected is float:
        if isinstance(value, bool):
            raise ValueError(f"{slug}.{name} must be a number, got {value!r}")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        raise ValueError(f"{slug}.{name} must be a number, got {value!r}")

    if expected is str:
        if isinstance(value, str):
            return value
        raise ValueError(f"{slug}.{name} must be text, got {value!r}")

    return value


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
