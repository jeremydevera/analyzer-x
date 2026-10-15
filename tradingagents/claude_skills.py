"""THE CLAUDE SKILLS TAB — every skill in this repo, grouped by what it is for.

The operator, Oct 15, 2026: *"can you create a tab called 'Claude skills'
then categorize them for their function and what do they do / for example
harddev-categorize as coding then give me description"*.

The LIST is read from the skill folders themselves (`.claude/skills/*/
SKILL.md`) every time the page asks, so a skill added or deleted shows up
without anyone touching this file. What this file adds is the two things a
skill folder does not carry: its GROUP and a description in plain words.
A skill with no entry here is still shown, under "Not sorted yet", with the
first sentence of its own text — never hidden (a new skill must be findable
the day it lands; `tests/test_the_claude_skills_tab.py` fails until it is
sorted).

"Runs by itself" is READ, never typed here: a skill whose own text says
ALWAYS ON, or that CLAUDE.md lists as "ALWAYS ON — `name`".
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / ".claude" / "skills"
CLAUDE_MD = ROOT / "CLAUDE.md"

# group -> what the group is for, in the order the page shows them
GROUPS = {
    "Coding": "How I build and fix the app's code, and the checks I run before calling it done.",
    "Checking the screen": "Opening the real app in a browser and looking at it before saying a screen change works.",
    "Finding strategies": "Searching the backtests for strategies worth running, and making sure you can find them.",
    "Trading checks": "Reading your practice and real trades, and switching strategies on by their #id.",
    "How I talk to you": "Rules for my replies: short, plain words, a sound when done, a ping when I need you.",
    "Design": "How the app and pages should look: colours, fonts, layouts, logos, slides.",
    "Animation": "How things on screen should move.",
}
UNSORTED = "Not sorted yet"

# name -> (group, plain description)
SKILLS = {
    # ------------------------------------------------------------- Coding
    "harddev": ("Coding",
        "After every code change I keep asking \"is there a bug here?\" and fix it, "
        "over and over until the answer is no, and only then run the tests."),
    "blast-radius": ("Coding",
        "After a change, list everything else that reads or writes the same thing, "
        "because the next bug usually hides where the last fix touched."),
    "three-gates": ("Coding",
        "Before any answer or \"done\": is it measured (not guessed), is it the real "
        "app (not a test copy), and did I actually test it."),
    "rca-log": ("Coding",
        "Every bug fix gets a written record in docs/RCA.md in the same save: what "
        "you saw, when, why, what it cost, and what now stops it."),
    "store-indexes": ("Coding",
        "After a big backtest or rebuild, make sure the search lists behind Stored "
        "strategies are built, so no filter quietly stops working."),
    # ------------------------------------------------- Checking the screen
    "verify-ui-change": ("Checking the screen",
        "Whenever a screen changes, open it in a real browser, take a picture and "
        "check nothing is doubled, misplaced or the wrong colour."),
    "verifying-ui-with-playwright": ("Checking the screen",
        "The older screen check for the first version of the app: open it in a "
        "browser and prove the change really shows."),
    "strict": ("Checking the screen",
        "When you type /strict, no screen change counts as done until I have "
        "looked at it in a browser."),
    "label-must-match-data": ("Checking the screen",
        "The words beside a number must be true too, e.g. a \"TOTAL PROFIT\" label "
        "must add up every trade, not 400 of 694."),
    "web-design-guidelines": ("Checking the screen",
        "Review a screen against common good-website rules: easy to read, works "
        "with a keyboard, clear to use."),
    "press-and-watch": ("Checking the screen",
        "Press a long button (download candles, backtest, update all) for real, "
        "watch it to the end, and fix whatever breaks along the way."),
    # -------------------------------------------------- Finding strategies
    "full-grid-search": ("Finding strategies",
        "Any strategy search tests every coin, every timeframe, every signal, "
        "several targets and stops, and both sizings, never a small slice."),
    "still-working": ("Finding strategies",
        "Only pick a strategy that made money in the last 1, 3 and 6 months and "
        "the whole year, not one that was good long ago and has gone cold."),
    "analyze15m30m": ("Finding strategies",
        "Find the highest win rate for one coin on 15-minute and 30-minute candles "
        "over a year that still makes money, and show it on a page."),
    "analyze1hr4hr": ("Finding strategies",
        "Same as above for 1-hour and 4-hour candles (or the timeframes you name)."),
    "yearly-strategy-sweep": ("Finding strategies",
        "Re-run the whole-market search over the longest history and compare it "
        "with the last run, to see what still works."),
    "store-strategy": ("Finding strategies",
        "A new strategy is not finished until you can find it in Stored "
        "strategies by its #id."),
    # ------------------------------------------------------ Trading checks
    "deploy-by-id": ("Trading checks",
        "When you say \"deploy #DM84QDSZ\", switch on exactly that one strategy, "
        "on its own coin, and read it back to you."),
    "feedcheck": ("Trading checks",
        "Read the trader's log and trade record and say which lines are normal "
        "and which are a real problem, e.g. \"why no trades today\"."),
    "practice_backtest_audit": ("Trading checks",
        "Check each practice trade against its backtest: same times, same price, "
        "same profit, using the real screens."),
    # --------------------------------------------------- How I talk to you
    "short-and-plain": ("How I talk to you",
        "Every reply is one short sentence in plain words with one of your own "
        "examples; an explanation is a boxed diagram that starts with BECAUSE."),
    "bug-scenario": ("How I talk to you",
        "Any bug is told as a step-by-step story with your own times, prices and "
        "dollars, never as code."),
    "say-done": ("How I talk to you",
        "When I finish a job you asked for, the PC says one calm sentence out "
        "loud."),
    "notify-on-confirmation": ("How I talk to you",
        "Whenever I need you to answer or approve something, I also send your "
        "phone a notification."),
    "remember-my-asks": ("How I talk to you",
        "Every message you send is saved word for word in docs/OPERATOR-ASKS.md, "
        "and I read it before writing any code."),
    # -------------------------------------------------------------- Design
    "design": ("Design",
        "The all-in-one design kit: logos, brand look, banners, icons, social "
        "pictures and slides."),
    "design-system": ("Design",
        "Set the app's building blocks once (colours, sizes, spacing) so every "
        "page matches."),
    "brand": ("Design",
        "Keep the brand's voice and look the same everywhere."),
    "banner-design": ("Design",
        "Make banners for social media, ads, a website's top section, or print."),
    "slides": ("Design",
        "Make a slide show as a web page, with charts."),
    "ui-styling": ("Design",
        "Build good-looking, easy-to-use screens with ready-made parts (buttons, "
        "tables, pop-ups) and dark mode."),
    "ui-ux-pro-max": ("Design",
        "A big library of looks, colour sets, fonts and usability rules to pick "
        "from when designing or fixing a screen."),
    "apple-design": ("Design",
        "Apple's way of designing: smooth swipes and springs, depth, careful "
        "text, made for the web."),
    "emil-design-eng": ("Design",
        "Emil Kowalski's ideas on the small finishing touches that make an app "
        "feel great."),
    "extract-design-system": ("Design",
        "Copy the colours, fonts and sizes from a website you like to start our "
        "own."),
    "pick-ui-library": ("Design",
        "Pick the right ready-made code library for a screen job (charts, "
        "pop-up messages, drag and drop). Only when asked."),
    "prototype": ("Design",
        "Build several different versions of one screen piece so you can flip "
        "through them and keep the best. Only when asked."),
    "ask-sonner": ("Design",
        "Help with Sonner, the little pop-up message (\"Saved\") library: set it "
        "up, style it, fix it."),
    # ----------------------------------------------------------- Animation
    "animate": ("Animation",
        "Add movement to something on screen, deciding first whether it should "
        "move at all, then how fast and how it stops."),
    "animation-vocabulary": ("Animation",
        "Tell you the proper name of a movement you describe, e.g. \"the bouncy "
        "thing when a menu opens\"."),
    "find-animation-opportunities": ("Animation",
        "Look through the app for places that should move but don't, and suggest "
        "exactly how. Changes nothing."),
    "improve-animations": ("Animation",
        "Check all the movement in the app and write a fix-it plan, most "
        "important first. Changes nothing."),
    "review-animations": ("Animation",
        "Strictly check one piece of movement against a high bar before it ships."),
}


def _front(text: str) -> dict:
    """name/description from a SKILL.md's top block (between the --- lines)."""
    m = re.match(r"\s*---\s*\n(.*?)\n---", text, re.S)
    out: dict = {}
    if not m:
        return out
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if k.strip() in ("name", "description") and v.strip():
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _always_on() -> set:
    """Names CLAUDE.md lists as `ALWAYS ON — \\`name\\``."""
    try:
        text = CLAUDE_MD.read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(re.findall(r"ALWAYS ON\s*[—-]+\s*`([^`]+)`", text))


def _first_sentence(s: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", s)
    return (m.group(1) if m else s)[:300]


def listing(skills_dir: Path | None = None) -> dict:
    """Every skill on disk, grouped. Groups in GROUPS order, then "Not sorted
    yet"; skills by name inside a group; empty groups are left out."""
    base = Path(skills_dir or SKILLS_DIR)
    always = _always_on()
    found = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        f = d / "SKILL.md"
        try:
            meta = _front(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        name = meta.get("name") or d.name
        own = meta.get("description", "")
        group, plain = SKILLS.get(name, (UNSORTED, _first_sentence(own)))
        found.append({
            "name": name, "group": group, "description": plain,
            "always": "ALWAYS ON" in own or name in always,
        })
    order = list(GROUPS) + [UNSORTED]
    groups = []
    for g in order:
        members = sorted((s for s in found if s["group"] == g), key=lambda s: s["name"])
        if members:
            groups.append({"name": g,
                           "about": GROUPS.get(g, "Skills added since this page was "
                                                  "last sorted; their own words are shown."),
                           "skills": members})
    return {"total": len(found),
            "always": sum(1 for s in found if s["always"]),
            "groups": groups}
