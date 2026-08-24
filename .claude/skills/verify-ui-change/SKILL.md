---
name: verify-ui-change
description: ALWAYS ON for any change that alters how the app LOOKS. Run the Playwright gate before reporting a UI change done. Written 2026-08-20 after the operator asked "why are my dropdown field messy can you not see?" — a property-only check had passed while an 18x36px bordered box sat inside every dropdown.
---

# Verify a UI change

The operator's instruction, verbatim:

> "create a skill to verify the ui using playwright when there is ui changes to
> avoid this"

## Why this exists

Contrast, font and token probes were passing on every screen while the UI was
visibly broken. Those probes measure **properties**. Almost every defect the
operator has had to report was a **composition** defect, which no property
check can see:

| What the operator saw | What the probes said |
|---|---|
| A bordered box inside every dropdown | contrast PASS, fonts PASS |
| Close button 801px from its table | contrast PASS |
| Position sizing radio in the red destructive well | contrast PASS |
| "4 STRATEGIES" in loss-red for a neutral count | contrast PASS |
| Nav unchanged through six passes | tokens PASS |
| `DOWNLOAD` / `UPDATE` on different baselines | contrast PASS |

**A green property sweep is not evidence the UI is correct.** Look at it.

## Run it

```bash
cd .claude/skills/verify-ui-change
node scripts/gate.mjs                       # Auto Trade
node scripts/gate.mjs "?p=backtest-2"       # any screen, by its nav slug
node scripts/gate.mjs "?p=stocks" '.st-key-tmsec_risk'   # + crop a component
```

Exits non-zero on failure and names the offending element. Playwright resolves
through a symlink to the sibling skill's `node_modules`; if it ever breaks,
`ln -sfn ../../verifying-ui-with-playwright/scripts/node_modules node_modules`.

**The script is the floor, not the ceiling.** It ends by telling you to open
the screenshot, because checks 1 and 5 below are the only automatable part of
"does this look right".

### Proving a check works

Before trusting a new check, REINTRODUCE the bug and confirm the gate fails.
Done for the empty-dropdown case: reverting the prefix selector back to the
exact testid produced

```
FAIL (1):
  - overlay fill LIGHT on a dark app: ul[stSelectboxVirtualDropdownEmpty]
```

A check that has never failed on a known-bad input is not a check.

### What it caught on its first run
- The rail's count badge carried live-vs-paper in hue alone.
- `1000000BABYDOGE` breaking mid-word inside a multiselect tag.
- `h1 -> h4` on Stocks and LLM Models — two skipped levels on two screens.

It also produced two false positives, both fixed in the script and worth
knowing about: `st.dataframe` ships an invisible zero-width accessibility
mirror of its grid whose cells "wrap", and a badge's meaning-cue lives on the
nav ROW, not on the badge element.

## The gate — all five, before saying a UI change is done

### 1. Screenshot the thing you changed, and READ it

Not the whole page — the component. Crop to it:

```js
const el = await p.$('.st-key-tmsec_risk');
await el.scrollIntoViewIfNeeded();
await el.screenshot({path: 'x.png'});
```

Then actually open the image and ask: is anything doubled, mis-aligned,
overlapping, orphaned, or wearing a colour that means something it isn't?

### 2. Nested-chrome check (the dropdown bug)

A generic `input` / `div` selector reaches INSIDE composite widgets. Assert no
element carries chrome it should not:

```js
for (const w of document.querySelectorAll('[data-baseweb="select"]')) {
  const inp = w.querySelector('input');
  const cs = getComputedStyle(inp);
  // an inner search input owns NO border, radius or min-height
  assert(cs.borderTopWidth === '0px', 'inner input grew a border');
  assert(cs.minHeight === '0px' || cs.minHeight === 'auto');
}
```

Generalise: after styling `input`, `button`, `div` or `a` broadly, list every
element the selector actually matched and check none of them is an internal
part of a composite control.

### 3. Baseline + proximity check

Controls in a row share a baseline; a control sits near the thing it acts on.

```js
const d = btn('DOWNLOAD').getBoundingClientRect();
const u = btn('UPDATE').getBoundingClientRect();
assert(Math.abs(d.top - u.top) < 2, 'buttons off baseline');
// a control must be near its subject
assert(confirmTop - tableBottom < 200, 'action stranded from its table');
```

### 4. Semantic-colour check

A colour that MEANS something must only appear where that meaning holds. On
this app green/red mean profit and loss:

```js
// resolve tokens THROUGH the browser — never regex a colour string.
// oklch(0.09 0.006 265) parsed as rgb reads r=0.09 g=0.006 b=265.
const probe = document.createElement('span'); document.body.appendChild(probe);
probe.style.color = 'var(--pos)'; const pos = getComputedStyle(probe).color;
```
Then assert nothing neutral (a count, a label, a heading) wears `--pos` or
`--neg`, and that anything which does also carries a non-colour cue (a sign,
an arrow, a word).

