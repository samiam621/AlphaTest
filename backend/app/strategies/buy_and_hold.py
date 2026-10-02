

"""Buy the asset and stay invested for the full backtest window.

Baseline: on first load the UI compares the other strategy against this in the "Excess" card.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

NAME = "Buy and Hold"


@dataclass(frozen=True)
class BuyAndHoldParams:
	"""No settings."""


def generate_signals(
	df: pd.DataFrame,
	params: BuyAndHoldParams | None = None,
) -> pd.DataFrame:
	"""Signal = 1 (hold) on every bar."""
	return pd.DataFrame(
		{"signal": pd.Series(1, index=df.index, dtype=int)},
		index=df.index,
	)