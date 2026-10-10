"""Every GitHub workflow that runs a script names the exchange (phase 3,
Oct 10, 2026, the move to Gate).

A shard reads the exchange through `tradingagents.venue`, and GitHub's
machines have no venue.json, so the workflow's own `env: TA_VENUE: gate` is
what makes a run measure Gate. A workflow that forgot it would measure MEXC
and its rows would be refused at collect (`cloud_sweep.land_rows`) — a whole
run of 20 machines thrown away. It is a workflow-level env, never an input:
`sweep.yml` is at GitHub's ten-input ceiling.
"""
import re
from pathlib import Path

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _runs_a_script(text: str) -> bool:
    return bool(re.search(r"python3? \.github/scripts/\w+\.py", text))


def test_every_script_workflow_sets_the_exchange_for_the_whole_run():
    missing = []
    for p in sorted(WF.glob("*.yml")):
        text = p.read_text(encoding="utf-8")
        if not _runs_a_script(text):
            continue
        if not re.search(r"(?m)^env:\n(?:  .*\n)*?  TA_VENUE: gate$", text):
            missing.append(p.name)
    assert not missing, f"these run a script without TA_VENUE: gate: {missing}"


def test_the_exchange_is_never_an_input():
    for p in WF.glob("*.yml"):
        assert "ta_venue:" not in p.read_text(encoding="utf-8").lower().replace(
            "ta_venue: gate", ""), p.name
