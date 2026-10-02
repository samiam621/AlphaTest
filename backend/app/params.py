"""Turns raw user input (JSON) into checked settings objects.

Used for both strategy settings (registry.Strategy) and BacktestConfig (backtest/config.py):
    describe(cls)       -> list of fields, so the UI can draw a form
    build(cls, values)  -> a settings object (strings converted to numbers, typos rejected)
Value checks (e.g. fast < slow) live in each dataclass's own __post_init__.
"""

from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass
from typing import Any, Mapping, get_type_hints

# Python type -> name the UI uses to pick an input widget.
TYPE_NAMES = {int: "int", float: "float", str: "str", bool: "bool"}


def describe(cls: type) -> list[dict[str, Any]]:
    """List each field's name, type, default and dropdown choices, so the UI can build a form."""
    if not is_dataclass(cls):
        raise TypeError(f"{cls.__name__} must be a dataclass")
    # Type hints are stored as strings here; get_type_hints turns them into real types.
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
        # Dropdown options, declared via field(metadata={"choices": ...}).
        choices = f.metadata.get("choices")
        if choices is not None:
            spec["choices"] = list(choices)
        described.append(spec)
    return described


def coerce(value: Any, expected: type, name: str, label: str) -> Any:
    """Convert one value to its field's type (e.g. "14" -> 14), or raise ValueError."""
    # Check bool first: bool is a subclass of int, so True would pass as 1.
    if expected is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValueError(f"{label}.{name} must be true or false, got {value!r}")

    if expected in (int, float):
        if isinstance(value, str):
            try:
                return expected(value.strip())
            except ValueError:
                pass
        # Numbers pass through; an int field also takes 3.0 but not 3.5.
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if expected is float or isinstance(value, int) or value.is_integer():
                return expected(value)
        kind = "a whole number" if expected is int else "a number"
        raise ValueError(f"{label}.{name} must be {kind}, got {value!r}")

    if expected is str:
        if isinstance(value, str):
            return value
        raise ValueError(f"{label}.{name} must be text, got {value!r}")

    return value


def build(cls: type, values: Mapping[str, Any] | None, label: str):
    """Create ``cls`` from user input. Unknown keys raise an error; missing ones keep their defaults."""
    values = dict(values or {})
    hints = get_type_hints(cls)
    known = {f.name for f in fields(cls)}

    # Reject typos, otherwise a misspelled setting would silently do nothing.
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
    # The dataclass's __post_init__ runs its own range checks from here.
    return cls(**supplied)
