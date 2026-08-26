/**
 * The one place the frontend talks to the backend.
 *
 * Every call goes through `get`/`post` so failures surface as thrown errors
 * with the route named — a screen must never render a blank table because a
 * fetch quietly returned undefined. Types mirror tradingagents/api.py, which
 * is pinned by tests/test_api.py on the Python side.
 */

/** Same-origin by default: this server proxies /api/* to the Python API
 * (see next.config.ts), so there is one port and no CORS. Override only to
 * point a browser at a backend on another host. */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`);
  return r.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`);
  return r.json() as Promise<T>;
}

// ---------------------------------------------------------------- types
export interface StrategyRow {
  id: string;
  coin: string;
  tf: string;
  signal: string;
  th?: number;
  sl: number;
  tp: number;
  sizing: string;
  trades: number;
  wins: number;
  losses: number;
  winrate: number;
  profit: number;
  lev?: number;
  base?: number;
  notional?: number;
  dd?: number;
  green?: number;
  months?: number;
  days?: number;
  funding?: number;
}

export interface TradeLogRow {
  "entry time": string;
  "exit time": string;
  side: string;
  why: string;
  entry: number;
  exit: number;
  step: number;
  "margin $": number;
  "funding $"?: number;
  "WIN/LOSE": string;
  "pnl $": number;
  "running total $": number;
}

export interface TradesResult {
  log: TradeLogRow[];
  trades?: number;
  wins?: number;
  losses?: number;
  profit?: number;
  winrate?: number;
  why?: string;
}

export interface CoinStorageRow {
  coin: string;
  tf: string;
  candles: number;
  rows: number;
  states: number;
  total: number;
  last_ms: number | null;
  bars: number | null;
}

export interface CoverageRow {
  symbol: string;
  timeframe: string;
  bars: number;
  first: string;
  last: string;
  days: number;
}

/** one core's slot in a parallel sweep */
export interface WorkerSlot {
  /** display index among the LIVING workers (0..n-1), assigned on read */
  core?: number;
  /** the worker process itself — the only stable identity a core has */
  pid?: number;
  slot: number | null;
  pair?: string;
  done?: number;
  total?: number;
  pct?: number;
  rows?: number;
  state?: string;
  updated?: number;
}

export interface JobStatus {
  running: boolean;
  /** how many cores the sweep was given */
  cores?: number;
  fresh?: boolean;      // true = replayed from scratch, false = gap fill
  /** live per-core progress, one entry per busy slot */
  workers?: WorkerSlot[];
  done?: number;
  total?: number;
  now?: string;
  bars_stored?: number;
  rows?: number;
  saved?: number;
  errors?: number;
  new_bars?: number;
  note?: string;
  error?: string;
  report?: string;
  report_url?: string;
  key?: string;
  cached?: boolean;
  mode?: string;
  stopped?: boolean;
  pct?: number;
  finished?: number;
  pid?: number;
}

export interface LedgerRow {
  ts: number;
  action: string;
  symbol?: string;
  strategy?: string;
  side?: string;
  entry?: number;
  exit?: number;
  margin?: number;
  /** The ledger writes `pnl_est`; `pnl` was never a field, so a table
   *  reading only `pnl` printed a dash on every trade. */
  pnl?: number;
  pnl_est?: number | null;
  /** Stable 8-char id minted at entry and carried to the exit row, plus the
   *  opening time and how long it was held (auto_trader.trade_code). */
  trade_id?: string;
  opened_at?: number | null;
  held_s?: number | null;
  why?: string;
  dry_run?: boolean | null;
}

export interface DeploymentRow {
  changed_at: number;
  strategy_key: string;
  symbol: string;
  action: string;
  timeframe?: string;
  signal?: string;
  threshold?: number;
  tp?: number;
  sl?: number;
  sizing?: string;
  books?: string;
  base_margin?: number;
  note?: string;
}

// ---------------------------------------------------------------- calls
export interface GridPlan {
  signals: number;
  barrier_pairs: number;
  sizings: number;
  coins: number;
  tfs: number;
  combinations: number;
  eta_minutes: number;
  note: string;
}

