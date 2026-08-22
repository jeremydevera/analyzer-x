"""Background watcher that alerts when MEXC lists a new coin.

Runs independently of the web UI, so alerts keep arriving with the browser
closed. Each poll is a single ``exchangeInfo`` request covering the whole
exchange — the age filter runs locally, so cost does not grow with how many
coins qualify. At the default two-minute interval that is 720 requests a day,
far below the rate where MEXC starts returning 429.

Usage:
    python scripts/watch_mexc.py                    # poll every 2 min, beep + notify
    python scripts/watch_mexc.py --interval 300     # gentler polling
    python scripts/watch_mexc.py --once             # single check, for cron
    python scripts/watch_mexc.py --no-sound --webhook https://hooks.example/x

The baseline of known symbols is persisted, so a restart resumes silently
instead of announcing every coin on the exchange.
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.dataflows.config import get_config  # noqa: E402
from tradingagents.dataflows.mexc import (  # noqa: E402
    MexcHostUnavailable,
    MexcRateLimited,
    MexcUnavailable,
    poll_new_listings,
    upcoming_listings,
)

logger = logging.getLogger("watch_mexc")

DEFAULT_INTERVAL_SECONDS = 120
DEFAULT_MAX_AGE_HOURS = 48.0
# Ships with macOS; a short, distinctly non-musical alert.
_MAC_SOUND = "/System/Library/Sounds/Submarine.aiff"


def default_state_path() -> Path:
    return Path(get_config()["data_cache_dir"]) / "mexc-watch-state.json"


def load_state(path: Path) -> set:
    """Known symbols from a previous run, or an empty set.

    A corrupt or missing file reads as empty, which makes the next poll seed a
    fresh baseline silently rather than crash the watcher.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return set()
    symbols = data.get("symbols") if isinstance(data, dict) else None
    return set(symbols) if isinstance(symbols, list) else set()


def _read_raw(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, symbols: set, *, now: float | None = None,
               last_alert: list | None = None) -> None:
    """Persist the baseline plus a heartbeat. A write failure is never fatal.

    Every poll stamps ``last_poll_at`` and bumps ``polls`` so liveness can be
    checked from outside the process — a watcher that only spoke when something
    happened was indistinguishable from a dead one. Alert details are carried
    forward across quiet polls rather than overwritten.
    """
    stamp = time.time() if now is None else now
    previous = _read_raw(path)
    payload = {
        "symbols": sorted(symbols),
        "symbol_count": len(symbols),
        "last_poll_at": stamp,
        "polls": int(previous.get("polls", 0)) + 1,
        "last_alert_at": previous.get("last_alert_at"),
        "last_alert": previous.get("last_alert"),
        # Carried forward, or every poll would forget which listings have already
        # been announced and re-alert them until they open.
        "announced": previous.get("announced"),
    }
    if last_alert:
        payload["last_alert_at"] = stamp
        payload["last_alert"] = [c["base"] for c in last_alert]
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError as exc:
        logger.warning("Could not save watcher state: %s", exc)


def _merge_state(path: Path, updates: dict) -> None:
    """Write extra keys into the state file without disturbing the rest."""
    payload = _read_raw(path)
    payload.update(updates)
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError as exc:
        logger.warning("Could not merge watcher state: %s", exc)


# A heartbeat older than this many intervals means the process is gone rather
# than merely slow; one missed interval can just be a long request.
_STALE_INTERVALS = 2.5


def status(path: Path, *, interval: int = DEFAULT_INTERVAL_SECONDS,
           now: float | None = None) -> dict:
    """Liveness snapshot read from the state file, without touching the network."""
    stamp = time.time() if now is None else now
    raw = _read_raw(path)
    last = raw.get("last_poll_at")
    since = (stamp - last) if isinstance(last, (int, float)) else None
    return {
        "running": since is not None and since <= interval * _STALE_INTERVALS,
        "last_poll_at": last,
        "seconds_since_poll": since,
        "polls": int(raw.get("polls", 0)),
        "symbol_count": int(raw.get("symbol_count", len(raw.get("symbols") or []))),
        "last_alert_at": raw.get("last_alert_at"),
        "last_alert": raw.get("last_alert") or [],
        "state_path": str(path),
    }


def format_status(snapshot: dict) -> str:
    """One-screen summary of a watcher's state."""
    if snapshot["last_poll_at"] is None:
        return (f"Watcher: never run (no state at {snapshot['state_path']}).\n"
                f"Start it with: python scripts/watch_mexc.py")
    when = time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(snapshot["last_poll_at"]))
    verb = "running" if snapshot["running"] else "STOPPED (heartbeat stale)"
    lines = [
        f"Watcher: {verb}",
        f"  last poll   : {when} ({snapshot['seconds_since_poll']:.0f}s ago)",
        f"  polls so far: {snapshot['polls']}",
        f"  watching    : {snapshot['symbol_count']} MEXC pairs",
    ]
    if snapshot["last_alert"]:
        alert_when = time.strftime("%Y-%m-%d %H:%M:%S",
                                   time.localtime(snapshot["last_alert_at"]))
        lines.append(f"  last alert  : {', '.join(snapshot['last_alert'])} "
                     f"at {alert_when}")
    else:
        lines.append("  last alert  : none yet")
    return "\n".join(lines)


def _fmt_age(hours: float) -> str:
    if hours < 1:
        return f"{int(round(hours * 60))}m"
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def alert_text(found: list) -> tuple[str, str]:
    """``(title, body)`` for a notification."""
    noun = "listing" if len(found) == 1 else "listings"
    title = f"{len(found)} new MEXC {noun}"
    body = " · ".join(
        f"{c['base']} ({c['name']}) {_fmt_age(c['age_hours'])} old" for c in found)
    return title, body


