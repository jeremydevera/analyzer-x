"""Detached LLM analysis runs, with live stage progress and reports.

Streamlit ran the graph inline, so clicking anything mid-run abandoned it and
closing the tab lost the work. Here each run is its own process: the caller
writes a spec, the run writes a progress+reports JSON after every graph chunk,
and the page polls it. Closing the browser does not stop the run.

    python -m tradingagents.analysis_jobs <run_id>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from tradingagents import portable

RUN_DIR = Path(os.path.expanduser("~/.tradingagents/analysis"))

# The pipeline every run walks, in order. The four analysts are optional; the
# rest always run. Kept here (not in app.py) so the API and the UI agree.
ANALYST_STAGES = [
    ("market", "Market Analyst", "market_report"),
    ("social", "Sentiment Analyst", "sentiment_report"),
    ("news", "News Analyst", "news_report"),
    ("fundamentals", "Fundamentals Analyst", "fundamentals_report"),
]


# Where the Sentiment Analyst reads social posts. X/Twitter is metered, so it
# is never on unless it was asked for by name — an unknown value falls back to
# the free source rather than spending credits (the same rule the Streamlit
# screen enforced through crypto_screener.social_flags).
SOCIAL_SOURCES = {
    "stocktwits": {"include_stocktwits": True, "include_twitter": False},
    "twitter": {"include_stocktwits": False, "include_twitter": True},
    "both": {"include_stocktwits": True, "include_twitter": True},
}
DEFAULT_SOCIAL = "stocktwits"


def social_config(spec: dict) -> dict:
    """Config flags for one run's social choice, plus any extra X terms."""
    choice = str(spec.get("social_source") or DEFAULT_SOCIAL).strip().lower()
    flags = dict(SOCIAL_SOURCES.get(choice, SOCIAL_SOURCES[DEFAULT_SOCIAL]))
    if flags["include_twitter"]:
        terms, seen = [], set()
        for raw in spec.get("twitter_keywords") or []:
            t = str(raw).strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                terms.append(t)
        if terms:
            flags["twitter_extra_terms"] = terms
    return flags


def _paths(run_id: str) -> dict:
    d = RUN_DIR / run_id
    return {"dir": d, "spec": d / "spec.json", "progress": d / "progress.json",
            "pid": d / "pid", "stop": d / "STOP", "log": d / "run.log"}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _alive(pid: int) -> bool:
    return portable.pid_alive(pid)


def _nonempty(v) -> bool:
    return bool(v and str(v).strip())


def stage_statuses(state: dict, selected: list[str]) -> list[dict]:
    """Ordered stages with status ∈ {done, running, waiting}. Pure.

    The first not-done stage is the running one — the graph does not announce
    what it is working on, so position in the pipeline is the only honest
    signal available.
    """
    state = state or {}
    debate = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    stages: list[tuple[str, bool]] = []
    for key, label, report_key in ANALYST_STAGES:
        if key in selected:
            stages.append((label, _nonempty(state.get(report_key))))
    stages += [
        ("Bull / Bear Debate", _nonempty(debate.get("judge_decision"))
         or _nonempty(state.get("investment_plan"))),
        ("Research Manager", _nonempty(state.get("investment_plan"))),
        ("Trader", _nonempty(state.get("trader_investment_plan"))),
        ("Risk Debate", _nonempty(risk.get("judge_decision"))
         or _nonempty(state.get("final_trade_decision"))),
        ("Final Decision", _nonempty(state.get("final_trade_decision"))),
    ]
    out, running_taken = [], False
    for label, done in stages:
        if done:
            out.append({"label": label, "status": "done"})
        elif not running_taken:
            out.append({"label": label, "status": "running"})
            running_taken = True
        else:
            out.append({"label": label, "status": "waiting"})
    return out


def reports_of(state: dict) -> dict:
    """Every report the run has produced so far, by section."""
    state = state or {}
    debate = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    out = {}
    for _key, label, rkey in ANALYST_STAGES:
        if _nonempty(state.get(rkey)):
            out[label] = state[rkey]
    for label, val in (("Bull / Bear Judgement", debate.get("judge_decision")),
                       ("Research Manager Plan", state.get("investment_plan")),
                       ("Trader Plan", state.get("trader_investment_plan")),
                       ("Risk Judgement", risk.get("judge_decision")),
                       ("Final Decision", state.get("final_trade_decision"))):
        if _nonempty(val):
            out[label] = val
    return out


