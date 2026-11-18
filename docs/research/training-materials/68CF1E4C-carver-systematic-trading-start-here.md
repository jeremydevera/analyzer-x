# Rob Carver — "Systematic trading" start-here page (68CF1E4C)

**Link:** https://qoppac.blogspot.com/p/systematic-trading-start-here.html
**Downloaded:** Nov 17, 2026, saved as `raw/68CF1E4C.html`, 8,484 words of text (`text/68CF1E4C.txt`), in the store
`G:\tradingagents-home\backtest\research\training-materials\`.
**Price:** free. The page says, in capitals, *"I DO NOT OFFER PAID FOR TRADING COURSES OR ANY OTHER SIMILAR PRODUCT."*
His four books are paid; nothing below comes from them.

## What it is

The index page of Rob Carver's blog. Carver spent 7 years at AHL, a large systematic hedge fund, and now trades his
own futures system with open-source code (pysystemtrade). The page is mostly a list of his posts, grouped by topic,
with a long comment thread where readers ask questions and he answers. The useful teaching is in that thread.

## What it teaches (each point quoted from the saved text)

1. **A great result on one market may be luck.** Asked about a simple S&P 500 system with a big backtest, he says:
   > "it's not unknown to find relatively simple things that deliver a high SR on a single market. You don't know if
   > the original authors found that by luck (this was the first thing they tested) or by testing lots of variations
   > first."

2. **Every variation you try makes the backtest look better than it is.** The reader had tried several stop-loss
   sizes. Carver:
   > "your backtest now contains futher 'implicit' fitting (trying different stoploss variations) which probably
   > means your sharpe ratio is overstated due to overfitting"

3. **The honest test: many markets, many variations, chosen on data not used to pick them.**
   > "A pure test of this would be to run it on lots of markets, testing different SMA variations, testing different
   > stoplosses, and allocating amongst these variations out of sample ... You'd get a much lower SR."

4. **Tight stops mean constant trading, so costs and fill delays decide the result.**
   > "With a 1% stoploss you're going to be trading almost every day with a very short holding period. You need
   > intraday data and you need to test the effect of delaying your fills for an hour... up to a day or even several
   > days"
   > "You also need to make sure your trading costs are spot on. What % of your account are you paying in costs
   > annually?"

5. **A stop does not fill at the stop in a crash.** The reader asked whether a 4% stop would fill near 4% in a crash
   like October 1987:
   > "It's safest to assume you'd have been filled at the low for the day - down around 22%."

6. **High leverage turns a hidden risk into a wipe-out.**
   > "these kinds of systems ... are toxic with leverage because they have low average risk, but high peak risk. A
   > market shock when you are 100% in equities and 10 times leverage will kill you before you can get out of your
   > position."

7. **Trade only as fast as your holding period needs.** Asked how often to recalculate, he says:
   > "It depends on your holding period. Currently I probably update too much (hourly), given a holding period of a
   > couple of weeks or more."

8. **Some ways to trade cost far more than others.**
   > "spread betting is around 10 times more expensive than say trading futures."

## What it means for this app

- **Point 2 is the lesson our own research already paid for.** The grids test millions of combinations. The Pro
  Trader research (Oct 20, 2026) found the chosen strategies made −$0.23 a trade on unseen days while random
  entries made −$0.22. That is Carver's "implicit fitting" at scale.
- **Point 3 is what the walk-forward checks already do** (chosen on older days, judged on newer ones, against random
  picks). Carver's version adds "lots of markets": a rule should be judged across coins, not coin by coin.
- **Point 5 and point 6 apply directly to the rooms.** The rooms trade $5 margin at 20x, so $100 of coin, with stops
  of 1% to 2%. At 20x the exchange closes the position about 4.5% against it (CLAUDE.md, the 20x liquidation rule).
  A gap of 22%, Carver's crash case, would skip the 1% stop and the liquidation level both: the whole $5 margin is
  gone, not the $1 the stop was meant to lose. The v3 engine already fills a jumped stop "where the price was"
  (CLAUDE.md, Backtest v3 rules). I have not checked whether the v2 backtest does the same.
- **Point 4's question has no answer on any screen I know of.** The repo measures cost per trade (about $0.23 on a
  $100 trade, from the Oct 20, 2026 walk-forward), but I have not found a screen that shows yearly cost as a share
  of the account. Worth adding as a number beside each room.

## Review notes

- The agent's summary section passes on substance: all five quotes are real. Three failed the automatic quote check
  only because the agent put labels such as "Quote 1 (costs):" inside the quote. The digest builder needs to strip
  those labels before it checks (not fixed yet).
- The agent also fetched two posts from the "small fund" series. Those files hold WebFetch summaries, not Carver's
  words, so nothing from them is used here.
- Posts on this page worth documenting next, by their own titles: "What is the right way to set stop losses",
  "How fast should we trade?", "Using random data to design trading systems", "Optimising with costs, and a summary
  of the gold standard model", and "Optimising my way out of a small fund", parts two and four marked
  "(doesn't work)" and parts three and five marked "(works)".
