"""Trade list: splits the position series into individual trades. Called by engine.run.

A trade = a run of consecutive bars holding the same side (long or short).
Going to cash ends it; switching long -> short ends one and starts another.

A trade's return multiplies together the engine's per-bar net returns (instead
of just exit_price / entry_price), so the trade list always adds up to the equity curve.

Exit fee: under "next_open" it's already inside the trade's last bar. Under
"close" it lands on the bar after the trade, so extract() subtracts it here
(only when going to cash; on a direct long<->short switch the next trade's
first bar already pays it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from backend.app.backtest.execution import Fills


@dataclass(frozen=True)
class Trade:
    """One trade, from buy to sell. Shown in the UI's Trade Log."""

    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    direction: str  # "long" or "short"
    bars: int
    #: Return after fees.
    net_return: float
    #: Still open when the data ended; valued at the last close.
    is_open: bool

    def as_dict(self) -> dict[str, Any]:
        """Convert to a JSON-safe dict (dates as strings, numpy numbers as Python ones)."""
        return {
            "entry_date": self.entry_date.isoformat(),
            "exit_date": self.exit_date.isoformat(),
            "entry_price": float(self.entry_price),
            "exit_price": float(self.exit_price),
            "direction": self.direction,
            "bars": int(self.bars),
            "net_return": float(self.net_return),
            "is_open": bool(self.is_open),
        }


def _runs(sign: np.ndarray) -> list[tuple[int, int]]:
    """Find (start, end) index pairs of back-to-back bars on the same non-zero side."""
    spans: list[tuple[int, int]] = []
    i, n = 0, len(sign)
    while i < n:
        if sign[i] == 0:
            i += 1
            continue
        j = i
        while j + 1 < n and sign[j + 1] == sign[i]:
            j += 1
        spans.append((i, j))
        i = j + 1
    return spans


def extract(
    fills: Fills,
    net_returns: pd.Series,
    mark_prices: pd.Series,
    cost_rate: float = 0.0,
) -> list[Trade]:
    """Build the trade list for one run. mark_prices (closes) value a trade still open at the end."""
    position = fills.position
    if len(position) == 0:
        return []

    sign = np.sign(position.to_numpy()).astype(int)
    pos = position.to_numpy(dtype=float)
    net = net_returns.to_numpy(dtype=float)
    fill = fills.fill_prices.to_numpy(dtype=float)
    mark = mark_prices.to_numpy(dtype=float)
    index = position.index
    last = len(position) - 1

    trades: list[Trade] = []
    for i, j in _runs(sign):  # i = first bar held, j = last bar held
        is_open = j == last
        # next_open: we sell at the following open, so the trade also gets that overnight move.
        end = min(j + fills.exit_return_offset, last)

        if fills.exit_return_offset and not is_open and sign[j + 1] != 0:
            # Under next_open, a direct long<->short switch would split one bar
            # between two trades. No strategy here does that, so fail loudly
            # instead of reporting wrong numbers.
            side = lambda k: "short" if sign[k] < 0 else "long"
            raise NotImplementedError(
                f"a direct {side(j)}-to-{side(j + 1)} flip at {index[j + 1]} "
                f"cannot be attributed under execution={fills.name!r}; "
                f"go flat between positions, or use execution='close'"
            )

        # Multiply (1 + return) over the trade's bars to get its total growth.
        net_growth = np.prod(1.0 + net[i : end + 1])

        if not is_open and not fills.exit_return_offset:
            # "close" model: the exit fee is charged on bar j+1, outside this trade.
            # If we went to cash, charge it to this trade. On a direct switch the
            # next trade already pays it, so don't count it twice.
            if sign[j + 1] == 0:
                net_growth *= 1.0 - abs(pos[j]) * cost_rate

        entry_bar = max(i + fills.fill_offset, 0)
        entry_price = fill[i]
        if not np.isfinite(entry_price):
            # Only happens for a hand-made position starting on bar 0 (lag keeps bar 0 at 0).
            entry_price = mark[entry_bar]

        if is_open:
            exit_bar, exit_price = last, mark[last]
        else:
            exit_bar = min(j + 1 + fills.fill_offset, last)
            exit_price = fill[j + 1]

        trades.append(
            Trade(
                entry_date=index[entry_bar],
                exit_date=index[exit_bar],
                entry_price=entry_price,
                exit_price=exit_price,
                direction="long" if sign[i] > 0 else "short",
                bars=j - i + 1,
                net_return=float(net_growth - 1.0),
                is_open=is_open,
            )
        )
    return trades


def returns(trades: Sequence[Trade]) -> list[float]:
    """Net return of each closed trade, passed to metrics.trade_stats.

    The open trade is skipped: its result just depends on the day the data ends.
    """
    return [t.net_return for t in trades if not t.is_open]


def to_records(trades: Sequence[Trade]) -> list[dict[str, Any]]:
    """Trades as JSON-ready dicts for the API response."""
    return [t.as_dict() for t in trades]
