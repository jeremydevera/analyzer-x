"""The training-materials manifest: which sources exist, which may be fetched.

Guards the free-only rule: a source the operator was given as free must be
one the manifest marks free, and a pirate or mirror host can never be fetched.
"""

from pathlib import Path

from tradingagents import training_manifest as tm

REPO = Path(__file__).resolve().parents[1]
LINKS = REPO / "research" / "training" / "links-free.txt"


def test_tier_one_equals_links_free_file():
    lines = [ln.strip() for ln in LINKS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    sources = tm.load()
    tier1 = {s.url for s in sources if s.tier == 1}
    assert len(lines) == 56
    assert tier1 == set(lines)


def test_ids_are_unique_and_come_from_the_url():
    sources = tm.load()
    assert len({s.id for s in sources}) == len(sources)
    for s in sources:
        assert s.id == tm.source_id(s.url)
        assert len(s.id) == 8 and s.id == s.id.upper()


def test_check_rejects_a_denied_host():
    url = "https://libgen.is/book/index.php?md5=x"
    src = tm.Source(id=tm.source_id(url), url=url, kind="pdf", free=True, tier=1, note="")
    problems = tm.check([src])
    assert len(problems) == 1
    assert "libgen.is" in problems[0]


def test_check_rejects_a_non_http_scheme():
    url = "ftp://example.org/paper.pdf"
    src = tm.Source(id=tm.source_id(url), url=url, kind="pdf", free=True, tier=1, note="")
    assert tm.check([src]) and "scheme" in tm.check([src])[0]


def test_check_accepts_the_manifest_as_it_stands():
    assert tm.check(tm.load()) == []


def test_every_kind_is_one_of_the_three():
    assert {s.kind for s in tm.load()} <= {"pdf", "html", "repo"}