export interface CloudShard { shard: number; stage?: string; pct?: number; note?: string }

export interface CloudStatus {
  available: boolean;
  why: string;
  run: { id?: number; url?: string } | null;
  shards: CloudShard[];
  conclusion?: string | null;
  done?: number;
}

export interface SysLoad {
  cores: number;
  load1: number;
  load5: number;
  load15: number;
  load_per_core: number;
  busy?: number;
  user?: number;
  sys?: number;
  idle?: number;
  thermal: {
    available: boolean;
    why: string;
    throttled: boolean;
    pressure: string | null;
    speed_limit: number | null;
  };
}

/** The orders the stored-strategy list can be ranked by. Mirrors
 *  rows_index.SORTS; the label is what the caption prints, so the caption
 *  can never disagree with the order (label-must-match-data). */
export const STRATEGY_SORTS = {
  profit: "profit $",
  winrate: "win %",
  trades: "trades",
  dd: "smallest dip $",
} as const;
export type StrategySort = keyof typeof STRATEGY_SORTS;

export const api = {
  system: () => get<SysLoad>("/api/system"),
  contracts: () => get<{ rows: string[]; why: string }>("/api/contracts"),
  candleGaps: () => get<{
    rows: { symbol: string; timeframe: string; bars: number; last: string;
            missing_bars: number; hours_behind: number }[];
    pairs: number; behind: number;
    worst: { symbol: string; timeframe: string; hours_behind: number } | null;
  }>("/api/candles/gaps"),
  /** the pairs the last download gave up on — what RETRY FAILED fetches */
  candleLost: () => get<{
    pairs: { symbol: string; timeframe: string }[]; count: number; written: string;
    /** what the LAST FAILED run lost that is back in the store now */
    recovered: { symbol: string; timeframe: string; bars: number | null; when: string }[];
    failed_run_when: string; unnamed: number;
  }>("/api/candles/lost"),
  /** contracts on MEXC x five timeframes vs the store — "is the candles complete?" */
  candleCompleteness: () => get<{
    ok: boolean; why: string; contracts: number | null; wanted: number | null;
    stored: number | null; missing: { symbol: string; timeframe: string }[];
    complete: boolean | null;
  }>("/api/candles/completeness"),
  plan: (coins: string[], tfs: string[]) =>
    get<GridPlan>(`/api/backtest/plan?coins=${coins.join(",")}&tfs=${tfs.join(",")}`),
  deployedRows: (coins: string[], tfs: string[]) =>
    get<{ rows: { coin: string; tf: string; signal: string; sl: number; tp: number; sizing: string; key: string }[] }>(
      `/api/backtest/deployed?coins=${coins.join(",")}&tfs=${tfs.join(",")}`),
  cloudStatus: () => get<CloudStatus>("/api/cloud/status"),
  cloudDispatch: (spec: { shards?: number; coins?: number; timeframes?: string; days?: number }) =>
    post<{ id?: number; url?: string }>("/api/cloud/dispatch", spec),
  cloudCancel: (run_id: number) => post<{ cancelled: number }>("/api/cloud/cancel", { run_id }),
  cloudMerge: (run_id: number) => post<{ fetched: number } & Record<string, unknown>>("/api/cloud/merge", { run_id }),
  cloudForget: () => post<{ forgotten: boolean }>("/api/cloud/forget", {}),
  health: () =>
    get<{ ok: boolean; storage: Record<string, { files: number; rows: number; bytes: number }> }>(
      "/api/health",
    ),

  strategies: (q: {
    coin?: string;
    tf?: string;
    signal?: string;
    profitable?: boolean;
    limit?: number;
    offset?: number;
    /** what to rank by — the server whitelists it (rows_index.SORTS) */
    sort?: StrategySort;
    /** a win rate with no denominator is not a result: 100% over 1 trade
     *  sat at the top of the live store until this existed */
    minTrades?: number;
  }) => {
    const p = new URLSearchParams();
    if (q.coin) p.set("coin", q.coin);
    if (q.sort) p.set("sort", q.sort);
    if (q.minTrades) p.set("min_trades", String(q.minTrades));
    if (q.tf) p.set("tf", q.tf);
    if (q.signal) p.set("signal", q.signal);
    if (q.profitable) p.set("profitable", "true");
    if (q.limit) p.set("limit", String(q.limit));
    if (q.offset) p.set("offset", String(q.offset));
    return get<{ rows: StrategyRow[]; total: number; index?: IndexStatus;
      /** the order the server actually used, so the caption is derived */
      sort?: StrategySort; min_trades?: number;
      /** a filtered count stops at COUNT_CAP: print "N+" */
      total_capped?: boolean }>(
      `/api/strategies?${p.toString()}`,
    );
  },

  facets: () =>
    get<{ coins: string[]; tfs: string[]; signals: string[] }>(
      "/api/strategies/facets",
    ),

  trades: (row: StrategyRow, baseMargin = 5.0) =>
    post<TradesResult>("/api/strategies/trades", {
      coin: row.coin,
      tf: row.tf,
      signal: row.signal,
      th: row.th ?? 0,
      sl: row.sl,
      tp: row.tp,
      sizing: row.sizing,
      base_margin: baseMargin,
    }),

  storageByCoin: () => get<{ rows: CoinStorageRow[] }>("/api/storage/by-coin"),
  coverage: () => get<{ rows: CoverageRow[] }>("/api/storage/coverage"),

  jobStatus: (kind: "download" | "backtest" | "btupdate" | "stratbt") =>
    get<JobStatus>(`/api/jobs/${kind}`),
  jobStart: (kind: "download" | "backtest" | "btupdate" | "stratbt", spec: unknown) =>
    post<{ pid: number }>(`/api/jobs/${kind}/start`, spec),
  /** Finish the pairs in flight, then hand this sweep to GitHub Actions.
   *  Not a stop: every measured pair stays, and the cloud is dispatched for
   *  the coins the Mac never reached. */
  jobHandoff: (kind: "backtest") =>
    post<{ requested: boolean; note: string }>(`/api/jobs/${kind}/handoff`, {}),
  jobHandoffState: (kind: "backtest") =>
    get<{ available: boolean; why: string; requested: boolean;
          handed_off: boolean; running: boolean;
          stalled: boolean; stalled_why: string }>(`/api/jobs/${kind}/handoff`),

  jobStop: (kind: "download" | "backtest" | "btupdate" | "stratbt") =>
    post<{ ok: boolean }>(`/api/jobs/${kind}/stop`, {}),

  ledger: (limit = 500) =>
    get<{ rows: LedgerRow[]; total: number }>(`/api/ledger?limit=${limit}`),
  deployments: () => get<{ rows: DeploymentRow[] }>("/api/deployments"),
  reports: () =>
    get<{ rows: { name: string; bytes: number; mtime: number }[] }>(
      "/api/reports",
    ),
};

