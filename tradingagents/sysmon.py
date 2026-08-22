"""What the machine is doing, for the progress panels.

CPU load is free and honest. TEMPERATURE IS NOT AVAILABLE without root on
Apple Silicon: `powermetrics` rejects the SMC sampler and demands superuser,
and nothing in sysctl/ioreg/pmset exposes a die temperature to a normal user.
So this module reports what it can actually read and SAYS SO when it cannot —
a plausible-looking number invented from load would be worse than a blank.
"""
from __future__ import annotations

import os
import re
import subprocess
import time

_CACHE: dict = {"at": 0.0, "value": None}
CACHE_SECONDS = 4.0          # `top` costs ~300ms; the UI polls far faster


def cpu_count() -> int:
    return os.cpu_count() or 1


def _top_sample() -> dict:
    """One `top` sample: user/sys/idle percentages. No root needed."""
    try:
        out = subprocess.run(["top", "-l", "1", "-n", "0"],
                             capture_output=True, text=True, timeout=8).stdout
    except Exception:                                          # noqa: BLE001
        return {}
    m = re.search(r"CPU usage:\s*([\d.]+)% user,\s*([\d.]+)% sys,\s*([\d.]+)% idle",
                  out)
    if not m:
        return {}
    user, sysp, idle = (float(m.group(i)) for i in (1, 2, 3))
    return {"user": user, "sys": sysp, "idle": idle,
            "busy": round(100.0 - idle, 1)}


def _thermal() -> dict:
    """Thermal pressure, if macOS has recorded any. Never a made-up degree.

    `pmset -g therm` prints limits only while the machine is actually being
    held back; with nothing recorded the honest answer is "no throttling
    reported", not a temperature.
    """
    info = {"available": False, "why": "temperature needs root on this Mac "
                                       "(powermetrics is superuser-only on "
                                       "Apple Silicon)",
            "throttled": False, "pressure": None, "speed_limit": None}
    try:
        out = subprocess.run(["pmset", "-g", "therm"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:                                          # noqa: BLE001
        return info
    m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", out)
    if m:
        limit = int(m.group(1))
        info.update(available=True, speed_limit=limit,
                    throttled=limit < 100,
                    pressure="throttling" if limit < 100 else "nominal",
                    why="")
    elif "No thermal warning level has been recorded" in out:
        info.update(available=True, pressure="nominal", throttled=False,
                    why="macOS reports no thermal warning; it exposes a "
                        "temperature only to root")
    return info


def snapshot(force: bool = False) -> dict:
    """CPU load and thermal state, cached for a few seconds."""
    now = time.time()
    if not force and _CACHE["value"] and now - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["value"]
    load1, load5, load15 = os.getloadavg()
    n = cpu_count()
    got = {"cores": n,
           "load1": round(load1, 2), "load5": round(load5, 2),
           "load15": round(load15, 2),
           # load per core: 1.0 means every core has a runnable process
           "load_per_core": round(load1 / n, 2),
           "thermal": _thermal(), **_top_sample()}
    _CACHE.update(at=now, value=got)
    return got
