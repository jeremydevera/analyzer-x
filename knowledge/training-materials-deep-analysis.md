# What the training materials teach, and what it means for this app

**Built:** Nov 18, 2026; updated Nov 19, 2026 after every link was read; from the 56 knowledge notes in [`sources/`](sources/) (index:
[`training-materials-links.md`](training-materials-links.md)).
**Source of every quote:** the text each source's own download produced on this PC. Every quote below was checked word
for word against those files before this file was committed.

## 1. What was read

The operator was given 56 free links, found by searching Reddit recommendation threads and following them to the
material itself. All 56 have a note.

| | Links |
|---|---|
| Downloaded and read in full by one agent each (the 141,835-word Quantopian forum index by seven agents) | 40 |
| Short pages, read in full (menus, READMEs, short pages) | 9 |
| Read by another route on Nov 19, 2026 (see below) | 6 |
| Read second-hand only (the site bars AI agents) | 1 |
| Quotes in the notes, each found word for word in its source | 3,557 |

**The six read by another route, Nov 19, 2026:** the quantstrat workshop slides (Google's HTML view of all 78 slides),
Tiingo's documentation and the DataCamp course page (rendered in a browser; DataCamp's robots.txt allows AI agents),
the ESL book page (through its frames, including the full table of contents), quant.stackexchange (Stack Exchange's
official API: 60 top-voted questions and their best answers), and *Causal Factor Investing* (Cambridge's open-access
copy of the same book SSRN would not serve). **The one read second-hand:** López de Prado's lecture 1, which lives only
on SSRN, whose robots.txt bars AI agents from the whole site; CXO Advisory's summary of the lecture series was read
instead and is labelled as such.

**The honest limit.** Many links are a front door: a blog's home page, a book's landing page, a repo's README, an
index of articles. Each front door was read in full, but the teaching behind some of them (the posts, the PDFs, the
notebooks) sits one click further in. This analysis is strong on *what the experts warn about* and *which ideas they
name*; where it gives a method or a number, it comes from the sources that were read whole (the book, the slides, the
excerpt, the Q&A, the comment threads). Section 6 lists what to read next.

## 2. Which sources are worth your time

**The core: read these first.** They speak directly to how this app tests and trades.

| Id | Source | Why |
|---|---|---|
| [68CF1E4C](sources/68CF1E4C.md) | Rob Carver, "start here" page and its comment thread | Costs, tight stops, crash fills, implicit fitting, the "pure test" |
| [AD774F84](sources/AD774F84.md) | Rob Carver's blog, Nov 2026 posts | Optimising with costs; choosing by bad outcomes; AI and overfitting |
| [BCA2B653](sources/BCA2B653.md) | Marcos López de Prado, lectures | Why most backtests are false; what to do about it |
| [D1E57A8C](sources/D1E57A8C.md) | López de Prado, publications | The papers behind it: Deflated Sharpe, overfitting probability, the False Strategy Theorem |
| [64103548](sources/64103548.md) | López de Prado, software | The code for those papers (GNU-GPL, "for non-business purposes only") |
| [467ADC99](sources/467ADC99.md) | Timothy Masters, TSSB | Why a walk-forward test alone is not enough |
| [ECB84568](sources/ECB84568.md) | Kevin Davey, free book excerpt | Real losses many times the planned stop; sample size; reversing a loser |
| [ECC89D1D](sources/ECC89D1D.md) | Davey, free calculators | Monte Carlo, and a "probability cone" to watch live results |
| [E4C53D34](sources/E4C53D34.md) | Davey, article index | 85 article titles: stops, high win rates, risk of ruin |
| [20ED5DC9](sources/20ED5DC9.md) | Stefan Jansen, *ML for Trading* repo | Costs as a limit on the whole workflow; multiple-testing tools |
| [24508276](sources/24508276.md) | Ilya Kipnis's blog | Fill timing; "timing luck" from the start day |
| [F817B7A9](sources/F817B7A9.md) | Ernest Chan's blog | Feature selection and overfitting in machine learning |
| [4DCEB70E](sources/4DCEB70E.md) | Quantocracy | Re-tests of advertised rules on later years |
| [B4C39202](sources/B4C39202.md) | quantstrat (R) README | "A backtest cannot be unseen" |
| [E4FB3067](sources/E4FB3067.md) | John Ehlers, technical papers | Walk-forward's own problems; cycle-tuned indicators |
| [B60874BA](sources/B60874BA.md) | López de Prado, *Causal Factor Investing* (full book) | Why a pick can pass unseen days and still be false |
| [6B35AB6E](sources/6B35AB6E.md) | quantstrat workshop slides (2013, 78 slides) | Smooth settings over peaks; walk-forward done by hand; stop-size curves |
| [4686630A](sources/4686630A.md) | quant.stackexchange, top 60 questions | Hold-out size, pessimistic fills, Kelly's dangers, what stops really do |
| [D5C72713](sources/D5C72713.md) | López de Prado's lecture series (second-hand) | "The 7 reasons most machine learning funds fail" |

