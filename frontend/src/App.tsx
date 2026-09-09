import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  ApiError,
  INTERVALS,
  PERIODS,
  fetchConfigSchema,
  fetchStrategies,
  runBacktest,
  type BacktestResponse,
  type ParamSpec,
  type StrategyInfo,
} from "@/lib/api";
import {
  EMPTY,
  day,
  labelFor,
  money,
  monthlyReturns,
  num,
  pct,
  pctPlain,
} from "@/lib/format";

// ─── Form state ───────────────────────────────────────────────────────────────

/**
 * Every parameter is held as a string, whatever the backend says its type is.
 *
 * `backend/app/params.py` coerces "14" to 14 and "true" to True on the way in,
 * so keeping the raw text means a half-typed number never has to be forced into
 * a number here — and a field the user clears is simply omitted from the
 * request, which the backend reads as "use the default".
 */
type Values = Record<string, string>;

/** Prefill a form from the schema's own defaults. */
function defaultsOf(specs: ParamSpec[]): Values {
  return Object.fromEntries(specs.map((s) => [s.name, String(s.default)]));
}

/** Drop cleared fields so the backend falls back to its defaults. */
function submitted(values: Values): Record<string, string> {
  return Object.fromEntries(
    Object.entries(values).filter(([, v]) => v.trim() !== ""),
  );
}

const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Suggestions only — the ticker box is free text, because the backend will
// fetch anything Yahoo knows about.
const TICKER_SUGGESTIONS = [
  "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ", "BTC-USD",
];

// ─── Presentational pieces ────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  sub,
  positive,
}: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean | null;
}) {
  const valueColor =
    positive === true
      ? "text-[var(--gain)]"
      : positive === false
        ? "text-[var(--loss)]"
        : "text-foreground";

  return (
    <div
      className="flex flex-col gap-1 p-3 border rounded"
      style={{ background: "var(--card)", borderColor: "var(--border)" }}
    >
      <span
        className="text-[10px] font-medium tracking-widest uppercase"
        style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}
      >
        {label}
      </span>
      <span
        className={`text-xl font-semibold leading-none ${valueColor}`}
        style={{ fontFamily: "var(--font-data)" }}
      >
        {value}
      </span>
      {sub && (
        <span className="text-[10px]" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
          {sub}
        </span>
      )}
    </div>
  );
}

const CustomTooltip = ({
  active,
  payload,
  label,
  kind = "money",
}: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
  kind?: "money" | "percent";
}) => {
  if (!active || !payload?.length) return null;
  return (
    <div
      className="text-xs border rounded px-3 py-2 shadow-xl"
      style={{
        background: "#131528",
        borderColor: "rgba(255,255,255,0.12)",
        fontFamily: "var(--font-data)",
      }}
    >
      <p className="mb-1.5 font-medium" style={{ color: "var(--muted-foreground)" }}>
        {label}
      </p>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 justify-between">
          <span style={{ color: p.color }}>{p.name}</span>
          <span style={{ color: "var(--foreground)" }}>
            {typeof p.value !== "number"
              ? EMPTY
              : kind === "money"
                ? money(p.value)
                : `${p.value.toFixed(2)}%`}
          </span>
        </div>
      ))}
    </div>
  );
};

const FIELD_STYLE = {
  background: "var(--secondary)",
  border: "1px solid var(--border)",
  color: "var(--foreground)",
  fontFamily: "var(--font-data)",
  fontSize: "0.75rem",
} as const;

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label
      className="text-[10px] tracking-widest uppercase font-medium"
      style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}
    >
      {children}
    </label>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <FieldLabel>{label}</FieldLabel>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-2 py-1.5 rounded text-sm outline-none cursor-pointer transition-colors"
        style={FIELD_STYLE}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} style={{ background: "#1a1d35" }}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  type = "text",
  step,
  list,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: "text" | "number" | "date";
  step?: string;
  list?: string;
  placeholder?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <FieldLabel>{label}</FieldLabel>
      <input
        type={type}
        step={step}
        list={list}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="px-2 py-1.5 rounded text-sm w-full outline-none"
        style={FIELD_STYLE}
      />
    </div>
  );
}

