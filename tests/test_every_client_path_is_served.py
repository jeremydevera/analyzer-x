"""Every `/api/...` path the browser asks for is a route the app really serves.

Found Sep 09, 2026 by restarting localhost and reading the browser's failed
requests. Every load of the Candles page answered:

    GET /api/candles/download-history?limit=20
    422 {"loc": ["query", "symbol"], "msg": "Field required"}

`@app.get("/api/candles/download-history")` had been separated from the
function it decorates: a helper, `_lost_kind_on(got, symbol, tf, texts=None)`,
was inserted BETWEEN the decorator and `download_history`. FastAPI therefore
registered the helper as the endpoint — its `got`, `symbol` and `tf` arguments
became required query and body fields — while `download_history` itself was
left undecorated, a route that existed in the source and not in the app.

Nothing caught it. The page still rendered, the panel was simply empty, and no
test asks whether the routes the CLIENT calls exist. So this file does.

Two guards, because they fail on different mistakes:

* no route may be bound to a private helper — the exact slip above;
* every literal path in `webapp/src/lib/api.ts` must match a registered route
  — which also catches a renamed path, a typo, and a route deleted from under
  a caller.
"""
from __future__ import annotations

import ast
import pathlib
import re

from tradingagents.api import app

API_TS = pathlib.Path("webapp/src/lib/api.ts")
API_PY = pathlib.Path("tradingagents/api.py")
ROUTE_DECORATORS = ("get", "post", "put", "delete", "patch")


def _registered() -> set[str]:
    return {getattr(r, "path", "") for r in app.routes if getattr(r, "path", "")}


def _client_paths() -> set[str]:
    """Literal `/api/...` paths in the browser client.

    A `${...}` hole becomes `{x}`, and the path stops at the first `?`, `$`,
    quote or backtick — the query string is not part of the route.
    """
    text = API_TS.read_text(encoding="utf-8")
    out = set()
    for m in re.finditer(r'["`](/api/[^"`]*)', text):
        raw = m.group(1)
        raw = re.sub(r"\$\{[^}]*\}", "{x}", raw)     # template hole
        raw = re.split(r"[?$]", raw)[0].rstrip("/")  # drop the query
        if raw.startswith("/api/"):
            out.add(raw)
    return out


def _matches(client: str, route: str) -> bool:
    """Does one client path match one route, allowing for parameters?"""
    pat = "^" + "/".join(
        "[^/]+" if seg in ("{x}",) or (seg.startswith("{") and seg.endswith("}"))
        else re.escape(seg)
        for seg in route.split("/")) + "$"
    if re.match(pat, client):
        return True
    pat2 = "^" + "/".join(
        "[^/]+" if seg == "{x}" else re.escape(seg)
        for seg in client.split("/")) + "$"
    return bool(re.match(pat2, route))


def test_no_route_is_bound_to_a_private_helper():
    """The exact slip: a helper inserted between a decorator and its handler.

    A route function whose name starts with `_` is either that mistake or a
    handler nobody meant to expose; both are worth failing on.
    """
    tree = ast.parse(API_PY.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in ROUTE_DECORATORS
                    and node.name.startswith("_")):
                path = dec.args[0].value if dec.args else "?"
                bad.append(f"api.py:{node.lineno} {path} -> {node.name}()")
    assert not bad, (
        "a route is bound to a private helper — the decorator has drifted off "
        f"the function it belongs to: {bad}")


def test_every_path_the_browser_calls_is_registered():
    """The general form: the client asks, the app must answer."""
    routes = _registered()
    client = _client_paths()
    assert len(client) > 40, f"only {len(client)} client paths parsed — check the regex"
    missing = sorted(p for p in client
                     if not any(_matches(p, r) for r in routes))
    assert not missing, (
        "the browser calls paths this app does not serve — a decorator off its "
        f"function, a rename, or a typo: {missing}")


def test_the_download_history_route_answers_without_a_symbol():
    """The incident itself, as a request.

    It took `limit` only; the wrongly-bound helper demanded `symbol`, `tf` and
    a body, so the panel got a 422 on every page load.
    """
    from fastapi.testclient import TestClient

    r = TestClient(app).get("/api/candles/download-history?limit=5")
    assert r.status_code == 200, r.text[:300]
    assert isinstance(r.json(), dict)


def test_the_helper_is_still_a_helper():
    """`_lost_kind_on` must keep working as a plain function — moving the
    decorator must not have moved the helper out of reach of its callers."""
    from tradingagents import api as api_mod

    assert callable(api_mod._lost_kind_on)
    got = api_mod._lost_kind_on({"stored": 0}, "AAA_USDT", "1h", None)
    assert isinstance(got, dict) and "kind" in got