### 5. Open-state check (portals)

**A dropdown, popover or tooltip does not exist until it is open, and baseweb
renders it in a PORTAL at `body` level — outside `.stApp`.** Every rule scoped
to `.stApp` misses it. Measured: an open menu kept `config.toml`'s paper fill
behind our white ink at **1.03:1** — every option invisible — while all five
other checks passed on the same page.

So the gate CLICKS the selects open and re-runs contrast on the overlay:

```js
const live = p.locator('[data-baseweb="select"]').nth(i);
await live.click();
await p.waitForSelector('[data-baseweb="popover"],[data-baseweb="menu"]');
// evaluate IMMEDIATELY — the click triggers a Streamlit rerun which closes it
```

**Check the EMPTY state as well as the populated one.** They are different
elements. `stSelectboxVirtualDropdown` is the list; **`…DropdownEmpty`** is the
"No results" panel — a separate testid. Covering only the first left a
paper-white 79px panel on a dark page while the populated list measured clean.
Match by PREFIX (`[data-testid^="stSelectboxVirtualDropdown"]`) so the next
variant cannot slip through, and drive one select to empty (click "Select all")
before opening it.

**Check overlay FILLS, not just overlay text.** The "No results" chip had white
ink on its own dark ground and passed a text-contrast check while the panel
behind it was white. The gate now walks every element in the portal and fails
any light fill on a dark app (or dark on light), naming the element.

Portaled surfaces to style unscoped, from `:root` tokens:
`[data-baseweb="popover"]`, `[data-baseweb="menu"]`, `li[role="option"]`,
`[data-baseweb="tooltip"]`, and **`ul[data-testid="stSelectboxVirtualDropdown"]`**
— Streamlit's virtualised list, which carries no `role`, so a
`ul[role="listbox"]` selector silently misses it and the list body stays paper
while the first row looks fixed.

### 6. Duplication check

Render the page and count the things a user would name. Two panels titled
almost the same, two confirm buttons for one action, a list and a grid showing
identical columns — all shipped here.

```js
const titles = [...document.querySelectorAll('h2')].map(h => h.innerText.trim());
assert(new Set(titles).size === titles.length, 'duplicate sections');
```

## Rules

- **Convert colours with the browser, never a regex.** Canvas: set `fillStyle`,
  read one pixel. Works for `oklch`, `color-mix`, named colours. A hand-rolled
  `rgb()` parser silently produced confident nonsense for a whole session.
- **Exclude the deliberately-invisible.** `.ani-sr` is a 1x1 accessible copy;
  counting it as clipped text reported 26 failures that were all correct.
- **Count line boxes, not element height,** for wrap detection. Padding fools a
  height heuristic; a `Range` over the text node does not:
  `range.getClientRects().length > 1` means a real mid-word break.
- **A probe that finds ZERO of what it looks for has verified nothing.** Assert
  the probe found candidates before trusting a pass.
- **Composite alpha; never stop at the first tinted ancestor.** Streamlit lays
  `rgba(180,172,156,0.15)` over rows. Treating a 15%-alpha tint as an opaque
  ground reported white-on-dark as **2.16:1** and sent me hunting a UI bug that
  did not exist. Collect layers upward, flatten downward.
- **`[].every()` is `true`.** Inferring "nothing opened" from an empty failure
  array failed a clean page. Count successes explicitly.
- **Re-query handles every pass.** A click makes Streamlit rerun, which detaches
  every element handle collected before the loop.
- **One un-openable control is not a failed page.** Fail only when NOTHING was
  inspected.
- **Screenshot after every fix, not once at the end.** Two fixes here each
  introduced a new visual bug that the next screenshot caught.
- **CSS uppercases text.** Match case-insensitively, or `DOWNLOAD` is not found
  because the DOM says `Download`.
- **Never `pkill streamlit` by name.** Kill by PID: `lsof -tiTCP:8503`, and
  check the trading runner's PID is untouched.

## Selector hazards proven in this app

| Pattern | What it hit by accident |
|---|---|
| `input { border: ... }` | the search input inside every select |
| `[data-testid="stColumn"]:last-child` | the last column of EVERY row, not one |
| `:not(.a):not(.b)` | adds specificity — it beat the rail's own colour rule |
| `.stApp span` | out-specified `.mv-num`, killing tabular figures |
| `--accent` re-pointed | legacy rules used it as a FILL, not text |

Prefer a keyed container (`st.container(key=...)` -> `.st-key-<key>`) over any
positional selector.

## Report honestly

State what was measured and what was only looked at. If a check could not run,
say so — do not let a skipped check read as a pass.
