"""Keep the runner up: a macOS LaunchAgent that restarts it when it dies.

Bought with a real outage. On 2026-08-22 the runner died at 05:33 from a
fatal OSError (the disk had 2.6 GB left), and nothing noticed for three
hours: two positions closed at the exchange on their resting brackets, and
neither exit reached the ledger until the runner was restarted by hand.

Why launchd and not a watchdog thread: a watchdog inside the UI or the API
dies with them, and the runner has to outlive both. launchd is already
running, restarts a job seconds after it exits, and survives logout/reboot.

Why a want-flag instead of KeepAlive=true: KeepAlive restarts a job the
operator deliberately stopped. `KeepAlive: {PathState: {<WANT_PATH>: true}}`
means "keep it up WHILE the operator wants it up" — STOP removes the file
and nothing fights the decision.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.tradingagents.runner"
PLIST = Path(os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist"))
ROOT = Path(__file__).resolve().parent.parent
LOG = Path(os.path.expanduser("~/.tradingagents/supervisor.log"))
# a crash loop must not spin: launchd waits this long between restarts
THROTTLE_SECONDS = 30
# below this the runner refuses to start rather than dying mid-write
MIN_FREE_MB = 500


def plist_body(python: str | None = None) -> dict:
    import tradingagents.auto_trader as at

    return {
        "Label": LABEL,
        "ProgramArguments": [python or sys.executable, "-m",
                             "tradingagents.auto_trader", "run"],
        "WorkingDirectory": str(ROOT),
        # restart it whenever it dies, but ONLY while the operator wants it up
        "KeepAlive": {"PathState": {str(at.WANT_PATH): True}},
        "ThrottleInterval": THROTTLE_SECONDS,
        # NOT RunAtLoad: loading the agent while the flag was absent started a
        # SECOND runner beside a healthy one (2026-08-22) — two runners double
        # every trade. KeepAlive's PathState starts it when the flag appears,
        # which is the only condition that should ever start it.
        "RunAtLoad": False,
        "StandardOutPath": str(LOG),
        "StandardErrorPath": str(LOG),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }


def installed() -> bool:
    return PLIST.exists()


def loaded() -> bool:
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:                                          # noqa: BLE001
        return False
    return LABEL in out


def free_mb() -> int:
    st = os.statvfs(os.path.expanduser("~"))
    return int(st.f_bavail * st.f_frsize / 1_000_000)


def status() -> dict:
    import tradingagents.auto_trader as at

    return {"installed": installed(), "loaded": loaded(),
            "wants_runner": at.wants_runner(), "pid": at.runner_pid(),
            "label": LABEL, "plist": str(PLIST), "log": str(LOG),
            "throttle_seconds": THROTTLE_SECONDS,
            "free_mb": free_mb(), "min_free_mb": MIN_FREE_MB,
            "disk_ok": free_mb() >= MIN_FREE_MB}


def install(python: str | None = None) -> dict:
    """Write and load the agent. Idempotent."""
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(plist_body(python)))
    subprocess.run(["launchctl", "unload", str(PLIST)],
                   capture_output=True, timeout=20)
    got = subprocess.run(["launchctl", "load", str(PLIST)],
                         capture_output=True, text=True, timeout=20)
    return {"ok": got.returncode == 0, "stderr": got.stderr.strip(),
            **status()}


def uninstall() -> dict:
    subprocess.run(["launchctl", "unload", str(PLIST)],
                   capture_output=True, timeout=20)
    PLIST.unlink(missing_ok=True)
    return status()
