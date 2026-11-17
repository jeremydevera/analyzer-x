"""Assemble the per-source sections into one HTML digest, and check every quote.

A quote in a section is kept only if it appears in that source's text, after
whitespace and case are normalised. A quote that does not appear is reported
by its words, and its section is still shown, marked as failing the check.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from tradingagents.training_manifest import Source


def _norm(s: str) -> str:
    s = s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    return " ".join(s.lower().split())


class _Quotes(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in = False
        self._buf: list[str] = []
        self.quotes: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "blockquote":
            self._in = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "blockquote" and self._in:
            self.quotes.append(" ".join("".join(self._buf).split()))
            self._in = False

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)


def quotes_in(section_html: str) -> list[str]:
    parser = _Quotes()
    parser.feed(section_html)
    parser.close()
    return [q.strip(' "“”‘’') for q in parser.quotes
            if q.strip(' "“”‘’')]


def quote_problems(section_html: str, source_text: str) -> list[str]:
    """Quotes that do not appear in the source text. Empty means every quote holds."""
    haystack = _norm(source_text)
    return [q for q in quotes_in(section_html) if _norm(q) not in haystack]


@dataclass
class Entry:
    source: Source
    title: str
    section: str | None  # the fragment, or None when there is none
    problems: list[str] = field(default_factory=list)
    unread_reason: str = ""


def assemble(entries: list[Entry], download_summary: dict, text_summary: dict, when: str) -> str:
    """The whole HTML page. Header counts are computed from `entries`, never typed."""
    total = len(entries)
    with_section = [e for e in entries if e.section is not None]
    passed = [e for e in with_section if not e.problems]
    failed = [e for e in with_section if e.problems]
    unread = [e for e in entries if e.section is None]

    parts: list[str] = []
    parts.append(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Training materials digest</title>"
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:860px;margin:0 auto;padding:16px;color:#1d1d1f}"
        "section{border-top:1px solid #ddd;padding:12px 0}blockquote{margin:6px 0;padding:6px 12px;"
        "border-left:3px solid #999;background:#f6f6f6}.bad{color:#a40000}.note{color:#555;font-size:14px}</style>"
        "</head><body>"
    )
    parts.append(f"<h1>Training materials digest</h1><p class='note'>Built {html.escape(when)}.</p>")
    parts.append(
        "<p><b>What this is:</b> a digest of the free sources the operator was given. "
        "Each section quotes the source. The quotes were checked against the downloaded text. "
        "A section whose quote did not match is marked, not hidden.</p>"
    )
    parts.append(
        "<p><b>Counts:</b> "
        f"{total} free sources in the manifest; "
        f"{download_summary.get('saved', 0)} downloaded, "
        f"{download_summary.get('refused', 0)} refused, "
        f"{download_summary.get('failed', 0)} failed, "
        f"{download_summary.get('duplicate', 0)} duplicate; "
        f"{text_summary.get('read', 0)} read as text, "
        f"{text_summary.get('unreadable', 0)} unreadable. "
        f"{len(with_section)} sections written: {len(passed)} pass the quote check, "
        f"{len(failed)} fail it.</p>"
    )
    if unread:
        parts.append("<h2>Not read</h2><ul>")
        for e in unread:
            parts.append(
                f"<li><a href='{html.escape(e.source.url)}'>{html.escape(e.source.url)}</a> "
                f"&mdash; {html.escape(e.unread_reason or 'no section written')}</li>"
            )
        parts.append("</ul>")
    parts.append("<h2>Sources</h2>")
    for e in sorted(with_section, key=lambda x: x.title.lower()):
        if e.problems:
            parts.append(
                "<p class='bad'>Quote check failed for this section: "
                + "; ".join(html.escape(p[:160]) for p in e.problems) + "</p>"
            )
        parts.append(e.section or "")
    parts.append("</body></html>")
    return "\n".join(parts)
