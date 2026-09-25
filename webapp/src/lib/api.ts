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

/** An API error that keeps the server's own sentence and its status.
 *
 * `Error: /api/strategies?sort=winrate… → HTTP 503` told the operator nothing;
 * the API had said "ranking by winrate needs its index; it is being built in
 * the background" and the screen threw it away (2026-08-26). */
export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(path: string, status: number, detail: string) {
    super(detail || `${path} → HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** THE LANE BUDGET. The browser gives one address six connections, and the
 * pages and the API share the address (the /api proxy). Measured Sep 09,
 * 2026: 17 requests in flight on the Backtest screen — the six lanes held by
 * slow API calls (the 500-row strategies query, GitHub status, the logs
 * walk) — and a click on Auto Trade could not change the URL for over two
 * minutes, because the next page's own fetch was queued behind them.
 *
 * So the app never uses more than FOUR lanes for data. The queue is ours
 * instead of the browser's: a fifth call waits here, and the two spare lanes
 * mean a page switch is always instant. Panels already show their own
 * "reading…" states while their data queues. */
const MAX_LANES = 4;
let lanes = 0;
const waiting: (() => void)[] = [];

async function takeLane(): Promise<void> {
  if (lanes < MAX_LANES) { lanes += 1; return; }
  await new Promise<void>((res) => waiting.push(res));
  lanes += 1;
}

function freeLane(): void {
  lanes -= 1;
  waiting.shift()?.();
}

async function fetchLaned(input: string, init?: RequestInit): Promise<Response> {
  await takeLane();
  try {
    return await fetch(input, init);
  } finally {
    freeLane();
  }
}

// WHICH STORE A CALL GOES TO. Backtest v2 (Sep 17, 2026) serves the same
// routes under /api/v2. The URL builders below are read by tests field by
// field, so they keep their exact shape; `storeApi` wraps a call in
// `withApiPrefix(<the v2 prefix>, ...)` instead, and `get`/`post` rebase the path
// SYNCHRONOUSLY — before the first await — so the prefix is back to "/api"
// by the time anything else runs. JavaScript is single-threaded; the window
// is the length of one function call.
let _apiPrefix = "/api";

function _rebase(path: string): string {
  return _apiPrefix === "/api" ? path : path.replace(/^\/api\//, `${_apiPrefix}/`);
}

export function withApiPrefix<T>(prefix: string, fn: () => T): T {
  const prev = _apiPrefix;
  _apiPrefix = prefix;
  try {
    return fn();
  } finally {
    _apiPrefix = prev;
  }
}

async function get<T>(path: string): Promise<T> {
  // rebased BEFORE the first await, while the caller's prefix is in force
  path = _rebase(path);
  let r = await fetchLaned(`${API_BASE}${path}`, { cache: "no-store" });
  // ONE second try, only for a GET. When the API restarts (a fix landing),
  // the proxy answers 500 for the few seconds it is down — on Sep 09, 2026
  // the operator opened Auto Trade in that window and every panel went red.
  // 503 is NOT retried: it carries a real sentence ("the index is being
  // built") the panels are built to show. A POST is never retried — a
  // second submit is a second order.
  if (r.status === 500 || r.status === 502 || r.status === 504) {
    await new Promise((res) => setTimeout(res, 1_500));
    r = await fetchLaned(`${API_BASE}${path}`, { cache: "no-store" });
  }
  if (!r.ok) {
    let detail = "";
    try {
      const body = await r.json();
      detail = typeof body?.detail === "string" ? body.detail : "";
    } catch {
      /* not JSON: the status is all there is */
    }
    throw new ApiError(path, r.status, detail);
  }
  return r.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  path = _rebase(path);
  const r = await fetchLaned(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`);
  return r.json() as Promise<T>;
}

/** post, but a refusal's `detail` becomes the error text — a 409 that says
 *  "a download job is writing this store right now" must reach the screen as
 *  that sentence, not as "HTTP 409" */
