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


class ClaimBoard:
    """First shard to create a coin's claim file owns that coin.

    WHY: the shards used to take a fixed slice each (`syms[SHARD::SHARDS]`) and
    EXIT when it was done. On run 34004227228 (Sep 06, 2026) four machines sat
    idle 12-21 minutes while the slowest was at 30 of 52 coins — the slices are
    equal in COUNT but not in WORK, so the run always ends on the unluckiest
    machine. The operator: *"did not i mentioned if the machine is 100% take a
    new job"*.

    The primitive is GitHub's contents API: a PUT that sends NO `sha` only
    CREATES — if the file already exists it answers 422. That makes creating
    `claims/run-<id>/<coin>.json` an atomic compare-and-swap, so exactly one
    shard wins each coin and a duplicate measurement (the collector APPENDS a
    re-seen pair — the operator's "no duplicate") cannot happen.

    Claims are namespaced by run id, so a new run starts with a clean board.
    Reads go over GIT (`fetch` + `ls-tree`), which spends no API budget — the
    same lesson as the progress panel, which the secondary rate limit blinded
    for hours on Sep 02, 2026 when it read through the API.
    """

    def __init__(self):
        self.repo = os.environ.get("GITHUB_REPOSITORY", "")
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.run = os.environ.get("GITHUB_RUN_ID", "0")
        self.shard = int(os.environ.get("SHARD", "0"))
        self.attempt = int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
        self.dir = f"claims/run-{self.run}"
        self.enabled = bool(self.repo and self.token)

    def taken(self) -> set:
        """Coins already claimed, read over git. Best-effort: an empty answer
        never blocks a claim — the PUT's own 422 is the real lock."""
        import subprocess

        try:
            subprocess.run(["git", "fetch", "--quiet", "--depth=1", "origin",
                            BRANCH], capture_output=True, timeout=60)
            out = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD",
                 "--", self.dir], capture_output=True, text=True,
                timeout=30).stdout
        except Exception:
            return set()
        got = set()
        for line in out.splitlines():
            name = line.rsplit("/", 1)[-1]
            if name.endswith(".json"):
                got.add(name[:-5])
        return got

    def claim(self, coin: str):
        """Try to own `coin`. True = mine. False = someone else's.
        None = the BOARD is unreachable — the caller must stop claiming, never
        guess: measuring an unclaimed-looking coin twice writes duplicate rows.
        """
        url = (f"{API}/repos/{self.repo}/contents/{self.dir}/{coin}.json")
        payload = {"shard": self.shard, "attempt": self.attempt,
                   "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        body = {"message": f"claim: shard {self.shard} takes {coin}",
                "content": __import__("base64").b64encode(
                    json.dumps(payload).encode()).decode(),
                "branch": BRANCH}
        # SIX attempts with jitter, because contention is the NORMAL case at
        # t=0: twenty shards commit their first claim to one branch ref in the
        # same second, and every collision is a 409. Three tries was enough to
        # fail a healthy shard out of claiming three seconds into the run.
        import random

        for attempt in range(6):
            try:
                _req("PUT", url, self.token, body)
                return True
            except urllib.error.HTTPError as exc:
                if exc.code in (409,):
                    # branch head moved under the create — not a lost claim,
                    # just contention on the ref. Try again.
                    time.sleep(0.5 + attempt + random.random())
                    continue
                if exc.code != 422:
                    time.sleep(0.5 + attempt + random.random())
                    continue
                # 422: the file exists. Usually another shard — but also MY OWN
                # claim when a create's response was lost on the wire, and my
                # attempt-1 claim when this job is a RE-RUN of a failed shard
                # (its coins died with it and nobody else will take them).
                try:
                    cur = _req("GET", f"{url}?ref={BRANCH}", self.token)
                    import base64 as _b64

                    owner = json.loads(_b64.b64decode(
                        (cur.get("content") or "").encode()))
                except Exception:
                    return False
                if int(owner.get("shard", -1)) != self.shard:
                    return False
                if int(owner.get("attempt", 0)) >= self.attempt:
                    return True                    # my own claim, lost response
                # my claim from a previous attempt: retake it (CAS on sha)
                body["sha"] = cur.get("sha")
                body["message"] = (f"claim: shard {self.shard} retakes {coin} "
                                   f"(attempt {self.attempt})")
                try:
                    _req("PUT", url, self.token, body)
                    return True
                except Exception:
                    return False
            except Exception:
                time.sleep(1.0 + attempt)
        return None


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
