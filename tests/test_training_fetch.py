"""The training-materials fetcher, against a real local HTTP server.

Each test names the rule it guards: free-only, denied hosts, retries,
cross-site redirects, robots.txt, the size cap, duplicates, and the store drive.
"""

from __future__ import annotations

import ast
import hashlib
import http.server
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tradingagents import training_fetch as tf
from tradingagents.training_manifest import Source, source_id

# These tests open a socket to a server they start themselves on 127.0.0.1.
# conftest blocks every socket in unit tests, so the file is marked integration:
# redirects, retries and robots.txt cannot be checked any other way.
pytestmark = pytest.mark.integration


@pytest.fixture
def site():
    routes: dict = {}
    hits: list = []
    fail_once: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            if self.path in fail_once:
                self.send_response(fail_once.pop(self.path))
                self.end_headers()
                return
            spec = routes.get(self.path)
            if spec is None:
                self.send_response(404)
                self.end_headers()
                return
            code, headers, body = spec
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        yield SimpleNamespace(
            base=f"http://127.0.0.1:{port}", port=port,
            routes=routes, hits=hits, fail_once=fail_once,
        )
    finally:
        srv.shutdown()
        srv.server_close()


def _src(url: str, kind: str = "html", free: bool = True) -> Source:
    return Source(id=source_id(url), url=url, kind=kind, free=free, tier=1, note="")


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(tf, "RETRY_SLEEP_S", 0)


def test_a_free_page_is_saved_with_its_hash_under_the_store(site, tmp_path):
    body = b"<html><body>" + b"hello world " * 40 + b"</body></html>"
    site.routes["/a.html"] = (200, {"Content-Type": "text/html"}, body)
    r = tf.fetch(_src(site.base + "/a.html"), store=tmp_path, gap_s=0)
    assert r.status == "saved"
    assert r.path is not None and r.path.exists()
    assert tmp_path in r.path.parents
    assert r.sha256 == hashlib.sha256(body).hexdigest()
    assert r.bytes == len(body)


def test_a_paid_source_is_refused_without_a_request(site, tmp_path):
    site.routes["/paid.html"] = (200, {}, b"x" * 50)
    r = tf.fetch(_src(site.base + "/paid.html", free=False), store=tmp_path, gap_s=0)
    assert r.status == "refused"
    assert "not free" in r.reason
    assert site.hits == []


def test_a_denied_host_is_refused_and_named(tmp_path):
    r = tf.fetch(_src("https://libgen.is/book/x.pdf", kind="pdf"), store=tmp_path, gap_s=0)
    assert r.status == "refused"
    assert "libgen.is" in r.reason


def test_a_500_then_200_is_retried_and_saved(site, tmp_path):
    site.routes["/r.html"] = (200, {}, b"<p>" + b"retry " * 60 + b"</p>")
    site.fail_once["/r.html"] = 500
    r = tf.fetch(_src(site.base + "/r.html"), store=tmp_path, gap_s=0)
    assert r.status == "saved"
    assert site.hits.count("/r.html") == 2


def test_a_redirect_to_another_site_is_refused_and_nothing_is_saved(site, tmp_path):
    site.routes["/go.html"] = (302, {"Location": f"http://localhost:{site.port}/x.html"}, b"")
    site.routes["/x.html"] = (200, {}, b"<p>" + b"elsewhere " * 60 + b"</p>")
    r = tf.fetch(_src(site.base + "/go.html"), store=tmp_path, gap_s=0)
    assert r.status == "refused"
    assert "redirected to a different site" in r.reason
    raw = tmp_path / "raw"
    assert not raw.exists() or not any(raw.iterdir())


def test_robots_disallow_is_respected(site, tmp_path):
    site.routes["/robots.txt"] = (200, {}, b"User-agent: *\nDisallow: /private/\n")
    site.routes["/private/p.html"] = (200, {}, b"<p>" + b"secret " * 60 + b"</p>")
    r = tf.fetch(_src(site.base + "/private/p.html"), store=tmp_path, gap_s=0)
    assert r.status == "refused"
    assert "robots.txt" in r.reason


def test_a_body_over_max_bytes_is_refused(site, tmp_path, monkeypatch):
    monkeypatch.setattr(tf, "MAX_BYTES", 100)
    site.routes["/big.html"] = (200, {}, b"y" * 500)
    r = tf.fetch(_src(site.base + "/big.html"), store=tmp_path, gap_s=0)
    assert r.status == "refused"
    assert "100" in r.reason


def test_the_same_bytes_under_two_urls_are_saved_once(site, tmp_path):
    body = b"<p>" + b"same page " * 60 + b"</p>"
    site.routes["/one.html"] = (200, {}, body)
    site.routes["/two.html"] = (200, {}, body)
    first = tf.fetch(_src(site.base + "/one.html"), store=tmp_path, gap_s=0)
    second = tf.fetch(_src(site.base + "/two.html"), store=tmp_path, gap_s=0)
    assert first.status == "saved"
    assert second.status == "duplicate"
    assert first.id in second.reason


def test_run_counts_add_up_and_names_every_problem(site, tmp_path, monkeypatch):
    monkeypatch.setattr(tf, "HOST_GAP_S", 0)
    ok_body = b"<p>" + b"keep this page " * 60 + b"</p>"
    site.routes["/ok.html"] = (200, {}, ok_body)
    site.routes["/dup.html"] = (200, {}, ok_body)
    site.routes["/missing.html"] = (404, {}, b"")  # no route -> 404, a named failure
    sources = [
        _src(site.base + "/ok.html"),
        _src(site.base + "/dup.html"),
        _src(site.base + "/missing.html"),
        _src(site.base + "/paid.html", free=False),
    ]
    progress = tf.run(sources, store=tmp_path)
    assert progress["total"] == 4
    assert progress["saved"] + progress["refused"] + progress["failed"] + progress["duplicate"] == 4
    named = {p["id"] for p in progress["problems"]}
    for s in sources[1:]:
        assert s.id in named
    assert sources[0].id not in named


def test_a_redo_of_one_source_keeps_the_other_results(site, tmp_path, monkeypatch):
    monkeypatch.setattr(tf, "HOST_GAP_S", 0)
    site.routes["/a.html"] = (200, {}, b"<p>" + b"alpha " * 60 + b"</p>")
    site.routes["/b.html"] = (200, {}, b"<p>" + b"beta " * 60 + b"</p>")
    a, b = _src(site.base + "/a.html"), _src(site.base + "/b.html")
    tf.run([a, b], store=tmp_path)
    progress = tf.run([a, b], store=tmp_path, only=b.id)
    assert progress["total"] == 2
    assert progress["saved"] == 2
    assert progress["not_run"] == 0


def test_a_repo_source_maps_to_its_raw_readme():
    src = _src("https://github.com/owner/repo", kind="repo")
    assert tf.resolve(src) == "https://raw.githubusercontent.com/owner/repo/HEAD/README.md"


def test_the_module_never_uses_the_system_temp_folder():
    path = Path(tf.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "tempfile" not in imported
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "TemporaryDirectory" not in called and "mkdtemp" not in called
    from tradingagents import market_sweep as msw

    assert str(tf.default_store()).startswith(str(msw.HOME))
