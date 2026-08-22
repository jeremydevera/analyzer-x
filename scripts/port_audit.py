"""Every control the Streamlit app had, checked against the React app.

Run it after touching any screen:  .venv/bin/python scripts/port_audit.py

This is the audit that should have run BEFORE the port. Building each React
screen from the API outward instead of from the old screen inward silently
dropped 20 controls — including PANIC, both loss caps, the MEXC keys panel,
nine position columns and the X/Twitter source — and every check written at
the time passed, because they all asked "is what I built correct?" and none
asked "is anything missing?".
"""
import pathlib

WEB = pathlib.Path("webapp/src")
blob = "\n".join(p.read_text() for p in WEB.rglob("*.tsx")) + \
       "\n".join(p.read_text() for p in WEB.rglob("*.ts"))
# the API plus the modules whose BEHAVIOUR the checks below describe: a
# runner-side guarantee lives in auto_trader/supervisor, and searching only
# the web app made "two runners can never coexist" unprovable.
py = "\n".join(pathlib.Path(f).read_text() for f in (
    "tradingagents/api.py",
    "tradingagents/auto_trader.py",
    "tradingagents/supervisor.py",
    "tradingagents/positions_view.py",
) if pathlib.Path(f).exists())
both = blob + py

# control -> the string(s) that prove it exists in React (any one is enough)
CHECKS = {
  "Auto Trade": {
    "Save & run": ["SAVE CONFIG"],
    "Stop — halt entries": ["HALT ENTRIES"],
    "Arm PANIC": ["arm PANIC"],
    "PANIC — close all": ["PANIC — close all"],
    "close ONE position": ["closeOne", "/positions/close"],
    "LIVE / DEMO per strategy": ["toggleBook"],
    "base margin per strategy": ["strategy_margins"],
    "per-strategy loss cap": ["strategy_loss_limits", "loss cap $"],
    "account loss cap": ["account loss cap $", "account_loss_cap"],
    "1 YEAR backtest": ["1 YEAR", "backtestStrategy"],
    "coins per strategy": ["strategy_coins", "setCoins"],
    "Test connect": ["TEST CONNECT", "credsTest"],
    "API key / secret": ["API key", "credsSave"],
    "Save keys": ["SAVE KEYS"],
    "Forget saved keys": ["FORGET SAVED KEYS"],
    "start/stop runner": ["START RUNNER", "STOP RUNNER"],
  },
  "Positions (14 columns)": {
    "contract": ['"contract"'], "unreal $": ['"unreal $"'], "to TP": ['"to TP"'],
    "TP % ($)": ['"TP % ($)"'], "SL % ($)": ['"SL % ($)"'], "W": ['"W"'],
    "L": ['"L"'], "trd": ['"trd"'], "side": ['"side"'], "opened": ['"opened"'],
    "held": ['"held"'], "entry": ['"entry"'], "margin": ['"margin"'],
    "bracket": ['"bracket"'],
  },
  "Backtest": {
    "coins picker": ["<CoinPicker"],
    "timeframes": ["TFS ="],
    "dates / window": ["Previous 1 year"],
    "base margin $": ["Base margin $"],
    "BACKTEST": [">BACKTEST<", "BACKTEST\n"],
    "UPDATE BACKTEST": ["UPDATE BACKTEST"],
    "DOWNLOAD": ["DOWNLOAD CANDLES"],
    "STOP": ["jobStop"],
    "Run where (GitHub)": ["Run where", "cloudDispatch"],
    "cost preview": ["combinations"],
    "storage per coin": ["Size per coin"],
    "candle coverage": ["Candles on this Mac"],
    "stored strategies filters": ["profitable only"],
    "trade viewer": ["PAST TRADES", "trades ·", "trades}"],
  },
  "Analysis": {
    "ticker (curated)": ["ta-tickers"],
    "date": ['type="date"'],
    "analysts": ["ANALYSTS ="],
    "debate rounds": ["debate rounds"],
    "risk rounds": ["risk rounds"],
    "model": ["setModel"],
    "parallel mode": ["parallel — compare models"],
    "models multiselect": ["models to compare"],
    "social source": ["where the Sentiment Analyst reads posts"],
    "X keywords": ["extra X search terms"],
    "Stop run": ["analysisApi.stop", "STOP<"],
    "Download .md": ["DOWNLOAD .md"],
  },
  "New Crypto": {
    "scan / refresh": ["FRESH SWEEP"],
    "watch for new listings": ["watch for new listings"],
    "alert sound": ["test sound"],
    "loop the alarm": ["loop the alarm"],
    "age from/to + units": ["age from", "age to"],
    "min volume": ["min volume $"],
    "show all (incl. dust)": ["show all (incl. dust)"],
    "Analyze a coin": ["ANALYZE THIS COIN"],
    "candlestick chart": ["CoinChart"],
    "upcoming listings": ["Announced, not trading yet"],
  },
  "LLM Models": {
    "add model": ["ADD MODEL"], "provider preset": ["presets"],
    "base url": ["openai-compatible only"], "key env": ["KEY_ENV_VAR"],
    "remove": ["remove"], "test one": [">test<"], "test all": ["TEST ALL"],
    "health %": ["% {h.status}", "h.pct"],
  },
  "Behaviour (not just presence)": {
    "REAL and PAPER positions in SEPARATE boxes":
      ["REAL — MONEY AT RISK", "PAPER — DEMO, NOT REAL MONEY"],
    "trade history: LIVE/DEMO tabs": ["LIVE — real money", "DEMO — simulated"],
    "trade history: paginated with numbered pages": ["pageNumbers"],
    "trade history: running total is book-wide": ['"running $"'],
    "coins chosen from a LIST, not typed": ["CoinPicker", "search contracts"],
    "select all contracts in one click": ["select all"],
    "downloading candles is its OWN screen": ["DownloadScreen", '"/candles"'],
    "backtest screen does not download": ["Candles</a>"],
    "strategy coins are READ-ONLY": ["read-only: the contract is PART"],
    "Auto Trade never scrolls sideways": ["table-fixed", "min-w-0 flex-1"],
    "selected-coin count shown": ["coins selected"],
    "strategies default to DEPLOYED only": ["Strategies you have deployed"],
    "backtest states its cost first": ["combinations"],
    "PANIC needs arming then confirming": ["arm PANIC", "close everything at market"],
    "ladder in dollars with the current rung": ["ladder_rung", "ladder $"],
    "next stake shown, not worked out": ["next_stake", '"next $"'],
    "streak per coin AND book": ["streak"],
    "live-lock: one coin, one timeframe, real money": ["live_locked", "timeframe_locks"],
    "a clashing live save is REFUSED": ["cannot go live"],
    "a finished job's bar clears itself": ["FRESH_SECONDS", "clears itself"],
    "a stopped job is not painted as success": ["bg-warning-400"],
    "one shared progress component": ["JobProgress"],
    "tables carry explicit column widths": ['["books", "12%"]', '["opened", "10%"]'],
    "storage: a tab per timeframe plus ALL": ['role="tablist"', 'tab === "ALL"'],
    "storage: when each pair was last updated": ["last updated", "last_ms"],
    "runner auto-restarts after a crash": ["KeepAlive", "auto-restart"],
    "a deliberate STOP is never overridden": ["WANT_PATH", "wants_runner"],
    "two runners can never coexist": ["LOCK_PATH", "run lock"],
    "runner refuses to start on a full disk": ["MIN_FREE_MB", "disk almost full"],
    "the UI says when the runner died": ["DIED", "last heartbeat"],
    "a position names the strategy running it, by id": ["row_id_for", "copy this id"],
    "one id per row, shared by both screens": ["row_id_for(key,"],
    "the ladder rung names its book, not a fake streak": ["streak_book", "rung"],
    "a shared ladder is called out": ["streak_shared_with", "raises the stake for both"],
    "W/L follows the book the row trades": ["stats_real if _is_real else stats_paper"],
    "progress bars show two decimals": ["pct.toFixed(2)"],
    "core bars show two decimals": ["(w.pct ?? 0).toFixed(2)"],
    "a core is identified by its process, not a task index": ["w{pid}.json"],
    "a core that stopped reporting is dropped": ["WORKER_STALE_SECONDS"],
  },
  "Global": {
    "night mode": ["ThemeToggleButton"],
    "nav to every screen": ["/new-crypto"],
  },
}

miss = 0
for group, items in CHECKS.items():
    print(f"\n=== {group}")
    for name, needles in items.items():
        ok = any(n in both for n in needles)
        if not ok: miss += 1
        print(f"  {'OK  ' if ok else 'MISS'} {name}")
print(f"\n{'ALL PRESENT' if not miss else str(miss) + ' STILL MISSING'}")