def notify_commands(system: str, title: str, body: str, sound: bool) -> list:
    """Desktop-notification commands for ``system``, or [] when unsupported.

    Returned rather than executed so the choice is testable without spawning
    anything, and so an unsupported platform degrades to log-only instead of
    raising.
    """
    if system == "Darwin":
        # ensure_ascii=False on purpose: json.dumps would escape "·" to ·,
        # which AppleScript cannot parse ("Expected \" but found unknown token").
        # It handles literal UTF-8 fine, and json still escapes quotes/newlines.
        script = (f'display notification {json.dumps(body, ensure_ascii=False)} '
                  f'with title {json.dumps(title, ensure_ascii=False)}')
        cmds = [["osascript", "-e", script]]
        if sound and Path(_MAC_SOUND).exists():
            cmds.append(["afplay", _MAC_SOUND])
        return cmds
    if system == "Linux":
        cmds = [["notify-send", title, body]]
        if sound and shutil.which("paplay"):
            cmds.append(["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"])
        return cmds
    return []


def post_webhook(url: str, payload: dict) -> None:
    """POST the alert as JSON. Failures are logged, never fatal."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info("Webhook responded %s", resp.status)
    except OSError as exc:
        logger.warning("Webhook post failed: %s", exc)


def deliver(title: str, body: str, *, sound: bool, webhook: str | None,
            coins: list) -> None:
    """Announce an alert on every configured channel."""
    print(f"\a[{time.strftime('%Y-%m-%d %H:%M:%S')}] {title}: {body}", flush=True)
    for cmd in notify_commands(platform.system(), title, body, sound):
        try:
            subprocess.run(cmd, check=False, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Notification command %s failed: %s", cmd[0], exc)
    if webhook:
        post_webhook(webhook, {"count": len(coins), "title": title, "coins": coins})


def announcement_text(upcoming: list) -> tuple[str, str]:
    """``(title, body)`` for listings MEXC has scheduled but not opened."""
    noun = "listing" if len(upcoming) == 1 else "listings"
    title = f"{len(upcoming)} MEXC {noun} announced"
    parts = []
    for coin in upcoming:
        hours = coin.get("hours_until")
        when = f"opens in {hours:.1f}h" if hours else "open time not published"
        parts.append(f"{coin['base']} ({coin['name']}) {when}")
    return title, " · ".join(parts)


def _announce_upcoming(state_path: Path, *, sound: bool, webhook: str | None) -> None:
    """Alert on newly scheduled listings, once each.

    This is the earliest warning the exchange gives — a pair appears with
    status "2" hours before it trades — so it is worth a separate alert from the
    listing itself. Announced coins are remembered in the state file so a coin is
    not re-announced on every poll while it waits to open.
    """
    try:
        upcoming = upcoming_listings()
    except (MexcUnavailable, MexcHostUnavailable, MexcRateLimited) as exc:
        logger.warning("Upcoming-listing lookup failed: %s", exc)
        return

    raw = _read_raw(state_path)
    seen = set(raw.get("announced") or [])
    fresh = [c for c in upcoming if c["symbol"] not in seen]
    if upcoming or seen:
        _merge_state(state_path, {"announced": sorted({c["symbol"] for c in upcoming})})
    if not fresh:
        return

    title, body = announcement_text(fresh)
    deliver(title, body, sound=sound, webhook=webhook, coins=fresh)


def tick(state_path: Path, *, max_age_hours: float, sound: bool,
         webhook: str | None) -> list:
    """One poll. Returns the coins announced, and never raises on MEXC trouble."""
    known = load_state(state_path)
    try:
        found, seen = poll_new_listings(known, max_age_hours=max_age_hours)
    except (MexcUnavailable, MexcHostUnavailable, MexcRateLimited) as exc:
        # Leave the baseline alone: overwriting it during an outage would make
        # the next successful poll treat every symbol as already known.
        logger.warning("Poll failed, keeping previous baseline: %s", exc)
        return []

    save_state(state_path, seen, last_alert=found)
    _announce_upcoming(state_path, sound=sound, webhook=webhook)
    if not known:
        logger.info("Seeded baseline with %d symbols; watching for changes.",
                    len(seen))
        return []
    if not found:
        # Logged every poll so tailing the log answers "is it alive" without
        # waiting for a listing that may be hours away.
        logger.info("Polled %d symbols · no new listings", len(seen))
        return []

    title, body = alert_text(found)
    deliver(title, body, sound=sound, webhook=webhook, coins=found)
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS,
                        help="seconds between polls (default: 120)")
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS,
                        help="ignore coins older than this (default: 48)")
    parser.add_argument("--no-sound", action="store_true", help="notify silently")
    parser.add_argument("--webhook", help="POST alerts as JSON to this URL")
    parser.add_argument("--state", type=Path, default=None,
                        help="baseline file (default: under data_cache_dir)")
    parser.add_argument("--once", action="store_true",
                        help="poll once and exit, for cron")
    parser.add_argument("--status", action="store_true",
                        help="print whether a watcher is alive and when it last polled")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    state_path = args.state or default_state_path()

    if args.status:
        print(format_status(status(state_path, interval=args.interval)))
        return 0
    kwargs = {"max_age_hours": args.max_age_hours, "sound": not args.no_sound,
              "webhook": args.webhook}

    if args.once:
        tick(state_path, **kwargs)
        return 0

    logger.info("Watching MEXC every %ds · state %s", args.interval, state_path)
    try:
        while True:
            tick(state_path, **kwargs)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
