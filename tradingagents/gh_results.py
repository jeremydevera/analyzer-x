"""THE REVIEWED GITHUB REPOS' STRATEGIES, COLLECTED AND ADDED UP (Nov 18, 2026).

`python -m tradingagents.acs dispatch --skill --set gh` measures every strategy of `gh_strats` on every
coin x 15m-1d on GitHub (every account). This module brings the lines home and adds them up, STREAMING:
the market's lines are about 1 GB (each coin about 1 MB: 72 combos x 5 timeframes, the newest 30%'s
trades), more than one `json.loads` of the whole run should hold on this PC.

* `collect()` - downloads every run of `skillgh-state.json` (and `skillgh-redo-state.json`, whose
  lines replace the first run's), and files each line by timeframe in `<acs home>/skillgh/<tf>.jsonl`
  (on the store's drive), with `meta.json`: every coin no machine reported, every coin-timeframe that
  raised or had too few candles, every download that failed - each NAMED;
* `summary()` - per strategy, per repo and per timeframe, pooled over every coin-timeframe, the
  NEWEST 30% of the candles only (days no setting was chosen on): trades, wins, losses, profit, profit
  a trade, the worst losing run (closing order, across coins), coin-timeframes that made money - beside
  the random entries (`gh_random`) of the same timeframe, the luck bar;
* `write_note()` - knowledge/github-repos/RESULTS.md;
* `write_page()` - the every-strategy page (acs_page.html), one timeframe's data files at a time.

Usage: python -m tradingagents.gh_results collect|summary|note|page
"""
from __future__ import annotations

import argparse
import json
import time
from array import array
from pathlib import Path

TFS = ("15m", "30m", "1h", "4h", "1d")
NOTE = Path(__file__).resolve().parents[1] / "knowledge" / "github-repos" / "RESULTS.md"


def folder() -> Path:
    from tradingagents import acs

    return acs.home() / "skillgh"


