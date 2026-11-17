# Learn From The Training Materials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download the free training materials the operator was given (56 links, tier 1), read them, and leave behind summaries that quote their sources, a searchable index, and a gap report against this repo's own backtest rules.

**Architecture:** A small manifest (`research/training/manifest.json`) names every source. A fetcher saves each free source to the store drive (G:), a text extractor turns it into plain text, and subagents write one summary section per source from that text only. A quote checker proves every quoted line exists in its source before a section is kept. Graphify indexes the text folder for questions, and the gap report compares what the sources teach with what the repo already does.

**Tech Stack:** Python 3 (`.venv/Scripts/python`), stdlib `urllib`/`http.server`/`html.parser`/`urllib.robotparser`, `pypdf`, pytest, the `graphify` skill, `skill-creator`.

**Spec:** No separate spec file. The requirement is the operator's asks of Nov 17, 2026, recorded word for word in `docs/OPERATOR-ASKS.md` by the hook: *"search on reddit and look for recommended training materials and look for the material they are talking about either pdf, or website or anything"*, *"if i want to scrape them and ask you to summarize what you learn where will you store it?"*, *"create me a plan so that you can learn from the links you provided use superpower"*. Decisions made in that chat: raw files on G:, summaries in `docs/research/`, Graphify for the index, free material only.

## Global Constraints

- Only sources flagged `free: true` are ever downloaded. Paid books are never copied; for them only the publisher's free sample may be read, and only if it is a free source in the manifest.
- Never fetch from pirate or mirror hosts: libgen, z-lib / zlibrary, annas-archive, sci-hub, scribd, pdfdrive, dokumen, vdoc (`training_manifest.DENIED_HOSTS`).
- Respect `robots.txt` and wait at least 2 seconds between requests to one host.
- Raw files and text go under `Path(msw.HOME) / "research" / "training-materials"` (the G: drive). Never `%TEMP%`, never `tempfile`, never the repo (CLAUDE.md, "Big files go where the STORE is").
- A failed source is named in the progress file, never only counted, and redone alone (CLAUDE.md, "A failed coin is redone alone").
- No `except Exception: pass` anywhere; a swallowed failure is a button that lies (CLAUDE.md, "A job that cannot start must SAY SO").
- Any date printed to a screen, log or doc uses `positions_view.fmt_when`; the format reads `Nov 17, 2026 8:03pm`.
- Run one full pytest suite at a time on this PC; for this plan run only the named test files.
- Commit through `python scripts/commit_own.py -F msg.txt <paths>`, push to `origin`, `colleague` and `teammate` after each task. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Never commit the operator's private notes (`.obsidian/`, scratch `*.md` in the repo root). `docs/research/` and `docs/superpowers/` are fine.
- Out of scope, named so nobody adds it silently: the earlier non-Reddit research links (articles, papers, courses; tier 2) and any change to backtest code. Both need the operator's yes after the gap report.

## Review Focus

1. A PDF downloads but has no text layer (scanned, DRM) → marked `unreadable` with the reason, never reported as learned (Task 3).
2. A URL now redirects to a different site (`quantstrattrader.com` became a gambling page) → the fetch is refused, named, and nothing is saved (Task 2).
3. A page returns a login wall, cookie wall or 403 body → under `MIN_WORDS` of text, flagged `unreadable`, not summarized (Task 3).
4. Two URLs return the same bytes → saved once, the second marked `duplicate` (Task 2).
5. A summary claims something the source never says → the quote check names the missing quote and the section is rejected (Task 5).

---

### Task 1: Manifest and its checks

**Files:**
- Create: `research/training/manifest.json`
- Create: `tradingagents/training_manifest.py`
- Test: `tests/test_training_manifest.py`
- Already present: `research/training/links-free.txt` (the 56 tier-1 URLs, one per line)

**Interfaces:**
- Produces:
  - `Source` (frozen dataclass): `id: str`, `url: str`, `kind: str` (`"pdf" | "html" | "repo"`), `free: bool`, `tier: int`, `note: str`
  - `DENIED_HOSTS: tuple[str, ...]`
  - `MANIFEST: Path`, the path of `research/training/manifest.json`
  - `source_id(url: str) -> str`: the first 8 characters of the upper-case SHA-1 hex of the URL with its scheme and trailing slash removed
  - `load(path: Path = MANIFEST) -> list[Source]`
  - `check(sources: list[Source]) -> list[str]`: problems, empty list means fine