export const fmtMB = (b: number) => `${(b / 1e6).toFixed(2)} MB`;
export const fmtMoney = (v: number | undefined | null) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;

/** THE date format, everywhere: `Aug 03, 2026 8:03pm`.
 *
 * The operator's exact words on 2026-08-22, after asking three times:
 * "i want format of Aug 03, 2026 8:03pm ... this applies to whole module".
 *
 * Each part matters, because each was wrong at some point:
 *   month  — three letters, capitalised: `Aug`
 *   day    — TWO DIGITS, zero padded: `03`, not `3`
 *   year   — four digits, after a comma
 *   hour   — 12-hour, NOT padded: `8`; midnight and noon are `12`
 *   minute — two digits: `03`
 *   am/pm  — LOWERCASE, no space before it: `8:03pm`
 *
 * The twin of `positions_view.fmt_when` on the Python side; a test runs both
 * over the same instants and fails if they ever disagree. Before this existed
 * seven components each called `toLocaleString()` and rendered
 * `8/22/2026, 4:00:00 PM`, a different format on every screen.
 */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtWhenMs(ms: number | undefined | null): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  const d = new Date(ms);
  const dd = String(d.getDate()).padStart(2, "0");
  const h12 = d.getHours() % 12 || 12;
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ap = d.getHours() < 12 ? "am" : "pm";
  return `${MONTHS[d.getMonth()]} ${dd}, ${d.getFullYear()} ${h12}:${mm}${ap}`;
}

