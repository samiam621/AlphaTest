"""Performance statistics for an equity curve.

Pure functions over pandas objects: no config, no I/O, no knowledge of how the
equity curve was produced. That makes every number here checkable against a
hand-written series in a test.

**Every function returns a plain float or None, never NaN.** Half of these
statistics are undefined on inputs that occur constantly in practice — a
strategy that never traded has no win rate, a flat equity curve has no Sharpe
because its volatility is zero, a curve that never dropped has no Calmar. NaN
would flow into the API response and JSON has no NaN literal, so the browser's
JSON.parse would reject the whole payload. Undefined is resolved to None here,
where the reason is visible, rather than being papered over at the edge.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


def _clean(value: float | None) -> float | None:
    """Map NaN and infinity to None; pass real numbers through as floats."""
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _is_negligible(deviation: float, mean: float) -> bool:
    """Is this dispersion zero, or so close to it that the ratio is meaningless?

    An exact zero is the case that actually occurs — a strategy that never took
    a position has a flat curve whose returns are all exactly 0.0. The relative
    test catches the other one: dispersion that is only floating-point residue
    from a near-constant series, which would otherwise divide into a Sharpe of
    1e15. No real return series has volatility twelve orders of magnitude below
    its mean, so nothing legitimate is caught here.
    """
    if not math.isfinite(deviation):
        return True
    return deviation <= abs(float(mean)) * 1e-12


def returns_from_equity(equity: pd.Series) -> pd.Series:
    """Per-bar fractional returns of an equity curve.

    The first bar has no prior value to compare against, so it is dropped
    rather than being called a zero return — a zero would drag the volatility
    and Sharpe estimates down by one observation's worth.
    """
    return equity.pct_change().dropna()


def total_return(equity: pd.Series) -> float | None:
    """Overall fractional gain: 0.5 is +50%."""
    if len(equity) < 2 or equity.iloc[0] == 0:
        return None
    return _clean(equity.iloc[-1] / equity.iloc[0] - 1)


def cagr(equity: pd.Series, periods_per_year: float) -> float | None:
    """Compound annual growth rate implied by the curve's start and end.

    Meaningless over a handful of bars — a 3% gain in a week annualises to
    something absurd — but the caller is better placed to decide that than
    a silent None here would be.
    """
    if len(equity) < 2 or equity.iloc[0] <= 0 or periods_per_year <= 0:
        return None
    years = (len(equity) - 1) / periods_per_year
    if years <= 0:
        return None
    final = equity.iloc[-1]
    if final <= 0:
        return -1.0  # wiped out; the root below would be a complex number
    return _clean((final / equity.iloc[0]) ** (1 / years) - 1)


def annualized_volatility(returns: pd.Series, periods_per_year: float) -> float | None:
    """Standard deviation of returns, scaled to a year by the square root of time."""
    returns = returns.dropna()
    if len(returns) < 2 or periods_per_year <= 0:
        return None
    # ddof=1: these returns are a sample of the strategy's behaviour, not the
    # entire population of it.
    return _clean(returns.std(ddof=1) * math.sqrt(periods_per_year))


def _excess(returns: pd.Series, periods_per_year: float, risk_free_rate: float) -> pd.Series:
    """Returns net of the risk-free rate, de-annualised to one bar.

    Compounded rather than divided: a 4% annual rate is not 4%/252 per day, it
    is the daily rate that compounds to 4% over 252 days. The difference is
    small at these levels and free to get right.
    """
    if risk_free_rate == 0:
        return returns
    per_period = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    return returns - per_period


def sharpe(
    returns: pd.Series,
    periods_per_year: float,
    risk_free_rate: float = 0.0,
) -> float | None:
    """Excess return per unit of total volatility, annualised.

    None when volatility is zero — a strategy that never took a position has a
    perfectly flat curve, and dividing by its zero standard deviation would give
    NaN or a meaningless infinity.
    """
    returns = returns.dropna()
    if len(returns) < 2 or periods_per_year <= 0:
        return None
    excess = _excess(returns, periods_per_year, risk_free_rate)
    deviation = excess.std(ddof=1)
    if _is_negligible(deviation, excess.mean()):
        return None
    return _clean(excess.mean() / deviation * math.sqrt(periods_per_year))


def sortino(
    returns: pd.Series,
    periods_per_year: float,
    risk_free_rate: float = 0.0,
) -> float | None:
    """Like Sharpe, but only downside deviation counts as risk.

    Upside volatility is not something anyone needs compensating for, which is
    the whole argument for preferring this to Sharpe.
    """
    returns = returns.dropna()
    if len(returns) < 2 or periods_per_year <= 0:
        return None
    excess = _excess(returns, periods_per_year, risk_free_rate)
    downside = excess.clip(upper=0)
    # Averaged over *all* periods, not just the losing ones: a strategy that
    # loses rarely should score better than one that loses constantly, and
    # dividing by only the losses would erase that difference.
    deviation = math.sqrt((downside**2).mean())
    if _is_negligible(deviation, excess.mean()):
        return None  # never lost — flattering, but not a finite ratio
    return _clean(excess.mean() / deviation * math.sqrt(periods_per_year))


def drawdown_series(equity: pd.Series) -> pd.Series:
    """Fractional distance below the highest equity seen so far, at every bar.

    Always <= 0. This is the series a UI shows as the underwater chart.
    """
    if equity.empty:
        return equity.astype(float)
    peak = equity.cummax()
    return (equity / peak - 1).replace([np.inf, -np.inf], np.nan)


def max_drawdown(equity: pd.Series) -> float | None:
    """The worst peak-to-trough fall, as a negative fraction.

    0.0 for a curve that only ever rose — that is a real answer, not a missing
    one, so it is not None.
    """
    if len(equity) < 2:
        return None
    worst = drawdown_series(equity).min()
    return _clean(worst)


def max_drawdown_duration(equity: pd.Series) -> int | None:
    """Longest stretch, in bars, spent below a previous peak.

    A drawdown still open on the final bar counts: not having recovered yet is
    the more worrying case, and ignoring it would understate the pain.
    """
    if len(equity) < 2:
        return None
    peak = equity.cummax()
    underwater = equity < peak
    longest = current = 0
    for below in underwater:
        current = current + 1 if below else 0
        longest = max(longest, current)
    return int(longest)


def calmar(equity: pd.Series, periods_per_year: float) -> float | None:
    """Annual growth per unit of worst-case drawdown.

    None when there was no drawdown at all — the ratio would be infinite.
    """
    growth = cagr(equity, periods_per_year)
    worst = max_drawdown(equity)
    if growth is None or worst is None or worst == 0:
        return None
    return _clean(growth / abs(worst))


def exposure(position: pd.Series) -> float | None:
    """Fraction of bars spent holding anything at all.

    Context for every other number here: a strategy in the market 20% of the
    time is not comparable to buy-and-hold on return alone.
    """
    if len(position) == 0:
        return None
    return _clean((position != 0).mean())


def trade_stats(trade_returns: Sequence[float] | Iterable[float]) -> dict[str, object]:
    """Win/loss statistics over a sequence of per-trade fractional returns.

    Takes plain numbers rather than trade objects so it stays independent of
    however the trade ledger ends up being represented.

    Trade returns are fractions of the position's value, which assumes each
    trade was sized alike. That holds for the 0/1 signals the strategies emit
    today; position sizing would make profit factor want currency P&L instead.
    """
    values = [float(r) for r in trade_returns if r is not None and math.isfinite(float(r))]
    empty: dict[str, object] = {
        "count": len(values),
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "avg_win": None,
        "avg_loss": None,
        "avg_trade": None,
        "profit_factor": None,
        "best": None,
        "worst": None,
    }
    if not values:
        return empty

    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]  # exactly-flat trades count as neither
    gross_loss = abs(sum(losses))

    return {
        "count": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _clean(len(wins) / len(values)),
        "avg_win": _clean(sum(wins) / len(wins)) if wins else None,
        "avg_loss": _clean(sum(losses) / len(losses)) if losses else None,
        # Expectancy: what an average trade returned, the sign that matters most.
        "avg_trade": _clean(sum(values) / len(values)),
        # None rather than infinity when nothing lost — a real result, but not a
        # number, and JSON cannot carry infinity either.
        "profit_factor": _clean(sum(wins) / gross_loss) if gross_loss > 0 else None,
        "best": _clean(max(values)),
        "worst": _clean(min(values)),
    }


def summarize(
    equity: pd.Series,
    position: pd.Series | None = None,
    *,
    periods_per_year: float,
    risk_free_rate: float = 0.0,
    trade_returns: Sequence[float] | None = None,
    benchmark_equity: pd.Series | None = None,
) -> dict[str, object]:
    """The full metrics block for an API response. All values JSON-safe."""
    returns = returns_from_equity(equity)

    summary: dict[str, object] = {
        "bars": int(len(equity)),
        "periods_per_year": float(periods_per_year),
        "initial_equity": _clean(equity.iloc[0]) if len(equity) else None,
        "final_equity": _clean(equity.iloc[-1]) if len(equity) else None,
        "total_return": total_return(equity),
        "cagr": cagr(equity, periods_per_year),
        "annualized_volatility": annualized_volatility(returns, periods_per_year),
        "sharpe": sharpe(returns, periods_per_year, risk_free_rate),
        "sortino": sortino(returns, periods_per_year, risk_free_rate),
        "max_drawdown": max_drawdown(equity),
        "max_drawdown_bars": max_drawdown_duration(equity),
        "calmar": calmar(equity, periods_per_year),
        "exposure": exposure(position) if position is not None else None,
        "trades": trade_stats(trade_returns or []),
    }

    if benchmark_equity is not None:
        # Buy and hold over the same window. Without it the strategy's return is
        # uninterpretable — beating cash and beating the stock are different wins.
        summary["benchmark"] = {
            "total_return": total_return(benchmark_equity),
            "cagr": cagr(benchmark_equity, periods_per_year),
            "max_drawdown": max_drawdown(benchmark_equity),
            "sharpe": sharpe(
                returns_from_equity(benchmark_equity), periods_per_year, risk_free_rate
            ),
        }
    return summary
