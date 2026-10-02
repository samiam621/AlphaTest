/**
 * Functions for calling the backend API (backend/app/main.py), plus TypeScript
 * types that match its JSON responses.
 *
 * Many fields are `number | null`: the backend sends null when a stat can't be
 * computed (e.g. no trades -> no win rate).
 */

// Empty = same server as the page (in dev, Vite forwards /api to the backend).
// Set VITE_API_BASE when the backend lives on a different host.
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** One form field (from a Python dataclass, via params.describe). */
export interface ParamSpec {
  name: string
  type: 'int' | 'float' | 'str' | 'bool'
  default: number | string | boolean
  /** If present, show a dropdown with these options. */
  choices?: string[]
}

/** One strategy from GET /api/strategies. */
export interface StrategyInfo {
  slug: string
  name: string
  description: string
  params: ParamSpec[]
}

/** Per-trade stats (metrics.trade_stats in Python). */
export interface TradeStats {
  count: number
  win_rate: number | null
  avg_win: number | null
  avg_loss: number | null
  avg_trade: number | null
  profit_factor: number | null
}

/** Headline stats for one run. Returns and drawdowns are fractions: 0.125 = +12.5%. */
export interface Metrics {
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
  cost_drag: number | null
  turnover: number
}

/** One point on the equity curve. drawdown is a fraction <= 0. */
export interface EquityPoint {
  date: string
  equity: number | null
  drawdown: number | null
}

/** One trade, buy to sell (trades.Trade in Python). */
export interface TradeRecord {
  entry_date: string
  exit_date: string
  entry_price: number
  exit_price: number
  direction: 'long' | 'short'
  bars: number
  net_return: number
  is_open: boolean
}

/** Response of POST /api/backtest. */
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

/** Body sent to POST /api/backtest (BacktestRequest in main.py). */
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
}

/** Error thrown when a request fails; message is the backend's error text when there is one. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Shared fetch wrapper: sends JSON, parses JSON, turns any failure into an ApiError. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    // No response at all: the backend is down or unreachable.
    throw new ApiError(
      'Cannot reach the backend. Is uvicorn running on port 8000?',
      0,
    )
  }

  if (!response.ok) {
    // FastAPI puts the error message in `detail` (e.g. "unknown ticker").
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') {
        detail = body.detail
      } else if (Array.isArray(body?.detail)) {
        // Request-shape errors (from Pydantic) come as a list of {loc, msg}.
        detail = body.detail
          .map((e: { loc?: string[]; msg?: string }) =>
            `${e.loc?.slice(1).join('.') ?? 'request'}: ${e.msg ?? 'invalid'}`
          )
          .join('; ')
      }
    } catch {
      // Body wasn't JSON; keep the generic message.
    }
    throw new ApiError(detail, response.status)
  }

  return response.json() as Promise<T>
}

/** GET /api/strategies: every strategy and its settings. Called once on page load. */
export async function fetchStrategies(): Promise<StrategyInfo[]> {
  const data = await request<{ strategies: StrategyInfo[] }>('/api/strategies')
  return data.strategies
}

/** GET /api/backtest/config: fields for the Execution & Costs form. Called once on page load. */
export async function fetchConfigSchema(): Promise<ParamSpec[]> {
  const data = await request<{ config: ParamSpec[] }>('/api/backtest/config')
  return data.config
}

/** POST /api/backtest: run one backtest. Called once per run (duplicate rows are skipped). */
export function runBacktest(body: BacktestRequest): Promise<BacktestResponse> {
  return request<BacktestResponse>('/api/backtest', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** Bar sizes the backend accepts. Must match VALID_INTERVALS in yfinance_source.py. */
export const INTERVALS = [
  '1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h',
  '1d', '5d', '1wk', '1mo', '3mo',
] as const

/** Preset date ranges. Must match VALID_PERIODS in yfinance_source.py. */
export const PERIODS = [
  '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max',
] as const
