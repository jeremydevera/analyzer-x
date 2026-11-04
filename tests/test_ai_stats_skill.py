"""ai_stats (operator, Nov 04, 2026: "use that api and create rule when i say
ai_stats showme top 10 ai models for coding and reasoning"). Offline: the API
is never called here."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude/skills/ai_stats/scripts/ai_stats.py"


def _load():
    spec = importlib.util.spec_from_file_location("ai_stats", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _m(name, coding=None, intel=None, gpqa=None, hle=None):
    return {"name": name, "model_creator": {"name": "Maker"},
            "evaluations": {"artificial_analysis_coding_index": coding,
                            "artificial_analysis_intelligence_index": intel,
                            "gpqa": gpqa, "hle": hle}}


def test_each_ranking_is_highest_first_and_leaves_out_a_missing_score():
    s = _load()
    models = [_m("A", coding=50, intel=60), _m("B", coding=70, intel=None),
              _m("C", coding=None, intel=80), _m("D", coding=60, intel=55)]
    assert [m["name"] for m in s.top(models, "artificial_analysis_coding_index")] == ["B", "D", "A"]
    assert [m["name"] for m in s.top(models, "artificial_analysis_intelligence_index")] == ["C", "A", "D"]
    assert len(s.top([_m(str(i), coding=i) for i in range(30)], "artificial_analysis_coding_index")) == 10


def test_the_report_has_both_tables_and_the_credit_the_terms_require():
    s = _load()
    out = s.report([_m("Best", coding=70.5, intel=72.1, gpqa=0.84, hle=0.25)], at=1_793_000_000)
    assert "CODING" in out and "REASONING" in out and "| 1 | Best | Maker | 70.5 |" in out
    assert "84.0%" in out and "25.0%" in out
    assert "artificialanalysis.ai" in out


def test_no_key_says_how_to_get_one_and_never_calls_the_api(monkeypatch, tmp_path, capsys):
    s = _load()
    monkeypatch.delenv(s.KEY_ENV, raising=False)
    monkeypatch.setattr(s, "KEY_FILE", tmp_path / "missing")
    monkeypatch.setattr(s, "fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called the API")))
    assert s.main([]) == 2
    assert "create an API key" in capsys.readouterr().out


def test_the_key_is_never_kept_in_the_repo():
    s = _load()
    assert ROOT not in s.KEY_FILE.resolve().parents and ROOT not in s.CACHE.resolve().parents
