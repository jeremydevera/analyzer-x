# Python for Algorithmic Trading Cookbook

Link: https://github.com/PacktPublishing/Algorithmic-Trading-with-Python-Cookbook
Type: code repository (only the README text was saved)
Free or paid: the README is free; the book it belongs to is paid (Packt, sold through Amazon)
Words read of total: 653 of 653 words of the saved text (all of it; the raw file is 673 words with its link markup)

## What it is

This is the GitHub page that holds the code for a paid Packt book, "Python for Algorithmic Trading Cookbook", by Jason Strimpel. The README is a short advert and setup sheet: a list of what the book covers, who it is for, the software you need, and five corrections to mistakes printed in the book. It does not teach any method in detail; every topic is one line naming a tool. The real teaching is in the book and in the code folders, and neither was saved.

## Everything it teaches

1. The book is a set of ready recipes for making, building and running trading strategies in Python.
> "Recipes for designing, building, and deploying algorithmic trading strategies with Python."
Where: the bold line under the title.

2. It promises step-by-step instructions that end with trading in a live setting.
> "have hands-on experience in a live trading environment"
Where: "What is this book about?".

3. You get free market data and clean it up with a tool called the OpenBB Platform.
> "Acquire and process freely available market data with the OpenBB Platform"
Where: the feature list, item 1.

4. You set up your own research workspace and fill it with market data.
> "Build a research environment and populate it with financial market data"
Where: the feature list, item 2.

5. You use machine learning to find things that might predict price moves ("alpha factors") and turn them into buy and sell signals.
> "Use machine learning to identify alpha factors and engineer them into signals"
Where: the feature list, item 3.

6. You use a tool called VectorBT to pick a strategy's settings with walk-forward optimization (the README names the method and does not explain it).
> "Use VectorBT to find strategy parameters using walk-forward optimization"
Where: the feature list, item 4.

7. You build backtests meant to be good enough for real use with a tool called Zipline Reloaded, and check how well each factor does.
> "Build production-ready backtests with Zipline Reloaded and evaluate factor performance"
Where: the feature list, item 5.

8. You write the code that connects to the broker Interactive Brokers and sends it an order.
> "Set up the code framework to connect and send an order to Interactive Brokers"
Where: the feature list, item 6.

9. The code is split into folders, and the recipes start by loading dates, pandas and OpenBB.
> "All of the code is organized into folders."
> "import datetime as dt import pandas as pd from openbb import obb"
Where: "Instructions and Navigations".

10. The reader is expected to already invest in stocks and know basic Python and pandas.
> "You should have experience investing in the stock market, knowledge of Python data structures, and a basic understanding of using Python libraries like pandas."
Where: "Following is what you need for this book".

11. All 13 chapters run on Python 3.10, the PostgreSQL database, OpenBB Platform 4 or newer and pandas 2 or newer, on any of Windows, Mac or Linux.
> "With the following software and hardware list you can run all code files present in the book (Chapter 1-13)."
Where: "Software and Hardware List".

12. Correction, page 34: the book's code averaged the whole volume column when it meant only rows 5 to 10 - average only the rows you mean.
> "**asset_2.volume.mean()** _should be_ **asset_2.volume[asset_2.index[5:10]].mean().astype(int)**"
Where: "Errata", item 1.

13. Correction, page 34: the book pointed at the wrong column by position; the volume column is position 4, not 5.
> "**asset_2.iat[10, 5]** _should be_ **asset_2.iat[10,4]**"
Where: "Errata", item 2.

14. Correction, page 34: the sentence explaining that result was wrong too, and the fixed sentence says the average goes into the cell at row 10, column 4.
> "The result is a scalar value corresponding to the mean of the 'volume' column, assigned to the cell located at row 10 and column 4 (which corresponds to the 'volume' column)."
Where: "Errata", item 3.

15. Correction, page 36: the option-chain table's column is spelled option_type, so every filter written with optionType must be changed.
> "the `chains` Dataframe contains a column named "option_type" and not "optionType"."
Where: "Errata", item 4.

16. Correction, page 49: the book names an OpenBB function (stocks.load) that the code does not use; the one really used is obb.equity.price.historical.
> "However, the method actually used is **obb.equity.price.historical**."
Where: "Errata", item 5.

## Numbers and rules it gives