def collect() -> dict:
    """Every account's lines of the gh run (then its redo, which replaces what it re-measured),
    filed by timeframe; a coin no machine reported, a failure and a failed download are named."""
    import shutil

    from tradingagents import acs

    states = [json.loads((acs.home() / n).read_text(encoding="utf-8"))
              for n in ("skillgh-state.json", "skillgh-redo-state.json") if (acs.home() / n).exists()]
    if not states:
        raise RuntimeError("no skillgh-state.json: dispatch first (python -m tradingagents.acs dispatch --skill --set gh)")
    lines: dict = {}            # 'COIN|tf' -> (file, byte offset, length) of the newest copy
    report: dict = {}           # 'COIN|tf' -> error / skipped of the newest run that reported it
    reported, board, dl_failed = set(), set(), []
    root = folder()
    root.mkdir(parents=True, exist_ok=True)
    for st in states:
        for key, r in st["runs"].items():
            repo = r.get("repo", key)
            board.update(r["coin_list"])
            d = acs.home() / f"skillgh-run-{r['run']}"
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            try:
                acs._gh("run", "download", str(r["run"]), "-R", repo, "-D", str(d), "-p", "skill-lines-*",
                        timeout=1800)
            except Exception as exc:                               # noqa: BLE001
                dl_failed.append(f"{repo} run {r['run']}: {str(exc)[:160]}")
                continue
            for f in sorted(d.rglob("skillgh-*.jsonl")):
                with open(f, "rb") as fh:
                    pos = 0
                    for raw in fh:
                        if raw.strip():
                            head = json.loads(raw)            # one line at a time, then dropped
                            lines[f"{head['coin']}|{head['tf']}"] = (str(f), pos, len(raw))
                            reported.add(head["coin"])
                            del head
                        pos += len(raw)
            for f in d.rglob("skillgh-report-*.json"):
                for e in json.loads(f.read_text(encoding="utf-8")):
                    reported.add(e.get("coin"))
                    k = f"{e.get('coin')}|{e.get('tf')}"
                    if e.get("error") or e.get("skipped"):
                        report[k] = e
                    elif k in report:
                        del report[k]                  # a redo measured it this time
    outs = {tf: open(root / f"{tf}.jsonl.tmp", "wb") for tf in TFS}
    try:
        for key in sorted(lines):
            path, pos, n = lines[key]
            with open(path, "rb") as fh:
                fh.seek(pos)
                raw = fh.read(n)
            outs[key.split("|")[1]].write(raw.rstrip(b"\r\n") + b"\n")
    finally:
        for fh in outs.values():
            fh.close()
    for tf in TFS:
        (root / f"{tf}.jsonl.tmp").replace(root / f"{tf}.jsonl")
    measured = set(lines)
    meta = {"pairs": len(lines), "coins": len({k.split('|')[0] for k in lines}),
            "failed": sorted(f"{k.replace('|', ' ')}: {e['error']}" for k, e in report.items()
                             if e.get("error") and k not in measured),
            "skipped": sorted(f"{k.replace('|', ' ')}: only {e['skipped']}" for k, e in report.items()
                              if e.get("skipped") and k not in measured),
            "not_reached": sorted(c.replace("_USDT", "") for c in board if c.replace("_USDT", "") not in reported),
            "downloads_failed": dl_failed, "collected_s": int(time.time()),
            "runs": [r["run"] for st in states for r in st["runs"].values()]}
    (root / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def meta() -> dict:
    return json.loads((folder() / "meta.json").read_text(encoding="utf-8"))


def lines_of(tf: str):
    p = folder() / f"{tf}.jsonl"
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for text in fh:
            if text.strip():
                yield json.loads(text)


def _worst_run(trades) -> tuple[float, int]:
    """The worst unbroken run of losing trades in closing order: (its sum, how many trades).
    `trades` are rows whose [0] is the entry, [1] the exit and [4] the profit."""
    worst, n_worst, cur, n = 0.0, 0, 0.0, 0
    for t in sorted(trades, key=lambda t: (t[1], t[0])):
        if t[4] < 0:
            cur, n = cur + t[4], n + 1
            if cur < worst:
                worst, n_worst = cur, n
        else:
            cur, n = 0.0, 0
    return round(worst, 2), n_worst


class _Acc:
    """One pooled row: counts and money, and the trades as three compact arrays for the worst run."""

    __slots__ = ("trades", "wins", "profit", "pairs", "green", "rows", "entry", "exit", "pnl")

    def __init__(self):
        self.trades = self.wins = self.pairs = self.green = self.rows = 0
        self.profit = 0.0
        self.entry, self.exit, self.pnl = array("q"), array("q"), array("d")

    def add(self, trades: list) -> None:
        self.rows += 1
        if not trades:
            return
        self.trades += len(trades)
        p = 0.0
        for t in trades:
            self.wins += t[4] > 0
            p += t[4]
            self.entry.append(int(t[0]))
            self.exit.append(int(t[1]))
            self.pnl.append(float(t[4]))
        self.profit += p
        self.pairs += 1
        self.green += p > 0

    def done(self) -> dict:
        w, n = _worst_run(zip(self.entry, self.exit, [0] * len(self.pnl), [0] * len(self.pnl), self.pnl))
        return {"trades": self.trades, "wins": self.wins, "losses": self.trades - self.wins,
                "profit": round(self.profit, 2),
                "per_trade": round(self.profit / self.trades, 4) if self.trades else None,
                "win_rate": round(100 * self.wins / self.trades, 1) if self.trades else None,
                "worst_run": w, "worst_run_n": n, "pairs": self.pairs, "green": self.green, "rows": self.rows}


def summary(lines=None) -> dict:
    """Every strategy, repo and timeframe's figures on the newest 30% of the candles. `lines` (an
    iterable of gh lines) is for tests; left out, the collected files are streamed."""
    from tradingagents import gh_strats

    by_strat, by_repo, by_tf, stops = {}, {}, {}, {}
    errors: dict = {}
    pairs = combos = open_at_end = 0
    src = lines if lines is not None else (x for tf in TFS for x in lines_of(tf))
    for x in src:
        pairs += 1
        combos += len(x["picks"])
        open_at_end += int(x.get("open_at_end") or 0)
        for s, e in (x.get("errors") or {}).items():
            errors.setdefault(s, []).append(f"{x['coin']} {x['tf']}: {e}")
        for c in x["picks"]:
            s = c["strategy"]
            new = [t for t in c["trades"] if t[0] >= x["split_ms"]]
            by_strat.setdefault(s, _Acc()).add(new)
            by_repo.setdefault(gh_strats.REPO_OF.get(s, "?"), _Acc()).add(new)
            by_tf.setdefault((x["tf"], s), _Acc()).add(new)
            stops.setdefault(s, set()).add((c["stop"], c.get("target")))
    tf_strat = {f"{tf}|{s}": a.done() for (tf, s), a in by_tf.items()}
    luck = {tf: tf_strat.get(f"{tf}|gh_random", {}).get("per_trade") for tf in TFS}
    strat = {}
    for s, a in by_strat.items():
        row = {**a.done(), "repo": gh_strats.REPO_OF.get(s, "?"), "rule": gh_strats.RULE_OF.get(s, ""),
               "stops": sorted(stops[s], key=lambda p: (p[0], p[1] or 0))}
        beat = [tf_strat[f"{tf}|{s}"]["per_trade"] > luck[tf] for tf in TFS
                if f"{tf}|{s}" in tf_strat and tf_strat[f"{tf}|{s}"]["trades"] and luck.get(tf) is not None]
        row["beats_random_tfs"] = f"{sum(beat)} of {len(beat)}"
        strat[s] = row
    m = meta() if lines is None else {}
    return {"strategies": strat, "repos": {r: a.done() for r, a in by_repo.items()}, "by_tf": tf_strat,
            "luck_per_trade": luck, "pairs": pairs, "combos": combos, "open_at_end": open_at_end,
            "errors": {s: e[:5] + ([f"... {len(e) - 5} more"] if len(e) > 5 else []) for s, e in errors.items()},
            "not_ported": dict(gh_strats.NOT_PORTED), "failed": m.get("failed", []),
            "skipped": m.get("skipped", []), "not_reached": m.get("not_reached", []),
            "downloads_failed": m.get("downloads_failed", []), "collected_s": m.get("collected_s")}


def _money(x):
    return "-" if x is None else f"{x:+,.2f}"


def write_note(sm: dict | None = None, page_url: str | None = None) -> Path:
    from tradingagents.positions_view import fmt_when

    sm = sm or summary()
    rows = sorted(sm["strategies"].items(), key=lambda kv: -(kv[1]["per_trade"] if kv[1]["per_trade"]
                                                             is not None else -1e9))
    out = ["# The reviewed repos' strategies, backtested on our market", "",
           f"Measured on GitHub, collected {fmt_when(sm['collected_s']) if sm['collected_s'] else '-'}: every "
           f"strategy in `tradingagents/gh_strats` on {sm['pairs']:,} coin-timeframes (every coin x 15m, 30m, "
           f"1h, 4h, 1d), {sm['combos']:,} strategy x setting x stop combinations tested in all. Figures are "
           "the NEWEST 30% of each coin-timeframe's candles (days no setting was chosen on), by the candle a "
           "trade opened in; every trade pays Gate's fee both ways, the recorded order book of its own minute "
           "where one exists (else the coin's usual gap) and funding over the hold, with stops and targets "
           "settled by the minute. $5 margin x 20x = $100 a trade, flat. Trades still open at the end are "
           f"left out ({sm['open_at_end']:,})." + (f" Page: {page_url}" if page_url else ""), "",
           "The luck bar is random entries through the same engine (`gh_random`): profit a trade by "
           "timeframe " + ", ".join(f"{tf} {_money(v)}" for tf, v in sm["luck_per_trade"].items()) + ".", "",
           "| Strategy | Repo | TP | SL | Leverage | Trades | Wins | Losses | Win rate | PROFIT / TOTAL $ "
           "| $ a trade | Worst losing run | Coin-timeframes that made money | Beats random (timeframes) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s, r in rows:
        tps = sorted({f"{p[1] * 100:g}%" if p[1] else "own exit" for p in r["stops"]})
        sls = sorted({f"{p[0] * 100:g}%" for p in r["stops"]})
        wr = "-" if r["win_rate"] is None else f"{r['win_rate']:.1f}%"
        out.append(f"| {s} | {r['repo']} | {', '.join(tps)} | {', '.join(sls)} | 20x | {r['trades']:,} | "
                   f"{r['wins']:,} | {r['losses']:,} | {wr} | {_money(r['profit'])} | {_money(r['per_trade'])} | "
                   f"{r['worst_run']:+,.2f} over {r['worst_run_n']} | {r['green']:,} of {r['pairs']:,} | "
                   f"{r['beats_random_tfs']} |")
    out += ["", "## Each strategy's rule", ""]
    out += [f"- `{s}` ({r['repo']}): {r['rule']}" for s, r in rows]
    out += ["", "## Not ported, and why", ""]
    out += [f"- {k}: {v}" for k, v in sorted(sm["not_ported"].items())]
    gaps = [f"- `{s}` raised on: " + "; ".join(e) for s, e in sm["errors"].items()]
    gaps += [f"- failed: {f}" for f in sm["failed"]]
    gaps += [f"- too few candles: {f}" for f in sm["skipped"][:40]]
    gaps += ([f"- ... {len(sm['skipped']) - 40} more with too few candles"] if len(sm["skipped"]) > 40 else [])
    gaps += [f"- not reached: {', '.join(sm['not_reached'])}"] if sm["not_reached"] else []
    gaps += [f"- download failed: {d}" for d in sm["downloads_failed"]]
    if gaps:
        out += ["", "## What did not run", ""] + gaps
    NOTE.write_text("\n".join(out) + "\n", encoding="utf-8")
    return NOTE


WORDS = {"what": "strategies from the reviewed GitHub repos (and random entries, the luck bar)",
         "cost_words": "Every trade pays the exchange's 0.075% fee both ways, the recorded order book of its own "
                       "minute where one exists (else the coin's usual gap) and funding over the hold; stops "
                       "and targets are settled by the minute;",
         "title_h": "Every strategy from the reviewed GitHub repos, every coin and timeframe"}


def write_page() -> Path:
    """The every-strategy page, built ONE timeframe at a time from the filed lines (acs_page's own
    rows, payload and packing), then every payload told the whole run's totals."""
    from tradingagents import acs_page, gh_strats

    m = meta()
    repos = sorted({r for r in gh_strats.REPO_OF.values() if not r.startswith("luck-bar")})
    words = {**WORDS, "prov_what": f"the reviewed GitHub repos' own strategies ({len(repos)} repos, "
             f"{len(gh_strats.GRID)} strategies, up to 2 settings each at the repo's own stop or 2%, "
             "knowledge/github-repos/) plus random entries through the same engine as the luck bar. Each row "
             "lists only the trades of the NEWEST 30% of its candles - the days it is judged on - so every "
             "figure, and the last N days box, is over those days; the older 70% is the row's 'chosen on' "
             "line, its figures only,"}
    from tradingagents import acs

    root = acs.home() / "github-repo-strategies"
    root.mkdir(parents=True, exist_ok=True)
    for f in root.glob("*.txt"):
        f.unlink()
    zf, ids, totals, payloads = {}, {}, {}, {}
    all_rows = 0
    for tf in TFS:
        sub = {f"{x['coin']}|{x['tf']}": x for x in lines_of(tf)}
        if not sub:
            continue
        out, tf_ids = acs_page.split_payloads({"lines": sub, "collected_s": m.get("collected_s"),
                                               "failed": m.get("failed"), "skipped": m.get("skipped"),
                                               "not_reached": m.get("not_reached")}, words)
        payloads[tf] = out[tf]
        totals.update(out[tf]["totals"])
        all_rows += out[tf]["all_rows"]
        ids.update(tf_ids)
        tmp = root / f"{tf}.payload.json"           # spilled to disk: one timeframe in memory at a time
        tmp.write_text(json.dumps(out[tf], separators=(",", ":")), encoding="utf-8")
        del sub, out
        payloads[tf] = tmp
    if len(ids) != all_rows:
        raise ValueError(f"{all_rows - len(ids):,} strategies share an id with another")

    def put(name, data):
        text = acs_page.pack(data)
        files = []
        for k in range(0, len(text), acs_page.CHUNK):
            fn = f"{name}-{k // acs_page.CHUNK}.txt"
            (root / fn).write_text(text[k:k + acs_page.CHUNK], encoding="ascii")
            files.append(fn)
        zf[name] = files

    combos = len(gh_strats.combos())
    for tf, tmp in payloads.items():
        data = json.loads(tmp.read_text(encoding="utf-8"))
        data.update({"totals": totals, "all_rows": all_rows, "pairs": m.get("pairs", 0), "combos": combos,
                     "failed": m.get("failed", []), "not_reached": m.get("not_reached", [])})
        put(tf, data)
        tmp.unlink()
    put("ids", ids)
    html = acs_page._HTML.read_text(encoding="utf-8").replace("const ZF={};", f"const ZF={json.dumps(zf)};", 1)
    html = html.replace("<title>All Coins Strategies</title>", "<title>GitHub Repo Strategies</title>", 1)
    (root / "index.html").write_text(html, encoding="utf-8")
    return root


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.gh_results")
    p.add_argument("cmd", choices=("collect", "summary", "note", "page"))
    a = p.parse_args(argv)
    if a.cmd == "collect":
        m = collect()
        print(json.dumps({k: (v if not isinstance(v, list) or len(v) < 30 else v[:30] + [f"... {len(v)} in all"])
                          for k, v in m.items()}, indent=1))
    elif a.cmd == "summary":
        sm = summary()
        print(json.dumps({k: v for k, v in sm.items() if k != "by_tf"}, indent=1, default=str)[:20000])
    elif a.cmd == "note":
        print(write_note())
    else:
        print(write_page())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
