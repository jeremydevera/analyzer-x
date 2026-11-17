"""Download the free training-material sources to the store drive.

Rules, each guarded by tests/test_training_fetch.py:
- a source the manifest does not mark free is never requested;
- a denied pirate or mirror host is refused before any request;
- robots.txt is obeyed, and a robots.txt that cannot be read refuses the fetch;
- a redirect to another site is refused, and nothing from it is saved;
- a transient failure (5xx, 429, a cut connection) is retried; a 4xx is not;
- a body over MAX_BYTES is refused;
- the same bytes under two URLs are saved once, the second marked duplicate;
- every file lands under the store (G:), never the system temp folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from tradingagents import market_sweep as msw
from tradingagents.training_manifest import DENIED_HOSTS, Source

def default_store() -> Path:
    """The store folder, read at call time (msw.HOME can be pointed elsewhere)."""
    return Path(msw.HOME) / "research" / "training-materials"


MAX_BYTES = 200 * 1024 * 1024
HOST_GAP_S = 2.0
RETRIES = 3
RETRY_SLEEP_S = 2.0
TIMEOUT_S = 60
USER_AGENT = "tradingagents-research/1.0"
EXT = {"pdf": ".pdf", "html": ".html", "repo": ".md"}

_last_hit: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


@dataclass(frozen=True)
class Result:
    id: str
    status: str  # "saved" | "refused" | "failed" | "duplicate"
    reason: str
    path: Path | None
    bytes: int
    sha256: str


def resolve(src: Source) -> str:
    """The URL that holds the source's text. A repo is read through its README."""
    if src.kind == "repo":
        parts = [p for p in urlparse(src.url).path.strip("/").split("/") if p]
        owner, repo = parts[0], parts[1].removesuffix(".git")
        return f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
    return src.url


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _site(host: str) -> str:
    return ".".join(host.split(".")[-2:])


def _denied(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in DENIED_HOSTS)


def _result(src: Source, status: str, reason: str, *, path: Path | None = None,
            body: bytes = b"", sha: str = "") -> Result:
    return Result(src.id, status, reason, path, len(body), sha)


def _wait_for_host(host: str, gap_s: float) -> None:
    last = _last_hit.get(host)
    if last is not None:
        wait = gap_s - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_hit[host] = time.monotonic()


def _robots_refusal(url: str) -> str | None:
    """None if robots.txt allows the URL, else the reason to refuse."""
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(origin + "/robots.txt",
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                rp.parse(resp.read(1024 * 1024).decode("utf-8", errors="replace").splitlines())
            _robots[origin] = rp
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                _robots[origin] = None  # no robots.txt: everything is allowed
            else:
                return f"robots.txt could not be read (HTTP {exc.code}), so what is allowed is unknown"
        except (urllib.error.URLError, OSError) as exc:
            return f"robots.txt could not be read ({type(exc).__name__}: {exc})"
    rp = _robots[origin]
    if rp is None or rp.can_fetch(USER_AGENT, url):
        return None
    return "robots.txt disallows this path"


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def fetch(src: Source, *, store: Path | None = None, gap_s: float | None = None) -> Result:
    store = default_store() if store is None else store
    gap = HOST_GAP_S if gap_s is None else gap_s
    if not src.free:
        return _result(src, "refused", "not free: a paid source is never downloaded")
    host = _hostname(src.url)
    if _denied(host):
        return _result(src, "refused", f"host {host} is a denied pirate or mirror host")
    url = resolve(src)
    refusal = _robots_refusal(url)
    if refusal:
        return _result(src, "refused", refusal)

    body: bytes | None = None
    last_error = ""
    for attempt in range(1, RETRIES + 1):
        _wait_for_host(host, gap)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                final_host = _hostname(resp.geturl())
                if _site(final_host) != _site(host):
                    return _result(src, "refused",
                                   f"redirected to a different site: {resp.geturl()}")
                body = resp.read(MAX_BYTES + 1)
            break
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code < 500 and exc.code != 429:
                return _result(src, "failed", last_error)
        except (urllib.error.URLError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < RETRIES:
            time.sleep(RETRY_SLEEP_S)
    if body is None:
        return _result(src, "failed", f"{last_error} after {RETRIES} attempts")
    if len(body) > MAX_BYTES:
        return _result(src, "refused", f"body is over {MAX_BYTES} bytes", body=body)

    sha = hashlib.sha256(body).hexdigest()
    index_path = store / "index.json"
    index = _load_json(index_path, {})
    owner = index.get(sha)
    if owner and owner != src.id:
        return _result(src, "duplicate", f"same bytes as {owner}", body=body, sha=sha)

    raw = store / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    path = raw / f"{src.id}{EXT[src.kind]}"
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(body)
    os.replace(tmp, path)
    index[sha] = src.id
    _write_json(index_path, index)
    return _result(src, "saved", "", path=path, body=body, sha=sha)


def run(sources: list[Source], store: Path | None = None, only: str | None = None) -> dict:
    """Fetch every source (or only the one named by `only`) and write progress.json.

    progress.json keeps every result already recorded, so redoing one source
    never erases the others. The counts cover the sources passed in.
    """
    store = default_store() if store is None else store
    store.mkdir(parents=True, exist_ok=True)
    progress_path = store / "progress.json"
    recorded = _load_json(progress_path, {"results": {}})
    for src in sources:
        if only is not None and src.id != only:
            continue
        r = fetch(src, store=store)
        recorded["results"][src.id] = {
            "url": src.url, "status": r.status, "reason": r.reason,
            "bytes": r.bytes, "sha256": r.sha256,
            "path": str(r.path) if r.path else "",
        }
        _write_json(progress_path, recorded)

    wanted = {s.id: s for s in sources}
    counts = {"saved": 0, "refused": 0, "failed": 0, "duplicate": 0, "not_run": 0}
    problems: list[dict] = []
    for sid, src in wanted.items():
        row = recorded["results"].get(sid)
        if row is None:
            counts["not_run"] += 1
            problems.append({"id": sid, "url": src.url, "status": "not_run",
                             "reason": "not fetched yet"})
            continue
        counts[row["status"]] += 1
        if row["status"] != "saved":
            problems.append({"id": sid, "url": src.url, "status": row["status"],
                             "reason": row["reason"]})
    progress = {"total": len(wanted), **counts, "problems": problems}
    return progress
