# FREE Algorithmic Trading Calculators | KJTradingSystems

- Link: https://kjtradingsystems.com/calculators.html
- Type: html (one web page by Kevin Davey listing ten trading calculators; four are spreadsheet downloads, three are small calculators built into the page, three are Investing.com tools shown inside the page)
- Free or paid: the page and every calculator on it say free; the books it names are sold on Amazon, and the "Strategy Factory workshop" it advertises is a course whose price the page does not state
- Words read of total: 1,343 of 1,343 (all 8,461 characters of the text file). No earlier summary exists for this source (no `sections/ECC89D1D.html`). The four spreadsheets and the six built-in calculators were NOT read: they are not in the saved files (see the last section).

## What it is

This is a single page on Kevin Davey's site, headed "10 Essential Trading Calculators You Need to Have". It lists ten calculators, each with a short paragraph saying what you type in and what comes out: two Monte Carlo spreadsheets (one also draws a "probability cone" for live results), an expectancy calculator, Fibonacci, pivot points, compounding, a forex pip value tool, an equity and drawdown curve spreadsheet, a current drawdown calculator and a part-time trading spreadsheet. It gives almost no formulas; the only hard numbers are two rules of thumb for expectancy. The rest of the page is an author bio, links to his books and course, and a disclaimer. It is a tool list, not a lesson, and several paragraphs read like text written for search engines.

## Everything it teaches

1. The page's stated aim: these tools are for modelling a strategy realistically, judging its risk and managing money.
> "these tools empower you to model strategies realistically, assess risk, and manage capital effectively"
Where: the opening paragraph, under "10 Essential Trading Calculators You Need to Have".

2. Monte Carlo Calculator And Probability Cone Calculator (spreadsheet): Monte Carlo is for the trades of a backtest, the probability cone is for following live results; you type in your trades, your starting money and "a few other values".
> "This is an advanced calculator, and includes both Monte Carlo analysis (for analyzing backtest trades) and Probability Cone analysis (for tracking live trading results)"
> "simply enter your trades, your starting equity and a few other values to perform a Monte Carlo probability analysis and Probability Cone analysis of your trading strategy"
Where: first calculator section; download `KJTradingSystems-MCandPC.xls` (click the screenshot).

3. Expectancy and Tharp Expectancy aka Risk/Reward Calculator (built into the page): first check that the strategy makes money on average after costs; the page gives two minimum figures, and you type in your average loss (the risk) and your average win (the reward).
> "If you do not have a profitable trading strategy - one with positive expectancy - chances are you will not get very far in algo trading."
> "Some rules of thumb: Expectancy after slippage and commission costs should be $50 or greater. Tharp Expectancy should be 0.10 or greater."
> "You can also treat this as risk/reward calculator, since you enter both the risk amount (Average loss) and the reward amount (average win)."
Where: second section; the calculator itself is a uCalc widget (id 221834) loaded by a script, not saved.

4. The same section says the risk/reward view compares what a trade is expected to make against the most it can lose.
> "This calculator allows you to compare the expected return on a trade against its maximum risk, helping you determine if it’s truly worth taking on that risk."
Where: second section, second paragraph.

5. FREE Monte Carlo Calculator/ Simulator (spreadsheet): a Monte Carlo-only version; same inputs (trades, starting money, a few other values); the author says he uses it nearly every day.
> "This is a more advanced calculator, but it is VERY powerful."
> "I use this simulator practically every day."
Where: third section; download `freemc.xls`.

6. Fibonacci Calculator (Investing.com tool in the page): gives Fibonacci retracement and extension levels; the page takes no side on whether they work ("Do you feel that Fibonacci numbers are important?").
> "Use this handy calculator to discover Fibonacci retracement and extension values."
> "The Fibonacci Calculator is powered by Investing.com"
Where: fourth section; an Investing.com frame, not saved.

