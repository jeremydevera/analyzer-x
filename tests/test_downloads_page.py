"""Downloads for a machine that only has the site (operator, Oct 09, 2026: "then
download in my mac", "i cant even see the chat"). Files under G:\\Download are
listed and sent to the browser — and nothing outside that folder ever is."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from tradingagents import api


@pytest.fixture
def folder(tmp_path, monkeypatch):
    d = tmp_path / "Download"
    (d / "2026-10-09" / "parts").mkdir(parents=True)
    (d / "2026-10-09" / "6-20am strategies-not-on-okx.zip").write_bytes(b"zip")
    (d / "2026-10-09" / "parts" / "part 01.zip").write_bytes(b"one")
    (tmp_path / "secret.txt").write_text("no")
    monkeypatch.setattr(api, "DOWNLOAD_DIR", d)
    return d


def test_the_page_lists_every_file_with_a_link(folder):
    page = api.downloads_page_route().body.decode()
    assert "2026-10-09/6-20am strategies-not-on-okx.zip" in page
    assert "/api/downloads/file?name=2026-10-09/parts/part%2001.zip" in page


def test_a_file_comes_back_as_an_attachment(folder):
    got = api.download_file_route("2026-10-09/6-20am strategies-not-on-okx.zip")
    assert str(got.path).endswith("6-20am strategies-not-on-okx.zip")
    assert 'attachment' in got.headers["content-disposition"]


@pytest.mark.parametrize("bad", ["../secret.txt", "2026-10-09/../../secret.txt", "nope.zip", "2026-10-09"])
def test_nothing_outside_the_folder_and_no_folder_is_sent(folder, bad):
    with pytest.raises(HTTPException) as e:
        api.download_file_route(bad)
    assert e.value.status_code == 404
