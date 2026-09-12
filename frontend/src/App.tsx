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
  type BacktestRequest,
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

// ─── Share links ──────────────────────────────────────────────────────────────
//
// A backtest is fully described by its requests, so a share link is just those
// flattened into the query string: range fields as-is, `tickers` and
// `strategies` as parallel comma lists, strategy params as `p.<slug>.<name>`,
// execution config as `c.<name>`. Nothing is stored server-side — the
// recipient's page rebuilds the form and re-runs.

/** One backtest to run, labelled for the results view. */
type Run = { label: string; body: BacktestRequest };

function toSearch(runs: Run[]): string {
  const q = new URLSearchParams();
  const first = runs[0]?.body;
  if (!first) return "";
  for (const k of ["period", "start", "end", "interval"] as const) if (first[k]) q.set(k, String(first[k]));
  q.set("tickers", runs.map((r) => r.body.ticker).join(","));
  q.set("strategies", runs.map((r) => r.body.strategy).join(","));
  for (const { body } of runs) {
    for (const [k, v] of Object.entries(body.params)) q.set(`p.${body.strategy}.${k}`, String(v));
  }
  for (const [k, v] of Object.entries(first.config)) q.set(`c.${k}`, String(v));
  return q.toString();
}

function fromSearch(search: string) {
  const q = new URLSearchParams(search);
  // Older links carried one `ticker`, one `strategy`, and flat `p.<name>` keys.
  const tickers = (q.get("tickers") ?? q.get("ticker") ?? "").split(",").filter(Boolean);
  const strategies = (q.get("strategies") ?? q.get("strategy") ?? "").split(",");
  const params: Record<string, Values> = {};
  const config: Values = {};
  for (const [k, v] of q) {
    if (k.startsWith("p.")) {
      const [a, b] = k.slice(2).split(".");
      const [slug, name] = b === undefined ? [strategies[0], a] : [a, b];
      if (slug) (params[slug] ??= {})[name] = v;
    } else if (k.startsWith("c.")) config[k.slice(2)] = v;
  }
  return { q, tickers, strategies, params, config };
}

const MAX_TICKERS = 5;
// First entry is the old single-strategy colour, so one ticker looks as before.
const SERIES_COLORS = ["var(--gain)", "#f5a623", "#c084fc", "#38bdf8", "#f472b6"];

/**
 * Thin a curve for the chart: ten years of daily bars is 2500 points, and an
 * SVG path with one node per pixel column looks the same as one with four.
 * The final bar carries the headline return; never let it fall in a gap.
 */
function thin<T>(points: T[]): T[] {
  const step = Math.max(1, Math.floor(points.length / 400));
  const kept = points.filter((_, i) => i % step === 0);
  const last = points[points.length - 1];
  if (last && kept[kept.length - 1] !== last) kept.push(last);
  return kept;
}

const LOADING_NOTE = "Backtest is loading... (takes a while on the first load since I'm using a free Render instance.)";

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
      step={spec.name === "risk_free_rate" ? "0.00001" : undefined}
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