/**
 * One input, chosen by what the backend said the field is.
 *
 * The whole point of `/api/strategies` returning a schema is that this is the
 * only place that decides how a parameter looks — adding a parameter to a
 * strategy dataclass in Python makes it appear here with no frontend change.
 */
function SchemaField({
  spec,
  value,
  onChange,
}: {
  spec: ParamSpec;
  value: string;
  onChange: (v: string) => void;
}) {
  const label = labelFor(spec.name);

  if (spec.choices) {
    return (
      <Select
        label={label}
        value={value}
        options={spec.choices.map((c) => ({ value: c, label: c }))}
        onChange={onChange}
      />
    );
  }
  if (spec.type === "bool") {
    return (
      <Select
        label={label}
        value={value}
        options={[
          { value: "true", label: "true" },
          { value: "false", label: "false" },
        ]}
        onChange={onChange}
      />
    );
  }
  return (
    <TextField
      label={label}
      value={value}
      onChange={onChange}
      type={spec.type === "int" || spec.type === "float" ? "number" : "text"}
      step={spec.type === "int" ? "0.01" : spec.type === "float" ? "0.01" : undefined}
    />
  );
}

function SidebarSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p
        className="text-[9px] font-semibold tracking-widest uppercase mb-3"
        style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}
      >
        {title}
      </p>
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  );
}

function Divider() {
  return <div className="h-px" style={{ background: "var(--border)" }} />;
}

function StatRow({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "gain" | "loss" | "neutral";
}) {
  return (
    <div
      className="flex items-center justify-between py-2 border-b"
      style={{ borderColor: "var(--border)" }}
    >
      <span className="text-[11px]" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
        {label}
      </span>
      <span
        className="text-[11px] font-medium"
        style={{
          fontFamily: "var(--font-data)",
          color: tone === "gain" ? "var(--gain)" : tone === "loss" ? "var(--loss)" : "var(--foreground)",
        }}
      >
        {value}
      </span>
    </div>
  );
}

/** Sign of a value that may be missing, for colouring. `null` means no colour. */
function toneOf(value: number | null | undefined): "gain" | "loss" | "neutral" {
  if (value == null || !Number.isFinite(value)) return "neutral";
  return value >= 0 ? "gain" : "loss";
}