- Chapters: 13.
> "(Chapter 1-13)"
- Python version 3.10 for every chapter.
> "Python version 3.10"
- A PostgreSQL database for every chapter (no version given).
> "PostgreSQL"
- OpenBB Platform version 4 or newer.
> "OpenBB Platform version 4+"
- pandas version 2 or newer.
> "pandas version 2+"
- Any operating system.
> "Windows, Mac OS X, and Linux (Any)"
- Errata page numbers 34, 36 and 49; rows 5 to 10 for the average; row 10, column 4 for the cell.
> "Page 34 (Code block snippet under section 5)"
> "asset_2.volume[asset_2.index[5:10]].mean().astype(int)"
> "Page 49 . It is stated as:"
- The author's experience: over 20 years (a claim about the author, not about trading results).
> "with a career spanning over 20 years in trading, risk management, and machine learning"
- The only rule for the reader is the entry requirement: stock-market experience plus Python and pandas (item 10 above).
- No trading numbers at all: no profit, win rate, fee, stop, target, size or date range anywhere.

## What it says on costs, overfitting, testing on unseen data, position size, leverage and stops

Costs: not covered. No fee, spread, slippage or funding is mentioned anywhere in the README.

Overfitting: not covered. The word does not appear; the nearest line is the walk-forward bullet (item 6), which names the method only.

Testing on unseen data: not covered in any detail. The README says VectorBT is used "to find strategy parameters using walk-forward optimization" and that Zipline is used to "evaluate factor performance", but it never says which data is held back, how long the windows are, or what result counts as a pass.

Position size: not covered.

Leverage: not covered.

Stops: not covered.

## Claims we could test on our own data

None. The README states no result with a number - no profit, win rate or test outcome - so there is nothing to check against our stores. It only names methods (machine-learning factors, walk-forward optimization, Zipline backtests) without saying what they found.

## Links it points to

There are no chapter links and no code-folder links in the README; it only says the code "is organized into folders".

- "Python for Algorithmic Trading Cookbook" (text link) and "copy" - https://amzn.to/4706Exu - the book on Amazon. PAID.
- Cover image link (alt text "Python for Algorithmic Trading Cookbook") - https://www.packtpub.com/en-in/product/python-for-algorithmic-trading-cookbook-9781835084700 - the book on Packt's shop. PAID. In the raw file this address starts with a stray "<", so the link as written may not open.
- Banner image with no text - https://www.packtpub.com/en-us/unlock?step=1 (image https://static.packt-cdn.com/assets/images/packt+events/finalGH_design_redeem.png) - a Packt "redeem" page; marketing.
- Banner image (alt text "https://www.packtpub.com/") - https://www.packtpub.com/?utm_source=github&utm_medium=banner&utm_campaign=GitHubBanner (image https://raw.githubusercontent.com/PacktPublishing/GitHub/master/GitHub.png) - Packt's home page; marketing.
- Cover image file - https://content.packt.com/_/image/xxlarge/B21323/cover_image_large.jpg.
- "PyQuant News" - https://www.pyquantnews.com/ - the author's site.
- "PyQuant Newsletter" - https://www.pyquantnews.com/subscribe-to-the-pyquant-newsletter - the README does not say if it costs money.
- "Getting Started With Python for Quant Finance" - https://www.pyquantnews.com/getting-started-with-python-for-quant-finance?utm_source=gh&utm_campaign=book - the author's course, called "best-selling"; the README gives no price, but "selling" suggests it is paid.

## What I did not read, and doubts

- I read all 653 words of the saved README and the raw file. I did not read the book (paid), the code in the folders, or any linked page; nothing else was saved.
- The README names 13 chapters but gives no chapter titles, so the six feature lines are the only map of the content I have.
- Most of it is marketing: "exciting features", "If you feel this book is for you, get your" (a buy link follows), "production-ready", "a live trading environment", "best-selling course" and the author's career are all stated, none shown. The two Packt banners are adverts.
- The link name ("Algorithmic-Trading-with-Python-Cookbook") does not match the book title ("Python for Algorithmic Trading Cookbook"); the README itself only uses the title.
- The heading says "Software and Hardware List" but no hardware is listed.
- The corrected page-34 sentence (item 14) is hard to follow: it speaks of an average "assigned to the cell located at row 10 and column 4", which mixes the two code fixes; I cannot check it without the book.
- The saved text shows broken characters where curly quote marks were (for example in "you'll" and "Master's"), so I avoided quoting those spots.
