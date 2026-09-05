"""The badge must say WHICH run this is, from the first tick to the last.

Sep 05, 2026: RESOLVE PENDING was pressed and its progress carried no `mode` at
all — `{"running": true, "mode": null, "done": 153, "total": 5152}`. The badge
reads `dl.mode` and falls through to "downloading", so a RESOLVE run wore a
DOWNLOAD label for its whole hour. A correct value under a false caption is the
failure `label-must-match-data` exists to catch.

Two places were missing it, not one: the per-pair tick inside `_run_download`,
and the stub `start()` writes before the job has measured anything — which
covers the seconds right after the click, when the operator is actually looking.
"""
import inspect
import io
import re

from tradingagents import db_jobs as dj

SCREEN = "webapp/src/components/candles/DownloadScreen.tsx"


def test_every_live_progress_tick_carries_the_mode():
    src = inspect.getsource(dj._run_download)
    ticks = [m for m in re.finditer(r'_write\(f\["progress"\], \{"running": True',
                                    src)]
    assert ticks, "the live tick moved"
    for m in ticks:
        chunk = src[m.start():m.start() + 400]
        assert '"mode"' in chunk, f"a live tick with no mode:\n{chunk[:200]}"


def test_the_stub_written_at_start_carries_it_too():
    """The seconds right after the click are when the operator is looking."""
    src = inspect.getsource(dj.start)
    assert '"mode"' in src


def test_every_mode_the_job_accepts_has_a_badge():
    """A mode with no case silently borrows another mode's label."""
    job = inspect.getsource(dj._run_download)
    modes = set(re.findall(r'mode == "(\w+)"', job)) | {"download"}
    screen = io.open(SCREEN, encoding="utf-8").read()
    i = screen.index("dl.mode ===")
    frag = screen[i - 200:i + 500]
    for m in modes:
        if m == "download":
            assert '"downloading"' in frag
            continue
        assert f'dl.mode === "{m}"' in frag, f"{m} has no badge case"


def test_resolve_says_resolving_not_downloading():
    screen = io.open(SCREEN, encoding="utf-8").read()
    assert '"resolving pending"' in screen
