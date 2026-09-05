"""The LOGS section is two folder tabs: PENDING and ERRORS.

Operator, 2026-09-05: *"create a logs for github action in backtest so i can
see if there are any errors when running it ... create 2 seperate -folder-like
tabs — pending and errors, errors should go to errors tab while pending should
go to pending tab"*.

The GitHub Actions failures already ride in the same errors list as this PC's
(`backtest_logs._cloud_errors` tags them `GitHub shard N`), so the ERRORS tab
is where a cloud run's failures land — these tests pin that the tab exists,
that its label counts the same payload its body renders, and that the panel
opens on ERRORS when there is one to see.
"""

SRC = "webapp/src/components/backtest/LogsPanel.tsx"


def _src() -> str:
    return open(SRC, encoding="utf-8").read()


def test_the_two_folder_tabs_exist_and_are_addressable():
    p = _src()
    assert 'role="tablist"' in p
    assert p.count('role="tab"') == 1, "one folder() helper renders both"
    assert 'folder("pending", "PENDING", p.count' in p
    assert 'folder("errors", "ERRORS", d.error_count' in p
    # folder-like: the active tab sits ON the border, rounded at the top
    assert "rounded-t-lg" in p and "-mb-px" in p and "border-b-0" in p


def test_each_tab_label_counts_the_payload_its_body_renders():
    """label-must-match-data: the PENDING badge is p.count — the same field
    the tab body prints as 'never measured' — and ERRORS is error_count, the
    same field the 'showing X of Y' line divides."""
    p = _src()
    i = p.index('folder("pending"')
    assert "p.count" in p[i:i + 60]
    j = p.index('folder("errors"')
    assert "d.error_count" in p[j:j + 60]
    # nothing renders outside its folder: the errors table and the pending
    # list are each inside their tab's conditional
    assert p.index('tab === "errors" && (') < p.index("<table")
    assert p.index('tab === "pending" && (') < p.index("never measured")


def test_the_panel_opens_on_errors_when_there_are_errors():
    """The tabs exist so a failed GitHub run is SEEN — a panel that always
    opens on pending would hide the thing the operator asked for."""
    p = _src()
    assert 'setTab(r.error_count ? "errors" : "pending")' in p
    # ...but only ONCE, from the first payload — the 30s refresh must never
    # yank a tab the operator chose
    assert "picked.current" in p


def test_resolve_pending_lives_in_the_pending_tab():
    p = _src()
    # anchor on the BUTTON's label ("RESOLVE PENDING · …"), not the comment
    # block near the top of the file that also says the words
    assert p.index('tab === "pending" && (') < p.index("RESOLVE PENDING ·")
    assert p.index("RESOLVE PENDING ·") < p.index('tab === "errors" && (')


def test_the_github_errors_reach_the_errors_tab():
    """The backend half: cloud failures are in the SAME list the tab maps."""
    from tradingagents import backtest_logs as bl
    import inspect

    s = inspect.getsource(bl._cloud_errors)
    assert "GitHub shard" in s
    s2 = inspect.getsource(bl.logs)
    assert "_cloud_errors" in s2, "logs() must merge the cloud errors in"


def test_a_silent_shard_is_still_named_inside_the_errors_tab():
    """0 errors with unread shards is 'unread', never 'clean' — and the note
    also shows when errors EXIST beside silent shards."""
    p = _src()
    assert p.count("have not reported yet") == 2, \
        "the empty state AND the has-errors state both carry the blind note"
