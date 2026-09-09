"""Results posted STRAIGHT to this PC while the run is still going.

The operator, Sep 09, 2026, after asking why a finished run's rows take an hour
to appear: *"why not immediately put the results in my pc"*, then *"i want it
open then, i want you to post the result immediately to my pc"*.

Until now a GitHub machine wrote its rows into a file on GitHub, GitHub only
published that file when the machine FINISHED, this PC asked "anything done?"
every five minutes, and then spent an hour importing 6 GB. Measured Sep 09:
run 34307921614 finished at 7:32am and its 96,858,236 rows were still landing
at 10:42pm.

WHAT IS OPEN, EXACTLY — this matters, because the trading API on 8787 can place
real orders with real money and must NEVER be reachable from the internet:

* this is a SEPARATE process on its own port (8788), bound to 127.0.0.1;
* it serves exactly two things: POST /rows (write measured rows for one pair)
  and GET /up (are you there). There is no route here that reads a key, moves
  money, or touches the runner;
* the door to the internet is a Cloudflare tunnel, an OUTBOUND connection this
  PC makes. No port is opened on the router, and killing this process closes
  it. The URL changes every time;
* every request must be SIGNED with the shared secret (32 random bytes, kept in
  ~/.tradingagents/ingest_token, given to GitHub as a repository secret so it
  never appears in a log). The signature covers the path and the body, and the
  secret itself is never sent — a quick-tunnel hostname is temporary and could
  in principle be handed to somebody else, and a request that reached the wrong
  host would then have taught them nothing they can reuse. The worst a leaked
  secret could do is write backtest rows for a pair — the same thing the
  collector does;
* it stops itself after IDLE_STOP_S without a valid post, and takes the tunnel
  with it, so the door is not left open between runs.

The artifact path is UNCHANGED and still runs: a machine writes every row into
its artifact whether or not the post succeeded, and the autopilot still
collects the finished run. A pair that already landed live is refused there by
the same freshness rule that refuses any stale measurement, so nothing is
written twice. If this PC is asleep, or the tunnel drops, the run loses nothing
— only immediacy.
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOME = Path(os.path.expanduser("~/.tradingagents"))
TOKEN_FILE = HOME / "ingest_token"
URL_FILE = HOME / "ingest_url.json"
PROGRESS_FILE = HOME / "ingest_progress.json"
CF_LOG = HOME / "ingest_cf.log"
SERVE_LOG = HOME / "ingest.log"

PORT = int(os.environ.get("INGEST_PORT", "8788"))
# one pair's rows are ~2 MB gzipped (0G 1h, 27,280 rows). The cap is for a
# stranger who found the URL, not for us.
MAX_BODY = 64 * 1024 * 1024
# the door does not stay open between runs. A whole-market run is ~5 hours and
# posts constantly, so this only fires when nothing is measuring.
IDLE_STOP_S = 3 * 3600
TF_OK = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"}
COIN_OK = re.compile(r"^[A-Z0-9_.\-]{1,40}$")
CF_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

_LOCK = threading.Lock()
_LAST_OK = [0.0]


def log(msg: str) -> None:
    from tradingagents.positions_view import fmt_when

    print(f"[ingest {fmt_when(time.time())}] {msg}", flush=True)


# ------------------------------------------------------------------ secret
def token(make: bool = True) -> str:
    """The shared secret, created once. 32 random bytes as hex."""
    try:
        got = TOKEN_FILE.read_text().strip()
        if got:
            return got
    except OSError:
        pass
    if not make:
        return ""
    HOME.mkdir(parents=True, exist_ok=True)
    got = secrets.token_hex(32)
    TOKEN_FILE.write_text(got)
    with contextlib.suppress(OSError):
        os.chmod(TOKEN_FILE, 0o600)
    return got


def sign(secret: str, path: str, body: bytes = b"") -> str:
    """What proves a request came from a machine this PC started.

    The PATH is in it as well as the body, so a signature captured for one
    route cannot be replayed against another. Both sides compute it the same
    way (the shard's `post_pair` is the other one) — one formula, or the door
    silently rejects every honest machine.
    """
    return hmac.new(secret.encode(), path.encode() + body,
                    hashlib.sha256).hexdigest()


# ------------------------------------------------------------- the writing
def land(payload: bytes, run_id: str = "") -> dict:
    """Write one POST's rows into the store, under the collector's own rule.

    The body is gzipped JSONL — the very lines the shard writes into its
    artifact, so a live post and a collected artifact cannot disagree about
    what a row is.
    """
    from tradingagents import cloud_sweep as cs

    raw = gzip.decompress(payload).decode("utf-8")
    by: dict = {}
    bad = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            bad += 1
            continue
        coin, tf = str(r.get("coin") or ""), str(r.get("tf") or "")
        if not COIN_OK.match(coin) or tf not in TF_OK:
            bad += 1
            continue
        by.setdefault((coin, tf), []).append(r)
    kept = stale = rows = 0
    pairs: list = []
    for (coin, tf), buf in by.items():
        marks = [r for r in buf if r.get("pair_done")]
        got = cs.land_rows(coin, tf, [r for r in buf if not r.get("pair_done")],
                           marks=marks)
        if got == "stale":
            stale += 1
            continue
        kept += 1
        rows += len(buf) - len(marks)
        pairs.append(f"{coin} {tf}")
    _note(run_id, kept, rows, stale, pairs)
    return {"ok": True, "pairs": kept, "rows": rows, "stale": stale,
            "bad": bad, "landed": pairs}


def _note(run_id: str, kept: int, rows: int, stale: int, pairs: list) -> None:
    """What THIS PC has received, counted by this PC — the panel prints it, so
    it must be the receiver's own tally and never the sender's claim."""
    with _LOCK:
        cur = progress()
        if str(cur.get("run") or "") != str(run_id):
            cur = {"run": run_id, "pairs": 0, "rows": 0, "stale": 0}
        cur["pairs"] = int(cur.get("pairs") or 0) + kept
        cur["rows"] = int(cur.get("rows") or 0) + rows
        cur["stale"] = int(cur.get("stale") or 0) + stale
        cur["at"] = time.time()
        if pairs:
            cur["last"] = pairs[-1]
        tmp = PROGRESS_FILE.with_suffix(".json.tmp")
        try:
            HOME.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(cur))
            tmp.replace(PROGRESS_FILE)
        except OSError as exc:
            log(f"could not write the progress file: {exc}")


def progress() -> dict:
    try:
        return json.loads(PROGRESS_FILE.read_text())
    except (OSError, ValueError):
        return {}


# -------------------------------------------------------------- the server
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ingest"
    sys_version = ""

    def _say(self, code: int, body: dict) -> None:
        blob = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        with contextlib.suppress(OSError):
            self.wfile.write(blob)

    def _authed(self, body: bytes = b"") -> bool:
        secret = token(make=False)
        got = self.headers.get("X-Ingest-Sig") or ""
        # constant time: a timing oracle on a public URL is a free brute force
        return bool(secret) and hmac.compare_digest(
            sign(secret, self.path.rstrip("/") or "/", body), got)

    def do_GET(self) -> None:                                   # noqa: N802
        if self.path.rstrip("/") != "/up":
            self._say(404, {"error": "no"})
            return
        if not self._authed():
            self._say(401, {"error": "no"})
            return
        self._say(200, {"ok": True, "port": PORT})

    def do_POST(self) -> None:                                  # noqa: N802
        if self.path.rstrip("/") != "/rows":
            self._say(404, {"error": "no"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            self._say(413, {"error": f"body must be 1..{MAX_BODY} bytes"})
            return
        # READ THE BODY BEFORE JUDGING IT: the signature covers the body, and
        # a connection closed with bytes still unread is a 401 the sender sees
        # as a broken pipe instead of a refusal.
        body = self.rfile.read(n)
        if len(body) != n:
            self._say(400, {"error": "short body"})
            return
        if not self._authed(body):
            log(f"refused a post that was not signed by this PC's secret, "
                f"from {self.client_address[0]}")
            self._say(401, {"error": "no"})
            return
        try:
            got = land(body, self.headers.get("X-Run-Id") or "")
        except Exception as exc:                                # noqa: BLE001
            log(f"a post could not be written: {type(exc).__name__}: {exc}")
            self._say(500, {"error": f"{type(exc).__name__}: {exc}"[:200]})
            return
        _LAST_OK[0] = time.time()
        log(f"landed {got['pairs']} pair(s) · {got['rows']:,} row(s)"
            + (f" · {got['stale']} not newer than the store" if got["stale"] else "")
            + (f" · {', '.join(got['landed'][:3])}" if got["landed"] else ""))
        self._say(200, got)

    def log_message(self, fmt, *args):        # the default writes to stderr
        return


# -------------------------------------------------------------- the tunnel
def cloudflared() -> str:
    """Where the tunnel program is. Downloaded once into the store's own bin,
    so nothing has to be installed system-wide."""
    got = os.environ.get("CLOUDFLARED")
    if got and Path(got).exists():
        return got
    exe = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    local = HOME / "bin" / exe
    if local.exists():
        return str(local)
    from shutil import which

    return which("cloudflared") or ""


def fetch_cloudflared() -> str:
    """Download the tunnel program (~55 MB) into ~/.tradingagents/bin."""
    plat = {"nt": "windows-amd64.exe"}.get(os.name, "darwin-amd64.tgz")
    url = ("https://github.com/cloudflare/cloudflared/releases/latest/download/"
           f"cloudflared-{plat}")
    dest = HOME / "bin" / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"downloading the tunnel program from {url}")
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=300) as r, tmp.open("wb") as fh:
        while chunk := r.read(1 << 20):
            fh.write(chunk)
    tmp.replace(dest)
    with contextlib.suppress(OSError):
        os.chmod(dest, 0o755)
    return str(dest)


def _spawn_tunnel() -> tuple:
    """Start cloudflared and read the public URL out of its own output."""
    exe = cloudflared() or fetch_cloudflared()
    if not exe:
        raise RuntimeError("cloudflared is not available")
    HOME.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        CF_LOG.unlink()
    fh = CF_LOG.open("w", encoding="utf-8")
    # a PLAIN child, deliberately: detaching it would leave a public address
    # alive with nothing behind it if this process were killed hard. It dies
    # with its parent's process tree, and `stop()` kills it by pid as well.
    proc = subprocess.Popen(                                    # noqa: S603
        [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
        stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    url = ""
    for _ in range(120):                       # cloudflared takes ~5-20 s
        time.sleep(0.5)
        if proc.poll() is not None:
            raise RuntimeError(f"cloudflared exited: {_tail(CF_LOG)}")
        with contextlib.suppress(OSError):
            m = CF_URL.search(CF_LOG.read_text(encoding="utf-8", errors="replace"))
            if m:
                url = m.group(0)
                break
    if not url:
        with contextlib.suppress(Exception):
            proc.kill()
        raise RuntimeError(f"cloudflared printed no URL: {_tail(CF_LOG)}")
    return proc, url


def _tail(path: Path, n: int = 3) -> str:
    try:
        return " / ".join(path.read_text(encoding="utf-8",
                                         errors="replace").splitlines()[-n:])[:300]
    except OSError:
        return "(no log)"


# ------------------------------------------------------------------- serve
def serve() -> int:
    """The whole door: the listener, the tunnel, and the idle stop that shuts
    both. One process, so nothing is left running that this pid does not own."""
    token()                                     # make the secret if it is new
    # an earlier door that was killed hard can leave its tunnel behind: a
    # public address answering 502 for ever. Take it down before opening a new
    # one.
    old = current()
    if old and not _alive(int(old.get("pid") or 0)):
        stop()
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        log(f"port {PORT} is taken ({exc}) — another listener is already up")
        return 3
    httpd.daemon_threads = True
    try:
        proc, url = _spawn_tunnel()
    except Exception as exc:                                    # noqa: BLE001
        log(f"no tunnel: {exc}")
        httpd.server_close()
        return 4
    URL_FILE.write_text(json.dumps({"url": url, "pid": os.getpid(),
                                    "tunnel_pid": proc.pid, "at": time.time(),
                                    "port": PORT}))
    _LAST_OK[0] = time.time()
    log(f"listening on 127.0.0.1:{PORT} · public url {url}")

    def watch():
        while True:
            time.sleep(20)
            if proc.poll() is not None:
                log(f"the tunnel died ({_tail(CF_LOG)}) — closing the door; "
                    f"the machines keep writing their artifacts")
                httpd.shutdown()
                return
            if time.time() - _LAST_OK[0] > IDLE_STOP_S:
                log(f"nothing posted for {IDLE_STOP_S // 3600}h — closing the door")
                httpd.shutdown()
                return

    threading.Thread(target=watch, daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=1.0)
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(Exception):
            proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=10)
        with contextlib.suppress(Exception):
            proc.kill()
        httpd.server_close()
        with contextlib.suppress(OSError):
            URL_FILE.unlink()
        log("closed")
    return 0


# ----------------------------------------------------------- the PC's side
def _alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}"],  # noqa: S603,S607
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def current() -> dict:
    try:
        return json.loads(URL_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _doh(host: str) -> str:
    """The address of `host`, asked of Cloudflare's resolver over HTTPS.

    Measured on this PC, Sep 09, 2026 11:15pm: the router's resolver
    (globebroadband.net) answers "Non-existent domain" for a fresh
    *.trycloudflare.com name that 1.1.1.1 resolves in milliseconds. GitHub's
    machines resolve it fine — this is only so the door can be PROVEN from
    here before its address is handed to twenty of them.
    """
    req = urllib.request.Request(
        f"https://cloudflare-dns.com/dns-query?name={host}&type=A",
        headers={"Accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        for a in (json.loads(r.read().decode()).get("Answer") or []):
            if a.get("type") == 1 and a.get("data"):
                return str(a["data"])
    return ""


def _up_over_doh(url: str, timeout: float) -> tuple:
    """GET /up at an address this machine's resolver will not look up: resolve
    it elsewhere, then speak TLS to that address under the real hostname (the
    certificate and Cloudflare's routing both key on the name, not the IP)."""
    import http.client
    import socket
    import ssl

    host = url.split("//", 1)[-1].split("/", 1)[0]
    ip = _doh(host)
    if not ip:
        return 0, "the name does not resolve anywhere"
    sock = socket.create_connection((ip, 443), timeout=timeout)
    ssock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    conn = http.client.HTTPConnection(host, timeout=timeout)
    conn.sock = ssock
    try:
        conn.request("GET", "/up", headers={"Host": host,
                                            "X-Ingest-Sig": sign(token(), "/up")})
        r = conn.getresponse()
        return r.status, r.read().decode() or "{}"
    finally:
        conn.close()


def reachable(url: str, timeout: float = 20.0) -> str:
    """Ask the public URL, from here, whether the door answers. Hand a URL to
    twenty machines only after it has been proven end to end."""
    req = urllib.request.Request(
        url.rstrip("/") + "/up",
        headers={"X-Ingest-Sig": sign(token(), "/up")})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, body = r.status, r.read().decode() or "{}"
    except urllib.error.HTTPError as exc:
        return f"the url answered {exc.code}"
    except Exception as exc:                                    # noqa: BLE001
        # a name this machine's own resolver refuses is not a shut door
        if "getaddrinfo" not in str(exc) and "Name or service" not in str(exc):
            return f"{type(exc).__name__}: {str(exc)[:80]}"
        try:
            status, body = _up_over_doh(url, timeout)
        except Exception as exc2:                               # noqa: BLE001
            return f"{type(exc2).__name__}: {str(exc2)[:80]}"
    if status != 200:
        return f"the url answered {status} {str(body)[:60]}"
    try:
        return "" if json.loads(body).get("ok") else "the url answered something else"
    except ValueError:
        return "the url answered something that is not ours"


def sync_secret(slug: str = "") -> str:
    """Give GitHub the secret the door is actually using, when it has changed.

    The machines read it from `secrets.INGEST_TOKEN`, so a token created or
    rotated here and not pushed means every post comes back 401 — the shard
    turns posting off and the whole run silently falls back to artifacts. The
    fingerprint of what was last pushed is kept beside the token, so this costs
    one `gh` call the first time and nothing after.
    """
    import hashlib

    from tradingagents import cloud_sweep as cs

    tok = token()
    want = hashlib.sha256(tok.encode()).hexdigest()[:16]
    seen = HOME / "ingest_secret.sha"
    with contextlib.suppress(OSError):
        if seen.read_text().strip() == want:
            return ""
    try:
        cs._gh("secret", "set", "INGEST_TOKEN", "--repo", slug or cs.repo_slug(),
               "--body", tok)
    except Exception as exc:                                    # noqa: BLE001
        return f"could not give GitHub the secret: {str(exc)[:120]}"
    with contextlib.suppress(OSError):
        seen.write_text(want)
    log("GitHub now has the door's secret (repository secret INGEST_TOKEN)")
    return ""


def ensure(*, wait_s: float = 90.0) -> dict:
    """Make sure the door is open, and return its public url.

    Never raises: a dispatch must go ahead without live posting rather than
    fail, because the artifact path still carries every row.
    """
    # NEVER during a test run. These open a real address on the internet and
    # spawn two processes; a suite that imported the dispatch by accident would
    # do both, on somebody's laptop, with no way to tell it happened.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"url": "", "why": "not opened during tests", "started": False}
    cur = current()
    if cur.get("url") and _alive(int(cur.get("pid") or 0)):
        why = reachable(cur["url"])
        if not why:
            return {"url": cur["url"], "why": "", "started": False}
        log(f"the open door did not answer ({why}) — starting a new one")
        stop()
    if not cloudflared():
        try:
            fetch_cloudflared()
        except Exception as exc:                                # noqa: BLE001
            return {"url": "", "why": f"no tunnel program: {exc}",
                    "started": False}
    HOME.mkdir(parents=True, exist_ok=True)
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                                   | subprocess.DETACHED_PROCESS)       # type: ignore[attr-defined]
    fh = SERVE_LOG.open("a", encoding="utf-8")
    subprocess.Popen([sys.executable, "-m", "tradingagents.live_ingest", "serve"],  # noqa: S603
                     stdout=fh, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, cwd=str(Path(__file__).parent.parent),
                     **kwargs)
    end = time.time() + wait_s
    while time.time() < end:
        time.sleep(1.0)
        cur = current()
        if cur.get("url"):
            why = reachable(cur["url"])
            if not why:
                return {"url": cur["url"], "why": "", "started": True}
    return {"url": "", "why": f"the door did not open in {int(wait_s)}s "
                              f"({_tail(SERVE_LOG)})", "started": True}


def stop() -> dict:
    cur = current()
    for key in ("tunnel_pid", "pid"):
        pid = int(cur.get(key) or 0)
        if pid and _alive(pid):
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],  # noqa: S603,S607
                               capture_output=True)
            else:
                with contextlib.suppress(OSError):
                    os.kill(pid, 15)
    with contextlib.suppress(OSError):
        URL_FILE.unlink()
    return {"stopped": bool(cur)}


def status() -> dict:
    cur = current()
    up = bool(cur.get("url")) and _alive(int(cur.get("pid") or 0))
    return {"open": up, "url": cur.get("url") or "", "since": cur.get("at"),
            **({"progress": progress()} if up else {})}


def main(argv: list | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    what = args[0] if args else "status"
    if what == "serve":
        return serve()
    if what == "up":
        print(json.dumps(ensure()))
        return 0
    if what == "stop":
        print(json.dumps(stop()))
        return 0
    if what == "token":
        print(token())
        return 0
    print(json.dumps(status()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
