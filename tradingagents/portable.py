"""Everything that differs between macOS/Linux and Windows, in one module.

Why this exists (2026-08-25, the operator's Windows PC):

* `import fcntl` sat at the top of market_sweep.py and auto_trader.py. fcntl
  does not exist on Windows, so the IMPORT failed, every module that imports
  market_sweep failed with it, and `/api/storage/by-coin` answered "Storage
  unreadable" — no screen on the PC could load data at all.
* `os.kill(pid, 0)` was the "is it alive?" probe in seven modules. On Windows
  `os.kill` is TerminateProcess for any signal but CTRL_C/CTRL_BREAK — the
  probe would have KILLED the runner it was asking about.
* `os.statvfs`, `signal.SIGKILL`, `ps` and `lsof` do not exist there either.

Rule: no module outside this one names fcntl, msvcrt, statvfs, SIGKILL or
`os.kill(pid, 0)` — `tests/test_portable.py` scans for them.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

WINDOWS = os.name == "nt"
MACOS = sys.platform == "darwin"

if WINDOWS:
    import ctypes
    import msvcrt
else:
    import fcntl

# Popen kwargs that make a job outlive the process that spawned it and ignore
# its Ctrl-C. `start_new_session` is a no-op on Windows; there the equivalent
# is a new process group with no console. Spread as `**portable.DETACHED`.
DETACHED: dict = (
    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP    # type: ignore[attr-defined]
     | subprocess.DETACHED_PROCESS}                          # type: ignore[attr-defined]
    if WINDOWS else {"start_new_session": True})


def _fd(fh) -> int:
    return fh if isinstance(fh, int) else fh.fileno()


# ----------------------------------------------------------------- file locks
def lock_exclusive(fh, *, blocking: bool = True) -> None:
    """Exclusive advisory lock on an open file (object or descriptor).

    Blocks until held, or with blocking=False raises OSError at once when
    another process holds it — the same contract the flock calls had. Works
    across processes on every OS; on Windows it locks the first byte of the
    file (msvcrt locks a byte RANGE, and a range past EOF locks fine, so an
    empty lock file works).
    """
    fd = _fd(fh)
    if not WINDOWS:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if not blocking:
                raise
            time.sleep(0.05)


def unlock(fh) -> None:
    fd = _fd(fh)
    if not WINDOWS:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    os.lseek(fd, 0, os.SEEK_SET)
    with contextlib.suppress(OSError):
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


# ------------------------------------------------------------------ processes
def pid_alive(pid) -> bool:
    """True when a process with this pid exists and is ours to see.

    Never sends a signal. A pid that exists but belongs to another user was
    treated as "not alive" by every caller before this module (PermissionError
    -> False), and still is. None / garbage -> False.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if not WINDOWS:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    kernel32 = ctypes.windll.kernel32                       # type: ignore[attr-defined]
    process_query_limited_information = 0x1000
    still_active = 259
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def kill_hard(pid: int) -> None:
    """SIGKILL on unix. On Windows every os.kill is already TerminateProcess.
    Raises ProcessLookupError / PermissionError like os.kill does."""
    os.kill(pid, signal.SIGTERM if WINDOWS else signal.SIGKILL)