function signOf(value: number | null | undefined, threshold = 0): boolean | null {
  if (value == null || !Number.isFinite(value)) return null;
  return value > threshold;
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  // Schemas, fetched once. Until they arrive there is no form to render, since
  // the form *is* the schema.
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [configSpecs, setConfigSpecs] = useState<ParamSpec[]>([]);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [loadingSchema, setLoadingSchema] = useState(true);

  // Data selection.
  const [ticker, setTicker] = useState("AAPL");
  const [rangeMode, setRangeMode] = useState<"period" | "custom">("period");
  const [period, setPeriod] = useState("2y");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [interval, setInterval] = useState("1d");

  // Strategy selection, with one set of parameter values per strategy so
  // switching away and back does not lose what was typed.
  const [slug, setSlug] = useState("");
  const [paramsBySlug, setParamsBySlug] = useState<Record<string, Values>>({});
  const [configValues, setConfigValues] = useState<Values>({});
  const [showSettings, setShowSettings] = useState(false);

  // Run state.
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"nav" | "drawdown" | "monthly">("nav");

  const strategy = strategies.find((s) => s.slug === slug);

  // The request builder reads current form state, so it is rebuilt on every
  // change; `run` below depends on it.
  const buildRequest = useCallback(() => {
    // The backend rejects a request carrying both a period and explicit dates,
    // so the mode toggle decides which pair goes in.
    const range =
      rangeMode === "period"
        ? { period, start: null, end: null }
        : { period: null, start: start || null, end: end || null };

    return {
      ticker: ticker.trim(),
      ...range,
      interval,
      strategy: slug,
      params: submitted(paramsBySlug[slug] ?? {}),
      config: submitted(configValues),
      // The per-bar frame is the largest part of the response and nothing on
      // this screen reads it.
      include_bars: false,
    };
  }, [ticker, rangeMode, period, start, end, interval, slug, paramsBySlug, configValues]);

  const requestRef = useRef(buildRequest);
  requestRef.current = buildRequest;

  const run = useCallback(async () => {
    const body = requestRef.current();
    if (!body.ticker) {
      setRunError("Enter a ticker to backtest.");
      return;
    }
    if (!body.strategy) return;

    setRunning(true);
    setRunError(null);
    try {
      setResult(await runBacktest(body));
    } catch (err) {
      // A 400 here is almost always the user's input — an unknown ticker, a
      // start date past the intraday lookback, fast >= slow — and the backend's
      // message says which, so show it rather than a generic failure.
      setRunError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }, []);

  // Load both schemas, then run once so the screen opens with real numbers
  // instead of an empty frame.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [catalogue, config] = await Promise.all([
          fetchStrategies(),
          fetchConfigSchema(),
        ]);
        if (cancelled) return;

        setStrategies(catalogue);
        setConfigSpecs(config);
        setConfigValues(defaultsOf(config));
        setParamsBySlug(
          Object.fromEntries(catalogue.map((s) => [s.slug, defaultsOf(s.params)])),
        );
        setSlug(catalogue[0]?.slug ?? "");
        setLoadingSchema(false);
      } catch (err) {
        if (cancelled) return;
        setSchemaError(err instanceof ApiError ? err.message : String(err));
        setLoadingSchema(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // `slug` is set only once the catalogue has loaded, so this fires exactly
  // once, after the form has real defaults in it.
  const autoRan = useRef(false);
  useEffect(() => {
    if (!slug || autoRan.current) return;
    autoRan.current = true;
    void run();
  }, [slug, run]);

  const setParam = (name: string, value: string) =>
    setParamsBySlug((all) => ({ ...all, [slug]: { ...all[slug], [name]: value } }));

  const setConfigValue = (name: string, value: string) =>
    setConfigValues((c) => ({ ...c, [name]: value }));

  const metrics = result?.metrics;
  const benchmark = metrics?.benchmark;
  const trades = result?.trades ?? [];

  // Excess return over buy-and-hold. Not Jensen's alpha — the backend does not
  // compute a beta — so it is labelled for what it is.
  const excess =
    metrics?.total_return != null && benchmark?.total_return != null
      ? metrics.total_return - benchmark.total_return
      : null;

  // Thin the curve for the chart: ten years of daily bars is 2500 points, and
  // an SVG path with one node per pixel column looks the same as one with four.
  const chartData = useMemo(() => {
    if (!result) return [];
    const points = result.equity;
    const step = Math.max(1, Math.floor(points.length / 400));
    const kept = points.filter((_, i) => i % step === 0);
    const last = points[points.length - 1];
    // The final bar carries the headline return; never let it fall in a gap.
    if (last && kept[kept.length - 1] !== last) kept.push(last);
    return kept.map((p) => ({
      date: day(p.date),
      equity: p.equity,
      benchmark: p.benchmark,
      drawdown: p.drawdown == null ? null : p.drawdown * 100,
    }));
  }, [result]);

  const monthly = useMemo(() => (result ? monthlyReturns(result.equity) : []), [result]);

  const monthlyByYear = useMemo(() => {
    const years: Record<number, Record<number, number>> = {};
    for (const m of monthly) {
      (years[m.year] ??= {})[m.month] = m.value;
    }
    return years;
  }, [monthly]);

  const heatmapYears = Object.keys(monthlyByYear).map(Number).sort((a, b) => b - a);

  const colorForReturn = (r: number) => {
    const p = r * 100;
    if (p > 8) return "rgba(0,229,160,0.85)";
    if (p > 4) return "rgba(0,229,160,0.55)";
    if (p > 1) return "rgba(0,229,160,0.28)";
    if (p > -1) return "rgba(255,255,255,0.06)";
    if (p > -4) return "rgba(255,77,109,0.28)";
    if (p > -8) return "rgba(255,77,109,0.55)";
    return "rgba(255,77,109,0.85)";
  };

  return (
    <div className="flex h-full overflow-hidden" style={{ background: "var(--background)", fontFamily: "var(--font-ui)" }}>
      {/* ── Sidebar ── */}
      <aside
        className="flex flex-col w-56 shrink-0 border-r overflow-y-auto"
        style={{ background: "#090b18", borderColor: "var(--border)" }}
      >
        <div className="flex items-center gap-2.5 px-4 py-4 border-b" style={{ borderColor: "var(--border)" }}>
          <div
            className="w-6 h-6 rounded flex items-center justify-center text-[10px] font-bold"
            style={{ background: "var(--primary)", color: "var(--primary-foreground)", fontFamily: "var(--font-data)" }}
          >
            α
          </div>
          <span className="font-semibold text-sm tracking-wide" style={{ color: "var(--foreground)" }}>
            AlphaTest
          </span>
        </div>

        {loadingSchema ? (
          <p className="p-4 text-xs" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
            Loading strategies…
          </p>
        ) : schemaError ? (
          <p className="p-4 text-xs leading-relaxed" style={{ color: "var(--loss)", fontFamily: "var(--font-data)" }}>
            {schemaError}
          </p>
        ) : (
          <div className="flex flex-col gap-4 p-4">
            <SidebarSection title="Universe">
              <TextField
                label="Ticker"
                value={ticker}
                onChange={(v) => setTicker(v.toUpperCase())}
                placeholder="Enter a ticker:ex.AAPL"
              />

              <Select
                label="Range"
                value={rangeMode}
                options={[
                  { value: "period", label: "Preset period" },
                  { value: "custom", label: "Custom dates" },
                ]}
                onChange={(v) => setRangeMode(v as "period" | "custom")}
              />
              {rangeMode === "period" ? (
                <Select
                  label="Period"
                  value={period}
                  options={PERIODS.map((p) => ({ value: p, label: p }))}
                  onChange={setPeriod}
                />
              ) : (
                <>
                  <TextField label="Start" value={start} onChange={setStart} type="date" />
                  <TextField label="End" value={end} onChange={setEnd} type="date" />
                </>
              )}
              <Select
                label="Interval"
                value={interval}
                options={INTERVALS.map((i) => ({ value: i, label: i }))}
                onChange={setInterval}
              />
            </SidebarSection>

            <Divider />

            <SidebarSection title="Strategy">
              <Select
                label="Model"
                value={slug}
                options={strategies.map((s) => ({ value: s.slug, label: s.name }))}
                onChange={setSlug}
              />
              {strategy?.description && (
                <p className="text-[10px] leading-snug" style={{ color: "var(--muted-foreground)" }}>
                  {strategy.description}
                </p>
              )}
              {strategy?.params.map((spec) => (
                <SchemaField
                  key={spec.name}
                  spec={spec}
                  value={paramsBySlug[slug]?.[spec.name] ?? ""}
                  onChange={(v) => setParam(spec.name, v)}
                />
              ))}
            </SidebarSection>

            <Divider />

            <div>
              <button
                onClick={() => setShowSettings((s) => !s)}
                className="flex items-center justify-between w-full text-[9px] font-semibold tracking-widest uppercase mb-3"
                style={{
                  color: "var(--muted-foreground)",
                  fontFamily: "var(--font-data)",
                  background: "none",
                  border: "none",
                  padding: 0,
                  cursor: "pointer",
                }}
              >
                <span>Execution &amp; Costs</span>
                <span>{showSettings ? "−" : "+"}</span>
              </button>
              {showSettings && (
                <div className="flex flex-col gap-3">
                  {configSpecs.map((spec) => (
                    <SchemaField
                      key={spec.name}
                      spec={spec}
                      value={configValues[spec.name] ?? ""}
                      onChange={(v) => setConfigValue(spec.name, v)}
                    />
                  ))}
                </div>
              )}
            </div>

            <button
              onClick={() => void run()}
              disabled={running}
              className="mt-1 py-2.5 rounded font-semibold text-xs tracking-widest uppercase transition-all"
              style={{
                background: running ? "var(--muted)" : "var(--primary)",
                color: running ? "var(--muted-foreground)" : "var(--primary-foreground)",
                fontFamily: "var(--font-data)",
                cursor: running ? "not-allowed" : "pointer",
                border: "none",
              }}
            >
              {running ? "Running…" : "Run Backtest"}
            </button>
          </div>
        )}
      </aside>

      {/* ── Main Panel ── */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <header
          className="flex items-center justify-between px-5 py-3 border-b shrink-0"
          style={{ background: "#090b18", borderColor: "var(--border)" }}
        >
          <div className="flex items-center gap-3">
            {result ? (
              <>
                <span className="ticker-badge">{result.ticker}</span>
                <span className="text-sm font-medium" style={{ color: "var(--foreground)" }}>
                  {result.strategy.name}
                </span>
                <span className="text-xs" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
                  {day(result.start)} → {day(result.end)} · {result.interval}
                </span>
              </>
            ) : (
              <span className="text-sm" style={{ color: "var(--muted-foreground)" }}>
                No backtest yet
              </span>
            )}
          </div>
          <div className="flex items-center gap-4">
            {result && (
              <span className="text-xs" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
                {result.count} bars
              </span>
            )}
            <div className="flex items-center gap-1.5 text-xs" style={{ fontFamily: "var(--font-data)", color: "var(--gain)" }}>
              <span className="w-2 h-2 rounded-full inline-block" style={{ background: "var(--gain)" }} />
              Strategy
            </div>
            <div className="flex items-center gap-1.5 text-xs" style={{ fontFamily: "var(--font-data)", color: "var(--primary)" }}>
              <span className="w-2 h-2 rounded-full inline-block" style={{ background: "var(--primary)" }} />
              Buy &amp; Hold
            </div>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-5">
          {runError && (
            <div
              className="rounded border px-4 py-3 text-xs"
              style={{
                background: "rgba(255,77,109,0.08)",
                borderColor: "rgba(255,77,109,0.35)",
                color: "var(--loss)",
                fontFamily: "var(--font-data)",
              }}
            >
              {runError}
            </div>
          )}

          {!result ? (
            <div
              className="flex-1 flex items-center justify-center rounded border"
              style={{ background: "var(--card)", borderColor: "var(--border)" }}
            >
              <p className="text-xs" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
                {running ? "Running backtest…" : "Pick a strategy and run a backtest."}
              </p>
            </div>
          ) : (
            <>
              {/* ── Key Metrics Row ── */}
              <div className="grid grid-cols-4 gap-2.5 md:grid-cols-8">
                <MetricCard
                  label="Total Return"
                  value={pct(metrics?.total_return)}
                  sub={`vs ${pct(benchmark?.total_return)} B&H`}
                  positive={signOf(metrics?.total_return)}
                />
                <MetricCard label="Excess vs B&H" value={pct(excess)} positive={signOf(excess)} />
                <MetricCard
                  label="Sharpe"
                  value={num(metrics?.sharpe)}
                  sub="Risk-adj. return"
                  positive={signOf(metrics?.sharpe, 1)}
                />
                <MetricCard
                  label="Sortino"
                  value={num(metrics?.sortino)}
                  sub="Downside-adj."
                  positive={signOf(metrics?.sortino, 1)}
                />
                <MetricCard
                  label="Max Drawdown"
                  value={pctPlain(metrics?.max_drawdown)}
                  sub={metrics?.max_drawdown_bars != null ? `${metrics.max_drawdown_bars} bars` : undefined}
                  positive={signOf(metrics?.max_drawdown, -0.15)}
                />
                <MetricCard
                  label="CAGR"
                  value={pct(metrics?.cagr)}
                  sub={`${pctPlain(metrics?.annualized_volatility)} vol`}
                  positive={signOf(metrics?.cagr)}
                />
                <MetricCard
                  label="Win Rate"
                  value={pctPlain(metrics?.trades.win_rate, 1)}
                  sub={`${metrics?.trades.count ?? 0} trades`}
                  positive={signOf(metrics?.trades.win_rate, 0.5)}
                />
                <MetricCard
                  label="Profit Factor"
                  value={num(metrics?.trades.profit_factor)}
                  positive={signOf(metrics?.trades.profit_factor, 1.5)}
                />
              </div>

              {/* ── Chart Section ── */}
              <div className="rounded border flex flex-col" style={{ background: "var(--card)", borderColor: "var(--border)" }}>
                <div className="flex items-center gap-0 border-b px-4 pt-3" style={{ borderColor: "var(--border)" }}>
                  {(["nav", "drawdown", "monthly"] as const).map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setActiveTab(tab)}
                      className="pb-2.5 px-3 text-xs font-medium tracking-wide uppercase transition-colors border-b-2"
                      style={{
                        fontFamily: "var(--font-data)",
                        borderColor: activeTab === tab ? "var(--primary)" : "transparent",
                        color: activeTab === tab ? "var(--primary)" : "var(--muted-foreground)",
                        background: "none",
                        cursor: "pointer",
                        letterSpacing: "0.08em",
                      }}
                    >
                      {tab === "nav" ? "Equity Curve" : tab === "drawdown" ? "Drawdown" : "Monthly Returns"}
                    </button>
                  ))}
                </div>

                <div className="p-4" style={{ height: 320 }}>
                  {activeTab === "nav" && (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 4, bottom: 0 }}>
                        <defs>
                          <linearGradient id="gainGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="var(--gain)" stopOpacity={0.18} />
                            <stop offset="95%" stopColor="var(--gain)" stopOpacity={0} />
                          </linearGradient>
                          <linearGradient id="benchGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.12} />
                            <stop offset="95%" stopColor="var(--primary)" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                        <XAxis
                          dataKey="date"
                          tick={{ fontSize: 9, fill: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}
                          tickLine={false}
                          axisLine={false}
                          interval="preserveStartEnd"
                          minTickGap={40}
                        />
                        <YAxis
                          tick={{ fontSize: 9, fill: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}
                          tickLine={false}
                          axisLine={false}
                          width={60}
                          domain={["auto", "auto"]}
                          tickFormatter={(v: number) => `$${(v / 1000).toFixed(1)}k`}
                        />
                        <Tooltip content={<CustomTooltip kind="money" />} />
                        {metrics?.initial_equity != null && (
                          <ReferenceLine y={metrics.initial_equity} stroke="rgba(255,255,255,0.1)" strokeDasharray="4 2" />
                        )}
                        <Area
                          type="monotone"
                          dataKey="benchmark"
                          name="Buy & Hold"
                          stroke="var(--primary)"
                          strokeWidth={1.5}
                          fill="url(#benchGrad)"
                          dot={false}
                          activeDot={{ r: 3, fill: "var(--primary)" }}
                          connectNulls
                        />
                        <Area
                          type="monotone"
                          dataKey="equity"
                          name="Strategy"
                          stroke="var(--gain)"
                          strokeWidth={1.5}
                          fill="url(#gainGrad)"
                          dot={false}
                          activeDot={{ r: 3, fill: "var(--gain)" }}
                          connectNulls
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}

                  {activeTab === "drawdown" && (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 4, bottom: 0 }}>
                        <defs>
                          <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="var(--loss)" stopOpacity={0.35} />
                            <stop offset="95%" stopColor="var(--loss)" stopOpacity={0.05} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                        <XAxis
                          dataKey="date"
                          tick={{ fontSize: 9, fill: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}
                          tickLine={false}
                          axisLine={false}
                          interval="preserveStartEnd"
                          minTickGap={40}
                        />
                        <YAxis
                          tick={{ fontSize: 9, fill: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}
                          tickLine={false}
                          axisLine={false}
                          width={52}
                          tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                        />
                        <Tooltip content={<CustomTooltip kind="percent" />} />
                        <ReferenceLine y={0} stroke="rgba(255,255,255,0.1)" />
                        <Area
                          type="monotone"
                          dataKey="drawdown"
                          name="Drawdown"
                          stroke="var(--loss)"
                          strokeWidth={1.5}
                          fill="url(#ddGrad)"
                          dot={false}
                          activeDot={{ r: 3, fill: "var(--loss)" }}
                          connectNulls
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}

                  {activeTab === "monthly" && (
                    <div className="w-full h-full overflow-auto">
                      {heatmapYears.length === 0 ? (
                        <p className="text-xs" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
                          This range is shorter than a month.
                        </p>
                      ) : (
                        <table className="w-full text-xs border-separate" style={{ borderSpacing: "2px", fontFamily: "var(--font-data)" }}>
                          <thead>
                            <tr>
                              <th
                                className="text-left pb-1 pr-3 font-medium"
                                style={{ color: "var(--muted-foreground)", fontSize: "0.65rem", letterSpacing: "0.08em" }}
                              >
                                YEAR
                              </th>
                              {MONTH_LABELS.map((m) => (
                                <th
                                  key={m}
                                  className="pb-1 font-medium text-center"
                                  style={{ color: "var(--muted-foreground)", fontSize: "0.65rem", letterSpacing: "0.08em", width: 52 }}
                                >
                                  {m}
                                </th>
                              ))}
                              <th
                                className="pb-1 font-medium text-center"
                                style={{ color: "var(--muted-foreground)", fontSize: "0.65rem", letterSpacing: "0.08em", width: 56 }}
                              >
                                FULL YR
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {heatmapYears.map((year) => {
                              const yearRets = monthlyByYear[year];
                              // Compounded, not summed: three +10% months are
                              // +33.1%, and a summed row would not tie back to
                              // the equity curve.
                              const yearTotal =
                                Object.values(yearRets).reduce((acc, r) => acc * (1 + r), 1) - 1;
                              return (
                                <tr key={year}>
                                  <td className="pr-3 font-semibold" style={{ color: "var(--muted-foreground)", fontSize: "0.7rem" }}>
                                    {year}
                                  </td>
                                  {MONTH_LABELS.map((label, monthIndex) => {
                                    const ret = yearRets[monthIndex];
                                    return (
                                      <td key={label} className="text-center">
                                        {ret !== undefined ? (
                                          <div
                                            className="rounded text-center py-1 text-[10px] font-medium"
                                            style={{
                                              background: colorForReturn(ret),
                                              color: Math.abs(ret) > 0.01 ? "var(--foreground)" : "var(--muted-foreground)",
                                              minWidth: 44,
                                            }}
                                          >
                                            {ret > 0 ? "+" : ""}
                                            {(ret * 100).toFixed(1)}
                                          </div>
                                        ) : (
                                          <div className="rounded py-1" style={{ background: "rgba(255,255,255,0.02)", minWidth: 44 }} />
                                        )}
                                      </td>
                                    );
                                  })}
                                  <td className="text-center">
                                    <div
                                      className="rounded text-center py-1 text-[10px] font-semibold"
                                      style={{ background: colorForReturn(yearTotal), color: "var(--foreground)", minWidth: 48 }}
                                    >
                                      {yearTotal >= 0 ? "+" : ""}
                                      {(yearTotal * 100).toFixed(1)}
                                    </div>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* ── Bottom Row ── */}
              <div className="grid gap-5 md:grid-cols-2" style={{ gridTemplateColumns: "1fr 1.6fr" }}>
                <div className="flex flex-col gap-5">
                  <div className="rounded border p-4" style={{ background: "var(--card)", borderColor: "var(--border)" }}>
                    <p
                      className="text-[10px] font-semibold tracking-widest uppercase mb-3"
                      style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}
                    >
                      Risk &amp; Costs
                    </p>
                    <StatRow label="Calmar Ratio" value={num(metrics?.calmar)} tone={toneOf(metrics?.calmar)} />
                    <StatRow label="Ann. Volatility" value={pctPlain(metrics?.annualized_volatility)} />
                    <StatRow label="Exposure" value={pctPlain(metrics?.exposure, 1)} />
                    <StatRow label="Avg Win" value={pct(metrics?.trades.avg_win)} tone="gain" />
                    <StatRow label="Avg Loss" value={pct(metrics?.trades.avg_loss)} tone="loss" />
                    <StatRow label="Avg Trade" value={pct(metrics?.trades.avg_trade)} tone={toneOf(metrics?.trades.avg_trade)} />
                    <StatRow label="Turnover" value={num(metrics?.turnover, 1)} />
                    <StatRow
                      label="Cost Drag"
                      value={pctPlain(metrics?.cost_drag)}
                      tone={metrics?.cost_drag ? "loss" : "neutral"}
                    />
                    <StatRow label="Final Equity" value={money(metrics?.final_equity)} tone={toneOf(metrics?.total_return)} />
                  </div>

                  <div className="rounded border p-4" style={{ background: "var(--card)", borderColor: "var(--border)" }}>
                    <p
                      className="text-[10px] font-semibold tracking-widest uppercase mb-3"
                      style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}
                    >
                      Buy &amp; Hold Benchmark
                    </p>
                    <StatRow label="Total Return" value={pct(benchmark?.total_return)} tone={toneOf(benchmark?.total_return)} />
                    <StatRow label="CAGR" value={pct(benchmark?.cagr)} tone={toneOf(benchmark?.cagr)} />
                    <StatRow label="Max Drawdown" value={pctPlain(benchmark?.max_drawdown)} tone="loss" />
                    <StatRow label="Sharpe" value={num(benchmark?.sharpe)} tone={toneOf(benchmark?.sharpe)} />
                  </div>
                </div>

                {/* Trade log */}
                <div className="rounded border flex flex-col overflow-hidden" style={{ background: "var(--card)", borderColor: "var(--border)" }}>
                  <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: "var(--border)" }}>
                    <p
                      className="text-[10px] font-semibold tracking-widest uppercase"
                      style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}
                    >
                      Trade Log
                    </p>
                    <span className="text-[10px]" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
                      {trades.length} round trips
                    </span>
                  </div>
                  <div className="overflow-auto flex-1" style={{ maxHeight: 420 }}>
                    {trades.length === 0 ? (
                      <p className="px-4 py-6 text-xs" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
                        This strategy never opened a position over the selected range.
                      </p>
                    ) : (
                      <table className="w-full" style={{ fontFamily: "var(--font-data)", fontSize: "0.7rem" }}>
                        <thead className="sticky top-0" style={{ background: "#0d0f1c" }}>
                          <tr>
                            {["Entry", "Exit", "Side", "Entry $", "Exit $", "Bars", "Net"].map((h) => (
                              <th
                                key={h}
                                className="px-3 py-2 text-left font-medium"
                                style={{ color: "var(--muted-foreground)", letterSpacing: "0.06em", fontSize: "0.65rem" }}
                              >
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {trades.map((t, i) => (
                            <tr
                              key={`${t.entry_date}-${i}`}
                              style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.018)" }}
                            >
                              <td className="px-3 py-1.5" style={{ color: "var(--muted-foreground)" }}>
                                {day(t.entry_date)}
                              </td>
                              <td className="px-3 py-1.5" style={{ color: "var(--muted-foreground)" }}>
                                {t.is_open ? "open" : day(t.exit_date)}
                              </td>
                              <td className="px-3 py-1.5">
                                <span
                                  className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase"
                                  style={{
                                    background: t.direction === "long" ? "rgba(0,229,160,0.15)" : "rgba(255,77,109,0.15)",
                                    color: t.direction === "long" ? "var(--gain)" : "var(--loss)",
                                  }}
                                >
                                  {t.direction}
                                </span>
                              </td>
                              <td className="px-3 py-1.5" style={{ color: "var(--foreground)" }}>
                                {t.entry_price.toFixed(2)}
                              </td>
                              <td className="px-3 py-1.5" style={{ color: "var(--foreground)" }}>
                                {t.exit_price.toFixed(2)}
                              </td>
                              <td className="px-3 py-1.5" style={{ color: "var(--muted-foreground)" }}>
                                {t.bars}
                              </td>
                              <td className="px-3 py-1.5" style={{ color: t.net_return >= 0 ? "var(--gain)" : "var(--loss)" }}>
                                {pct(t.net_return)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