/** Same, for a unix timestamp in SECONDS — which is what the API sends. */
export const fmtWhen = (seconds: number | undefined | null): string =>
  seconds == null ? "—" : fmtWhenMs(seconds * 1000);

// ---------------------------------------------------------------- trading
export interface OpenPosition {
  symbol: string;
  unrealized: number;
  margin: number;
  side: string;
  entry: number;
}

export interface PaperPosition {
  symbol: string;
  side: string;
  entry?: number;
  margin?: number;
  strategy?: string;
}

export interface TradeSummary {
  pid: number | null;
  mode: string;
  halted: boolean;
  equity: number | null;
  today_real: { total: number; wins: number; losses: number; trades: number };
  today_paper: { total: number; wins: number; losses: number; trades: number };
  all_time_closed: number;
  open_unrealized: number;
  all_time: number;
  open_positions: OpenPosition[];
  paper_positions: PaperPosition[];
}

export interface CredStatus {
  has_credentials: boolean;
  source: string;
  key_fingerprint: string;
  secret_fingerprint: string;
  stored_on_disk: boolean;
  store_path: string;
  file_mode: string | null;
  file_mode_ok: boolean;
  env_conflict?: Record<string, unknown>;
}

export interface Preflight {
  credentials: boolean;
  read_assets: boolean;
  read_positions: boolean;
  order_permission: boolean | null;
  can_rest_stop: boolean | null;
  [k: string]: unknown;
}

export interface StrategyDeployRow {
  key: string;
  /** a human name for the row, from auto_trader.STRATEGY_LABELS. Provenance,
   *  never numbers: barriers are derived from the spec so they cannot drift. */
  label?: string;
  /** stable row id, hashed from the combination by backtest_report.row_code —
   *  the same id a report's find-by-ID box takes. Blank when the strategy has
   *  no contract, since there is then no combination to hash. */
  id?: string;
  interval?: string;
  tp?: number;
  sl?: number;
  threshold?: number;
  books: string[];
  coins: string[];
  base_margin?: number | null;
  loss_cap?: number | null;
  live_locked?: { coin: string; held_by: string } | null;
  streak?: number;
  streak_book?: string;
  streak_shared_with?: string[];
  ladder?: number[];
  ladder_rung?: number;
  next_stake?: number;
  notional?: number;
  tripped?: boolean;
  today?: number;
  pnl: number;
  trades: number;
  wins: number;
  losses: number;
  open_on: string[];
  open_on_paper: string[];
}

export interface TradeStrategies {
  rows: StrategyDeployRow[];
  sizing: string;
  conflicts: { symbol?: string; keys?: string[] }[];
  real_count: number;
  paper_count: number;
  idle_count: number;
  deployed_count: number;
  catalog_count: number;
  showing_catalog: boolean;
  account_loss_cap: number;
  account_cap_hit: boolean;
  tripped: string[];
  locks: Record<string, { coin: string; held_by: string }>;
  flat: boolean;
  leverage: number;
  ladder_steps: number[];
}

export interface DayStat {
  pnl: number;
  wins: number;
  losses: number;
  trades: number;
  coins: string[];
}

export interface BarrierValue { pct: number; usd: number }

export interface PositionRow {
  id: string;
  symbol: string;
  coin: string;
  state: string;
  strategy: string;
  /** the same human name the strategies grid shows, from
   *  auto_trader.label_for. Blank when the row has none. */
  label?: string;
  side: string;
  opened: string;
  held: string;
  opened_ts?: number;
  vol: number | null;
  margin: number | null;
  entry: number | null;
  tp: number | null;
  sl: number | null;
  bracket: string;
  unrealized: number | null;
  realized: number;
  wins: number;
  losses: number;
  trades: number;
  total: number;
  notional: number;
  price: number | null;
  tp_value: BarrierValue | null;
  sl_value: BarrierValue | null;
  progress_pct: number | null;
  progress_to: string | null;
}

