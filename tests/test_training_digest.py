"""The digest assembler: every quote is checked against its source text."""

from __future__ import annotations

from tradingagents import training_digest as td
from tradingagents.training_manifest import Source, source_id

TEXT = "Out of\n  sample testing   is the only honest check. Fees are charged on every trade."


def _src(url: str) -> Source:
    return Source(id=source_id(url), url=url, kind="html", free=True, tier=1, note="")


def test_a_quote_that_is_in_the_source_passes_across_line_breaks_and_spaces():
    section = "<section><blockquote>out of sample testing is the only honest check</blockquote></section>"
    assert td.quote_problems(section, TEXT) == []


def test_a_quote_not_in_the_source_is_reported_by_its_words():
    section = "<section><blockquote>guaranteed profit every month</blockquote></section>"
    assert td.quote_problems(section, TEXT) == ["guaranteed profit every month"]


def test_curly_quotes_and_case_do_not_hide_a_real_quote():
    section = "<section><blockquote>“Fees are charged on every trade.”</blockquote></section>"
    assert td.quote_problems(section, TEXT) == []


def test_a_section_with_no_quotes_has_no_problems():
    assert td.quote_problems("<section><p>not covered</p></section>", TEXT) == []


def test_header_counts_come_from_the_entries_not_typed_numbers():
    urls = ["https://a.example/x", "https://b.example/y", "https://c.example/z"]
    entries = [
        td.Entry(source=_src(urls[0]), title="A", section="<section>ok</section>"),
        td.Entry(source=_src(urls[1]), title="B", section="<section>bad</section>",
                 problems=["missing"]),
        td.Entry(source=_src(urls[2]), title="C", section=None, unread_reason="unreadable"),
    ]
    page = td.assemble(entries, {"saved": 2, "refused": 0, "failed": 1, "duplicate": 0},
                       {"read": 2, "unreadable": 1}, "Nov 17, 2026 8:03pm")
    assert "3 free sources in the manifest" in page
    assert "2 sections written: 1 pass the quote check, 1 fail it." in page
    assert "Quote check failed for this section" in page
    assert "https://c.example/z" in page
