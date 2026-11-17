"""Turn the downloaded training sources into plain text.

A source with fewer than MIN_WORDS words, or with no text layer (a scanned PDF),
is marked unreadable and named with its reason. Nothing unreadable is ever
written as text, so nothing unreadable can be summarised as if it were read.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import pypdf
from pypdf import errors as pdf_errors

from tradingagents.training_fetch import default_store

MIN_WORDS = 300
SKIP_TAGS = frozenset({"script", "style", "nav", "footer", "noscript"})


@dataclass(frozen=True)
class TextResult:
    ok: bool
    words: int
    reason: str
    text: str


class _Visible(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_text(raw: str) -> str:
    parser = _Visible()
    parser.feed(raw)
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def _pdf_text(path: Path) -> str:
    reader = pypdf.PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract(path: Path) -> TextResult:
    try:
        if path.suffix.lower() == ".pdf":
            text = _pdf_text(path)
        else:
            text = _html_text(path.read_text(encoding="utf-8", errors="replace"))
    except pdf_errors.PdfReadError as exc:
        return TextResult(False, 0, f"PDF could not be read: {exc}", "")
    text = " ".join(text.split())
    words = len(text.split())
    if path.suffix.lower() == ".pdf" and words == 0:
        return TextResult(False, 0, "no text layer (a scanned or image-only PDF)", "")
    if words < MIN_WORDS:
        return TextResult(False, words, f"only {words} words, under {MIN_WORDS} words", "")
    return TextResult(True, words, "", text)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def run(store: Path | None = None) -> dict:
    """Extract every raw download to store/text/<id>.txt and write text-progress.json."""
    store = default_store() if store is None else store
    raw = store / "raw"
    text_dir = store / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    read = 0
    unreadable = 0
    problems: list[dict] = []
    for path in sorted(raw.glob("*")) if raw.exists() else []:
        if path.suffix.lower() not in {".pdf", ".html", ".md"}:
            continue
        sid = path.stem
        out = text_dir / f"{sid}.txt"
        r = extract(path)
        if r.ok:
            tmp = out.with_suffix(".txt.part")
            tmp.write_text(r.text, encoding="utf-8")
            os.replace(tmp, out)
            read += 1
        else:
            out.unlink(missing_ok=True)
            unreadable += 1
            problems.append({"id": sid, "reason": r.reason})
    progress = {"read": read, "unreadable": unreadable, "problems": problems}
    _write_json(store / "text-progress.json", progress)
    return progress
