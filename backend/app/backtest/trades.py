"""Round-trip trade ledger.

A trade is a maximal run of bars holding the same *side*. Going flat ends one;
flipping from long to short ends one and starts another on the same bar.

Trade returns are compounded from the per-bar returns the engine already
computed, not from ``exit_price / entry_price``. The two agree exactly while
position size is constant, but only the compounded form stays correct once size
varies within a trade — and only it is guaranteed to reconcile with the equity
curve. A ledger whose P&L disagrees with the headline return is worse than no
ledger, so that reconciliation is the property this module is built around and
the one its tests assert.

Cost attribution follows the engine's own rule. The entry cost is already inside
the first held bar's net return. Where the exit cost sits depends on the
execution model, and :class:`~backend.app.backtest.execution.Fills` says which:
under ``next_open`` the trade already spans the bar it was sold on, so that bar
carries it; under ``close`` the exit lands on the bar *after* the last held one
and has to be applied here — but only when the strategy went flat, since on a
direct flip that bar is the next trade's first held bar and already carries the
whole turnover charge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from backend.app.backtest.execution import Fills


@dataclass(frozen=True)
class Trade:
    """One round trip, from the bar it was entered to the bar it was closed."""

    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    direction: str  # "long" or "short"
    size: float     # signed position held, e.g. 1.0 or -1.0
    bars: int
    gross_return: float
    net_return: float
    #: What costs took off this trade, in return terms.
    cost_impact: float
    #: Best and worst the trade was ever up/down before it closed. The raw
    #: material for deciding where a stop or target would have helped.
    mfe: float
    mae: float
    #: Still on when the data ran out: marked to the last close, not a result yet.
    is_open: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_date": self.entry_date.isoformat(),
            "exit_date": self.exit_date.isoformat(),
            "entry_price": float(self.entry_price),
            "exit_price": float(self.exit_price),
            "direction": self.direction,
            "size": float(self.size),
            "bars": int(self.bars),
            "gross_return": float(self.gross_return),
            "net_return": float(self.net_return),
            "cost_impact": float(self.cost_impact),
            "mfe": float(self.mfe),
            "mae": float(self.mae),
            "is_open": bool(self.is_open),
        }


def _runs(sign: np.ndarray) -> list[tuple[int, int]]:
    """Index ranges of consecutive bars sharing one non-zero side."""
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
    """Build the ledger from one backtest run.

    ``fills`` carries the execution model's answers: what was held on each bar,
    what it earned, and the price and timing of the fills. ``mark_prices`` (the
    close) is used to value a trade that is still open when the data ends.
    """
    position = fills.position
    if len(position) == 0:
        return []

    sign = np.sign(position.to_numpy()).astype(int)
    pos = position.to_numpy(dtype=float)
    gross = fills.gross_returns.to_numpy(dtype=float)
    net = net_returns.to_numpy(dtype=float)
    fill = fills.fill_prices.to_numpy(dtype=float)
    mark = mark_prices.to_numpy(dtype=float)
    index = position.index
    last = len(position) - 1

    trades: list[Trade] = []
    for i, j in _runs(sign):
        is_open = j == last
        # Under next_open the position is not sold until the following open, so
        # the trade still earns that night's gap — one bar past the last one it
        # was held through.
        end = min(j + fills.exit_return_offset, last)

        if fills.exit_return_offset and not is_open and sign[j + 1] != 0:
            # Bar j+1 would then be split between this trade's exit gap and the
            # next trade's session, and both would claim the whole bar. No
            # strategy here flips without going flat first, so this is a guard
            # against silently wrong numbers rather than a live limitation.
            side = lambda k: "short" if sign[k] < 0 else "long"
            raise NotImplementedError(
                f"a direct {side(j)}-to-{side(j + 1)} flip at {index[j + 1]} "
                f"cannot be attributed under execution={fills.name!r}; "
                f"go flat between positions, or use execution='close'"
            )

        growth = np.prod(1.0 + gross[i : end + 1])
        net_growth = np.prod(1.0 + net[i : end + 1])

        if not is_open and not fills.exit_return_offset:
            # Who owns the cost charged on bar j+1, the bar the position changed
            # on? With no exit offset that bar sits outside the trade, so if the
            # strategy went flat it belongs to no one else and this trade has to
            # carry it. On a direct flip it is the next trade's first held bar,
            # whose net return already contains the whole turnover charge, so
            # subtracting it here as well would double-count it.
            if sign[j + 1] == 0:
                net_growth *= 1.0 - abs(pos[j]) * cost_rate

        entry_bar = max(i + fills.fill_offset, 0)
        entry_price = fill[i]
        if not np.isfinite(entry_price):
            # Only reachable for a hand-built position that starts on bar 0;
            # the engine's lag always leaves bar 0 flat.
            entry_price = mark[entry_bar]

        if is_open:
            exit_bar, exit_price = last, mark[last]
        else:
            exit_bar = min(j + 1 + fills.fill_offset, last)
            exit_price = fill[j + 1]

        # Running P&L within the trade, for the best/worst it ever showed.
        path = np.cumprod(1.0 + gross[i : end + 1]) - 1.0

        trades.append(
            Trade(
                entry_date=index[entry_bar],
                exit_date=index[exit_bar],
                entry_price=entry_price,
                exit_price=exit_price,
                direction="long" if sign[i] > 0 else "short",
                size=pos[i],
                bars=j - i + 1,
                gross_return=float(growth - 1.0),
                net_return=float(net_growth - 1.0),
                cost_impact=float((growth - 1.0) - (net_growth - 1.0)),
                mfe=float(path.max()),
                mae=float(path.min()),
                is_open=is_open,
            )
        )
    return trades


def returns(trades: Sequence[Trade], include_open: bool = False) -> list[float]:
    """Net returns for :func:`~backend.app.backtest.metrics.trade_stats`.

    The still-open trade is left out by default. Its result is whatever the last
    bar happened to be, so counting it would make the win rate drift with the
    date the backtest was run rather than with the strategy.
    """
    return [t.net_return for t in trades if include_open or not t.is_open]


def to_records(trades: Sequence[Trade]) -> list[dict[str, Any]]:
    """JSON-serialisable ledger rows."""
    return [t.as_dict() for t in trades]