export interface PositionsPayload {
  real: PositionRow[];
  paper: PositionRow[];
  leverage: number;
  unprotected: string[];
}

export interface HistoryRow {
  ts: number; when: string; coin: string; side: string;
  strategy: string; why: string; profit: number; running: number;
  /** Stable 8-char trade id, its opening time and how long it was held —
   *  stored on the ledger row itself, not derived for display. */
  id?: string; opened?: string; held?: string;
}

export interface MonthRow {
  key: string; label: string; trades: number; wins: number;
  losses: number; profit: number; win_rate: number;
}

export interface HistoryPayload {
  rows: HistoryRow[]; total: number; page: number; pages: number;
  per_page: number; months: MonthRow[];
  totals: { trades: number; wins: number; losses: number; profit: number };
}

export const tradeApi = {
  equity: (dry = false) =>
    get<{ points: { ts: number; equity: number; coin: string }[]; last: number; trades: number }>(
      `/api/trade/equity?dry=${dry}`),
  history: (dry: boolean, page = 1, per_page = 5) =>
    get<HistoryPayload>(`/api/trade/history?dry=${dry}&page=${page}&per_page=${per_page}`),
  positions: () => get<PositionsPayload>("/api/trade/positions"),
  closeOne: (symbol: string) =>
    post<{ closed: boolean; why?: string; pnl?: number }>("/api/trade/positions/close", { symbol }),
  panic: (close_positions = true) =>
    post<{ halted: boolean; runner_stopped: boolean; closed: string[]; failed: string[] }>(
      "/api/trade/panic", { confirm: true, close_positions }),
  halt: (halt: boolean) => post<{ halted: boolean }>("/api/trade/halt", { halt }),
  backtestStrategy: (key: string, label: string) =>
    post<{ pid: number }>("/api/trade/strategies/backtest", { key, label }),
  supervisor: () => get<{
    installed: boolean; loaded: boolean; wants_runner: boolean;
    pid: number | null; free_mb: number; min_free_mb: number; disk_ok: boolean;
    throttle_seconds: number; last_beat_seconds: number | null; stale: boolean;
    log: string;
  }>("/api/trade/supervisor"),
  setSupervisor: (enabled: boolean) =>
    post<{ ok?: boolean; installed: boolean; loaded: boolean }>("/api/trade/supervisor", { enabled }),
  creds: () => get<CredStatus>("/api/trade/credentials"),
  credsSave: (api_key: string, api_secret: string) =>
    post<{ saved: boolean } & CredStatus>("/api/trade/credentials", { api_key, api_secret }),
  credsForget: () => post<{ cleared: boolean } & CredStatus>("/api/trade/credentials/forget", {}),
  credsTest: (symbol = "BTC_USDT") => post<Preflight>("/api/trade/credentials/test", { symbol }),
  summary: () => get<TradeSummary>("/api/trade/summary"),
  strategies: (catalog = false) =>
    get<TradeStrategies>(`/api/trade/strategies${catalog ? "?catalog=true" : ""}`),
  settingsGet: () => get<{ settings: Record<string, unknown> }>("/api/trade/settings"),
  settingsSave: (settings: unknown) =>
    post<{ ok: boolean; changes_recorded: number }>("/api/trade/settings", settings),
  runnerStart: () => post<{ pid: number }>("/api/trade/runner/start", {}),
  runnerStop: () => post<{ stopped: boolean }>("/api/trade/runner/stop", {}),
  pnlDaily: (dry = false) => get<{ days: Record<string, DayStat> }>(`/api/trade/pnl/daily?dry=${dry}`),
  pnlByCoin: (dry = false) =>
    get<{ coins: Record<string, { pnl: number; trades: number; wins: number; losses: number }> }>(
      `/api/trade/pnl/by-coin?dry=${dry}`,
    ),
  log: (n = 200) => get<{ lines: string[] }>(`/api/trade/log?n=${n}`),
};

// ----------------------------------------------------------------- models
export interface ModelRow {
  id: string;
  label?: string;
  provider?: string;
  base_url?: string | null;
  key_env?: string | null;
  key_present: boolean;
  custom: boolean;
}

