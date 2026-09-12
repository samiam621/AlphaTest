

"""Buy the asset and stay invested for the full backtest window."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.strategies.signal_utils import require_columns

NAME = "Buy and Hold"


@dataclass(frozen=True)
class BuyAndHoldParams:
	"""no params"""


def generate_signals(
	df: pd.DataFrame,
	params: BuyAndHoldParams | None = None,
) -> pd.DataFrame:
	"""Return a long signal for every bar in the input data."""
	require_columns(df, ("close",))
	return pd.DataFrame(
		{"signal": pd.Series(1, index=df.index, dtype=int)},
		index=df.index,
	)