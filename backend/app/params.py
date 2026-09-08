"""Building validated settings objects out of untrusted user input.

Strategy parameters and backtest configuration are the same problem twice: a
frozen dataclass of defaults, a user who overrides some of them, and a JSON or
query-string value that may not even be the right type. This module does that
job once, so ``rsi_threshold`` and ``BacktestConfig`` behave identically when a
field is misspelled or a number arrives as text.

The dataclass keeps ownership of what its values *mean* — ``__post_init__``
still raises for a fast window longer than the slow one. This module only gets
the values to it in the right shape.
"""

from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass
from typing import Any, Mapping, get_type_hints

# Python type -> the name a frontend uses to pick an input widget.
TYPE_NAMES = {int: "int", float: "float", str: "str", bool: "bool"}


def describe(cls: type) -> list[dict[str, Any]]:
    """Field name, type, default and any fixed choices, for rendering a form.

    Read off the dataclass itself so there is no second copy of the schema to
    drift: change a default in the dataclass and the UI follows.
    """
    if not is_dataclass(cls):
        raise TypeError(f"{cls.__name__} must be a dataclass")
    # These modules use `from __future__ import annotations`, so the raw
    # annotations are strings; get_type_hints resolves them to real types.
    hints = get_type_hints(cls)

    described = []
    for f in fields(cls):
        if f.default is MISSING:
            raise TypeError(
                f"{cls.__name__}.{f.name} has no default; every setting needs "
                f"one so a form can be prefilled and a partial request completed"
            )
        spec: dict[str, Any] = {
            "name": f.name,
            "type": TYPE_NAMES.get(hints.get(f.name, str), "str"),
            "default": f.default,
        }
        # Nothing in the annotation says a field is one of a fixed set, so the
        # dataclass declares it as field metadata.
        choices = f.metadata.get("choices")
        if choices is not None:
            spec["choices"] = list(choices)
        described.append(spec)
    return described


def coerce(value: Any, expected: type, name: str, label: str) -> Any:
    """Convert one value to the type its field expects, or say why it can't.

    A JSON body arrives correctly typed, but a query string makes everything a
    string, so ``period="14"`` has to become ``14`` before the strategy tries
    arithmetic with it.
    """
    # bool subclasses int, so it must be handled first or True would quietly
    # become the window length 1.
    if expected is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValueError(f"{label}.{name} must be true or false, got {value!r}")

    if expected is int:
        if isinstance(value, bool):
            raise ValueError(f"{label}.{name} must be a whole number, got {value!r}")
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                pass
        raise ValueError(f"{label}.{name} must be a whole number, got {value!r}")

    if expected is float:
        if isinstance(value, bool):
            raise ValueError(f"{label}.{name} must be a number, got {value!r}")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        raise ValueError(f"{label}.{name} must be a number, got {value!r}")

    if expected is str:
        if isinstance(value, str):
            return value
        raise ValueError(f"{label}.{name} must be text, got {value!r}")

    return value


def build(cls: type, values: Mapping[str, Any] | None, label: str):
    """Construct ``cls`` from partial user input.

    Unknown keys are rejected rather than ignored: a misspelled field would
    otherwise silently run on the default and look like the setting simply had
    no effect. Fields left out — or sent as null — keep their defaults.
    """
    values = dict(values or {})
    hints = get_type_hints(cls)
    known = {f.name for f in fields(cls)}

    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(
            f"{label} has no parameter(s) {', '.join(unknown)}; "
            f"valid parameters are {', '.join(sorted(known))}"
        )

    supplied = {
        name: coerce(value, hints.get(name, str), name, label)
        for name, value in values.items()
        if value is not None
    }
    # The dataclass's own __post_init__ does the real validation from here.
    return cls(**supplied)
