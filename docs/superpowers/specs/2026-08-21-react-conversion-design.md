# React conversion: TailAdmin frontend, FastAPI backend, screen by screen

**Date:** 2026-08-21 · **Approved:** "can i convert my app to react?" → plan
presented → "/goal okay do it, make sure there will be no bug"

## What changes and what must not

The Python beneath the app — engine, `market_sweep`, `backtest_report`,
`parquet_store`, `auto_trader`, the runner, 1,861 tests — is untouched. The
Streamlit UI (`app.py`) is REPLACED screen by screen with the operator's
chosen template, TailAdmin (Next.js + Tailwind), talking to a new thin
FastAPI layer. Streamlit keeps serving on :8503 until every replaced screen
is verified; the React app grows on :3000 with the API on :8787.

## Architecture

```
Next.js (TailAdmin)  :3000  ──HTTP──▶  FastAPI  :8787  ──imports──▶ existing modules
        │                                   │
        └── Playwright E2E                  └── pytest (TestClient), TDD
```

* **The API mirrors what the screens already call** — no new business logic:
  storage sizes/by-coin/coverage, stored strategies (+filters), trades-for,
  job start/status/stop (download, backtest, btupdate), reports list,
  ledger, deployments, settings read.
* **No secrets cross the wire**: the API serves localhost only by default;
  MEXC keys never appear in any response.
* **Job model unchanged**: detached processes + progress files; the API just
  reads/starts/stops them, so downloads still survive tab switches.

## The zero-bug bar (the goal's words: "make sure there will be no bug")

1. every endpoint TDD'd with FastAPI's TestClient before the frontend uses it
2. the React screen is verified by Playwright against the REAL api + real
   store, including: numbers on screen equal the API's numbers (label-must-
   match-data), progress survives reload, empty stores say so
3. parity check: for Backtest 2, the React screen's counts (stored
   strategies, per-coin sizes, coverage) must equal the Streamlit page's on
   the same store before cut-over
4. nothing replaces a Streamlit screen until 1–3 pass; both run side by side

## Screen order

1. **Backtest 2** (this spec's deliverable): storage panel, size-per-coin,
   market data + download progress, archive backtest run/update, stored
   strategies + trade viewer, deployment history, ledger
2. Back Test (market sweep) · 3. Auto Trade (last — live money) ·
4. New Crypto · 5. Stocks · 6. LLM Models

## Out of scope now

Auth/multi-user (comes with the SaaS decision), cut-over/retirement of
Streamlit, cloud deploy.
