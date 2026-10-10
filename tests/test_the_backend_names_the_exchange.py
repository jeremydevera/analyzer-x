"""The back end's own messages name the exchange from the setting (Oct 10,
2026, the move to Gate) — never "MEXC" in a module that serves both.

A refusal, a log line on the Runner feed or a reason on a screen that still
says MEXC over Gate's numbers is the label-must-match-data failure. Docstrings
and comments may tell MEXC's history; a STRING the program prints may not,
outside the MEXC-only modules and the few places that are about MEXC itself.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tradingagents"
MEXC_ONLY = {"mexc_futures.py", "mexc.py", "mexc_trade.py", "mexc_credentials.py",
             "venue.py", "error_fixer.py", "error_issues.py", "replay_page.py",
             "report_template.py", "research_page.py"}
ABOUT_MEXC = {("live_price.py", "MEXC"),                    # MexcProtocol.name
              ("costs_daily.py", "the costs job is Gate's (the app trades MEXC)")}


def test_no_printed_string_spells_mexc():
    bad = []
    for p in sorted(ROOT.rglob("*.py")):
        if p.name in MEXC_ONLY:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                body = node.body
                if body and isinstance(body[0], ast.Expr) and isinstance(
                        getattr(body[0], "value", None), ast.Constant):
                    docs.add(id(body[0].value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and "MEXC" in node.value and id(node) not in docs
                    and (p.name, node.value) not in ABOUT_MEXC):
                bad.append(f"{p.name}:{node.lineno}: {node.value[:80]!r}")
    assert not bad, "name the exchange with venue.name():\n" + "\n".join(bad)