7. Pivot Point Calculator aka Support & Resistance Calculator (Investing.com tool in the page): works out the main pivot levels and invites you to check yourself whether they are worth anything; because many traders watch them, they may act as support and resistance.
> "This handy calculator lets you try out the major pivot calculations. See for yourself whether pivots have any value!"
> "Since so many traders use pivots, these levels can also be used as support and resistance indicators."
Where: fifth section; an Investing.com frame, not saved.

8. Compounding Calculator aka Profit/Loss Ratio Calculator (built into the page): type in starting money, number of years and a yearly return, and it shows the account's size at the end. A second paragraph under the same heading describes a profit/loss ratio tool, which is a different thing (see the last section).
> "just enter your starting trading capital, the number of years, your annual rate of return, and you'll see how big your trading account will be at the end."
> "A profit/loss ratio calculator allows you to find the expected return on investment (ROI) in your trades."
Where: sixth section; a uCalc widget (id 221860), not saved.

9. Forex Pip Calculator (Investing.com tool in the page): type in the trade size and your account's currency to get what one pip is worth.
> "Simply enter the trade size, and your account currency base and the calculator will give you the value of a pip."
Where: seventh section; an Investing.com frame, not saved.

10. Equity And Drawdown Curve Calculator aka Position Sizing Calculator And Visualizer (spreadsheet): type in your trades and it draws the money curve and the drawdown curve; some people use it to see how a chosen way of sizing trades changes the curve.
> "Once you download this spreadsheet, simply enter your trade data, and the spreadsheet will create an equity curve, and a drawdown curve, for you."
> "Some astute traders use this as a position sizing calculator, so they can see the equity curves including their choice of position sizing approach."
> "A position sizing calculator is used to determine the amount of money you should invest in each trade."
Where: eighth section; download `equitydrawdowncurvebuilder.xls`.

11. Current Drawdown Calculator (built into the page): type in the highest the account has been and what it is now, and it gives how far down you are, in percent.
> "Simply enter your peak trading equity value, and your current trading equity value, and this calculator will return your current percentage drawdown."
> "Hopefully that number is very close to zero!"
Where: ninth section; a uCalc widget (id 221854), not saved.

12. Part Time Trading Calculator (spreadsheet): checks whether trading part time could pay enough to live on; the page gives no inputs or outputs.
> "Here is a spreadsheet that will help you determine if you can make it by part time trading. A real eye opener!"
Where: tenth section; download `part_time.xls`.

## Numbers and rules it gives