async function postDetail<T>(path: string, body: unknown): Promise<T> {
  const r = await fetchLaned(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = "";
    try { detail = String((await r.json())?.detail ?? ""); } catch { /* no body */ }
    throw new Error(detail || `${path} → HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

// ---------------------------------------------------------------- types
export interface StrategyRow {
  /** Backtest v2 only: trades whose exit MINUTE touched both the win and the
   *  lose price and were booked as a loss by rule — the count of trades that
   *  are still a guess. Absent on a v1 row. */
  unclear?: number | null;
  /** the resolution the exits were settled at ("1m" on a v2 row) */
  res?: string | null;
  /** LAST N MONTHS: what this row did inside the window. Profit and green are
   *  exact (the sweep stores profit per month); there is deliberately no
   *  w_trades or w_winrate, because the sweep does not keep those per month. */
  /** 1-10 over win rate AND profit together, and the sentence behind it.
   *  Re-rated on the window's own figures when a window is on. */
  balanced?: number;
  balanced_why?: string;
  /** month key ("2026-08") -> that month's profit for this row. The month
   *  columns in the grid are these keys — the store's own, not a fixed ladder */
  monthly?: Record<string, number>;
  w_profit?: number;
  /** the window's own trades, wins, losses and win rate — present only when the
   *  server could rebuild this row's log (an #id lookup; see RESTATE_MAX) */
  w_trades?: number;
  /** the window THIS row was measured over — each row's own, because a window
   *  ends where its measurement ends, not where the candle file does */
  w_first_ms?: number;
  w_last_ms?: number;
  /** how many of this row's counted trades opened BEFORE the window and closed
   *  inside it (operator, Sep 11, 2026: "open: aug 1 closed aug 12 what will
   *  happen" — they used to be dropped) */
  w_straddle?: number;
  /** WHEN THIS ROW WAS LAST BACKTESTED — from the pair summary, so every row
   *  of the same coin+timeframe shares it.
   *  `measured_ms` is the last CANDLE the backtest tested (what decides
   *  whether a "last 30 days" window is real); `measured_run_ms` is when that
   *  coin's results were last written. Undefined means UNKNOWN, and the screen
   *  prints a dash — never a zero, which would read as `Jan 01, 1970`. */
  measured_ms?: number;
  measured_run_ms?: number;
  w_streak?: number;
  w_streak_len?: number;
  w_dd?: number;
  w_wins?: number;
  w_losses?: number;
  w_winrate?: number;
  w_profit_log?: number;
  restated?: boolean;
  w_green?: number;
  w_months?: number;
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
  /** How long it was held, in the words the live Positions table uses —
   *  "3d 4h", "5h 12m", "42m". A trade that exits inside its own entry bar
   *  reads "<1h" (the frame), because the candles cannot say where in the bar
   *  the barrier was hit and "0m" would claim it closed instantly. */
  held?: string;
  /** the exact bar-to-bar seconds behind `held`; 0 for a same-bar exit */
  held_s?: number;
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
  /** where the candles came from — always "stored candles" since 2026-09-02.
   *  It used to DOWNLOAD the newest bars first, so the log covered days the
   *  row never measured (42 trades and +$164.40 under a row saying 40). */
  source?: string;
  /** "row" = the row's own recorded end bar, so the log reproduces it;
   *  "pair watermark" = an older row that predates `last_ms`, so the replay
   *  can be a trade or two out and the panel says so. */
  window_from?: string;
  bars?: number;
  first?: string;
  last?: string;
  /** the taker fee the replay charged, and where it came from. A contract's
   *  fee CHANGES: PONS_USDT reads 0.04% today and its stored rows were
   *  measured at 0.02%, which is +$1,638.14 against +$1,288.70 over the same
   *  1,820 trades. Rows measured from 2026-09-02 carry their own. */
  fee?: number;
  fee_from?: string;
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

/** one calendar month of a store — candles: bars whose time is in the month;
 *  results: pairs LAST MEASURED in the month (see storage_months.py) */
export interface MonthRow {
  month: string;      // "2025-02"
  label: string;      // "Feb 2025"
  pairs: number;
  bytes: number;
  bars?: number;      // candles
  rows?: number;      // results
  unsized?: number;   // results: pairs indexed before bytes were recorded
}
/** one stored coin the venue no longer lists, and what it costs */
export interface DelistedCoin {
  coin: string;
  symbol: string;
  candle_pairs: number;
  candle_bytes: number;
  result_pairs: number;
  result_rows: number;
  result_bytes: number;
}
export interface DelistedReport {
  /** false = MEXC could not be asked; NOTHING is called delisted then */
  known: boolean;
  why: string;
  coins: DelistedCoin[];
  candle_pairs: number;
  candle_bytes: number;
  result_pairs: number;
  result_rows: number;
  result_bytes: number;
  bytes: number;
}
export interface MonthJob {
  kind: "candles" | "results" | "delisted";
  /** delisted only: the coins it removed */
  coins?: string[];
  /** what the detached worker is doing right now, in words */
  phase?: string;
  through: string;
  label: string;
  running: boolean;
  started_at: string;
  finished_at: string;
  done: number;
  total: number;
  freed: number;
  errors: string[];
  error_count: number;
  files_removed: number;
  files_trimmed: number;
  bars_removed: number;
  rows_removed: number;
}
export interface StorageMonths {
  candles: { rows: MonthRow[]; estimated: boolean; total_bars: number;
             total_bytes: number; files: number };
  results: { rows: MonthRow[]; estimated: boolean; total_rows: number;
             total_bytes: number };
  jobs: { candles: MonthJob | null; results: MonthJob | null };
  writers: { candles: string; results: string };
  this_month: string;
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
  /** THE FULL CSV job (db_jobs "export"/"export_v2"): the filter it was built
   *  for, the finished file, its size, which phase it is in and the time left
   *  (operator, Sep 25, 2026: "if the result is bilion i want to see billion
   *  in csv") */
  spec?: Record<string, unknown>;
  file?: string;
  bytes?: number;
  phase?: string;
  floor_note?: string;
  eta_s?: number | null;
  pairs_total?: number;
  pairs_done?: number;
  /** when the job began (epoch seconds) — with `finished` and `total`, the
   *  speed this PC really achieved, which the next estimate is built from */
  started?: number;
  /** `pairbt` only — the ONE pair a row's UPDATE button is re-measuring, and
   *  what came of it. `index_error` is separate from `error` on purpose: a
   *  pair can measure perfectly and fail to reindex, which leaves a current
   *  row file behind a stale screen (2026-09-09). */
  pair?: string;
  indexed?: number;
  index_error?: string;
  /** the rule the row's UPDATE re-tested, whether the searchable table was
   *  busy and the pair is next in line, and whether there were no new candles
   *  at all — what "Done at …" is built from (RCA-2026-09-24-K) */
  signal?: string;
  index_queued?: boolean;
  already_current?: boolean;
  /** the exchange's cost at the press was NOT charged, and why
   *  (backtest_report.cost_note) */
  cost_note?: string;
  /** THE SLOW HALF, measured. Writing a pair back into the 63 GB table is one
   *  SQLite DELETE + INSERT with no percentage to report, so the job publishes
   *  how long it has been going (`index_seconds`), how many rows it is
   *  replacing (`index_rows` — 29,040 for XPIN 1h against 220 newly measured)
   *  and the estimate from this PC's own last write (`index_eta_s`). */
  index_seconds?: number;
  index_rows?: number;
  index_eta_s?: number | null;
  before_ms?: number;
  after_ms?: number;
  /** how many cores the sweep may use RIGHT NOW — re-asked after every
   *  completed pair, so it rises when memory frees up and falls when it does
   *  not. It used to be the reading taken at startup, which pinned a 28-hour
   *  run to 3 of 11 cores after a crash restart (Sep 03, 2026). */
  cores?: number;
  /** how many pairs are actually in flight, which lags `cores` while the
   *  window ramps up one pair at a time */
  cores_inflight?: number;
  /** cores the machine offered, and why the run is using fewer (low memory) */
  cores_offered?: number;
  cores_why?: string;
  ram_free_gb?: number | null;
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

export interface CloudShard {
  shard: number;
  /** WHICH ACCOUNT ran this machine, and which run it belongs to. One press
   *  starts one run per account ("i want 40") and both number their machines
   *  0..19, so the number alone is not a name. */
  repo?: string;
  run?: number;
  stage?: string;
  pct?: number;
  note?: string;
  /** OLDER readers' fields: the coin this machine is ON (1-based) over the
   *  coins it has claimed so far. The one-at-a-time claim board keeps those
   *  equal, so a bar drawn from them read 100% from the first second
   *  (RCA-2026-09-09-S). Kept for runs measured before Sep 09, 2026. */
  done?: number;
  total?: number;
  /** coins this machine has FINISHED, and the coins the whole run holds (the
   *  same number on every machine): the run's progress is
   *  sum(finished) / board. Absent on older runs — the panel falls back. */
  finished?: number;
  board?: number;
  /** combinations this machine has measured so far */
  rows?: number;
  /** the history window this run was asked for, in days — the header prints
   *  it as real dates ("i dont see what dates are being tested", 2026-09-09) */
  days?: number;
  /** THE PAIR'S OWN DATES: "18,959 bars · Aug 10, 2025 5:00am → Sep 09, 2026
   *  4:00am". Its own field because it used to live inside `note`, where the
   *  per-rule note overwrote it 120 times a pair — 17 of 20 machines showed
   *  no dates at all. Empty while a pair's candles are downloading and once
   *  the machine is done: a span belongs to a pair being tested. Absent on
   *  runs measured before 2026-09-09. */
  span?: string;
  /** pairs this machine posted straight to the operator's PC, and pairs a
   *  post could not reach it with. What the MACHINE tried; the PC's own tally
   *  is CloudStatus.live, and a gap between them names a broken tunnel. */
  posted?: number;
  post_failed?: number;
  /** the span's two bars as milliseconds, printed by the BROWSER's clock
   *  (fmtWhenMs) so the tile and the store's "last bar" name one bar the same
   *  way; `span` is the runner's clock (UTC) and read "12:00pm → 1:00pm" while
   *  the same bars were 8:00pm → 9:00pm on this PC (Sep 09, 2026). Absent on
   *  older runs — the panel falls back to `span`. */
  span_ms?: [number, number];
  /** "full" = every pair from scratch (BACKTEST); "update" = each pair with
   *  a saved position continued over its new bars only (UPDATE). Absent on
   *  runs before 2026-09-09. */
  mode?: "full" | "update";
  /** UPDATE: pairs this machine continued from a saved position, and pairs
   *  it had to measure in full (no saved position yet) */
  continued?: number;
  fresh?: number;
}

export interface CloudStatus {
  /** the run on screen is already in this PC's store, so there is
   *  nothing left to merge */
  collected?: boolean;
  available: boolean;
  why: string;
  /** true before the FIRST background read of GitHub has landed — the API
   *  answers at once rather than holding the request (216 s on Sep 09, 2026,
   *  four of them holding every browser lane); not the same as "not available" */
  reading?: boolean;
  /** `res` is WHICH STORE this run measures for: "" is v1, "1m" is Backtest
   *  v2 (the same frames rebuilt from 1-minute candles). The screen shows a
   *  run only on its own store's tab — a v2 run on the v1 screen is the
   *  label-must-match-data failure this repo keeps paying for. */
  run: { id?: number; url?: string; res?: string } | null;
  shards: CloudShard[];
  conclusion?: string | null;
  /** when the last machine finished, epoch seconds — set only on a finished run */
  finished?: number | null;
  done?: number;
  /** THE OTHER ACCOUNTS' RUNS from the same press. Since Sep 21, 2026 one
   *  press deals the board between every GitHub account this checkout has a
   *  remote for — the operator's and their partner's fork — so 20 machines
   *  became 40 and a tile naming one run would count half of them. */
  siblings?: { id: number; repo: string; url?: string; coins?: number;
               running?: number; done?: number; total?: number;
               conclusion?: string | null; why?: string }[];
  /** how many GitHub accounts this press is using (1 = as it always was) */
  accounts?: number;
  /** THE LIVE DOOR: whether the machines can post finished pairs straight to
   *  this PC, and what has already come through it FOR THE RUN ON SCREEN —
   *  counted by this PC as it writes them, never taken from the machines'
   *  own claim. `pairs`/`rows` are absent when the tally belongs to an
   *  earlier run. */
  live?: {
    open: boolean;
    url?: string;
    pairs?: number;
    rows?: number;
    /** coins that arrived and were ALREADY up to date (no new candle since
     *  their last test). Not a failure — without it the screen would read
     *  "0 pairs written" for a door that worked. */
    stale?: number;
    /** seconds; the last time a pair landed here */
    at?: number | null;
    /** the last pair that landed, e.g. "0G 1h" */
    last?: string;
  };
}

export interface SysLoad {
  cores: number;
  /** free physical memory, or null when the machine will not report it */
  ram_total_gb?: number | null;
  ram_free_gb?: number | null;
  ram_used_pct?: number | null;
  ram_kind?: "measured" | "unknown";
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
  profit: "PROFIT $",
  winrate: "win %",
  trades: "trades",
  dd: "dip $",
} as const;
export type StrategySort = keyof typeof STRATEGY_SORTS;

/** `GET /api/backtest/capacity` — where an update would run. */
export type BacktestPlan = {
  local: string[];
  cloud: string[];
  why: string;
  local_free: boolean;
  local_why: string;
  cloud_free: boolean;
  cloud_why: string;
  workers: number;
  runners: number;
  timeframes: string[];
};

/** `GET /api/backtest/logs` — pending work and named errors. */
export type BacktestLogs = {
  pending: {
    stored: number; measured: number; count: number;
    by_timeframe: Record<string, number>;
    pairs: { symbol: string; timeframe: string }[];
    unnamed: number; checked: string;
    /** pairs on contracts MEXC no longer lists — named, never counted:
     *  no fleet can measure them (Sep 06, 2026) */
    delisted?: number; delisted_coins?: string[];
    /** the half a sweep can ACTUALLY do — what RESOLVE PENDING promises.
     *  A pair needs MIN_BARS[tf] candles (500, or 60 on 1d) before any sweep
     *  makes a row for it, and a young contract has plenty of 15m bars and
     *  almost no 4h ones: 653 pending on Sep 06, 2026 was 8 measurable and
     *  645 short. */
    measurable?: number;
    measurable_by_timeframe?: Record<string, number>;
    too_short?: number;
    too_short_by_timeframe?: Record<string, number>;
    too_short_pairs?: { symbol: string; timeframe: string; bars: number;
                        floor: number }[];
  };
  errors: { where: string; job: string; when: string; pair: string; text: string }[];
  error_count: number;
  cloud: { ok: boolean; why?: string; run?: number | null; url?: string;
           status?: string; shards?: number; silent?: number };
  plan: { when?: number; why?: string; local?: string[]; cloud?: string[];
          cloud_run?: number | null; cloud_url?: string; coins?: number };
  checked: string;
};

/** `GET /api/candles/pending` */
export type CandlePending = {
  count: number;
  behind: number;
  missing: number;
  lost: number;
  delisted: number;
  empty: number;
  unfixable: number;
  /** pairs the run actually touches — LONGER than `count` by the delisted
   *  pairs, which get one confirming attempt each */
  queue: number;
  indexing?: boolean;
  /** how old the candle index these counts come from is, in seconds. A count
   *  from a 27-minute-old index is a 27-minute-old count — which is how a
   *  RESOLVE run that was working perfectly appeared to make things worse
   *  (2026-09-05). */
  index_age_s?: number;
  /** how far behind the MEDIAN stale pair is, in hours — what "behind"
   *  actually means. The count returns to ~5,000 within hours of any run
   *  because every stored pair is behind again as soon as a bar prints, so a
   *  bare count can never be a to-do list (2026-09-06). */
  behind_hours?: number;
  /** the furthest-behind pair, in hours */
  worst_hours?: number;
  checked: string;
};

/** `GET /api/system/staleness` — three states per process, never two:
 *  stale, current, or `null` for unknown when git could not be read. */
export type Staleness = {
  processes: {
    kind: string; running: boolean; stale: boolean | null;
    commits_behind: number | null; started: string; why: string;
  }[];
  stale_count: number;
  unknown_count: number;
  head: { sha: string; committed: number; when: string } | null;
  summary: string;
};

/** A Stored strategies request's filters — the table and its exact count
 *  are built from the same `strategyParams`, so the number beside the table
 *  can never describe a different filter from the rows in it. */
export interface StrategyQuery {
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
  /** the win-rate floor, in the unit the "win %" column PRINTS: 50 means
   *  50.00% or better, inclusive — not 0.5 (operator, 2026-08-27) */
  minWinrate?: number;
  /** the take-profit floor, in the unit the TP% column PRINTS: 4 means TP
   *  4% or wider, not 0.04 (operator, 2026-08-27) */
  maxTp?: number;
  /** the stop's CEILING, in the unit the SL% column prints: 1 means SL 1%
   *  or TIGHTER. The opposite direction from maxTp on purpose (operator,
   *  2026-09-02: "for sl if i input 1 then show below 1 or equal 1") — the
   *  useful end of a target is up, the useful end of a stop is down. */
  maxSl?: number;
  /** The LOW ends. TP and SL are each a RANGE — "create filter to tp using
   *  between / EXAMPLE BETWEEN .5 - 2.5" (operator, 2026-09-03) — and both
   *  ends are INCLUSIVE, in the unit the column prints: minTp 0.5 with
   *  maxTp 2.5 keeps a row measured at exactly 0.5% and one at exactly
   *  2.5%. A ceiling alone also kept every 0.05% scalp whose target is
   *  smaller than the round-trip cost. */
  minTp?: number;
  minSl?: number;
  /** TP WIDER THAN SL — a checkbox, because there is no number to type and
   *  nothing to compare against but the row's own other column (operator,
   *  2026-09-04). It supersedes the two ranges: while it is on, they are
   *  greyed out and NOT sent. */
  tpOverSl?: boolean;
  /** "crypto" keeps real coins; "stocks" keeps the tokenized stocks (the
   *  STOCK-suffix contracts that go quiet outside US market hours) */
  asset?: "crypto" | "stocks";
  /** "flat" or "martingale" — the ladder is a sizing CHOICE, not a
   *  measurement (rule 19), so it has to be possible to see one alone */
  sizing?: string;
  /** HOW FRESH THE MEASUREMENT IS, in days. Operator, Sep 10, 2026: *"my
   *  goal is to filter on when was the last backtest for each strategy,
   *  because even i filter last 30 days some of them was last backtested 3
   *  weeks ago which is obsolete"*. Measured on their store that minute:
   *  EPIK-30m last measured `Aug 26, 2026 3:30am`, BICO-15m `Sep 10, 2026
   *  9:45am` — 15.8 days apart, so a 30-day window on the first ENDS 15.8
   *  days ago. 7 keeps only coins backtested within the last week. */
  measuredDays?: number;
  /** ONE row by the code in its first column (#6YACZSXX). It overrides every
   *  other filter — kit item H, and how a row is quoted without ambiguity */
  rowId?: string;
  /** "preset" = the ten researched confluence setups at three levels each
   *  (every rule named cf_...); "classic" = the 75 signals that existed
   *  before them. The operator's own names: Preset Confluence / Classic */
  group?: "preset" | "classic" | "sep25";
  /** LAST N MONTHS: every row also reports what it did INSIDE that window —
   *  profit and green months, the two the store keeps per month */
  months?: number;
  /** LAST N DAYS — a RE-MEASUREMENT from the stored candles, because the
   *  store keeps profit per month and no trade counts at all. Months wins
   *  when both are set (operator, 2026-09-02: "if months is 0 then follow
   *  the days"), and the server caps how many rows one request may restate. */
  days?: number;
  /** false = lowest first; omit for the column's useful end */
  desc?: boolean;
}

/** The filter half of a Stored strategies request, in ONE place: the
 *  table, its exact count and anything else that must describe the same
 *  rows build their query string here. */
export function strategyParams(q: StrategyQuery): URLSearchParams {
  const p = new URLSearchParams();
  if (q.coin) p.set("coin", q.coin);
  if (q.sort) p.set("sort", q.sort);
  if (q.minTrades) p.set("min_trades", String(q.minTrades));
  if (q.minWinrate) p.set("min_winrate", String(q.minWinrate));
  if (q.maxTp) p.set("max_tp", String(q.maxTp));
  if (q.maxSl) p.set("max_sl", String(q.maxSl));
  if (q.minTp) p.set("min_tp", String(q.minTp));
  if (q.minSl) p.set("min_sl", String(q.minSl));
  if (q.tpOverSl) p.set("tp_over_sl", "true");
  if (q.asset) p.set("asset", q.asset);
  if (q.months) p.set("months", String(q.months));
  if (q.days) p.set("days", String(q.days));
  if (q.measuredDays) p.set("measured_days", String(q.measuredDays));
  if (q.sizing) p.set("sizing", q.sizing);
  if (q.group) p.set("group", q.group);
  if (q.rowId) p.set("row_id", q.rowId);
  if (q.desc !== undefined) p.set("desc", String(q.desc));
  if (q.tf) p.set("tf", q.tf);
  if (q.signal) p.set("signal", q.signal);
  if (q.profitable) p.set("profitable", "true");
  if (q.limit) p.set("limit", String(q.limit));
  if (q.offset) p.set("offset", String(q.offset));
  return p;
}

export const api = {
  system: () => get<SysLoad>("/api/system"),
  contracts: () => get<{ rows: string[]; why: string }>("/api/contracts"),
  /** How many things in the candle store a RESOLVE would fix — the ONE
   *  definition, shared by the RESOLVE PENDING button and the Pending tab.
   *  `unfixable` is reported apart and never counted as work. */
  /** Which long-running process is still holding OLD CODE. A process keeps
   *  the code it started with, and nothing said so: the backtest job ran 32
   *  hours 24 commits behind, and the live runner held a loss-cap version that
   *  killed the runner (Sep 04, 2026). */
  staleness: () => get<Staleness>("/api/system/staleness"),
  candlePending: () => get<CandlePending>("/api/candles/pending"),
  candleGaps: () => get<{
    rows: { symbol: string; timeframe: string; bars: number; last: string;
            missing_bars: number; hours_behind: number }[];
    pairs: number; behind: number;
    /** the route returns the whole row here — `last` and `bars` were missing
     *  from this type, so the screen could not print the last bar it has */
    worst: { symbol: string; timeframe: string; hours_behind: number;
             bars?: number; last?: string; missing_bars?: number } | null;
    /** stored pairs the venue no longer lists: they can never catch up, so
     *  they are OUT of `behind` and `worst` and named on their own */
    delisted?: { symbol: string; timeframe: string; hours_behind: number }[];
    delisted_count?: number;
  }>("/api/candles/gaps"),
  /** the pairs the last download gave up on — what RETRY FAILED fetches */
  candleLost: () => get<{
    /** `kind` is WHY it is lost, measured against the run that lost it:
     *  "retry" (a run would fetch it), "empty" (the venue serves no candles
     *  for that pair, so a retry gets the same nothing), "delisted" (the
     *  contract is gone) or "recovered" (stored since). Without it "26 still
     *  lost" read as 26 problems when 25 were the venue having no data. */
    pairs: { symbol: string; timeframe: string; kind?: string }[];
    count: number; written: string;
    /** what the LAST FAILED run lost that is back in the store now */
    recovered: { symbol: string; timeframe: string; bars: number | null; when: string }[];
    failed_run_when: string; unnamed: number;
    /** contracts MEXC no longer lists: not lost, not retryable, named so the
     *  screen can stop showing a button that cannot succeed */
    delisted: { symbol: string; timeframe: string }[]; delisted_count: number;
  }>("/api/candles/lost"),
  /** contracts on MEXC x five timeframes vs the store — "is the candles complete?" */
  candleCompleteness: () => get<{
    ok: boolean; why: string; contracts: number | null; wanted: number | null;
    stored: number | null; missing: { symbol: string; timeframe: string }[];
    complete: boolean | null;
    /** the frames the count is OF — five on v1, ["1m"] on Candles v2 — so
     *  the screen never prints "x 5 timeframes" over a one-frame store */
    timeframes?: string[];
  }>("/api/candles/completeness"),
  /** the combination count for THIS store: Backtest v2 measures one sizing */
  plan: (coins: string[], tfs: string[], store?: StoreName) =>
    get<GridPlan>(`/api/backtest/plan?coins=${coins.join(",")}&tfs=${tfs.join(",")}`
      + (store ? `&store=${store}` : "")),
  deployedRows: (coins: string[], tfs: string[]) =>
    get<{ rows: { coin: string; tf: string; signal: string; sl: number; tp: number; sizing: string; key: string }[] }>(
      `/api/backtest/deployed?coins=${coins.join(",")}&tfs=${tfs.join(",")}`),
  /** RESOLVE PENDING on the Backtest screen: measure every pair this PC has
   *  candles for but has never measured, in one GitHub dispatch. Returns what
   *  it sent, so the panel can say it rather than assume it. */
  backtestResolvePending: () =>
    post<{ dispatched: boolean; pending: number; measurable?: number;
           too_short?: number; unreachable?: number; timeframes: string[];
           why: string; run?: { id?: number; url?: string } }>(
      "/api/backtest/pending/resolve", {}),
  cloudStatus: () => get<CloudStatus>("/api/cloud/status"),
  /** `coin_list` is WHICH coins to measure, by name — `coins` is only the most
   *  coins one machine may claim. Sending the count alone is how BACKTEST with
   *  BTC picked measured 0G, ALPINE, AVAAI… and never BTC (Sep 10, 2026).
   *  An empty `coin_list` means the whole market. */
  // `res`: "" is v1 (each frame's own candles); "1m" is Backtest v2 — the SAME
  // frames, rebuilt from 1-minute candles, every exit settled minute by minute.
  // A resolution, never a timeframe.
  cloudDispatch: (spec: { shards?: number; coins?: number; coin_list?: string[];
                          timeframes?: string; days?: number; base?: number;
                          res?: string }) =>
    post<{ id?: number; url?: string; coins_named?: string[]; coin_list_why?: string }>(
      "/api/cloud/dispatch", spec),
  cloudCancel: (run_id: number) => post<{ cancelled: number }>("/api/cloud/cancel", { run_id }),
  cloudMerge: (run_id: number) => post<{ fetched: number } & Record<string, unknown>>("/api/cloud/merge", { run_id }),
  cloudForget: () => post<{ forgotten: boolean }>("/api/cloud/forget", {}),
  health: () =>
    get<{ ok: boolean; storage: Record<string, { files: number; rows: number; bytes: number }> }>(
      "/api/health",
    ),

  /** EVERY matching row as a CSV download — the store is far larger than
   *  any table: 21,858,026 rows when the operator asked for "all". */
  /** index every measured pair now — the trickle is one pair a cycle
   *  while a sweep runs, which is hours when it falls behind */
  strategiesReindex: () =>
    post<{ started: boolean; behind: number; why: string }>(
      "/api/strategies/reindex", {}),
  strategiesCsvUrl: (q: {
    coin?: string; tf?: string; signal?: string; profitable?: boolean;
    sort?: StrategySort; minTrades?: number; minWinrate?: number;
    maxTp?: number;
    /** the stop's CEILING, so the download carries the same slice as the
     *  table: 1 keeps rows whose SL is 1% or tighter */
    maxSl?: number;
    /** the LOW end of each range ("BETWEEN .5 - 2.5"), so the file holds the
     *  same slice the table showed */
    minTp?: number;
    minSl?: number;
    /** only rows whose target is wider than their stop, so the file holds the
     *  same slice the table showed */
    tpOverSl?: boolean;
    /** "crypto" or "stocks" — tokenized stocks carry a STOCK suffix and go
     *  quiet outside US market hours */
    asset?: "crypto" | "stocks";
    /** the DAYS window, so the file holds the same measurement the table
     *  showed rather than every row's whole history */
    days?: number; months?: number;
    /** HOW FRESH THE MEASUREMENT IS, in days. Operator, Sep 10, 2026: *"my
     *  goal is to filter on when was the last backtest for each strategy,
     *  because even i filter last 30 days some of them was last backtested 3
     *  weeks ago which is obsolete"*. Measured on their store that minute:
     *  EPIK-30m last measured `Aug 26, 2026 3:30am`, BICO-15m `Sep 10, 2026
     *  9:45am` — 15.8 days apart, so a 30-day window on the first ENDS 15.8
     *  days ago. 7 keeps only coins backtested within the last week. */
    measuredDays?: number;
    sizing?: string; rowId?: string; desc?: boolean;
    /** the download has to carry the same group as the table it came from */
    group?: "preset" | "classic" | "sep25";
  }) => {
    const p = new URLSearchParams();
    if (q.coin) p.set("coin", q.coin);
    if (q.tf) p.set("tf", q.tf);
    if (q.signal) p.set("signal", q.signal);
    if (q.profitable) p.set("profitable", "true");
    if (q.sort) p.set("sort", q.sort);
    if (q.minTrades) p.set("min_trades", String(q.minTrades));
    if (q.minWinrate) p.set("min_winrate", String(q.minWinrate));
    if (q.maxTp) p.set("max_tp", String(q.maxTp));
    if (q.maxSl) p.set("max_sl", String(q.maxSl));
    if (q.minTp) p.set("min_tp", String(q.minTp));
    if (q.minSl) p.set("min_sl", String(q.minSl));
    if (q.tpOverSl) p.set("tp_over_sl", "true");
    if (q.asset) p.set("asset", q.asset);
    if (q.sizing) p.set("sizing", q.sizing);
    if (q.group) p.set("group", q.group);
    if (q.rowId) p.set("row_id", q.rowId);
    // THE WINDOW. Declared above and passed by the panel since 2026-09-03,
    // but never written here — so on Sep 09, 2026 a table reading "last 30
    // days, 2,001 rows" downloaded 42,420 rows of whole history, 17.3 MB
    // instead of 876 KB, under a filename that still said `last30d`. The
    // window is what makes the file's profit, wins and losses the window's
    // own; without it every number in the file answers a different question
    // than the screen it came from (kit item G).
    if (q.months) p.set("months", String(q.months));
    else if (q.days) p.set("days", String(q.days));
    // the FRESHNESS filter travels too, or the file holds stale rows the
    // table had already cut — the same way the window was dropped on Sep 09
    if (q.measuredDays) p.set("measured_days", String(q.measuredDays));
    if (q.desc !== undefined) p.set("desc", String(q.desc));
    return `${API_BASE}/api/strategies.csv?${p.toString()}`;
  },
  /** THE EXACT NUMBER of rows a filter matches, counted in the background
   *  (operator, Sep 25, 2026: "when i filter the table can you show how many
   *  rows exacty is it"). Same filter fields as `strategies` — built by the
   *  same code below, minus paging, ordering and the months/days window,
   *  which change what a row PRINTS, not whether it matches. First asks
   *  answer "counting"; ask again until "done". */
  strategiesCount: (q: StrategyQuery) => {
    const full = strategyParams({ ...q, limit: undefined, offset: undefined,
                                       sort: undefined, desc: undefined,
                                       months: undefined, days: undefined });
    return get<{ state: "done" | "counting" | "waiting" | "failed";
                 total: number | null; seconds?: number; why?: string }>(
      `/api/strategies/count?${full.toString()}`);
  },
  strategies: (q: StrategyQuery) => {
    const p = strategyParams(q);
    return get<{ rows: StrategyRow[]; total: number; index?: IndexStatus;
      /** the order the server actually used, so the caption is derived */
      sort?: StrategySort; min_trades?: number; min_winrate?: number;
      max_tp?: number; max_sl?: number;
      /** the low end of each range, echoed so the chips describe what was
       *  APPLIED rather than what the boxes hold */
      min_tp?: number; min_sl?: number; tp_over_sl?: boolean;
      asset?: string;
      sizing?: string; row_id?: string;
      desc?: boolean;
      /** the window's REAL months, newest first ("2026-08") */
      window?: string[]; months_window?: number;
      /** the DAYS window the server measured, in real dates, and how many
       *  coin/timeframe/signal groups it had to re-walk to answer */
      days?: number; days_window?: string[]; days_groups?: number;
      /** the most rows a WINDOWED download can hold (rows_index.DAYS_CSV_MAX).
       *  The download re-measures that many and then drops the ones the
       *  window's own figures fail, so it can never deliver `total` — the
       *  button must name this, not the match count. */
      days_csv_max?: number;
      /** rows the window re-measured and then CUT because the window's own
       *  win %, trades or profit missed a floor the whole history had passed.
       *  Sep 09, 2026: "Winrate 90% or better" over rows printing 89.47. */
      window_hidden?: number;
  /** trades counted in the window that opened before it began */
  window_straddled?: number;
  /** why rows kept their whole-history figures: no candles, outside the
   *  window, or the re-measure raised */
  window_skipped?: {
    no_candles?: number; outside_window?: number; failed?: number;
  };
      /** a filtered count stops at COUNT_CAP: print "N+" */
      total_capped?: boolean;
      /** which store answered ("v2" for Backtest v2) and, on an empty v2
       *  store, the sentence that says what to do first */
      store?: string; why?: string }>(
      `/api/strategies?${p.toString()}`,
    );
  },

  facets: () =>
    /** `tps` are the TP% values this store's timeframes can hold, from the
     *  measuring grid — the TP box offers them and caps itself at the
     *  largest, because a TP no row has costs a full scan to answer */
    get<{ coins: string[]; tfs: string[]; signals: string[]; tps?: number[];
           sls?: number[];
      sizings?: string[] }>(
      "/api/strategies/facets",
    ),

  /** Re-measure THIS ROW's pair now — the row's own UPDATE button. It
   *  measures the PAIR (coin + timeframe), because the store keeps one
   *  watermark per pair; bringing one row forward alone would leave the
   *  pair's other rows behind a watermark that claims otherwise. */
  strategyRowUpdate: (rowId: string, store: "v1" | "v2" = "v1") =>
    postDetail<{ started: boolean; pid: number; row: string; coin: string;
                 tf: string; why: string; store: string; kind: string }>(
      `/api/strategies/${encodeURIComponent(rowId)}/update?store=${store}`, {}),

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
  /** `reading` is true while the background read is still walking the
   *  candle files — an EMPTY list then means "not known yet", never
   *  "no candles". The two must never print the same sentence. */
  coverage: () => get<{ rows: CoverageRow[]; reading?: boolean }>(
    "/api/storage/coverage"),
  /** what each month of stored data costs, and the delete jobs' progress */
  storageMonths: () => get<StorageMonths>("/api/storage/months"),
  /** delete `through` AND every older month of one store; a refusal comes
   *  back as HTTP 409 with the reason in `detail`. kind "delisted" ignores
   *  `through` and removes every stored coin MEXC no longer lists */
  deleteMonths: (kind: "candles" | "results" | "delisted", through = "") =>
    postDetail<MonthJob>("/api/storage/months/delete", { kind, through }),
  /** the coins MEXC no longer lists that are still on this PC, and the
   *  delete job's progress — the DELETE N DELISTED button */
  storageDelisted: () =>
    get<{ delisted: DelistedReport; job: MonthJob | null; writer: string }>(
      "/api/storage/delisted"),

  /** Who is free to run a sweep right now — this PC, GitHub, or both, and
   *  which timeframes each would take. Shown on the UPDATE button before it
   *  is clicked. */
  backtestCapacity: (timeframes?: string) =>
    get<BacktestPlan>(`/api/backtest/capacity${timeframes ? `?timeframes=${encodeURIComponent(timeframes)}` : ""}`),
  /** The LOGS section: pending pairs on this machine, and every named error
   *  from this PC and from the GitHub shards. */
  backtestLogs: () => get<BacktestLogs>("/api/backtest/logs"),

  jobStatus: (kind: "download" | "backtest" | "btupdate" | "stratbt" | "pairbt" | "pairbt_v2" | "collect" | "download_v2" | "backtest_v2" | "btupdate_v2" | "export" | "export_v2") =>
    get<JobStatus>(`/api/jobs/${kind}`),
  jobStart: (kind: "download" | "backtest" | "btupdate" | "stratbt" | "pairbt" | "pairbt_v2" | "collect" | "download_v2" | "backtest_v2" | "btupdate_v2", spec: unknown) =>
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

  jobStop: (kind: "download" | "backtest" | "btupdate" | "stratbt" | "pairbt" | "pairbt_v2" | "collect" | "download_v2" | "backtest_v2" | "btupdate_v2" | "export" | "export_v2") =>
    post<{ ok: boolean }>(`/api/jobs/${kind}/stop`, {}),

  /** The ledger, newest first. `actions` names the rows wanted — "enter,exit"
   *  for TRADES. Asking for 200 ROWS gets 200 refusals: the file was 3,666
   *  rows on Sep 09, 2026 with 2,868 `gate_blocked` and 12 trades, so the
   *  newest 200 held 2 of them and a real demo loss was invisible. */
  ledger: (limit = 500, actions?: string) =>
    get<{ rows: LedgerRow[]; total: number; matched?: number }>(
      `/api/ledger?limit=${limit}${actions ? `&actions=${actions}` : ""}`),
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

/** "1h 40m" / "12m" / "under a minute" — for a wait the screen is naming */
export function fmtLeft(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return "under a minute";
  // DAYS past one day: the v1 re-file's honest estimate was ~5,300 hours and
  // printed as "5341h 0m", which nobody reads as seven months
  if (s >= 86400) {
    const d = Math.floor(s / 86400), dh = Math.floor((s % 86400) / 3600);
    return dh ? `${d}d ${dh}h` : `${d}d`;
  }
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

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
  /** unix seconds the CURRENT arming began, from the deploy log,
   *  keyed by strategy AND coin. null when the log has no record. */
  /** true when Martingale mode is on for THIS row's book, so the screen
   *  can say that the next stake doubles rather than just printing it */
  martingale?: boolean;
  deployed_at?: number | null;
  /** the other end of the window when the date was read back from a saved
   *  settings file rather than logged; null/absent means it is exact */
  deployed_at_from?: number | null;
  next_stake?: number;
  notional?: number;
  tripped?: boolean;
  /** the row's OWN book */
  today?: number;
  pnl: number;
  trades: number;
  wins: number;
  losses: number;
  /** BOTH books, so a row ticked LIVE can still show what its demo did.
   *  Live and demo are separate records and are never blended. */
  real?: BookRecord;
  paper?: BookRecord;
  open_on: string[];
  open_on_paper: string[];
}

/** One book's realized record for a strategy. */
export interface BookRecord {
  pnl: number;
  trades: number;
  wins: number;
  losses: number;
  winrate?: number | null;
  today: number;
  armed: boolean;
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
  /** THIS TRADE's own id — the one Trade History prints once it closes, and
   *  the one every ledger row for this trade carries. Blank on a position
   *  opened before trade ids existed. */
  trade_id?: string;
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
  /** the STRATEGY's own id for this coin (`#PNK3G9KZ`), the same one the
   *  strategies grid and the positions table print — so a closed trade can
   *  be traced back to the row that took it, and pasted into a report's
   *  find-by-ID box. Empty for a key the runner does not know. */
  strategy_id?: string;
  /** "live" or "demo". Both books stamp a trade with the SAME id, so a row
   *  that does not say which book it is on turns two trades into one — which
   *  is how #MTX4FSGN read as a single trade for a whole evening. */
  book?: string;
}

export interface MonthRow {
  key: string; label: string; trades: number; wins: number;
  losses: number; profit: number; win_rate: number;
}

export interface HistoryPayload {
  rows: HistoryRow[]; total: number; page: number; pages: number;
  per_page: number; months: MonthRow[];
  totals: { trades: number; wins: number; losses: number; profit: number };
  /** the id that was searched for, cleaned up (no #, upper case) */
  q?: string;
  /** how many closed trades were looked at — so an empty answer can name
   *  what it checked instead of speaking for the whole store */
  examined?: number;
  /** which books this answer covers: both while searching */
  books?: string[];
}

/** What the RUNNER's own websocket is seeing. Read from the status the feed
 *  thread publishes, so the screen shows the socket being proven rather than
 *  a second one opened to agree with it. */
export interface FeedPrice {
  symbol: string;
  price: number | null;
  at: number | null;
  ticks: number | null;
  age: number;
}
export interface FeedStatus {
  running: boolean;
  connected: boolean;
  logged_in?: boolean;
  stale?: boolean;
  url?: string;
  messages?: number;
  connects?: number;
  tracking?: string[];
  klines?: string[];
  armed?: string[];
  last_error?: string;
  status_age?: number;
  prices?: FeedPrice[];
  why?: string;
}

export const tradeApi = {
  equity: (dry = false) =>
    get<{ points: { ts: number; equity: number; coin: string }[]; last: number; trades: number }>(
      `/api/trade/equity?dry=${dry}`),
  /** `q` searches BOTH books by trade id or strategy id and ignores `dry`:
   *  both books stamp a trade with the same id, so a search that honoured
   *  the tab would show one of the two and look like the other never
   *  happened. Sent to the server, never filtered in the browser. */
  history: (dry: boolean, page = 1, per_page = 5, q = "") =>
    get<HistoryPayload>(`/api/trade/history?dry=${dry}&page=${page}`
      + `&per_page=${per_page}&q=${encodeURIComponent(q)}`),
  positions: () => get<PositionsPayload>("/api/trade/positions"),
  /** the runner's live websocket: connection state and the last price
   *  pushed for every coin it is listening to */
  feed: () => get<FeedStatus>("/api/trade/feed"),
  /** the RESET W/L button: archives the trade rows, never deletes them.
   *  Resetting the real book also resets today's loss-cap counter. */
  /** the RESET CAP button: the loss cap counts from zero again; nothing is
   *  deleted and the today tiles keep showing the real figure */
  lossCapReset: () =>
    post<{ ok: boolean; forgave: number; counted_now: number; limit: number }>(
      "/api/trade/losscap/reset", { confirm: true }),
  recordReset: (books: ("paper" | "real")[]) =>
    post<{ ok: boolean; removed: number; backup: string;
      paper_positions_cleared: number; runner_restarted: boolean;
      loss_cap_counter_reset: boolean }>(
      "/api/trade/record/reset", { confirm: true, books }),
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
  /** why it is lost — see api.candleLost */
  kind?: string;
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

// ----------------------------------------------------------------- stores
/** Which store a panel reads: v1 (the year-deep grid) or v2 (Backtest v2,
 *  minute-exact exits on 1-minute candles, Sep 17, 2026). The v2 methods are
 *  the v1 methods under the v2 prefix with the v2 job kinds; v1 delegates to the
 *  existing functions, so nothing a v1 panel calls changes. */
export type StoreName = "v1" | "v2";

// ---------------------------------------------------- the account forecast
/** one closed trade of the account replay */
export interface ForecastTrade {
  key: string; coin: string; symbol: string; tf: string; side: 1 | -1;
  entry_ms: number; entry: number; tp: number; sl: number;
  exit_ms: number | null; exit: number | null; why: "TP" | "SL" | "LIQ" | "END";
  unclear: 0 | 1; cost: number; cost_source: "record" | "saved";
  margin: number; pnl: number | null;
}
export interface ForecastRow {
  row: string; key: string; coin: string; tf: string; tp: number; sl: number;
  trades: number; wins: number; losses: number; win_rate: number; pnl: number;
  unclear: number; worst_run: number; signals: number; cost_refused: number;
  id?: string;
  /** set when another switched-on row fires on exactly the same bars with
   *  the same prices — this row can only ever copy that one's trades */
  twin_of?: string | null; twin_id?: string;
}
export interface ForecastSide {
  book: "demo" | "live"; sizing: "martingale" | "flat";
  rows_deployed: number; rows_replayed: number; rows_traded: number;
  rows_refused: Record<string, string>;
  signals: number; refused: Record<string, number>;
  gate_source: { record: number; saved: number };
  taken: number; trades: number; wins: number; losses: number; win_rate: number;
  pnl: number; worst_run: { pnl: number; trades: number }; unclear: number;
  still_open: number; slices_per_coin: number; leverage: number; base_margin: number;
  window: { first_ms: number | null; last_ms: number | null };
  rows: ForecastRow[]; twins: Record<string, string>; assumptions: string[];
  cost_sources: { saved: number; default: number }; seconds: number;
}
export interface ForecastActual {
  entries: number; trades: number; wins: number; losses: number; win_rate: number;
  pnl: number; pnl_fee_once: number; pnl_at_base: number | null; base_margin: number | null;
  refused: Record<string, number>;
  rows: Record<string, { trades: number; wins: number; losses: number; pnl: number }>;
  first_ms: number | null; last_ms: number | null;
}
export interface PortfolioForecast {
  /** set when nothing could be replayed — the sentence to print instead */
  why?: string;
  book?: "demo" | "live";
  account?: ForecastSide;
  flat?: Pick<ForecastSide, "trades" | "wins" | "losses" | "win_rate" | "pnl" | "worst_run" | "sizing">;
  checked?: ForecastSide | null;
  actual?: ForecastActual;
  readings?: Record<string, number>;
  log?: ForecastTrade[];
  computed_at?: number;
}

export function storeApi(store: StoreName) {
  // built from two pieces on purpose: tests/test_every_client_path_is_served
  // reads every quoted api path in this file (comments included) as a ROUTE
  // the app must serve, and the bare v2 prefix is a prefix, not a route
  const P = store === "v2" ? "/api" + "/v2" : "/api";
  const dl = (store === "v2" ? "download_v2" : "download") as "download" | "download_v2";
  const bt = (store === "v2" ? "backtest_v2" : "backtest") as "backtest" | "backtest_v2";
  const up = (store === "v2" ? "btupdate_v2" : "btupdate") as "btupdate" | "btupdate_v2";
  const kindOf = (k: "download" | "backtest" | "update") =>
    k === "download" ? dl : k === "backtest" ? bt : up;
  return {
    store,
    downloadKind: dl,
    backtestKind: bt,
    updateKind: up,
    /** the frames THIS store downloads — v2 is 1m and nothing else */
    tfs: store === "v2" ? ["1m"] : ["15m", "30m", "1h", "4h", "1d"],
    candlePending: () => get<CandlePending>(`${P}/candles/pending`),
    candleGaps: () => get<Awaited<ReturnType<typeof api.candleGaps>>>(`${P}/candles/gaps`),
    candleLost: () => get<Awaited<ReturnType<typeof api.candleLost>>>(`${P}/candles/lost`),
    candleCompleteness: () =>
      get<Awaited<ReturnType<typeof api.candleCompleteness>> & { timeframes?: string[] }>(
        `${P}/candles/completeness`),
    downloadHistory: (limit = 20) =>
      get<DownloadHistory>(`${P}/candles/download-history?limit=${limit}`),
    // the v1 builders, byte for byte, under this store's prefix
    strategies: (q: Parameters<typeof api.strategies>[0]) =>
      withApiPrefix(P, () => api.strategies(q)),
    strategiesCount: (q: Parameters<typeof api.strategies>[0]) =>
      withApiPrefix(P, () => api.strategiesCount(q)),
    /** start building the FULL CSV of this filter (every matching row) */
    strategiesExport: (body: Record<string, unknown>) =>
      postDetail<{ started: boolean; running?: boolean; why?: string; pid?: number }>(
        `${P}/strategies/export`, body),
    /** the finished full CSV */
    strategiesExportFileUrl: () => `${API_BASE}${P}/strategies/export/file`,
    /** the command-window line that builds this filter's full CSV and saves
     *  it to G:\Download\yyyy-mm-dd\ (tradingagents/csv_download.py) */
    strategiesExportCommand: (body: Record<string, unknown>) =>
      postDetail<{ command: string; key: string; folder: string }>(
        `${P}/strategies/export/command`, body),
    strategiesCsvUrl: (q: Parameters<typeof api.strategiesCsvUrl>[0]) =>
      api.strategiesCsvUrl(q).replace(`${API_BASE}/api/`, `${API_BASE}${P}/`),
    facets: () =>
      get<Awaited<ReturnType<typeof api.facets>> & { store?: string; why?: string }>(
        `${P}/strategies/facets`),
    storage: () => get<BtStorage & { store?: string; why?: string }>(`${P}/backtest/storage`),
    /** Backtest v2 only: every deployed row replayed TOGETHER through the
     *  runner's gates, beside what the practice book actually did */
    portfolio: (book: "demo" | "live" = "demo", fresh = false) =>
      get<PortfolioForecast>(`${P}/portfolio?book=${book}${fresh ? "&fresh=1" : ""}`),
    /** the trade-by-trade log of one row, replayed from THIS store — on v2
     *  from the 1-minute candles with exits settled by the minute */
    trades: (row: StrategyRow, baseMargin = 5.0) =>
      withApiPrefix(P, () => api.trades(row, baseMargin)),
    jobStatus: (kind: "download" | "backtest" | "update") => api.jobStatus(kindOf(kind)),
    jobStart: (kind: "download" | "backtest" | "update", spec: unknown) =>
      api.jobStart(kindOf(kind), spec),
    jobStop: (kind: "download" | "backtest" | "update") => api.jobStop(kindOf(kind)),
  };
}

// ------------------------------------------------------------- running jobs
export interface RunningJob {
  kind: string; now: string; done: number; total: number; pct: number | null;
  /** seconds left, from the work's own measured pace — absent when the step has none */
  eta_s?: number | null; eta_at?: number | null; eta_why?: string;
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
  behind: number;        // pairs NEVER indexed
  /** pairs the catch-up will actually WALK — every pair whose file has moved
   *  since it was indexed, not just the ones never seen. On Sep 12, 2026 the
   *  store read `behind: 4` and `stale: 5,206`, so a button labelled from
   *  `behind` offered a 4-pair job for a 5,206-pair walk. The reindex route
   *  has taken `stale or behind` as its size since 2026-09-10
   *  (RCA-2026-09-10-C); this is the same number, so the label agrees with
   *  the job. Optional: a status read that is still loading has neither.
   *  (Do not write the route's path here across two lines —
   *  `test_every_client_path_is_served` scans this file for paths and a
   *  wrapped one parses as a route the app does not serve.) */
  stale?: number | null;
  /** is a process actually working the backlog off? A backlog with no worker
   *  is a different sentence from one being worked, and until Sep 14, 2026
   *  the screen could not tell them apart: the indexer died at
   *  `Sep 13, 2026 4:05pm` on `database is locked`, nothing restarted it, and
   *  `stale` climbed to 5,344 overnight under a button and no explanation. */
  indexer_running?: boolean | null;
  /** "" while the v1 indexer may run; otherwise who switched it off and when
   *  (Sep 24, 2026: "stop the v1 i dont need it anymore"). Its own state —
   *  never "dead", never "catching up". */
  indexer_off?: string;
  /** "job" on Backtest v2: its rows are filed by the backtest job when it
   *  finishes — there is no indexer process to be "catching up" */
  filed_by?: "job" | "indexer";
  /** a fresh-file rebuild of THIS store's index in flight (empty when none):
   *  the table reads the old file until it swaps in, so its dates are stale */
  rebuild?: {
    phase?: string; pairs_done?: number; pairs_total?: number; rows?: number;
    seconds?: number; pairs_per_min?: number; running?: boolean;
    store?: "this" | "unknown"; age_s?: number;
    /** seconds left and the clock time it lands, from the rebuild's own pace;
     *  null when this step has no measured pace — `eta_why` says which */
    eta_s?: number | null; eta_at?: number | null; eta_why?: string;
  };
  /** the OTHER store's running job, which shares this machine's one disk:
   *  the backlog waits for it, a row you press UPDATE on does not */
  deferring_to?: string;
  /** WHICH job owns the disk while the indexer stands down, in words
   *  ("collect", "backtest"). "paused" with no name is the stalled screen
   *  RCA-2026-09-10-C was about. */
  paused_by?: string;
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
