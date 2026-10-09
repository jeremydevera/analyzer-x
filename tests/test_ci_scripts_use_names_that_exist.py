"""Every name a GitHub script reads from this repo's own modules exists.

Oct 08, 2026: deleting the Forecast page's "Where the money goes" took
forecast_v2.HOURS and forecast_v2.HELD with it, while
.github/scripts/forecast_shard.py still read both. Every machine of every daily
base run would have failed, 40 a day, from the first push. Every test on this
PC passed, because none of them ran that line, and the scripts run on GitHub
from `main`, so nothing here would have noticed. The code review found it
before it was pushed.

So this walks every script's imports of `tradingagents`. For each one it
checks that every `alias.name` the script reads, and every
`from tradingagents.x import name`, still exists. Removing a name a script
uses now fails here, on this PC, before it can fail on GitHub.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ROOT / ".github" / "scripts").glob("*.py"))


def _uses(path: Path) -> set[tuple[str, str]]:
    """{(module, name)} the script reads from `tradingagents`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    aliases: dict[str, str] = {}
    used: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tradingagents":
            for a in node.names:
                if node.module == "tradingagents":
                    aliases[a.asname or a.name] = f"tradingagents.{a.name}"
                else:
                    used.add((node.module, a.name))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("tradingagents.") and a.asname:
                    aliases[a.asname] = a.name
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in aliases):
            used.add((aliases[node.value.id], node.attr))
    return used


def test_the_scripts_are_found():
    assert len(SCRIPTS) >= 5 and any(p.name == "forecast_shard.py" for p in SCRIPTS)
    assert ("tradingagents.forecast_v2", "family") in _uses(ROOT / ".github/scripts/forecast_shard.py"), \
        "the walk must see `f2.family` in the shard, or it checks nothing"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_every_name_a_github_script_reads_exists(script):
    missing = []
    for mod, name in sorted(_uses(script)):
        if hasattr(importlib.import_module(mod), name):
            continue
        try:                                   # `from tradingagents.x import sub`: a submodule
            importlib.import_module(f"{mod}.{name}")
        except ImportError:
            missing.append(f"{mod}.{name}")
    assert not missing, f"{script.name} reads names that no longer exist: {missing}"