export interface PingResult {
  model_id: string;
  status: string;
  pct: number;
  ms: number;
  detail: string;
}

export const modelsApi = {
  list: () => get<{ rows: ModelRow[]; presets: string[] }>("/api/models"),
  add: (body: { model_id: string; preset: string; base_url?: string; key_env?: string }) =>
    post<{ ok: boolean; message: string }>("/api/models/add", body),
  remove: (model_id: string) => post<{ ok: boolean }>("/api/models/remove", { model_id }),
  ping: (model_id: string) => post<PingResult>("/api/models/ping", { model_id }),
};

// ------------------------------------------------------------ new listings
export interface NewCoinRow {
  symbol: string;
  base: string;
  name: string;
  contract: string;
  listed_date: string;
  age_hours: number;
  age_days: number;
  price: number;
  change_pct: number;
  quote_volume: number;
}

export interface ScreenPayload {
  rows: NewCoinRow[];
  scanned: number;
  unresolved: number;
  hidden_by_volume: number;
  hidden_by_age: number;
  fetched_at: number;
  from_cache: boolean;
  stale: boolean;
  window_days: number;
}

export interface UpcomingRow {
  symbol: string;
  base: string;
  name: string;
  open_ms: number | null;
  hours_until: number | null;
}

export interface Candle { t: number; o: number; h: number; l: number; c: number; v: number }

export const cryptoApi = {
  watch: (known: string[], max_age_hours = 48) =>
    post<{ found: NewCoinRow[]; known: string[]; seeded: boolean; merged_into_sweep?: number; why: string }>(
      "/api/crypto/watch", { known, max_age_hours }),
  candles: (symbol: string, interval = "Min60", limit = 200) =>
    get<{ rows: Candle[]; symbol: string; interval: string }>(
      `/api/crypto/candles?symbol=${symbol}&interval=${interval}&limit=${limit}`),
  newListings: (q: { min_volume?: number; include_all?: boolean; min_age_hours?: number; max_age_hours?: number; refresh?: boolean } = {}) => {
    const p = new URLSearchParams();
    if (q.min_volume) p.set("min_volume", String(q.min_volume));
    if (q.include_all) p.set("include_all", "true");
    if (q.min_age_hours) p.set("min_age_hours", String(q.min_age_hours));
    if (q.max_age_hours) p.set("max_age_hours", String(q.max_age_hours));
    if (q.refresh) p.set("refresh", "true");
    return get<ScreenPayload>(`/api/crypto/new?${p.toString()}`);
  },
  upcoming: () => get<{ rows: UpcomingRow[]; why?: string }>("/api/crypto/upcoming"),
};

// ---------------------------------------------------------------- analysis
export interface StageRow {
  label: string;
  status: "done" | "running" | "waiting";
}

export interface AnalysisRun {
  running: boolean;
  run_id: string;
  started_at?: number;
  finished_at?: number;
  spec?: { ticker?: string; trade_date?: string; model?: string; analysts?: string[];
    asset_type?: string; social_source?: string; twitter_keywords?: string[] };
  stages: StageRow[];
  reports: Record<string, string>;
  decision?: string | null;
  error?: string | null;
}

export interface RunListRow {
  run_id: string;
  running: boolean;
  started_at?: number;
  ticker?: string;
  model?: string;
  decision?: string | null;
  error?: string | null;
}

export interface SocialSources {
  sources: { id: string; label: string; note: string }[];
  default: string;
  x_key_present: boolean;
  x_key_env: string;
}

export const analysisApi = {
  socialSources: () => get<SocialSources>("/api/analysis/social/sources"),
  tickers: () => get<{ rows: { symbol: string; name: string }[] }>("/api/analysis/tickers"),
  reportUrl: (id: string) => `${API_BASE}/api/analysis/${id}/report.md`,
  startMany: (spec: unknown) =>
    post<{ run_id: string; run_ids: { model: string; run_id: string }[] }>("/api/analysis/start", spec),
  runs: () => get<{ rows: RunListRow[] }>("/api/analysis/runs"),
  start: (spec: unknown) => post<{ run_id: string }>("/api/analysis/start", spec),
  status: (id: string) => get<AnalysisRun>(`/api/analysis/${id}`),
  stop: (id: string) => post<{ stopped: boolean }>(`/api/analysis/${id}/stop`, {}),
};

