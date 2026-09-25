"""THE FULL CSV FROM A COMMAND WINDOW — progress on screen, file in G:\\Download.

The operator, Sep 25, 2026: *"Instead of downloading via browser, can i see
progress via cmd then wright it in my g drive/download folder? The format
should br yyyy-mm-dd/time"*.

    G:\\analyzer-x\\download_csv.bat --store v2 --min-winrate 85 --tp-over-sl --days 30

It is the SAME job the browser's "build the full CSV" button starts
(`db_jobs` kind `export` / `export_v2`, body in `full_export.run`), never a
second copy of it: one filter is built at a time, the screen's spinner and
stop button see a build started here, and a build already running for the
same filter is WATCHED, not started twice. When it finishes, the file is put
at

    G:\\Download\\2026-09-25\\8-03pm v2-full-strategies-wr85-...csv

— a folder per day (yyyy-mm-dd, the operator's own words for a FOLDER name;
the project's printed dates stay `Sep 25, 2026 8:03pm`), and the time it
finished in front of the name (a colon is not allowed in a Windows file name,
so `8:03pm` becomes `8-03pm`). The finished file stays where the browser's
download link reads it too, and G:\\Download gets a COPY — never a hard link:
a linked file open in Excel cannot be deleted, and the next build of the same
filter replaces its file by deleting it, so one open spreadsheet would have
failed a two-hour build at its last step.

Ctrl+C asks the build to stop. A finished re-check is kept, so running the
same command again only writes the file.

The panel prints the exact command for the filter on screen
(`command_for`), so nobody has to type these options by hand.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BAT = REPO / "download_csv.bat"
# the operator's folder (Sep 25, 2026: "my g drive/download folder")
DOWNLOAD_DIR = Path(os.environ.get("TA_DOWNLOAD_DIR") or r"G:\Download")
# an Excel sheet holds at most this many lines, header included
EXCEL_ROWS = 1_048_576

# option -> spec key, and what the option takes. The ONE list: the parser
# and `command_for` both read it, so a filter can never be written by one and
# refused by the other.
_VALUE_OPTS = {
    "coin": str, "tf": str, "signal": str, "asset": str, "sizing": str,
    "group": str, "row_id": str, "min_trades": int, "min_winrate": float,
    "max_tp": float, "max_sl": float, "min_tp": float, "min_sl": float,
    "measured_days": int, "days": int, "sort": str,
}
_FLAG_OPTS = ("profitable", "tp_over_sl")


def _opt(key: str) -> str:
    return "--" + key.replace("_", "-")


def parser() -> argparse.ArgumentParser:
    from tradingagents import full_export as fx

    p = argparse.ArgumentParser(
        prog="download_csv",
        description="Build the full CSV of a Stored strategies filter, show "
                    f"its progress here, and put it in {DOWNLOAD_DIR}.")
    p.add_argument("--store", choices=("v1", "v2"), default="v2",
                   help="Backtest v1 or Backtest v2 (default v2)")
    for key, kind in _VALUE_OPTS.items():
        p.add_argument(_opt(key), dest=key, type=kind, default=None)
    for key in _FLAG_OPTS:
        p.add_argument(_opt(key), dest=key, action="store_true")
    order = p.add_mutually_exclusive_group()
    order.add_argument("--desc", dest="desc", action="store_const", const=True)
    order.add_argument("--asc", dest="desc", action="store_const", const=False)
    p.add_argument("--out", default=str(DOWNLOAD_DIR),
                   help=f"the folder the day folders go in (default {DOWNLOAD_DIR})")
    assert set(_VALUE_OPTS) | set(_FLAG_OPTS) >= set(fx.FILTER_KEYS), \
        "a filter the full CSV takes has no option here"
    return p


def spec_from(args: argparse.Namespace) -> dict:
    from tradingagents import full_export as fx

    raw = {k: getattr(args, k) for k in (*_VALUE_OPTS, *_FLAG_OPTS)}
    raw["desc"] = args.desc
    return fx.clean_spec(raw)


def command_for(spec: dict, store: str) -> str:
    """The exact command that builds THIS filter's full CSV — what the panel
    prints beside the button. Round-trips through `parser()` to the same
    `full_export.key_of` (tests/test_download_csv_from_cmd.py)."""
    from tradingagents import full_export as fx

    spec = fx.clean_spec(spec)
    parts = [f'"{BAT}"' if " " in str(BAT) else str(BAT), "--store", store]
    for key in _VALUE_OPTS:
        v = spec.get(key)
        if key in ("sort",) and v == "profit":
            continue                       # the default, said by leaving it out
        if key == "days" and not v:
            continue
        if v is None or v == "" or v == 0:
            continue
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        text = str(v)
        parts += [_opt(key), f'"{text}"' if (" " in text or not text) else text]
    parts += [_opt(k) for k in _FLAG_OPTS if spec.get(k)]
    if spec.get("desc") is not None:
        parts.append("--desc" if spec["desc"] else "--asc")
    return " ".join(parts)


def dated_target(out_dir: Path, name: str, when: float) -> Path:
    """<out>\\yyyy-mm-dd\\<time> <name>, never over an earlier file."""
    import datetime as _dt

    from tradingagents.positions_view import fmt_when

    d = _dt.datetime.fromtimestamp(when)
    day = out_dir / f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
    # the time exactly as every screen prints it (`8:03pm`), from the one
    # formatter — only the colon, which Windows refuses in a name, changes
    clock = fmt_when(when).rsplit(" ", 1)[-1].replace(":", "-")
    target = day / f"{clock} {name}"
    n = 2
    while target.exists():
        target = day / f"{clock} ({n}) {name}"
        n += 1
    return target


def place(src: Path, target: Path) -> None:
    """Copy the finished file to `target`, whole or not at all: into a
    `.part` beside it, renamed only once every byte is there, so a copy cut
    short never sits in the folder looking like the file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    try:
        shutil.copyfile(src, part)
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)


