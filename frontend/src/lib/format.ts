/**
 * Display helpers.
 *
 * The backend returns `null` for any statistic it could not compute rather than
 * NaN, so every formatter here has to have an answer for "no value" — an em
 * dash, so a missing Sharpe reads as missing instead of as zero.
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

export function num(value: number | null | undefined, decimals = 2): string {
  if (value == null || !Number.isFinite(value)) return EMPTY
  return value.toFixed(decimals)
}

export function money(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return EMPTY
  return `$${value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/** ISO timestamps from the API carry a timezone; the calendar day is enough. */
export function day(iso: string): string {
  return iso.slice(0, 10)
}

/** `ma_type` -> `Ma Type`, so a form label comes straight from the field name. */
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
 * Month-by-month returns of the equity curve.
 *
 * Derived here rather than fetched: the backend sends the full curve already,
 * and asking it for a second, differently-bucketed view of the same numbers
 * would be a round trip to compute something the browser is holding.
 *
 * Each month is measured from the last equity value of the previous month, so
 * the months chain back to the total return. The first month measures from the
 * curve's opening value.
 */
export function monthlyReturns(equity: EquityPoint[]): MonthlyReturn[] {
  const out: MonthlyReturn[] = []
  let previousClose: number | null = null
  let current: { year: number; month: number; close: number } | null = null

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
    // The date is an ISO string from pandas; slicing beats constructing a Date,
    // which would shift the bar into the viewer's timezone and can move a
    // month-end bar into the next month.
    const year = Number(point.date.slice(0, 4))
    const month = Number(point.date.slice(5, 7)) - 1

    if (!current) {
      // The opening bar is the base for the first month, not a return itself.
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
