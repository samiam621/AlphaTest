/**
 * Helpers that turn numbers into display text, plus the monthly-returns calculation.
 *
 * The backend sends null for stats it couldn't compute, so every formatter
 * shows null as "—" (missing), never as 0.
 */

import type { EquityPoint } from './api'

export const EMPTY = '—'

/** A fraction (0.125) as a percentage string (+12.50%). */
export function pct(value: number | null | undefined, decimals = 2): string {
  if (value == null || !Number.isFinite(value)) return EMPTY
  const scaled = value * 100
  return `${scaled >= 0 ? '+' : ''}${scaled.toFixed(decimals)}%`
}

/** A fraction as a percentage with no forced sign — for drawdowns and rates. */
export function pctPlain(value: number | null | undefined, decimals = 2): string {
  if (value == null || !Number.isFinite(value)) return EMPTY
  return `${(value * 100).toFixed(decimals)}%`
}

/** Number with fixed decimals: 1.234 -> "1.23". */
export function num(value: number | null | undefined, decimals = 2): string {
  if (value == null || !Number.isFinite(value)) return EMPTY
  return value.toFixed(decimals)
}

/** Dollar amount: 12345.6 -> "$12,345.60". */
export function money(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return EMPTY
  return `$${value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/** "2024-03-15T00:00:00-04:00" -> "2024-03-15". */
export function day(iso: string): string {
  return iso.slice(0, 10)
}

/** Field name -> form label: `ma_type` -> `Ma Type`. */
export function labelFor(name: string): string {
  return name
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

export interface MonthlyReturn {
  year: number
  /** 0-11, so it indexes a month-label array directly. */
  month: number
  /** Fractional return over the month. */
  value: number
}

/**
 * Month-by-month returns for the Monthly Returns heatmap.
 *
 * Computed in the browser since it already has the full equity curve (no extra API call).
 * Each month = this month's last value / last month's last value - 1, so the
 * months multiply back to the total return. The first month starts from the first bar.
 */
export function monthlyReturns(equity: EquityPoint[]): MonthlyReturn[] {
  const out: MonthlyReturn[] = []
  let previousClose: number | null = null
  let current: { year: number; month: number; close: number } | null = null

  // Finish the current month and record its return.
  const flush = () => {
    if (!current) return
    const base = previousClose
    if (base != null && base !== 0) {
      out.push({
        year: current.year,
        month: current.month,
        value: current.close / base - 1,
      })
    }
    previousClose = current.close
  }

  for (const point of equity) {
    if (point.equity == null || !Number.isFinite(point.equity)) continue
    // Read year/month straight from the date string. new Date() would convert to
    // the viewer's timezone and could push a month-end bar into the next month.
    const year = Number(point.date.slice(0, 4))
    const month = Number(point.date.slice(5, 7)) - 1

    if (!current) {
      // First bar = starting value for month one, not a return itself.
      previousClose = point.equity
      current = { year, month, close: point.equity }
      continue
    }

    if (year !== current.year || month !== current.month) {
      flush()
      current = { year, month, close: point.equity }
    } else {
      current.close = point.equity
    }
  }
  flush()

  return out
}
