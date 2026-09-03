"""Let a runner say where it has got to, while it is still running.

GitHub does not serve a job's log until the job ends (`/logs` answers 404 with
BlobNotFound), and artifacts only upload at the end of a step. So a machine that
will be busy for three hours has no way to report progress — unless it writes it
somewhere itself.

Each shard PUTs one small JSON file per run onto an orphan branch:

    progress/run-<run_id>/shard-<n>.json

One file per machine means twenty machines never touch the same path, so their
writes cannot conflict with each other. The branch is orphan, so `main`'s
history stays clean.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

BRANCH = "sweep-progress"
API = "https://api.github.com"


def _req(method: str, url: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "sweep-progress",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


class Reporter:
    """Writes this shard's progress, at most once every ``every`` seconds."""

    def __init__(self, every: float = 45.0):
        self.repo = os.environ.get("GITHUB_REPOSITORY", "")
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.run = os.environ.get("GITHUB_RUN_ID", "0")
        self.shard = os.environ.get("SHARD", "0")
        self.every = every
        self._last = 0.0
        self._sha = None
        self.path = f"progress/run-{self.run}/shard-{self.shard}.json"
        self.enabled = bool(self.repo and self.token)

    def __call__(self, stage: str, done: int, total: int, rows: int = 0,
                 note: str = "", force: bool = False,
                 failed: list | None = None) -> None:
        """stage is 'screening' or 'testing' — what the machine is doing now.

        `failed` NAMES the pairs this shard lost. It used to be a count inside
        `note` ("3 pair(s) lost"), which sends the reader to a runner log that
        expires — the same mistake the download job made and the operator's
        rule against it (CLAUDE.md: every pair still lost is NAMED). The
        backtest LOGS panel reads these.
        """
        if not self.enabled:
            return
        now = time.time()
        if not force and now - self._last < self.every:
            return
        self._last = now
        payload = {"shard": int(self.shard), "stage": stage, "done": done,
                   "total": total, "rows": rows, "note": note[:120],
                   "failed": [str(x)[:120] for x in (failed or [])][:200],
                   "pct": round(100 * done / total, 1) if total else 0.0,
                   "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                            time.gmtime())}
        body = {
            "message": f"progress: shard {self.shard} {stage} {done}/{total}",
            "content": __import__("base64").b64encode(
                json.dumps(payload).encode()).decode(),
            "branch": BRANCH,
        }
        if self._sha:
            body["sha"] = self._sha
        url = f"{API}/repos/{self.repo}/contents/{self.path}"
        for attempt in range(4):
            try:
                out = _req("PUT", url, self.token, body)
                self._sha = (out.get("content") or {}).get("sha")
                return
            except urllib.error.HTTPError as exc:
                if exc.code in (409, 422):
                    # someone else moved the branch head, or our sha is stale:
                    # re-read this file's sha and try again
                    try:
                        cur = _req("GET", f"{url}?ref={BRANCH}", self.token)
                        self._sha = cur.get("sha")
                        body["sha"] = self._sha
                    except Exception:
                        body.pop("sha", None)
                        self._sha = None
                    time.sleep(1.5 * (attempt + 1))
                    continue
                return                      # progress is best-effort, never fatal
            except Exception:
                return
