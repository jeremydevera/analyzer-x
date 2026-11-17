"""Text extraction for the training-material downloads.

A page or PDF with too few words, or with no text layer, is marked unreadable
with its reason. It is never reported as learned.
"""

from __future__ import annotations

import io
from pathlib import Path

import pypdf
import pytest

from tradingagents import training_text as tt


def _pdf_bytes(pages_text: list[str] | None) -> bytes:
    """A real PDF. With pages_text=None, one blank page (no text layer)."""
    writer = pypdf.PdfWriter()
    if pages_text is None:
        writer.add_blank_page(width=300, height=300)
    else:
        for text in pages_text:
            page = writer.add_blank_page(width=300, height=300)
            page.merge_page(_text_page(text))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _text_page(text: str) -> pypdf.PageObject:
    from pypdf.generic import (ArrayObject, ContentStream, DecodedStreamObject,
                               DictionaryObject, NameObject, NumberObject)

    stream = DecodedStreamObject()
    escaped = text.replace("(", r"\(").replace(")", r"\)")
    stream.set_data(f"BT /F1 9 Tf 10 280 Td ({escaped}) Tj ET".encode("latin-1"))
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page = pypdf.PageObject.create_blank_page(width=300, height=300)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    page[NameObject("/Contents")] = stream
    return page


def _words(n: int, word: str = "backtest") -> str:
    return " ".join([word] * n)


def test_a_normal_page_is_read_and_script_and_style_are_dropped(tmp_path):
    body = (
        "<html><head><style>.x{color:red}</style><script>var secret=1;</script></head>"
        f"<body><p>{_words(400, 'overfitting')}</p></body></html>"
    )
    path = tmp_path / "a.html"
    path.write_text(body, encoding="utf-8")
    r = tt.extract(path)
    assert r.ok
    assert r.words >= 300
    assert "secret" not in r.text
    assert "color:red" not in r.text


def test_a_login_wall_is_unreadable(tmp_path):
    path = tmp_path / "wall.html"
    path.write_text(f"<html><body><p>{_words(40)}</p></body></html>", encoding="utf-8")
    r = tt.extract(path)
    assert not r.ok
    assert "under 300 words" in r.reason


def test_a_pdf_with_no_text_layer_is_unreadable(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(_pdf_bytes(None))
    r = tt.extract(path)
    assert not r.ok
    assert "no text layer" in r.reason


def test_a_pdf_with_text_is_read(tmp_path):
    path = tmp_path / "text.pdf"
    path.write_bytes(_pdf_bytes([_words(350, "walkforward")]))
    r = tt.extract(path)
    assert r.ok
    assert r.words >= 300


def test_run_counts_add_up(tmp_path):
    store = tmp_path / "store"
    (store / "raw").mkdir(parents=True)
    (store / "raw" / "good.html").write_text(
        f"<p>{_words(320, 'sizing')}</p>", encoding="utf-8")
    (store / "raw" / "thin.html").write_text("<p>short</p>", encoding="utf-8")
    progress = tt.run(store=store)
    assert progress["read"] + progress["unreadable"] == 2
    assert progress["read"] == 1
    assert (store / "text" / "good.txt").exists()
    assert not (store / "text" / "thin.txt").exists()
