"""The training-materials manifest: the sources the operator was given, and
which of them may be fetched.

Every source carries a `free` flag. Only free sources are ever downloaded; a
paid book is never copied. Pirate and mirror hosts are refused by name, so a
search result can never route the fetcher to one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "research" / "training" / "manifest.json"
LINKS_FREE = REPO / "research" / "training" / "links-free.txt"

# Hosts that only ever carry unlicensed copies, or that mirror them.
DENIED_HOSTS: tuple[str, ...] = (
    "libgen.is", "libgen.rs", "libgen.li", "libgen.st", "libgen.info",
    "z-lib.org", "zlibrary.to", "1lib.sk", "singlelogin.re",
    "annas-archive.org", "annas-archive.li", "sci-hub.se", "sci-hub.ru",
    "scribd.com", "pdfdrive.com", "dokumen.pub", "vdoc.pub", "ebin.pub",
)

# Plain http is allowed only on these hosts (their pages are served on http).
HTTP_ALLOWED: tuple[str, ...] = ("www.timothymasters.info", "timothymasters.info")

KINDS = ("pdf", "html", "repo")


@dataclass(frozen=True)
class Source:
    id: str
    url: str
    kind: str  # "pdf" | "html" | "repo"
    free: bool
    tier: int
    note: str


def source_id(url: str) -> str:
    """First 8 hex characters (upper case) of the SHA-1 of the URL, scheme and
    trailing slash removed. Stable across runs, short enough for a filename."""
    core = url.split("://", 1)[-1].rstrip("/")
    return hashlib.sha1(core.encode("utf-8")).hexdigest()[:8].upper()


def _kind_of(url: str) -> str:
    parsed = urlparse(url)
    if parsed.path.lower().endswith(".pdf"):
        return "pdf"
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.netloc == "github.com" and len(parts) == 2:
        return "repo"
    return "html"


def load(path: Path = MANIFEST) -> list[Source]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Source(**row) for row in raw["sources"]]


def check(sources: list[Source]) -> list[str]:
    """Problems with a manifest. An empty list means it may be fetched."""
    problems: list[str] = []
    for s in sources:
        parsed = urlparse(s.url)
        host = parsed.netloc.lower()
        if s.kind not in KINDS:
            problems.append(f"{s.id} {s.url}: kind {s.kind!r} is not one of {KINDS}")
        if any(host == d or host.endswith("." + d) for d in DENIED_HOSTS):
            problems.append(f"{s.id} {s.url}: host {host} is a denied pirate or mirror host")
        if parsed.scheme == "https":
            pass
        elif parsed.scheme == "http" and host in HTTP_ALLOWED:
            pass
        else:
            problems.append(f"{s.id} {s.url}: scheme {parsed.scheme or '(none)'} is not allowed here")
        if s.id != source_id(s.url):
            problems.append(f"{s.id} {s.url}: id does not match the URL")
    return problems


def build_from_links(links: Path = LINKS_FREE) -> dict:
    """Manifest content for the tier-1 URLs, one per non-empty line."""
    urls = [ln.strip() for ln in links.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows = [
        {
            "id": source_id(u),
            "url": u,
            "kind": _kind_of(u),
            "free": True,
            "tier": 1,
            "note": "",
        }
        for u in urls
    ]
    return {"sources": rows}