function TabBar<T extends string>({
  tabs,
  active,
  onChange,
  dense = false,
}: {
  tabs: { value: T; label: string }[];
  active: T;
  onChange: (t: T) => void;
  /** Tighter spacing for the narrow sidebar. */
  dense?: boolean;
}) {
  return (
    <div className={`flex items-center gap-0 border-b pt-3 shrink-0 ${dense ? "px-2" : "px-4"}`} style={{ borderColor: "var(--border)" }}>
      {tabs.map((tab) => (
        <button
          key={tab.value}
          onClick={() => onChange(tab.value)}
          className={`pb-2.5 font-medium tracking-wide uppercase transition-colors border-b-2 ${dense ? "px-2 text-[11px]" : "px-3 text-xs"}`}
          style={{
            fontFamily: "var(--font-data)",
            borderColor: active === tab.value ? "var(--primary)" : "transparent",
            color: active === tab.value ? "var(--primary)" : "var(--muted-foreground)",
            background: "none",
            cursor: "pointer",
            letterSpacing: "0.08em",
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
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

  // Data selection. Each row pairs a ticker with the strategy that runs on it;
  // the range and interval are shared by every row.
  const [rows, setRows] = useState<{ ticker: string; slug: string; hidden?: boolean }[]>([{ ticker: "AAPL", slug: "" }]);
  const [rangeMode, setRangeMode] = useState<"period" | "custom">("period");
  const [period, setPeriod] = useState("2y");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [interval, setInterval] = useState("1d");

  // One set of parameter values per strategy, shared by every ticker running
  // it, so switching away and back does not lose what was typed.
  const [paramsBySlug, setParamsBySlug] = useState<Record<string, Values>>({});
  const [configValues, setConfigValues] = useState<Values>({});
  const [showSettings, setShowSettings] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(224);
  const [sidebarTab, setSidebarTab] = useState<"tickers" | "strategy" | "params">("tickers");

  // Run state: one result per run label, and which one fills the detail view.
  const [results, setResults] = useState<Record<string, BacktestResponse>>({});
  const [selected, setSelected] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"nav" | "drawdown" | "monthly">("nav");
  const [copied, setCopied] = useState(false);

  const strategyOf = (slug: string) => strategies.find((s) => s.slug === slug);
  // Strategies in use, in the order they first appear in the Strategy tab, so
  // the Params tab reads top-to-bottom the same way.
  const usedSlugs = [...new Set(rows.map((r) => r.slug).filter(Boolean))];

  // The request builder reads current form state, so it is rebuilt on every
  // change; `run` below depends on it. This is the one place form state turns
  // into requests — a pair-trading run would be one more entry here.
  const tickerOf = (r: { ticker: string }) => r.ticker.trim().toUpperCase();
  // The same ticker under two strategies is a legitimate comparison, so
  // label it by both. This label keys `results` and the chart series.
  const labelOf = useCallback(
    (row: { ticker: string; slug: string }) => {
      const t = tickerOf(row);
      const repeated = rows.filter((r) => tickerOf(r) === t).length > 1;
      return repeated ? `${t} · ${strategies.find((s) => s.slug === row.slug)?.name ?? row.slug}` : t;
    },
    [rows, strategies],
  );
  const hiddenLabels = new Set(rows.filter((r) => r.hidden).map(labelOf));

  const buildRequests = useCallback((): Run[] => {
    // The backend rejects a request carrying both a period and explicit dates,
    // so the mode toggle decides which pair goes in.
    const range =
      rangeMode === "period"
        ? { period, start: null, end: null }
        : { period: null, start: start || null, end: end || null };

    const seen = new Set<string>();
    const runs: Run[] = [];
    for (const row of rows) {
      const t = tickerOf(row);
      const { slug } = row;
      if (!t || !slug) continue;
      // Only an exact repeat (same ticker, same strategy) is skipped.
      const label = labelOf(row);
      if (seen.has(label)) continue;
      seen.add(label);
      runs.push({
        label,
        body: {
          ticker: t,
          ...range,
          interval,
          strategy: slug,
          params: submitted(paramsBySlug[slug] ?? {}),
          config: submitted(configValues),
          // The per-bar frame is the largest part of the response and nothing
          // on this screen reads it.
          include_bars: false,
        },
      });
    }
    return runs;
  }, [rows, labelOf, rangeMode, period, start, end, interval, paramsBySlug, configValues]);

  const requestRef = useRef(buildRequests);
  requestRef.current = buildRequests;

  const run = useCallback(async () => {
    const runs = requestRef.current();
    if (!runs.length) {
      setRunError("Enter a ticker to backtest.");
      return;
    }

    setRunning(true);
    setRunError(null);
    // One bad ticker should not sink the others, so every run settles and the
    // failures are listed together. A 400 is almost always the user's input —
    // an unknown ticker, a start date past the intraday lookback, fast >= slow
    // — and the backend's message says which, so show it verbatim.
    const settled = await Promise.allSettled(runs.map((r) => runBacktest(r.body)));
    const next: Record<string, BacktestResponse> = {};
    const errors: string[] = [];
    settled.forEach((s, i) => {
      if (s.status === "fulfilled") next[runs[i].label] = s.value;
      else errors.push(`${runs[i].label}: ${s.reason instanceof ApiError ? s.reason.message : String(s.reason)}`);
    });
    setResults(next);
    setSelected((sel) => (next[sel] ? sel : Object.keys(next)[0] ?? ""));
    setRunError(errors.length ? errors.join("\n") : null);
    setRunning(false);
  }, []);

  const share = useCallback(async () => {
    const url = `${window.location.origin}${window.location.pathname}?${toSearch(requestRef.current())}`;
    window.history.replaceState(null, "", url);
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard is blocked (insecure origin, denied permission) — the URL is
      // already in the address bar, so the user can copy it from there.
      setRunError("Couldn't copy automatically — copy the link from the address bar.");
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

        // A share link overlays the schema defaults; anything it omits or
        // names wrongly just falls through to the defaults (or a backend 400).
        const shared = fromSearch(window.location.search);
        const known = (slug: string | undefined) => catalogue.some((s) => s.slug === slug);
        const first = catalogue[0]?.slug ?? "";
        const defaults = Object.fromEntries(catalogue.map((s) => [s.slug, defaultsOf(s.params)]));
        for (const [slug, values] of Object.entries(shared.params)) {
          if (known(slug)) defaults[slug] = { ...defaults[slug], ...values };
        }

        setStrategies(catalogue);
        setConfigSpecs(config);
        setConfigValues({ ...defaultsOf(config), ...shared.config });
        setParamsBySlug(defaults);
        const tickers = shared.tickers.length ? shared.tickers.slice(0, MAX_TICKERS) : ["AAPL"];
        setRows(
          tickers.map((t, i) => ({
            ticker: t.toUpperCase(),
            slug: known(shared.strategies[i]) ? shared.strategies[i] : first,
          })),
        );
        const [interval, period, start, end] = ["interval", "period", "start", "end"].map((k) => shared.q.get(k));
        if (interval) setInterval(interval);
        if (period) setPeriod(period);
        if (start || end) {
          setRangeMode("custom");
          setStart(start ?? "");
          setEnd(end ?? "");
        }
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

  // Fires exactly once, after the schema load has put real defaults in the form.
  const autoRan = useRef(false);
  useEffect(() => {
    if (loadingSchema || schemaError || autoRan.current) return;
    autoRan.current = true;
    void run();
  }, [loadingSchema, schemaError, run]);

  const setRow = (i: number, patch: Partial<{ ticker: string; slug: string; hidden?: boolean }>) =>
    setRows((all) => all.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const setParam = (slug: string, name: string, value: string) =>
    setParamsBySlug((all) => ({ ...all, [slug]: { ...all[slug], [name]: value } }));

  const setConfigValue = (name: string, value: string) =>
    setConfigValues((c) => ({ ...c, [name]: value }));

  const labels = Object.keys(results);
  const result = results[selected];
  const metrics = result?.metrics;
  const benchmark = metrics?.benchmark;
  const trades = result?.trades ?? [];

  // Excess return over buy-and-hold. Not Jensen's alpha — the backend does not
  // compute a beta — so it is labelled for what it is.
  const excess =
    metrics?.total_return != null && benchmark?.total_return != null
      ? metrics.total_return - benchmark.total_return
      : null;

  // Every run's curve merged by date into one table (`eq_<label>` columns) so
  // they overlay on one chart; runs share initial_equity, so raw dollars are
  // comparable. Benchmark and drawdown come from the selected run only.
  // Different tickers trade on different days (BTC-USD has weekends), hence
  // the merge rather than a zip.
  const chartData = useMemo(() => {
    const byDate = new Map<string, Record<string, string | number | null>>();
    for (const [label, r] of Object.entries(results)) {
      for (const p of thin(r.equity)) {
        const row = byDate.get(p.date) ?? { date: p.date };
        row[`eq_${label}`] = p.equity;
        if (label === selected) {
          row.benchmark = p.benchmark;
          row.drawdown = p.drawdown == null ? null : p.drawdown * 100;
        }
        byDate.set(p.date, row);
      }
    }
    return [...byDate.keys()]
      .sort()
      .map((d) => ({ ...byDate.get(d)!, date: day(d) }));
  }, [results, selected]);

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
      {sidebarOpen && (
      <aside
        className="flex flex-col shrink-0 border-r overflow-y-auto"
        style={{ width: sidebarWidth, background: "#090b18", borderColor: "var(--border)" }}
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
          <>
            <TabBar
              tabs={[
                { value: "tickers", label: "Tickers" },
                { value: "strategy", label: "Strategy" },
                { value: "params", label: "Params" },
              ]}
              active={sidebarTab}
              onChange={setSidebarTab}
              dense
            />
            <div className="flex flex-col gap-4 p-4">
              {sidebarTab === "tickers" && (
                <SidebarSection title="Universe">
                  {rows.map((r, i) => (
                    <div key={i} className="flex items-end gap-1.5">
                      <div className="flex-1">
                        <TextField
                          label={`Ticker ${i + 1}`}
                          value={r.ticker}
                          onChange={(v) => setRow(i, { ticker: v.toUpperCase() })}
                          list="tickers"
                          placeholder="Enter a ticker:ex.AAPL"
                        />
                      </div>
                      <button
                        onClick={() => setRow(i, { hidden: !r.hidden })}
                        title={r.hidden ? "Show curve" : "Hide curve"}
                        aria-pressed={!!r.hidden}
                        className="px-2 py-1.5 rounded"
                        style={{ ...FIELD_STYLE, cursor: "pointer", color: r.hidden ? "var(--muted-foreground)" : "var(--foreground)" }}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
                          <circle cx="12" cy="12" r="3.5" />
                          {r.hidden && <path d="M3 21 21 3" />}
                        </svg>
                      </button>
                      {rows.length > 1 && (
                        <button
                          onClick={() => setRows((all) => all.filter((_, j) => j !== i))}
                          title="Remove ticker"
                          className="px-2 py-1.5 rounded text-sm"
                          style={{ ...FIELD_STYLE, cursor: "pointer", color: "var(--muted-foreground)" }}
                        >
                          ×
                        </button>
                      )}
                    </div>
                  ))}
                  <datalist id="tickers">
                    {TICKER_SUGGESTIONS.map((t) => (
                      <option key={t} value={t} />
                    ))}
                  </datalist>
                  <button
                    onClick={() => setRows((all) => [...all, { ticker: "", slug: strategies[0]?.slug ?? "" }])}
                    disabled={rows.length >= MAX_TICKERS}
                    className="py-1.5 rounded text-[10px] tracking-widest uppercase font-medium"
                    style={{
                      ...FIELD_STYLE,
                      cursor: rows.length >= MAX_TICKERS ? "not-allowed" : "pointer",
                      color: rows.length >= MAX_TICKERS ? "var(--muted-foreground)" : "var(--foreground)",
                    }}
                  >
                    {rows.length >= MAX_TICKERS ? `Max ${MAX_TICKERS} tickers` : "+ Add ticker"}
                  </button>

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
              )}

              {sidebarTab === "strategy" && (
                <SidebarSection title="Strategy per ticker">
                  {rows.map((r, i) => (
                    <div key={i} className="flex flex-col gap-1">
                      <Select
                        label={`#${i + 1} ${r.ticker || "(no ticker)"}`}
                        value={r.slug}
                        options={strategies.map((s) => ({ value: s.slug, label: s.name }))}
                        onChange={(slug) => setRow(i, { slug })}
                      />
                      {strategyOf(r.slug)?.description && (
                        <p className="text-[10px] leading-snug" style={{ color: "var(--muted-foreground)" }}>
                          {strategyOf(r.slug)?.description}
                        </p>
                      )}
                    </div>
                  ))}
                </SidebarSection>
              )}

              {sidebarTab === "params" && (
                <>
                  {usedSlugs.map((slug, i) => (
                    <SidebarSection key={slug} title={`#${i + 1} ${strategyOf(slug)?.name ?? slug}`}>
                      <p className="text-[10px] -mt-2" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
                        {rows.filter((r) => r.slug === slug).map((r) => r.ticker).join(", ")}
                      </p>
                      {strategyOf(slug)?.params.map((spec) => (
                        <SchemaField
                          key={spec.name}
                          spec={spec}
                          value={paramsBySlug[slug]?.[spec.name] ?? ""}
                          onChange={(v) => setParam(slug, spec.name, v)}
                        />
                      ))}
                    </SidebarSection>
                  ))}

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
                </>
              )}

              <Divider />

              <button
                onClick={() => void share()}
                className="mt-1 py-2.5 rounded font-semibold text-xs tracking-widest uppercase transition-all"
                style={{
                  background: "var(--secondary)",
                  color: copied ? "var(--gain)" : "var(--foreground)",
                  fontFamily: "var(--font-data)",
                  cursor: "pointer",
                  border: "1px solid var(--border)",
                }}
              >
                {copied ? "Link copied" : "Share Results"}
              </button>

              <button
                onClick={() => void run()}
                disabled={running}
                className="py-2.5 rounded font-semibold text-xs tracking-widest uppercase transition-all"
                style={{
                  background: running ? "var(--muted)" : "var(--primary)",
                  color: running ? "var(--muted-foreground)" : "var(--primary-foreground)",
                  fontFamily: "var(--font-data)",
                  cursor: running ? "not-allowed" : "pointer",
                  border: "none",
                }}
              >
                {running ? "Backtest is loading..." : "Run Backtest"}
              </button>
            </div>
          </>
        )}
      </aside>
      )}
      {sidebarOpen && (
        <div
          className="w-1 shrink-0 cursor-col-resize hover:bg-[var(--primary)]"
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            e.preventDefault();
          }}
          onPointerMove={(e) => {
            if (e.buttons & 1) setSidebarWidth(Math.min(600, Math.max(160, e.clientX)));
          }}
        />
      )}

      {/* ── Main Panel ── */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <header
          className="flex items-center justify-between px-5 py-3 border-b shrink-0"
          style={{ background: "#090b18", borderColor: "var(--border)" }}
        >
          <div className="flex items-center gap-3 flex-wrap">
            <button
              onClick={() => setSidebarOpen((o) => !o)}
              title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
              className="px-2 py-1 rounded text-sm"
              style={{ ...FIELD_STYLE, cursor: "pointer" }}
            >
              ☰
            </button>
            {result ? (
              <>
                {/* One badge per run; clicking picks which fills the detail view. */}
                {labels.map((label, i) => (
                  <button
                    key={label}
                    onClick={() => setSelected(label)}
                    className="ticker-badge whitespace-nowrap"
                    style={{
                      cursor: "pointer",
                      opacity: label === selected ? 1 : 0.5,
                      color: SERIES_COLORS[i],
                      borderColor: label === selected ? SERIES_COLORS[i] : "var(--border)",
                      background: "transparent",
                    }}
                  >
                    {label}
                  </button>
                ))}
                <span className="text-sm font-medium" style={{ color: "var(--foreground)" }}>
                  {result.strategy.name}
                </span>
                <span className="text-xs" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
                  {day(result.start)} → {day(result.end)} · {result.interval}
                </span>
              </>
            ) : (
              <span className="text-sm" style={{ color: "var(--muted-foreground)" }}>
                {LOADING_NOTE}
              </span>
            )}
          </div>
          <div className="flex items-center gap-4">
            {result && (
              <span className="text-xs" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-data)" }}>
                {result.count} bars
              </span>
            )}
            {(labels.length ? labels : ["Strategy"]).map((label, i) => (
              <div key={label} className="flex items-center gap-1.5 text-xs whitespace-nowrap" style={{ fontFamily: "var(--font-data)", color: SERIES_COLORS[i] }}>
                <span className="w-2 h-2 rounded-full inline-block" style={{ background: SERIES_COLORS[i] }} />
                {label}
              </div>
            ))}
            <div className="flex items-center gap-1.5 text-xs whitespace-nowrap" style={{ fontFamily: "var(--font-data)", color: "var(--primary)" }}>
              <span className="w-2 h-2 rounded-full inline-block" style={{ background: "var(--primary)" }} />
              Buy &amp; Hold
            </div>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-5">
          {runError && (
            <div
              className="rounded border px-4 py-3 text-xs whitespace-pre-line"
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
                {running ? LOADING_NOTE : "Backtest is loading..."}
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
                <TabBar
                  tabs={[
                    { value: "nav", label: "Equity Curve" },
                    { value: "drawdown", label: "Drawdown" },
                    { value: "monthly", label: "Monthly Returns" },
                  ]}
                  active={activeTab}
                  onChange={setActiveTab}
                />

                <div className="p-4" style={{ height: 320 }}>
                  {activeTab === "nav" && (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 4, bottom: 0 }}>
                        <defs>
                          {labels.map((label, i) => (
                            <linearGradient key={label} id={`grad${i}`} x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor={SERIES_COLORS[i]} stopOpacity={0.18} />
                              <stop offset="95%" stopColor={SERIES_COLORS[i]} stopOpacity={0} />
                            </linearGradient>
                          ))}
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
                        {labels.map((label, i) => (
                          <Area
                            key={label}
                            type="monotone"
                            dataKey={`eq_${label}`}
                            name={label}
                            stroke={SERIES_COLORS[i]}
                            hide={hiddenLabels.has(label)}
                            strokeWidth={label === selected ? 2 : 1.25}
                            fill={label === selected ? `url(#grad${i})` : "transparent"}
                            dot={false}
                            activeDot={{ r: 3, fill: SERIES_COLORS[i] }}
                            connectNulls
                          />
                        ))}
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