def child_pids(parent: int) -> list[int]:
    """Direct children of `parent`, by asking the OS's process table."""
    if WINDOWS:
        cmd = ["powershell", "-NoProfile", "-Command",
               f"Get-CimInstance Win32_Process -Filter 'ParentProcessId={int(parent)}' "
               "| Select-Object -ExpandProperty ProcessId"]
    else:
        cmd = ["ps", "-eo", "pid,ppid"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    kids: list[int] = []
    for line in out.splitlines():
        parts = line.split()
        if WINDOWS:
            if parts and parts[0].isdigit():
                kids.append(int(parts[0]))
        elif (len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()
              and int(parts[1]) == parent):
            kids.append(int(parts[0]))
    return kids


# ----------------------------------------------------------------------- disk
def load_average() -> tuple[float, float, float]:
    """The unix 1/5/15-minute load average. POSIX only — see cpu_busy_percent."""
    return os.getloadavg()


def cpu_busy_percent(sample_s: float = 0.0) -> float:
    """How busy the CPU is, 0-100. Windows has no load average, so this is the
    equivalent question: `os.getloadavg()` raised AttributeError on the
    operator's PC and /api/system answered HTTP 500 on every page load.

    Read from the OS counter (typeperf is slow; WMI's LoadPercentage is one
    call and needs nothing installed). Raises OSError when the counter cannot
    be read, so the caller can decide what to show.
    """
    if not WINDOWS:
        return min(100.0, 100.0 * load_average()[0] / max(1, (os.cpu_count() or 1)))
    import subprocess

    try:
        out = subprocess.run(
            ["wmic", "cpu", "get", "loadpercentage", "/value"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(f"could not read the CPU counter: {exc}") from exc
    for line in out.splitlines():
        if "=" in line and line.split("=")[0].strip().lower() == "loadpercentage":
            try:
                return float(line.split("=", 1)[1].strip())
            except ValueError:
                break
    raise OSError("the CPU counter returned nothing usable")


def disk_free_mb(path) -> int:
    """Free space for an unprivileged writer at `path` (or its nearest existing
    parent), in MB — the same figure statvfs's f_bavail * f_frsize gave."""
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    return int(shutil.disk_usage(str(p)).free / 1_000_000)


# --------------------------------------------------------------------- memory
# Why this exists: on 2026-08-27 the operator's PC froze twice while a sweep ran
# unattended. Not a crash -- 16 GB with 9.1 GB already held by other apps, and
# when the rest went Windows paged to a MECHANICAL disk. The sweep now sizes
# itself to what is free, which needs one number the standard library will not
# give: available physical memory. `psutil` is not a dependency of this project
# and will not become one for two syscalls.
def _ram_windows() -> tuple[float, float]:
    """(total, available) in GB from GlobalMemoryStatusEx.

    The structure is declared INSIDE the function: `ctypes` is imported at the
    top of this module only on Windows (line 32), so a class body referring to
    ctypes.Structure would raise NameError at import time on the operator's Mac
    and take every module that imports portable with it.
    """
    if not WINDOWS:
        return 0.0, 0.0
    try:
        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = _MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return 0.0, 0.0
        return (round(st.ullTotalPhys / 2**30, 2),
                round(st.ullAvailPhys / 2**30, 2))
    except Exception:
        return 0.0, 0.0


def _ram_unix() -> tuple[float, float]:
    """(total, available) in GB. MemAvailable on Linux -- the kernel's own
    estimate of what a new process can have, which is the question being asked;
    MemFree alone would read as "almost nothing" on any machine with a cache.
    macOS has no /proc, so sysctl gives the total and vm_stat the free pages."""
    try:
        vals = {}
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                k, _, rest = line.partition(":")
                vals[k.strip()] = float(rest.strip().split()[0]) / 2**20
        total = vals.get("MemTotal", 0.0)
        avail = vals.get("MemAvailable", vals.get("MemFree", 0.0))
        if total:
            return round(total, 2), round(avail, 2)
    except (OSError, ValueError, IndexError):
        pass
    try:
        import subprocess

        total = float(subprocess.run(["sysctl", "-n", "hw.memsize"],
                                     capture_output=True, text=True,
                                     timeout=5).stdout.strip()) / 2**30
        out = subprocess.run(["vm_stat"], capture_output=True, text=True,
                             timeout=5).stdout
        page = 4096.0
        free = spec = 0.0
        for line in out.splitlines():
            if "page size of" in line:
                page = float(line.split("page size of")[1].split()[0])
            if line.startswith("Pages free:"):
                free = float(line.split(":")[1].strip().rstrip("."))
            if line.startswith("Pages speculative:"):
                spec = float(line.split(":")[1].strip().rstrip("."))
        return round(total, 2), round((free + spec) * page / 2**30, 2)
    except Exception:
        return 0.0, 0.0


def ram_gb() -> tuple[float, float]:
    """(total, available) physical memory in GB, or (0.0, 0.0) if unreadable.

    Zeros mean "this machine will not say" -- callers must then leave the
    behaviour they would have had, never guess a number. Every other helper in
    this module degrades the same way.
    """
    return _ram_windows() if WINDOWS else _ram_unix()