- [ ] **Step 1: Write the failing tests** in `tests/test_training_manifest.py`:
  - `test_tier_one_equals_links_free_file`: the set of tier-1 URLs in `load()` equals the set of non-empty lines of `research/training/links-free.txt`, and both have 56 entries
  - `test_ids_are_unique_and_come_from_the_url`: `{s.id for s in load()}` has the same length as the list, and every `s.id == source_id(s.url)`
  - `test_check_rejects_a_denied_host`: `check([Source(id=source_id("https://libgen.is/x"), url="https://libgen.is/x", kind="pdf", free=True, tier=1, note="")])` returns one problem naming `libgen.is`
  - `test_check_rejects_a_non_https_free_source_that_is_not_listed_http`: a free source with a `ftp://` URL returns a problem (plain `http://` is allowed only for the two timothymasters.info lines)
  - `test_every_kind_is_one_of_the_three`

- [ ] **Step 2: Run to verify they fail**
  Run: `.venv/Scripts/python -m pytest tests/test_training_manifest.py -v`
  Expected: FAIL (`ModuleNotFoundError: tradingagents.training_manifest`)

- [ ] **Step 3: Implement** `tradingagents/training_manifest.py` with the signatures above. `kind` is `repo` for `github.com/<owner>/<repo>` URLs with no deeper path, `pdf` for URLs ending `.pdf` or the two SSRN/Cambridge book pages' PDF links where known, otherwise `html`. Generate `manifest.json` once from `links-free.txt` with a short script run inline (not kept), `free: true`, `tier: 1`, `note: ""`.

- [ ] **Step 4: Run to verify they pass**
  Run: `.venv/Scripts/python -m pytest tests/test_training_manifest.py -v`
  Expected: 5 passed

- [ ] **Step 5: Commit and push**
  `python scripts/commit_own.py -F msg.txt research/training tradingagents/training_manifest.py tests/test_training_manifest.py`, then `git push origin main`, `git push colleague main`, `git push teammate main`.

### Task 2: Fetcher

**Files:**
- Create: `tradingagents/training_fetch.py`
- Test: `tests/test_training_fetch.py`

**Interfaces:**
- Consumes: `training_manifest.Source`, `training_manifest.DENIED_HOSTS`, `market_sweep.HOME`
- Produces:
  - `STORE: Path` = `Path(msw.HOME) / "research" / "training-materials"`; raw files in `STORE/raw/<id>.<ext>`
  - `MAX_BYTES = 200 * 1024 * 1024`, `HOST_GAP_S = 2.0`, `RETRIES = 3`
  - `Result` (frozen dataclass): `id: str`, `status: str` (`"saved" | "refused" | "failed" | "duplicate"`), `reason: str`, `path: Path | None`, `bytes: int`, `sha256: str`
  - `fetch(src: Source, *, store: Path = STORE, gap_s: float = HOST_GAP_S) -> Result`
  - `run(sources: list[Source], store: Path = STORE, only: str | None = None) -> dict`: writes `store/progress.json` with `{"total", "saved", "refused", "failed", "duplicate", "problems": [{"id","url","status","reason"}]}` and returns it

