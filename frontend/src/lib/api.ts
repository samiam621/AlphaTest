/**
 * Client for the FastAPI backend in `backend/app/main.py`.
 *
 * Every type here mirrors a response that backend actually returns, so a change
 * on the Python side shows up as a type error rather than as `undefined` in a
 * chart. Numbers the backend cannot compute come back as `null` (a flat equity
 * curve has no Sharpe, a strategy that never traded has no win rate) — that is
 * why so many fields below are nullable.
 */

// Empty by default: requests go to the same origin and Vite proxies /api to
// uvicorn. Set VITE_API_BASE to point a built bundle at another host.
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** A single tunable input, read off a strategy's params dataclass. */
export interface ParamSpec {
  name: string
  type: 'int' | 'float' | 'str' | 'bool'
  default: number | string | boolean
  /** Present when the field is one of a fixed set — render a dropdown. */
  choices?: string[]
}

export interface StrategyInfo {
  slug: string
  name: string
  description: string
  params: ParamSpec[]
}

export interface TradeStats {
  count: number
  wins: number
  losses: number
  win_rate: number | null
  avg_win: number | null
  avg_loss: number | null
  avg_trade: number | null
  profit_factor: number | null
  best: number | null
  worst: number | null
}

/** All returns and drawdowns are fractions: 0.125 is +12.5%. */
export interface Metrics {
  bars: number
  periods_per_year: number
  initial_equity: number | null
  final_equity: number | null
  total_return: number | null
  cagr: number | null
  annualized_volatility: number | null
  sharpe: number | null
  sortino: number | null
  max_drawdown: number | null
  max_drawdown_bars: number | null
  calmar: number | null
  exposure: number | null
  trades: TradeStats
  gross_total_return: number | null
  cost_drag: number | null
  turnover: number
}

export interface EquityPoint {
  date: string
  equity: number | null
  drawdown: number | null
}

export interface TradeRecord {
  entry_date: string
  exit_date: string
  entry_price: number
  exit_price: number
  direction: 'long' | 'short'
  size: number
  bars: number
  gross_return: number
  net_return: number
  cost_impact: number
  mfe: number
  mae: number
  is_open: boolean
}

export interface BacktestResponse {
  ticker: string
  interval: string
  strategy: { slug: string; name: string }
  /** The settings the run actually used, defaults filled in. */
  params: Record<string, number | string | boolean>
  config: Record<string, number | string>
  start: string
  end: string
  count: number
  metrics: Metrics
  equity: EquityPoint[]
  trades: TradeRecord[]
}

export interface BacktestRequest {
  ticker: string
  start?: string | null
  end?: string | null
  period?: string | null
  interval: string
  auto_adjust?: boolean
  prepost?: boolean
  strategy: string
  params: Record<string, number | string | boolean>
  config: Record<string, number | string | boolean>
  include_bars?: boolean
}

/** A failed request, carrying the backend's own explanation where there is one. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    // No HTTP status at all — the server is down or unreachable.
    throw new ApiError(
      'Cannot reach the backend. Is uvicorn running on port 8000?',
      0,
    )
  }

  if (!response.ok) {
    // FastAPI puts the useful message in `detail`, and HTTPException raised for
    // a bad ticker or an impossible date range is the common case here.
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') {
        detail = body.detail
      } else if (Array.isArray(body?.detail)) {
        // Pydantic validation errors arrive as a list of field problems.
        detail = body.detail
          .map((e: { loc?: string[]; msg?: string }) =>
            `${e.loc?.slice(1).join('.') ?? 'request'}: ${e.msg ?? 'invalid'}`
          )
          .join('; ')
      }
    } catch {
      // Non-JSON error body; the status line above is all we have.
    }
    throw new ApiError(detail, response.status)
  }

  return response.json() as Promise<T>
}

/** Every strategy and its parameter schema, for building the strategy form. */
export async function fetchStrategies(): Promise<StrategyInfo[]> {
  const data = await request<{ strategies: StrategyInfo[] }>('/api/strategies')
  return data.strategies
}

/** Defaults and types for the trading assumptions, for the settings form. */
export async function fetchConfigSchema(): Promise<ParamSpec[]> {
  const data = await request<{ config: ParamSpec[] }>('/api/backtest/config')
  return data.config
}

export function runBacktest(body: BacktestRequest): Promise<BacktestResponse> {
  return request<BacktestResponse>('/api/backtest', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** Bar sizes the backend will fetch — `VALID_INTERVALS` in yfinance_source.py. */
export const INTERVALS = [
  '1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h',
  '1d', '5d', '1wk', '1mo', '3mo',
] as const

/** Shorthand ranges — `VALID_PERIODS` in yfinance_source.py. */
export const PERIODS = [
  '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max',
] as const
