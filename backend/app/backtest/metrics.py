"""Performance stats computed from an equity curve.

Used by engine.run (summarize, total_return) and main.py (drawdown_series).

Pure functions (no I/O, no global state), so each one is easy to unit test.

Every function returns a float or None, never NaN or infinity. JSON has no NaN,
so one NaN would make the browser reject the whole response. None means "can't
be computed", e.g. no trades -> no win rate, zero volatility -> no Sharpe.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


def _clean(value: float | None) -> float | None:
    """NaN or infinity -> None; anything else -> plain float."""
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _is_negligible(deviation: float, mean: float) -> bool:
    """True if volatility is zero (or tiny float rounding error), so dividing by it would blow up.

    Example: a strategy that never trades has all returns = 0.0 -> std dev = 0.
    """
    if not math.isfinite(deviation):
        return True
    return deviation <= abs(float(mean)) * 1e-12


def returns_from_equity(equity: pd.Series) -> pd.Series:
    """Percent change of equity per bar. First bar is dropped (nothing before it to compare to)."""
    return equity.pct_change().dropna()


def total_return(equity: pd.Series) -> float | None:
    """Overall gain: end / start - 1. 0.5 = +50%."""
    if len(equity) < 2 or equity.iloc[0] == 0:
        return None
    return _clean(equity.iloc[-1] / equity.iloc[0] - 1)


def cagr(equity: pd.Series, periods_per_year: float) -> float | None:
    """CAGR (compound annual growth rate): the steady yearly return that gives the same result.

    Formula: (end / start) ^ (1 / years) - 1. Misleading over very short periods.
    """
    if len(equity) < 2 or equity.iloc[0] <= 0 or periods_per_year <= 0:
        return None
    years = (len(equity) - 1) / periods_per_year
    if years <= 0:
        return None
    final = equity.iloc[-1]
    if final <= 0:
        return -1.0  # lost everything; can't take a root of a negative number
    return _clean((final / equity.iloc[0]) ** (1 / years) - 1)


def annualized_volatility(returns: pd.Series, periods_per_year: float) -> float | None:
    """Volatility = how much returns jump around (std dev), scaled to a year by sqrt(bars per year)."""
    returns = returns.dropna()
    if len(returns) < 2 or periods_per_year <= 0:
        return None
    # ddof=1: sample standard deviation.
    return _clean(returns.std(ddof=1) * math.sqrt(periods_per_year))


def _excess(returns: pd.Series, periods_per_year: float, risk_free_rate: float) -> pd.Series:
    """Subtract the risk-free rate from each bar's return (yearly rate converted to per-bar)."""
    if risk_free_rate == 0:
        return returns
    per_period = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    return returns - per_period


def sharpe(
    returns: pd.Series,
    periods_per_year: float,
    risk_free_rate: float = 0.0,
) -> float | None:
    """Sharpe ratio: return above the risk-free rate per unit of volatility, per year.

    Higher = better reward for the risk taken. None if volatility is zero.
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
    """Sortino ratio: like Sharpe, but only counts downward moves as risk."""
    returns = returns.dropna()
    if len(returns) < 2 or periods_per_year <= 0:
        return None
    excess = _excess(returns, periods_per_year, risk_free_rate)
    downside = excess.clip(upper=0)
    # Average over ALL bars (gains count as 0), so a strategy that loses rarely
    # scores better than one that loses often.
    deviation = math.sqrt((downside**2).mean())
    if _is_negligible(deviation, excess.mean()):
        return None  # no bar ever returned less than the risk-free rate
    return _clean(excess.mean() / deviation * math.sqrt(periods_per_year))


def drawdown_series(equity: pd.Series) -> pd.Series:
    """Drawdown at every bar: how far below its highest point so far the equity is (always <= 0).

    This is what the UI's Drawdown chart plots.
    """
    if equity.empty:
        return equity.astype(float)
    peak = equity.cummax()
    return (equity / peak - 1).replace([np.inf, -np.inf], np.nan)


def max_drawdown(equity: pd.Series) -> float | None:
    """Biggest drop from a high point to a later low point, as a negative fraction. 0.0 if it never dropped."""
    if len(equity) < 2:
        return None
    worst = drawdown_series(equity).min()
    return _clean(worst)


def max_drawdown_duration(equity: pd.Series) -> int | None:
    """Longest stretch of bars spent below a previous high (counts one still going at the end)."""
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
    """Calmar ratio: CAGR / |max drawdown|. Yearly growth per unit of worst loss. None if no drawdown."""
    growth = cagr(equity, periods_per_year)
    worst = max_drawdown(equity)
    if growth is None or worst is None or worst == 0:
        return None
    return _clean(growth / abs(worst))


def exposure(position: pd.Series) -> float | None:
    """Fraction of bars where we held a position (vs sitting in cash)."""
    if len(position) == 0:
        return None
    return _clean((position != 0).mean())


def trade_stats(trade_returns: Sequence[float] | Iterable[float]) -> dict[str, object]:
    """Per-trade stats (count, win rate, average win/loss/trade, profit factor).

    Input is a plain list of trade returns from trades.returns().
    Assumes every trade is the same size, which holds for 0/1 signals.
    Every stat except count is None when there are no trades.
    """
    values = [float(r) for r in trade_returns if r is not None and math.isfinite(float(r))]
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]  # trades at exactly 0 count as neither
    gross_loss = abs(sum(losses))

    return {
        "count": len(values),
        "win_rate": _clean(len(wins) / len(values)) if values else None,
        "avg_win": _clean(sum(wins) / len(wins)) if wins else None,
        "avg_loss": _clean(sum(losses) / len(losses)) if losses else None,
        # Average return per trade (a.k.a. expectancy).
        "avg_trade": _clean(sum(values) / len(values)) if values else None,
        # Profit factor = total gains / total losses. None (not infinity) if there were no losses.
        "profit_factor": _clean(sum(wins) / gross_loss) if gross_loss > 0 else None,
    }


def summarize(
    equity: pd.Series,
    position: pd.Series | None = None,
    *,
    periods_per_year: float,
    risk_free_rate: float = 0.0,
    trade_returns: Sequence[float] | None = None,
) -> dict[str, object]:
    """All stats in one JSON-safe dict. Called by engine.run; ends up as "metrics" in the response."""
    returns = returns_from_equity(equity)

    summary: dict[str, object] = {
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

    return summary