// ---------------------------------------------------------------- notifications
export interface NotifyRow {
  id: number;
  ts: number;
  when: string;
  kind: "download" | "backtest" | "trade_open" | "trade_close" | "error" | string;
  /** false marks a FAILURE (or, for a closed trade, a loss) */
  ok: boolean;
  title: string;
  detail: string;
  /** a FAILED download made whole since: true/false with the measured reason;
   *  null when there is nothing to resolve */
  resolved?: boolean | null; resolved_why?: string;
  read: boolean;
  meta: Record<string, unknown>;
}
export interface NotifyPayload { rows: NotifyRow[]; unread: number; total: number }

/** a pair a download gave up on, and whether the store has it NOW */
export interface LostPair {
  symbol: string; timeframe: string; recovered: boolean; bars: number | null; when: string;
}
export interface DownloadHistoryRow {
  ts: number; when: string; ok: boolean; title: string; detail: string;
  pairs?: number | null; bars?: number | null; errors?: number | null;
  stopped: boolean; mode: string;
  lost?: LostPair[]; unnamed?: number;
  resolved?: boolean | null; resolved_why?: string;
}
export interface DownloadHistory {
  rows: DownloadHistoryRow[]; total: number; ok: number; failed: number;
}

export const notifyApi = {
  list: (limit = 30) => get<NotifyPayload>(`/api/notifications?limit=${limit}`),
  markRead: (ids?: number[]) =>
    post<{ marked: number; unread: number }>("/api/notifications/read",
      ids ? { ids } : {}),
  downloadHistory: (limit = 20) =>
    get<DownloadHistory>(`/api/candles/download-history?limit=${limit}`),
};

// ------------------------------------------------------------- running jobs
export interface RunningJob {
  kind: string; now: string; done: number; total: number; pct: number | null;
}
export interface JobsAll {
  jobs: Record<string, JobStatus>;
  running: RunningJob[];
  any_running: boolean;
}

export const jobsApi = {
  /** every job in ONE request — the header indicator polls this so a running
   *  job stays visible after you navigate away from the screen that started it */
  all: () => get<JobsAll>("/api/jobs"),
};

// --------------------------------------------------------- backtest store
export interface BtStorageRow {
  coin: string; tf: string; rows: number; combos: number | null; bytes: number;
  version: string;
  /** the last CANDLE the grid was tested against — the honest freshness mark */
  measured_through: string | null;
  measured_ms: number | null;
  /** rows on disk but no watermark: a checkpoint kept the work of a pair that
   *  never finished */
  incomplete: boolean;
  last_run: string | null;
  last_run_ts: number | null;
}
export interface BtStorage {
  rows: BtStorageRow[];
  pairs: number; coins: number; total_rows: number; total_bytes: number;
  incomplete: number; newest_measured: string | null;
}

export interface BtHistoryRow {
  ts: number; when: string; ok: boolean; title: string; detail: string;
  rows?: number | null; report?: string | null; fatal: boolean;
  save_error: string;
}
export interface BtHistory {
  rows: BtHistoryRow[]; total: number; ok: number; failed: number;
}

export type IndexStatus = {
  pairs_indexed: number;
  pairs_on_disk: number;
  rows: number;
  behind: number;        // pairs measured but not yet queryable
  syncing: boolean;
  updated: number | null;
};

export const backtestApi = {
  storage: () => get<BtStorage>("/api/backtest/storage"),
  history: (limit = 20) => get<BtHistory>(`/api/backtest/history?limit=${limit}`),
};

/** bytes -> a size a human reads */
export function fmtBytes(b?: number | null): string {
  if (!b) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0, n = b;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i += 1; }
  return `${n < 10 && i ? n.toFixed(1) : Math.round(n)} ${u[i]}`;
}