def _bar(frac: float, width: int = 24) -> str:
    frac = max(0.0, min(1.0, frac))
    full = int(round(frac * width))
    return "[" + "#" * full + "-" * (width - full) + "]"


def _left(seconds) -> str:
    if seconds is None or seconds < 0:
        return ""
    m = int(seconds // 60)
    if m >= 60:
        return f"about {m // 60} h {m % 60:02d} min left"
    return f"about {max(1, m)} min left"


class Screen:
    """One line that rewrites itself; a new line when the phase changes."""

    def __init__(self, out=None):
        self.out = out or sys.stdout
        self.phase = None
        self.width = 0
        self.seen: list = []           # (time, done) in this phase, for a pace

    def show(self, st: dict, now: float) -> str:
        phase = str(st.get("phase") or st.get("now") or "starting")
        done, total = int(st.get("done") or 0), int(st.get("total") or 0)
        if phase != self.phase:
            if self.phase is not None:
                self.out.write("\n")
            self.phase, self.width, self.seen = phase, 0, []
        self.seen = [*self.seen, (now, done)][-120:]
        eta = st.get("eta_s")
        if eta is None and len(self.seen) >= 2 and total:
            (t0, d0), (t1, d1) = self.seen[0], self.seen[-1]
            if t1 > t0 and d1 > d0:
                eta = (total - d1) / ((d1 - d0) / (t1 - t0))
        if total:
            line = (f"{phase:<18} {_bar(done / total)} {100.0 * done / total:5.1f}%  "
                    f"{done:,} of {total:,} rows  {_left(eta)}")
        else:
            line = f"{phase}  {st.get('now') or ''}"
        pad = max(0, self.width - len(line))
        self.out.write("\r" + line + " " * pad)
        self.out.flush()
        self.width = len(line)
        return line

    def say(self, text: str) -> None:
        if self.phase is not None:
            self.out.write("\n")
            self.phase = None
        self.out.write(text + "\n")
        self.out.flush()


def run(spec: dict, store: str, out_dir: Path, *, poll_s: float = 1.0,
        screen: Screen | None = None, clock=time.time, sleep=time.sleep) -> int:
    """Start (or join) the build, show it, place the file. Returns an exit
    code: 0 done, 1 failed, 2 another filter is being built, 130 stopped."""
    from tradingagents import db_jobs as dj, full_export as fx
    from tradingagents.positions_view import fmt_when

    scr = screen or Screen()
    kind = "export_v2" if store == "v2" else "export"
    key = fx.key_of(spec)
    st = dj.status(kind)
    if st.get("running"):
        if st.get("key") and st.get("key") != key:
            scr.say("Another filter's full CSV is being built right now:\n"
                    f"  {st.get('key')}\n"
                    "Only one is built at a time. Wait for it, or press its stop "
                    "button on the screen, then run this again.")
            return 2
        scr.say(f"This filter's full CSV is already being built (started "
                f"{fmt_when(st.get('started') or clock())}) - showing its progress.")
        since = float(st.get("started") or 0)
    else:
        since = clock() - 2
        try:
            dj.start(kind, spec)
        except dj.JobBusy as exc:
            scr.say(f"Cannot start: {exc}")
            return 2
        scr.say(f"Building the full CSV ({'Backtest v2' if store == 'v2' else 'Backtest v1'}), "
                f"started {fmt_when(clock())}. Ctrl+C stops it.")
    stopping = False
    while True:
        try:
            sleep(poll_s)
            st = dj.status(kind)
            # the PREVIOUS build's finished file must never read as this one
            if float(st.get("started") or 0) < since - 1:
                continue
            if st.get("key") and st.get("key") != key:
                scr.say("The build running now is for another filter; stopped watching.")
                return 2
            if st.get("running"):
                scr.show(st, clock())
                continue
            if st.get("stopped"):
                scr.say(f"Stopped. {st.get('note') or ''}".rstrip())
                return 130
            if st.get("error") or not st.get("file"):
                scr.say(f"The build FAILED: {st.get('error') or st.get('note') or 'no file was written'}")
                return 1
            break
        except KeyboardInterrupt:
            if stopping:
                scr.say("Leaving it to stop by itself.")
                return 130
            stopping = True
            dj.request_stop(kind)
            scr.say("Stopping... (a finished re-check is kept, so running this "
                    "again only writes the file). Ctrl+C again to stop watching.")
    src = fx.export_dir(store) / str(st["file"])
    if not src.exists():
        scr.say(f"The build finished but its file is missing: {src}")
        return 1
    target = dated_target(Path(out_dir), src.name, float(st.get("finished") or clock()))
    scr.say(f"Copying it to {target.parent} ...")
    try:
        place(src, target)
    except OSError as exc:
        # a full or missing G:, say so - and where the finished file IS
        scr.say(f"Could not copy it there ({type(exc).__name__}: {exc}). "
                f"The finished file is here: {src}")
        return 1
    rows = int(st.get("done") or 0)
    scr.say(f"Done: {rows:,} row(s) of {int(st.get('total') or 0):,} matched, "
            f"{src.stat().st_size / 1e6:,.0f} MB.")
    scr.say(f"Saved to {target}")
    if st.get("floor_note"):
        scr.say(str(st["floor_note"]))
    if rows + 1 > EXCEL_ROWS:
        scr.say(f"Note: Excel opens only the first {EXCEL_ROWS:,} lines of a "
                f"sheet; this file has {rows + 1:,}. Every row is in the file.")
    return 0


def main(argv: list[str] | None = None) -> int:
    # the job's own words carry dashes and dots a code-page console cannot
    # print; a character it cannot show must never end the watch
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")
    args = parser().parse_args(argv)
    return run(spec_from(args), args.store, Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