- [ ] **Step 1: Write the failing tests** in `tests/test_training_fetch.py`, driving a real `http.server` on `127.0.0.1` in a thread (the repo's real-socket style):
  - `test_a_free_page_is_saved_with_its_hash_under_the_store`: status `saved`, file exists under `tmp_path/raw`, `sha256` equals the hash of the served bytes
  - `test_a_paid_source_is_refused_without_a_request`: `free=False` → `refused`, server request count 0
  - `test_a_denied_host_is_refused`: URL host in `DENIED_HOSTS` → `refused`, reason names the host
  - `test_a_500_then_200_is_retried_and_saved`: server answers 500 once; result `saved`
  - `test_a_redirect_to_another_site_is_refused`: server at `127.0.0.1` redirects to `localhost` → `refused`, reason says "redirected to a different site", nothing saved
  - `test_robots_disallow_is_respected`: `/robots.txt` disallows the path → `refused`
  - `test_a_body_over_max_bytes_is_refused`: patch `MAX_BYTES` to 100, serve 500 bytes → `refused`
  - `test_the_same_bytes_under_two_urls_are_saved_once`: second result `duplicate`
  - `test_run_names_every_problem_and_the_counts_add_up`: `progress.json` has `saved + refused + failed + duplicate == total` and every non-saved id appears in `problems`
  - `test_the_module_never_uses_the_system_temp_folder`: AST walk over `training_fetch.py` finds no `tempfile` import or `TemporaryDirectory` call, and `STORE` starts with `Path(msw.HOME)`

- [ ] **Step 2: Run to verify they fail**
  Run: `.venv/Scripts/python -m pytest tests/test_training_fetch.py -v`
  Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement** `fetch` and `run` in `tradingagents/training_fetch.py`. Use `urllib.request` with a plain `User-Agent: tradingagents-research/1.0` (no contact details). A redirect is allowed only when the final host's last two labels equal the original's. A `repo` source fetches `https://raw.githubusercontent.com/<owner>/<repo>/HEAD/README.md` instead. Retry only transient failures (5xx, 429, a cut connection) up to `RETRIES` within 60 seconds. Keep a per-host last-request time for `gap_s`. Write the file to `<id>.part` then rename.

- [ ] **Step 4: Run to verify they pass**
  Run: `.venv/Scripts/python -m pytest tests/test_training_fetch.py -v`
  Expected: 10 passed

- [ ] **Step 5: Commit and push** (same commit and push commands, paths `tradingagents/training_fetch.py tests/test_training_fetch.py`).

### Task 3: Text extraction

**Files:**
- Create: `tradingagents/training_text.py`
- Test: `tests/test_training_text.py`

**Interfaces:**
- Consumes: `training_fetch.STORE`, `Result.path`
- Produces:
  - `MIN_WORDS = 300`
  - `TextResult` (frozen dataclass): `ok: bool`, `words: int`, `reason: str`, `text: str`
  - `extract(path: Path) -> TextResult`
  - `run(store: Path = STORE) -> dict`: writes `store/text/<id>.txt` for each `ok` file and `store/text-progress.json` with `{"read", "unreadable", "problems": [{"id","reason"}]}`

- [ ] **Step 1: Write the failing tests** in `tests/test_training_text.py`:
  - `test_a_normal_page_is_read_and_script_and_style_are_dropped`: HTML with 400 words, a `<script>` and a `<style>` → `ok`, neither appears in `text`
  - `test_a_login_wall_is_unreadable`: a 40-word HTML page → `ok False`, reason contains `"under 300 words"`
  - `test_a_pdf_with_no_text_layer_is_unreadable`: a one-page PDF built with `pypdf.PdfWriter().add_blank_page(...)` → `ok False`, reason contains `"no text layer"`
  - `test_a_pdf_with_text_is_read`: a minimal PDF built in the test from raw bytes holding 350 words → `ok`, `words >= 300`
  - `test_run_counts_add_up`: `read + unreadable` equals the number of raw files

- [ ] **Step 2: Run to verify they fail**
  Run: `.venv/Scripts/python -m pytest tests/test_training_text.py -v`
  Expected: FAIL

- [ ] **Step 3: Implement** `extract` and `run`. HTML uses stdlib `html.parser`, skipping `script`, `style`, `nav`, `footer`. PDFs use `pypdf`; first run `.venv/Scripts/python -c "import pypdf"`, and if it fails, `.venv/Scripts/python -m pip install pypdf` and note it in the commit message.

- [ ] **Step 4: Run to verify they pass**
  Run: `.venv/Scripts/python -m pytest tests/test_training_text.py -v`
  Expected: 5 passed

- [ ] **Step 5: Commit and push** (paths `tradingagents/training_text.py tests/test_training_text.py`).

### Task 4: Run it on the 56 sources

**Files:**
- No new code. Output: `STORE/raw/`, `STORE/text/`, `STORE/progress.json`, `STORE/text-progress.json` on G:.

**Interfaces:**
- Consumes: `training_fetch.run`, `training_text.run`, `training_manifest.load`

- [ ] **Step 1: Fetch all tier-1 sources**
  Run: `.venv/Scripts/python -c "from tradingagents import training_manifest as m, training_fetch as f; print(f.run(m.load()))"`
  Expected: a dict whose `saved + refused + failed + duplicate == 56`, printed with every problem named.

- [ ] **Step 2: Redo each failed source alone**
  Run: `.venv/Scripts/python -c "from tradingagents import training_manifest as m, training_fetch as f; print(f.run(m.load(), only='<ID>'))"` for each failed id in `problems` (never the whole run). A source still failing after one redo stays named in the final report.

- [ ] **Step 3: Extract text**
  Run: `.venv/Scripts/python -c "from tradingagents import training_text as t; print(t.run())"`
  Expected: `read + unreadable == saved`. Open two `text/<id>.txt` files by hand and confirm they read as the page they came from (one PDF, one HTML).

- [ ] **Step 4: Report the real counts** to the operator: how many sources were saved, refused, failed, duplicate, read, unreadable, each non-read one named with its reason. No commit (the files live on G:).

### Task 5: Quote check

**Files:**
- Create: `tradingagents/training_quotes.py`
- Test: `tests/test_training_quotes.py`

**Interfaces:**
- Produces:
  - `MIN_QUOTES = 2`
  - `check_section(section: str, text: str) -> list[str]`: problems, empty means kept. A section lists quotes as lines of the form `> "exact words" (where)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_training_quotes.py`:
  - `test_a_quote_that_is_in_the_source_passes`
  - `test_a_quote_not_in_the_source_is_reported_by_its_words`
  - `test_line_breaks_and_double_spaces_do_not_hide_a_real_quote`: the source holds `"out of\n  sample"`, the quote says `"out of sample"` → passes
  - `test_a_section_with_fewer_than_two_quotes_is_rejected`
  - `test_a_quote_under_six_words_does_not_count`: guards against matching common phrases

- [ ] **Step 2: Run to verify they fail**
  Run: `.venv/Scripts/python -m pytest tests/test_training_quotes.py -v`
  Expected: FAIL

- [ ] **Step 3: Implement** `check_section`: normalise whitespace and curly quotes on both sides, case-insensitive substring match, count only quotes of six or more words.

- [ ] **Step 4: Run to verify they pass**
  Run: `.venv/Scripts/python -m pytest tests/test_training_quotes.py -v`
  Expected: 5 passed

- [ ] **Step 5: Commit and push** (paths `tradingagents/training_quotes.py tests/test_training_quotes.py`).

### Task 6: Summaries and the assembled document

**Files:**
- Create: `tradingagents/training_report.py`
- Test: `tests/test_training_report.py`
- Create: `docs/research/2026-11-17-training-materials.md`
- Scratch (not committed): `STORE/sections/<id>.md`

**Interfaces:**
- Consumes: `training_manifest.Source`, `training_quotes.check_section`, `STORE/text/<id>.txt`
- Produces:
  - `assemble(sources: list[Source], sections: dict[str, str], unread: dict[str, str]) -> str`: the document text. Header counts are derived from the arguments, never typed.

Section template each subagent must follow, one per source, fields in this order: `### <name> (<id>)`, `Link:`, `What it teaches:` (at most 3 sentences), `Costs / overfitting / out-of-sample:` (each yes, no or partly, with a quote), `Use for us:` (one line), then the quote lines `> "..." (page or heading)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_training_report.py`:
  - `test_every_read_source_has_exactly_one_section`
  - `test_every_unread_source_is_listed_with_its_reason`
  - `test_read_plus_unread_equals_the_manifest_count_printed_in_the_header`: parse the header line and assert it equals `len(sources)`
  - `test_a_section_for_an_unknown_id_is_rejected`

- [ ] **Step 2: Run to verify they fail**
  Run: `.venv/Scripts/python -m pytest tests/test_training_report.py -v`
  Expected: FAIL

- [ ] **Step 3: Implement** `assemble` in `tradingagents/training_report.py`.

- [ ] **Step 4: Write the summaries.** Split the `read` sources into batches of at most 8. For each batch, start one subagent with only this brief: read `STORE/text/<id>.txt` for each id, write `STORE/sections/<id>.md` in the template, quote exact words, never use outside knowledge, say "not covered" when a field is not in the text. Batches run in parallel. Then, for every section, run `check_section(section, text)`; send any rejected section back to a subagent once with the missing quotes named; a section still rejected is dropped and its source is listed as unread with reason "summary failed the quote check".

- [ ] **Step 5: Assemble and verify**
  Run: `.venv/Scripts/python -c "from tradingagents import training_report as r; ..."` (load sections and unread from the store, write `docs/research/2026-11-17-training-materials.md`)
  Run: `.venv/Scripts/python -m pytest tests/test_training_report.py -v`
  Expected: 4 passed; the header counts match the progress files.

- [ ] **Step 6: Commit and push** (paths `tradingagents/training_report.py tests/test_training_report.py docs/research/2026-11-17-training-materials.md`).

### Task 7: Searchable index with Graphify

**Files:**
- Output only: `STORE/graphify-out/` (graph, report, HTML), created with `STORE` as the working folder so nothing lands in the repo.

**Interfaces:**
- Consumes: `STORE/text/*.txt`

- [ ] **Step 1: Run Graphify** on `STORE/text` by invoking the `graphify` skill with that path. Before it starts, state the file count and the rough token cost it printed, and wait for the operator's yes if it is over 30 files with PDFs inside.

- [ ] **Step 2: Verify the graph exists**
  Run: `Test-Path "$STORE\graphify-out\graph.json"` (PowerShell)
  Expected: `True`. Run `git status --short` in the repo; expect no `graphify-out` entry.

- [ ] **Step 3: Ask the graph three questions** with `/graphify query`: "what do these sources say about overfitting and how to test for it", "how should fees and slippage be modelled in a backtest", "how should position size be chosen". Expected: each answer names at least one source id from the manifest; an answer naming none is reported as a failure, not shown as an answer.

- [ ] **Step 4: No commit.** The graph stays on G:.

### Task 8: Gap report, checklist skill and memory

**Files:**
- Create: `docs/research/2026-11-17-training-gap-report.md`
- Create: `.claude/skills/backtest-checklist/SKILL.md`
- Create: `C:\Users\Jeremy\.claude\projects\g--analyzer-x\memory\training-materials-notes.md`
- Modify: `C:\Users\Jeremy\.claude\projects\g--analyzer-x\memory\MEMORY.md` (one added line)

**Interfaces:**
- Consumes: `docs/research/2026-11-17-training-materials.md`, `CLAUDE.md`, `tradingagents/backtest_report.py`, `tradingagents/auto_trader.py`

- [ ] **Step 1: Write the gap report.** One row per piece of advice that at least two sources agree on, each row with: the advice, source ids and one quote each, what this repo does today (file and section of `CLAUDE.md` or the code), and one of `done`, `partly`, `not done`. Candidates to check, not conclusions: out-of-sample holdout and walk-forward, deflated Sharpe or a multiple-testing correction, purged cross-validation, realistic costs and funding, position sizing from volatility. A row with no repo evidence is marked `unknown`, never `not done`.

- [ ] **Step 2: Write the checklist skill** `.claude/skills/backtest-checklist/SKILL.md` using the `skill-creator` skill. Each checklist line cites a source id and a quote from the summaries doc; a line without both is removed. Its description says when to use it: before reporting any strategy result.

- [ ] **Step 3: Save the memory.** Write `training-materials-notes.md` (type `reference`): where the manifest, store folder, summaries, gap report and graph live. Add one line to `MEMORY.md`.

- [ ] **Step 4: Verify**
  Run: `Select-String -Path docs\research\2026-11-17-training-gap-report.md -Pattern '\(src:'` (each row has a source id)
  Expected: every table row matches. Open the skill file and confirm each line has an id and a quote.

- [ ] **Step 5: Commit and push** (paths `docs/research/2026-11-17-training-gap-report.md .claude/skills/backtest-checklist/SKILL.md`; the memory files are outside the repo and are not committed). Then tell the operator what the gap report found, and ask whether to start tier 2 or change any backtest code.