**Useful as tools or textbooks** (free, but not about this app's questions): *An Introduction to Statistical Learning*
([CEB3F52E](sources/CEB3F52E.md)), *The Elements of Statistical Learning* ([7CD6075B](sources/7CD6075B.md)), *Python for
Data Analysis* ([B82E8DD8](sources/B82E8DD8.md)), the Quantopian lectures ([877EA8D7](sources/877EA8D7.md)), Carver's
spreadsheets ([53DDE89B](sources/53DDE89B.md)) and pysystemtrade ([2EF0D137](sources/2EF0D137.md)).

**Low value for this app:** valuation and finance-school pages (Damodaran: [1882C4FF](sources/1882C4FF.md),
[26CD3759](sources/26CD3759.md), [7409942A](sources/7409942A.md); Wikipedia [5CBA8361](sources/5CBA8361.md); Tsay's data
page [80687756](sources/80687756.md); WorldQuant University [028F2747](sources/028F2747.md)), sales pages for paid books
([37EFD5EF](sources/37EFD5EF.md), [6B2EAD35](sources/6B2EAD35.md), [7278B0E2](sources/7278B0E2.md),
[6AFDFFCD](sources/6AFDFFCD.md), [9D579C06](sources/9D579C06.md)), and menus or empty shells (the rest; see the index).

## 3. The ten lessons, and how the app compares

Each lesson is what several sources agree on. "The app" is this repo as of Nov 18, 2026.

### 3.1 The best of many backtests is usually a winner by luck

> "Most discoveries in empirical finance are false, as a consequence of selection bias under multiple testing."
> — López de Prado ([BCA2B653](sources/BCA2B653.md))

> "your backtest now contains futher 'implicit' fitting (trying different stoploss variations) which probably means your
> sharpe ratio is overstated due to overfitting" — Carver ([68CF1E4C](sources/68CF1E4C.md))

Every extra setting you try makes the best one look better, even when none of them works. López de Prado gives tools
that correct for this: the **Deflated Sharpe Ratio** (shrinks the best score for how many were tried) and the
**Probability of Backtest Overfitting** (how often the best on old days lands in the bottom half on new days)
([D1E57A8C](sources/D1E57A8C.md), [64103548](sources/64103548.md)).

**The app: partly.** It already compares picks with random entries chosen the same way, and that comparison is how the
repo learned this lesson the hard way: the Pro Trader research (Oct 20, 2026) picked 2,255 strategies that made
−$0.23 a trade on 220,977 unseen trades, against −$0.22 for random entries. **Not done anywhere in the code:** no
Deflated Sharpe, no overfitting probability, and no count of tries printed beside a "best" result. A search of every
Python and TypeScript file on Nov 18, 2026 found none of them. The numbers of tries are large: Forecast v4 walks 24,480
rule sets, and the picker lab then tests 20 picker rules on top.

### 3.2 Walk-forward alone is not enough, and a test you reuse gets fitted too

> "Many developers believe that a basic walkforward test is sufficient to vet the performance of their proposed system.
> Unfortunately, this is far from true." — Timothy Masters ([467ADC99](sources/467ADC99.md))

> "It is easy to find a system that provides enticing walkforward performance but that goes on to fail miserably in
> actual trading." — Masters ([467ADC99](sources/467ADC99.md))

> "A backtest cannot be unseen" — quantstrat README ([B4C39202](sources/B4C39202.md))

Once you have looked at a result on the "unseen" days and changed anything because of it, those days are no longer
unseen. López de Prado calls it "test set overfitting" ([BCA2B653](sources/BCA2B653.md)).

**The app: this is its biggest open risk.** The daily picker re-chooses which rule set each room follows from the
recent days, again and again, and the picker lab chose among 20 picker rules by how they did on the same 73 days. The
two nights the lab was run gave opposite answers (12 of 20 picker rules made money on the store of Nov 11, 2026; one of
20 on the store of Nov 12, 2026). Part of that flip came from a change in how the store priced each coin's costs between
the two nights (RCA-2026-11-12-B), so it is not proof of reuse alone; but a ranking that flips that easily is the case
these sources warn about. The repo's own rule to check a v4 ranking on two nights already guards one half of this;
nothing yet measures how much of a winner's lead is selection.

### 3.3 Costs are more certain than profits, so measure them exactly and judge after them

> "costs are more certain than gross returns" — Carver ([AD774F84](sources/AD774F84.md))

> "What % of your account are you paying in costs annually?" — Carver ([68CF1E4C](sources/68CF1E4C.md))

> "Expectancy after slippage and commission costs should be $50 or greater." — Davey, for futures
> ([ECC89D1D](sources/ECC89D1D.md))

Carver measures each instrument's cost per trade, drops the ones that cost too much, and slows trading with a buffer.
Jansen treats costs as a limit on the whole workflow, not a footnote ([20ED5DC9](sources/20ED5DC9.md)).

**The app: ahead of these sources.** It charges Gate's fee both ways, each minute's own recorded order book, and
funding; it refuses trades whose cost eats the target; it keeps only rows paying 2:1 after fees; and since Nov 13, 2026
it prices skill fills at the recorded book (five room rule sets' 707 trades read +$131 as measured and −$1,125 at the
real book). **Not done:** Carver's question. No screen shows a room's yearly cost as a share of its account. Davey's
$50 rule is for futures contracts and does not carry over to a $100 crypto trade.

### 3.4 A planned stop is not a guaranteed exit, and leverage turns a gap into a wipe-out

> "It's safest to assume you'd have been filled at the low for the day - down around 22%." — Carver, on a 4% stop in a
> crash like October 1987 ([68CF1E4C](sources/68CF1E4C.md))

> "This was about seven times the maximum loss I had expected" — Davey, on a market that stayed locked for three days
> ([ECB84568](sources/ECB84568.md))

**The app: mostly covered.** Backtest v3 and the skill engine fill a stop that the price jumped past where the price
really was. The live guard refuses a stop past 80% of the distance to liquidation. At $5 margin and 20x, a gap past the
liquidation price loses the whole $5, not the $1 a 1% stop was meant to lose. **Not checked:** whether Backtest v2 books
a gapped stop at the stop price or where the price really was.

### 3.5 A high win rate can hide the loss that matters

Davey's article list asks about strategies with "90% or more winning trades" and has one titled "Pick Up Pennies, Get
Steamrolled" ([E4C53D34](sources/E4C53D34.md)). Quantocracy links re-tests of advertised rules on the years after their
authors stopped looking: an RSI(2) dip-buying rule published in February 2007 ("84% Claimed, 80.7% Measured" on the 20
years after), and a gold moving-average rule ("58% Claimed, 42.3% Measured") ([4DCEB70E](sources/4DCEB70E.md)). A win
rate measured on the days a rule was found on is higher than the one it earns later.

**The app: partly.** The rooms switch on rule sets that won 80% to 90% of their trades, so this applies directly. The
repo already knows the cost side of it (a loss is the stop plus the costs, a win is the target minus them, so equal
targets need about 62% wins to break even) and keeps only rows paying 2:1 after fees. What the sources add is the
size of the worst losing run against the total profit, which the room screens do not compare.

### 3.6 Small samples lie

Davey says a test needs hundreds of trades, and that the 10 or 20 he counted by hand when he started were not enough
([ECB84568](sources/ECB84568.md)). López de Prado adds that the more settings you try, the longer the test must be
([BCA2B653](sources/BCA2B653.md)).

**The app: at the low end.** Room rules switch on at 20 to 50 trades in the judging window. With thousands of rule sets
tried, that is the case López de Prado warns about: short windows and many tries.

### 3.7 When you trade, and when your day starts, can change the result

> "this is a strategy that is fairly sensitive to the exact execution due to its fairly high turnover." — Kipnis
> ([24508276](sources/24508276.md))

Kipnis found that trading at the next open instead of the same close cost about a fifth of his return, and that results
moved with the start day ("timing luck").

**The app: fills yes, start day no.** Entries already pay the book three seconds after the close, as practice does. Whether
a 4h or 1d result survives moving the candle boundary by an hour has not been tested.

### 3.8 Choose by the bad outcomes, not the average

Carver's Nov 2026 post argues for picking settings by a bad-outcome point (the 10% or 25% worst case) instead of the
middle ([AD774F84](sources/AD774F84.md)). Davey's calculators run Monte Carlo on a trade list and draw a "probability cone"
that live results should stay inside ([ECC89D1D](sources/ECC89D1D.md)).

**The app: partly.** Forecast v4 already sorts by the worst whole month. Monte Carlo exists only on one results page
(80% of 200 draws in profit). No room is checked against a cone built from its own backtest.

### 3.9 A pick can pass on unseen days and still be false

> "It could take decades to collect enough out-of-sample evidence to determine that the association is false"
> — López de Prado, *Causal Factor Investing* ([B60874BA](sources/B60874BA.md))

The book splits false findings in two. Noise mistaken for a pattern (from trying many versions) is what testing on
unseen days catches. A real pattern mistaken for a cause is not: if a strategy only makes money because it moves with
something else, it keeps passing unseen days until that other thing changes. Its own example shows the wrong model
fitting better than the right one.

**The app: not tested.** On Gate the obvious "something else" is BTC's direction. A strategy that buys coins mostly
wins when the whole market rises, whatever its signal says. Nothing checks whether a winning rule set's profit is just
the market's move. The test is cheap: fit each winning strategy's trade profits against BTC's move over the same
holds, and compare with random entries treated the same way.

### 3.10 Most ideas fail; prefer settings that sit on a smooth surface

> "Vast majority (90%+) of ideas will not work out" — the quantstrat authors ([6B35AB6E](sources/6B35AB6E.md))

> "no huge peaks based on small changes" — the same slides, on what a good setting looks like

> "in this case, the objective function chooses rather poor out-of-sample parameters" — their own walk-forward
> example, which chose by highest profit

A setting whose neighbours (one step longer, one step tighter) also do well is more likely to be real than a lone best
setting. In their walk-forward example, picking the highest profit on the choosing months gave poor settings on the
next month. The quant.stackexchange answers say the same in other words: use fewer settings, keep ones that do not
flip when nudged, and treat a hold-out as spent once it has been used to choose ([4686630A](sources/4686630A.md)).

**The app: not done.** Rule sets and strategy rows are ranked one by one; nothing asks whether a row's neighbours also
pass.

## 4. What the sources do not cover that this app needs

None of them deals with crypto perpetual futures: no funding settlements, no exchange liquidation at 20x, no order
books that change by the minute, no offers an API order cannot take. On costs and fills, this app's rules are more
detailed than anything in these materials. The materials are most useful on the question the app keeps failing:
**whether a winner chosen from many tries is real.**

## 5. What to do next, in order

Each is a suggestion for the operator to decide. Nothing has been changed in the app.

1. **Correct the winners for the number of tries.** Compute a Deflated Sharpe Ratio and the Probability of Backtest
   Overfitting for Forecast v4's rule sets, using the per-day results already filed for every rule set. Build it from
   the published papers: López de Prado's own code is offered "for non-business purposes only"
   ([64103548](sources/64103548.md)).
2. **Count the picker as a layer of tries.** Print beside any winner how many rule sets and picker rules were tried to
   find it, and test the picker on days no picker rule was chosen on.
3. **A probability cone per room.** From each room's backtest trades, draw the band its practice total should stay
   inside, and flag a room that falls below it (Davey's idea).
4. **Yearly cost as a share of the account, per room** (Carver's question).
5. **Check Backtest v2's gapped stops** against where the price really was (Carver, Davey).
6. **Test the trade floor.** How often does a rule set's verdict at 20 trades still hold at 100 and 200 (Davey)?
7. **Test timing luck.** Re-run a few 4h and 1d strategies with the candle boundary moved by one to three hours
   (Kipnis).
8. **Check winners against BTC's move.** For every rule set or strategy that made money on unseen days, fit its trade
   profits against BTC's move over the same holds, beside random entries ([B60874BA](sources/B60874BA.md)).
9. **Prefer smooth neighbourhoods.** When choosing among settings, rank by how well a setting's neighbours also do,
   not by the single best, and compare both on unseen days ([6B35AB6E](sources/6B35AB6E.md)).
10. **Keep a final hold-out that nothing has touched.** The newest stretch, used once only to confirm, never to choose.
    A 10-vote answer quotes Ernest Chan on its size: "we should at least have one-third as much test data as training
    data." ([4686630A](sources/4686630A.md)).

## 6. What to read next

The material that would turn these warnings into methods, all free:

- López de Prado's papers on the Deflated Sharpe Ratio, the Probability of Backtest Overfitting and the False Strategy
  Theorem (links in [D1E57A8C](sources/D1E57A8C.md)).
- Carver's posts "The three kinds of overfitting", "Optimising with costs" and "What is the right way to set stop
  losses" (listed in [68CF1E4C](sources/68CF1E4C.md)).
- Davey's articles on walk-forward testing, Monte Carlo and risk of ruin (listed in [E4C53D34](sources/E4C53D34.md)), and
  his Monte Carlo spreadsheet ([ECC89D1D](sources/ECC89D1D.md)).
- The Quantopian lecture notebooks ([877EA8D7](sources/877EA8D7.md)), and the free PDFs of *ISLR* and *ESL*.
- The TSSB manual, free by email from Timothy Masters ([467ADC99](sources/467ADC99.md)).

The four blocked sources can be added by saving them from a browser (each note says how).