- Expectancy after costs must be at least $50; Tharp Expectancy at least 0.10. The page does not say per what ($50 per trade? per contract?) and gives no formula for either.
> "Expectancy after slippage and commission costs should be $50 or greater. Tharp Expectancy should be 0.10 or greater."
- Positive expectancy comes first; without it the rest does not matter.
> "It all starts here."
- The risk amount is the average loss and the reward amount is the average win.
> "you enter both the risk amount (Average loss) and the reward amount (average win)"
- Monte Carlo goes on backtest trades; the probability cone goes on live results.
> "Monte Carlo analysis (for analyzing backtest trades) and Probability Cone analysis (for tracking live trading results)"
- Current drawdown is a percentage worked out from the peak and the current account value (the page does not print the formula; the obvious reading is (peak − now) ÷ peak, which is my reading, not the page's words).
> "this calculator will return your current percentage drawdown"
- Compounding takes three inputs: starting money, years, yearly return.
> "just enter your starting trading capital, the number of years, your annual rate of return"
- Ten calculators; "roughly half" are the author's own.
> "10 Essential Trading Calculators You Need to Have"
> "Roughly half of these calculators you will not find anywhere else - they were developed by me for my personal trading."
- Author claims (not checkable here): over 30 years trading; over 100% a year three years running in a real-money contest, first or second each time; one Wiley 2014 book and 5 others.
> "He has been trading for over 30 years."
> "Three consecutive years Kevin achieved over 100% annual returns in a real time, real money, year long trading contest, finishing in first or second place each of those years."
> "(Wiley 2014) and 5 other best selling algo trading books"
- The one warning on the page.
> "Don't trade with money you can't afford to lose!"

## What it says on costs, overfitting, testing on unseen data, position size, leverage and stops

**Costs.** One sentence only: the $50 expectancy rule is measured "after slippage and commission costs", so the author judges a strategy on what is left after paying to trade, not before. Nothing on funding, spreads or how to estimate slippage.
> "Expectancy after slippage and commission costs should be $50 or greater."

**Overfitting.** Not covered. (A book title in the bio mentions "Data Mining to Monte Carlo Simulation", but the page says nothing about curve fitting.)

**Testing on unseen data.** Not covered as such. The nearest idea is the split between Monte Carlo on backtest trades and a "Probability Cone" for "tracking live trading results", which suggests checking live results against what the backtest led you to expect; the page does not say how the cone is drawn or when to act on it.

**Position size.** The equity and drawdown spreadsheet can show the curve under a chosen sizing method, and the page defines a sizing calculator as one that sets the money per trade from the trade's risk and reward and your target risk. No rule, percentage or method is given.
> "This is determined by taking into consideration the potential risk and reward of a trade, as well as your target level of risk."

**Leverage.** Not covered.

**Stops.** Not covered directly. The risk/reward tool uses the average loss as the "risk amount", and the support and resistance paragraph says such tools give hints on when to close a trade, without saying how.
> "these calculators also provide indicators for when it may be time to close a trade or adjust your position size for an optimal exit point"

## Claims we could test on our own data

1. **Monte Carlo on a room's or a strategy's trades.** Take one trade list (a Backtest v4 strategy's trades, a Forecast v4 rule set's walked trades, or a skill room's closed practice trades such as #D7EN8BNV's), redraw the order of the trades many times from the room's starting $5-per-trade wallet, and report the spread of ending profit and of the worst dip and worst losing run. The repo already counts "80%+ of 200 Monte Carlo draws in profit" as one of the skills' seven checks, so the machinery exists. The page does not say whether its spreadsheet reshuffles or redraws with repeats, how many runs it makes, or what "a few other values" are, so we would have to choose those and print them.
2. **A probability cone for practice against its backtest.** From a rule set's backtest trades, work out the average and the spread of profit per trade, draw the band that the running total should stay inside after N trades, and lay the room's real practice total on it; a room under the low edge is a warning. The page gives no band width, so the width (and its meaning) would be ours to state.
3. **Expectancy after every cost.** Our trade lists already pay the fee, the buy-sell gap and funding, so the average profit per trade is the page's "expectancy after slippage and commission costs". The $50 floor does not carry over: the author trades futures, and our trades are $100 of coin, so $50 a trade would be half of what is traded. Tharp Expectancy has no formula on this page, so it cannot be checked from this source alone.
4. **Risk against reward.** Average win and average loss per strategy are already in our lists; the repo's own break-even win rate (loss ÷ (win + loss)) is the test the page points at without stating it.
5. **Equity and drawdown curves.** Every row's trade log can draw its money curve and drawdown curve; the kit already shows the worst dip and the worst losing run.
6. **Current drawdown of each room.** (Highest practice total − current total) ÷ highest, per room, is a one-line figure that could sit on each room's tiles.
7. **Pivots.** The page itself says "See for yourself whether pivots have any value!"; a pivot-level entry could be measured as a signal family in the grid like any other. The pivot formulas are in the Investing.com tool, which was not saved, so the source does not give them.
8. **Compounding** does not match how the rooms trade: the runner stakes a flat $5 every trade, so a compounded figure would be a projection, never a measurement.

## Links it points to

Calculator downloads and tools (all free, as the page says):
- https://kjtradingsystems.com/KJTradingSystems-MCandPC.xls — no link text (a screenshot, image alt "Picture"): the Monte Carlo and Probability Cone spreadsheet. Free.
- https://kjtradingsystems.com/freemc.xls — no link text (screenshot, alt "Picture"): the Monte Carlo simulator spreadsheet. Free.
- https://kjtradingsystems.com/equitydrawdowncurvebuilder.xls — no link text (screenshot, alt "Picture"): the equity and drawdown curve spreadsheet. Free.
- https://kjtradingsystems.com/part_time.xls — no link text (screenshot, alt "Picture"): the part time trading spreadsheet. Free.
- Built into the page by a script, not links: `ucalc.pro/api/widget.js?id=221834` (expectancy), `id=221860` (compounding), `id=221854` (current drawdown).
- Shown inside the page in frames: https://ssltools.forexprostools.com/fibonacci-calculator/index.php?force_lang=1, https://ssltools.forexprostools.com/pivot-calculator/index.php?force_lang=1, https://ssltools.forexprostools.com/pip-calculator/index.php?force_lang=1&acc=12.
- https://www.investing.com/ — "Investing.com" (three times, the credit lines under the three Investing.com tools).

Author's other material:
- https://www.amazon.com/stores/Kevin-J-Davey/author/B00J34ZNPQ — "Amazon": his books. PAID (sold).
- /strategy-workshop-alt.html — "Strategy Factory workshop"; /strategy-workshop.html — "Algo Trading Workshop" / "Strategy Workshop" in the menus. A course; the page gives no price, so marked PROBABLY PAID (not stated).
- / — "article collection" (his free articles, per the page).
- Menus and footer: /backtest-series-blog.html "Backtest Series Blog", /podcasts.html "Podcasts", /my-algo-trading-books.html "Books", /articles.html "Trading Tips", /free.html "Resources", /about.html "About", /subscribe-to-my-algo-trading.html "Subscribe", /calculators.html "Calculators", /disclaimer.html "https://kjtradingsystems.com/disclaimer.html".
- A request address printed in the text: "kdavey @ kjtradingsystems.com".

## What I did not read, and doubts

- **None of the calculators themselves was read.** The four `.xls` spreadsheets are links only and were not downloaded; the three uCalc calculators and the three Investing.com tools load from other sites when the page opens and are not in the saved HTML. So this note has no formula for expectancy, Tharp Expectancy, the Monte Carlo runs, the probability cone, pivots, Fibonacci, compounding or the part-time sheet, and no idea how many Monte Carlo runs are made or what the "few other values" are.
- **The page states two Monte Carlo tools** and does not say how they differ except that one adds the probability cone.
- **The "$50 or greater" rule has no unit** beyond dollars (per trade? per contract?) and is written for the author's futures trading; it cannot be applied to $100 crypto trades as is.
- **The "aka" names look added for search engines.** "Compounding Calculator aka Profit/Loss Ratio Calculator": the inputs described (capital, years, yearly return) cannot compare "the potential profits against the potential losses of any given position", which the second paragraph says it does. "Equity And Drawdown Curve Calculator aka Position Sizing Calculator" is described as a curve drawer that some people also use to look at sizing. These second paragraphs read as generic filler.
- **Claims I could not check or that look doubtful:** the support and resistance paragraph says such tools "help explain the probability of price directions", while the same section asks you to "See for yourself whether pivots have any value!"; the risk/reward paragraph says the tool "provides useful visuals that illustrate various outcomes depending on whether the asset price rises or falls", which I could not see; the sizing paragraph says sizing reduces "the chances of excessive losses or gains", an odd aim.
- **Marketing:** "Verified Champion Trader", "award winning", "highly acclaimed", "best selling", the contest returns and the workshop plug are self-description and cannot be checked from this page. The page's hidden search-engine data (in the raw file only, not the text) calls him "World Champion", dates the page Nov 16, 2025, sets every calculator's price at 0 USD, and repeats the expectancy rules in a step list whose inputs are average win, average loss and win rate; I did not quote it because it is not in the text file.
