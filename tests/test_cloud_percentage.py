"""The CLOUD RUN's own percentage, on the screen.

Operator, 2026-09-03: *"show percentage of cloud in the ui as well"*. The panel
had a bar per machine and no figure for the run, so "how far along is the cloud?"
could only be answered by adding up twenty tiles by eye — which is what I was
doing for them in chat every few minutes.

It is DERIVED from the shard rows the machines publish (`done`/`total`/`rows`),
never a number the component keeps of its own. And an EMPTY shard list is not
"nothing is running": this panel reads the shards through GitHub's Actions API,
which secondary-limits a polling client — at 9:59pm on 2026-09-02 it returned
403 "API rate limit exceeded" while all 20 machines were working, and the panel
showed "0 machine(s) reporting" over a healthy run.
"""
PANEL = "webapp/src/components/backtest/JobsPanel.tsx"
CLIENT = "webapp/src/lib/api.ts"


def _panel() -> str:
    return open(PANEL, encoding="utf-8").read()


def test_the_run_has_one_percentage_summed_from_the_machines():
    p = _panel()
    assert "((100 * done) / total).toFixed(1)" in p, "the run's own figure"
    assert p.count('cloud.shards.reduce((a, s) => a + (s.done ?? 0), 0)') >= 2
    assert 'cloud.shards.reduce((a, s) => a + (s.total ?? 0), 0)' in p
    # and the numbers behind it, so the percentage can be checked
    assert "coins ·" in p and "rows measured ·" in p
    assert 'machine(s) finished' in p


def test_it_never_divides_by_zero_before_a_machine_reports():
    p = _panel()
    assert 'total ? ((100 * done) / total).toFixed(1) : "0.0"' in p
    assert "const pct = total ? (100 * done) / total : 0;" in p


def test_there_is_a_bar_for_the_whole_run():
    p = _panel()
    i = p.index("one bar for the RUN")
    seg = p[i:i + 700]
    assert "style={{ width: `${pct.toFixed(1)}%` }}" in seg, seg[:300]


def test_an_empty_shard_list_says_why_instead_of_reading_as_stopped():
    """The label-must-match-data half: 0 machines reporting looked exactly like
    a dead run while GitHub was merely rate-limiting the poll."""
    p = _panel()
    assert "{!cloud.shards.length && (" in p
    assert "no machine has reported through GitHub" in p
    assert "sweep-progress" in p, "and it names where the truth lives"
    assert "rate-limits this panel" in p


def test_the_shard_type_carries_the_fields_the_percentage_needs():
    c = open(CLIENT, encoding="utf-8").read()
    seg = c[c.index("export interface CloudShard"):]
    seg = seg[:seg.index("}")]
    for f in ("done?: number", "total?: number", "rows?: number"):
        assert f in seg, (f, seg)


def test_the_merge_route_streams_the_shard_artifacts():
    """Operator, 2026-09-03: MERGE answered HTTP 500 with
    `no artifact matches any of the names or patterns provided` while 82,736,360
    measured rows sat in the run's twenty rows-N artifacts.

    `fetch()` asks for ONE artifact named "sweep-results" — which the workflow's
    merge job stopped producing after it was OOM-killed concatenating 29.7M rows
    on a 7 GB runner — and it builds one Python list of every row, which is the
    same MemoryError that killed the 5:20am grid on 2026-08-26. The route must
    use `collect_into_store`, which prefers the per-shard artifacts, streams
    them a line at a time, and refuses to overwrite a pair this machine has
    already measured.
    """
    src = open("tradingagents/api.py", encoding="utf-8").read()
    i = src.index('@app.post("/api/cloud/merge")')
    body = src[i:i + 1800]
    assert "cs.collect_into_store(run_id)" in body, body[:400]
    assert "cs.fetch(" not in body, "fetch() is the single-artifact path"
    assert "rows-0..rows-19" in body, "the incident is written down"


def test_the_collector_prefers_the_per_shard_artifacts():
    """They ARE the measurement; the merge job only concatenates them."""
    from tradingagents import cloud_sweep as cs

    src = open("tradingagents/cloud_sweep.py", encoding="utf-8").read()
    seg = src[src.index("def artifact_names("):]
    seg = seg[:seg.index("def collect_into_store(")]
    assert 'n.startswith("rows-")' in seg
    assert "return shards or [n for n in live if n == ARTIFACT]" in seg, (
        "per-shard first, the merged file only as a fallback")
    assert cs.ARTIFACT == "sweep-results"