def start(spec: dict) -> str:
    """Spawn one analysis. Returns its run id."""
    run_id = f"{spec.get('ticker', 'RUN')}-{uuid.uuid4().hex[:8]}"
    p = _paths(run_id)
    p["dir"].mkdir(parents=True, exist_ok=True)
    _write(p["spec"], spec)
    _write(p["progress"], {"running": True, "run_id": run_id,
                           "started_at": time.time(), "spec": spec,
                           "stages": stage_statuses({}, spec.get("analysts", [])),
                           "reports": {}, "decision": None, "error": None})
    with p["log"].open("a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "tradingagents.analysis_jobs", run_id],
            stdout=log, stderr=log, **portable.DETACHED,
            cwd=str(Path(__file__).resolve().parent.parent))
    p["pid"].write_text(str(proc.pid), encoding="utf-8")
    return run_id


def status(run_id: str) -> dict:
    """The run's progress. A dead process is never reported as running."""
    p = _paths(run_id)
    got = _read(p["progress"])
    if not got:
        return {"running": False, "error": "no such run", "run_id": run_id}
    if got.get("running"):
        try:
            pid = int(p["pid"].read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if not _alive(pid):
            got["running"] = False
            got["error"] = got.get("error") or "the run process died before finishing"
            _write(p["progress"], got)
    return got


def stop(run_id: str) -> bool:
    """Ask a run to stop at its next chunk boundary; kill if it ignores us."""
    p = _paths(run_id)
    p["stop"].parent.mkdir(parents=True, exist_ok=True)
    p["stop"].write_text("stop", encoding="utf-8")
    try:
        pid = int(p["pid"].read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if _alive(pid):
        os.kill(pid, 15)
    got = _read(p["progress"])
    if got:
        got.update({"running": False, "error": "stopped by the operator"})
        _write(p["progress"], got)
    return True


def runs(limit: int = 25) -> list[dict]:
    """Recent runs, newest first — one line each, no report bodies."""
    if not RUN_DIR.exists():
        return []
    out = []
    for d in sorted(RUN_DIR.iterdir(), key=lambda p: -p.stat().st_mtime):
        if not d.is_dir():
            continue
        got = _read(d / "progress.json")
        if not got:
            continue
        out.append({"run_id": d.name, "running": got.get("running"),
                    "started_at": got.get("started_at"),
                    "ticker": (got.get("spec") or {}).get("ticker"),
                    "model": (got.get("spec") or {}).get("model"),
                    "decision": got.get("decision"),
                    "error": got.get("error")})
        if len(out) >= limit:
            break
    return out


def _run(run_id: str) -> None:
    """The worker. Writes a progress snapshot after every graph chunk."""
    p = _paths(run_id)
    spec = _read(p["spec"])
    got = _read(p["progress"])
    selected = spec.get("analysts") or [k for k, _, _ in ANALYST_STAGES]

    def snap(state: dict, **extra) -> None:
        got.update({"stages": stage_statuses(state, selected),
                    "reports": reports_of(state), **extra})
        _write(p["progress"], got)

    try:
        import app_models
        import model_registry
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        model = spec.get("model") or DEFAULT_CONFIG["deep_think_llm"]
        mspec = model_registry.merged_models(app_models.MODELS).get(model, {})
        cfg = dict(DEFAULT_CONFIG)
        cfg.update({
            "llm_provider": mspec.get("provider") or DEFAULT_CONFIG["llm_provider"],
            "backend_url": mspec.get("base_url") or DEFAULT_CONFIG.get("backend_url"),
            "deep_think_llm": model, "quick_think_llm": model,
            "max_debate_rounds": int(spec.get("debate_rounds") or 1),
            "max_risk_discuss_rounds": int(spec.get("risk_rounds") or 1),
        })
        cfg.update(social_config(spec))
        key_env = mspec.get("key_env")
        if key_env and mspec.get("provider") == "openai_compatible":
            env_key = os.environ.get(key_env, "")
            if env_key:
                cfg["api_key"] = env_key

        ta = TradingAgentsGraph(selected_analysts=tuple(selected), debug=False,
                                config=cfg)
        ticker = spec["ticker"]
        asset = spec.get("asset_type") or "stock"
        init = ta.propagator.create_initial_state(
            ticker, spec["trade_date"], asset_type=asset,
            past_context=ta.memory_log.get_past_context(ticker),
            instrument_context=ta.resolve_instrument_context(ticker, asset))
        final: dict = {}
        for chunk in ta.graph.stream(init, **ta.propagator.get_graph_args()):
            final = chunk
            if p["stop"].exists():
                snap(final, running=False, error="stopped by the operator")
                return
            snap(final)
        decision = (final.get("final_trade_decision") or "").strip()
        snap(final, running=False, decision=decision,
             finished_at=time.time())
    except Exception as exc:                                   # noqa: BLE001
        got.update({"running": False,
                    "error": f"{type(exc).__name__}: {exc}"})
        _write(p["progress"], got)
        raise


if __name__ == "__main__":
    _run(sys.argv[1])
