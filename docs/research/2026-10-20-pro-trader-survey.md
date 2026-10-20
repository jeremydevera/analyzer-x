# Survey: what holds up out of sample, and what can pay ~0.25% a trade on Gate perps

Prepared Oct 20, 2026 for the Gate.io USDT-perps trader ($5 margin x 20x = $100 a trade, one position per coin, entries on CLOSED 15m-1d candles, fixed % stop and target, "2:1 after fees").
Literature survey only: no file in G:\analyzer-x was edited, no trading code was run, no order was sent. Two small math scripts (no market data) sit beside this file: `pro-trader-survey-scripts/barrier_math.py`, `pro-trader-survey-scripts/luck_counts.py`.

**How each source is tagged**
- **[read]** I read the relevant pages of the full text.
- **[abs]** abstract, publisher or repository page only.
- **[sec]** secondary summary (CXO Advisory, Alpha Architect, Quantpedia, news); treat its figures as unconfirmed.
- **[math]** my own derivation, checked by simulation.

**Evidence grades for the families:** **A** strong, out-of-sample, many markets · **B** decent (peer-reviewed and consistent, but in-sample or one market class) · **C** weak, anecdotal, unreviewed or contradicted.

---

## 0. The short version

1. Your measured "about $0.00 per trade before fees" is exactly what random entries give. With fixed barriers and no drift, a trade wins SL / (TP + SL) of the time and earns zero before costs. An edge is a win rate **above** that number. [math]
2. The lift you need over random is cost / (TP + SL): **6.2 points** at SL 1% / TP 2.69%, **3.4 points** at SL 2% / TP 4.69% (cost 0.23%). Your "cost / target under 20%" rule passes for all of these; the lift is the real hurdle. [math]
3. Gross profit per trade = drift x holding time (Wald's identity). For fixed % barriers that is about **S x TP x SL / sigma**, where S is the signal's yearly Sharpe while the trade is open and sigma the contract's yearly volatility. Tight stops on volatile coins need an S no published signal has. [math]
4. The best-documented edge, time-series momentum (trend following), shows single-contract Sharpe of roughly 0.4-0.8 in futures (Moskowitz, Ooi & Pedersen 2012, Fig. 2 [read]). That is enough only on **low- or moderate-volatility contracts with stops near your 2% room cap**; not on 80-150%-volatility alts, and not inside SL <= 1% except on the calmest contracts.
5. Crypto studies agree on one pattern (6+ papers): **large, liquid coins trend; small, illiquid coins revert**, and the reversal premium sits where your costs are highest.
6. Funding, open interest and liquidations are documented as carry and crash-risk variables. None has peer-reviewed evidence as a 15m-1d direction signal.
7. Your past-winner failure is what luck produces at your scale: among 3.8 million variants with 30 trades each, the best win rate expected from pure chance is about **73% when the truth is 30%** (section 4.2).
8. So: trend families on the right contracts, gates that make the fixed barriers fit volatility and liquidity, and pooled out-of-sample tests with multiple-testing corrections (sections 3 and 4).

---

## 1. The arithmetic every idea must pass [math]

### 1.1 Random baseline
For a price with no drift, the chance of touching TP before SL is **p0 = SL / (TP + SL)** (gambler's ruin for a Brownian path). At that win rate the gross expectation is exactly zero: p0 x TP - (1 - p0) x SL = 0. Your 3.8M-row average of ~$0.00 gross is what this predicts for rules with no drift.

### 1.2 Break-even and the lift you need
With a round-trip cost c on every trade, a win pays TP - c and a loss costs SL + c, so break-even is **p* = (SL + c) / (TP + SL)** and the lift over random is **p* - p0 = c / (TP + SL)**. "2:1 after fees" means TP >= 2 x SL + 3c, which pins p* at 33.3%.

Table 1 - barriers that pay exactly 2:1 after fees (c = 0.23%):

| SL | TP | cost / target | random win rate p0 | break-even | lift needed |
|---|---|---|---|---|---|
| 0.30% | 1.29% | 17.8% | 18.9% | 33.3% | 14.5 pts |
| 0.50% | 1.69% | 13.6% | 22.8% | 33.3% | 10.5 pts |
| 0.75% | 2.19% | 10.5% | 25.5% | 33.3% | 7.8 pts |
| 1.00% | 2.69% | 8.6% | 27.1% | 33.3% | 6.2 pts |
| 1.50% | 3.69% | 6.2% | 28.9% | 33.3% | 4.4 pts |
| 2.00% | 4.69% | 4.9% | 29.9% | 33.3% | 3.4 pts |
| 3.00% | 6.69% | 3.4% | 31.0% | 33.3% | 2.4 pts |

Wider payoffs (net ratio after the 0.23% cost): SL 1% / TP 3% = 2.25:1, p0 25.0%, break-even 30.8%, lift 5.8 · SL 1% / TP 4% = 3.07:1, p0 20.0%, break-even 24.6%, lift 4.6 · SL 2% / TP 6% = 2.59:1, p0 25.0%, break-even 27.9%, lift 2.9 · SL 2% / TP 8% = 3.48:1, p0 20.0%, break-even 22.3%, lift 2.3.

A 65-90% win rate at 2:1 would need a lift of 35-60 points over a ~30% random baseline. Nothing in the literature comes close, which matches what you observed.

### 1.3 How much signal is needed (Wald's identity)
Expected gross profit per trade = drift x expected holding time. For a driftless path the expected hold is **E[T] = TP x SL / sigma^2**, so with drift mu = S x sigma the gross is about **S x TP x SL / sigma**, and the Sharpe needed just to pay the cost is **S* = c x sigma / (TP x SL)**.

Table 2 - S* needed to break even (expected hold in days), c = 0.23%, sigma = yearly volatility on 24/7 days:

| sigma | SL 1% / TP 2.69% | SL 1.5% / TP 3.69% | SL 2% / TP 4.69% | SL 2% / TP 6% |
|---|---|---|---|---|
| 10% | 0.86 (9.8 d) | 0.42 (20 d) | 0.25 (34 d) | 0.19 (44 d) |
| 20% | 1.71 (2.5 d) | 0.83 (5.1 d) | 0.49 (8.6 d) | 0.38 (11 d) |
| 35% | 2.99 (0.8 d) | 1.45 (1.6 d) | 0.86 (2.8 d) | 0.67 (3.6 d) |
| 50% | 4.28 (0.4 d) | 2.08 (0.8 d) | 1.23 (1.4 d) | 0.96 (1.8 d) |
| 75% | 6.41 (0.2 d) | 3.12 (0.4 d) | 1.84 (0.6 d) | 1.44 (0.8 d) |
| 100% | 8.55 (0.1 d) | 4.16 (0.2 d) | 2.45 (0.3 d) | 1.92 (0.4 d) |
| 150% | 12.8 (<0.1 d) | 6.23 (0.1 d) | 3.68 (0.15 d) | 2.88 (0.2 d) |

What the literature offers for S: single-contract time-series momentum in futures has gross Sharpe of roughly 0.4-0.8 (MOP 2012 Fig. 2 plots 0 to ~1.2 for the 58 contracts, 52 significant at 5% [read]). Crypto trend papers report more, but in-sample and decaying (section 2.1). For a strategy that is in the market only part of the time, in-trade S = overall Sharpe / sqrt(time-in-market share).

Reading Table 2:
- With S around 0.5-1, only contracts with sigma up to about 20-35% clear the cost at SL 2%, and almost nothing clears at SL <= 1% unless sigma is about 10%.
- Inside your MAX TP 3% / MAX SL 1% preference (CLAUDE.md), documented edges reach only the calmest contracts: forex, indices, metals, the calmest large stock tokens.
- On 75-150% alts no published OHLCV signal is strong enough at SL <= 2%.
- Longer holds add funding: at 0.01% per 8 hours (about 0.03% a day) an 8.6-day hold pays about 0.26%, roughly doubling the cost. Your backtests already charge it.
- Lowering cost is the other lever (maker entries, tighter books), but that is outside a closed-candle market-order engine and outside this survey.

### 1.4 Simulation check [math]
Minute-step random walk, 60% yearly volatility, SL 2% / TP 4.69%, 20,000 trades per case (`barrier_math.py`):
- No drift: win 29.4% (formula 29.9%; the gap is minute-step overshoot), mean hold 0.99 d (formula 0.95 d), mean gross -0.03% (zero within sampling error).
- In-trade Sharpe 2: win 35.1%, mean gross +0.346% per trade (formula +0.313%).

### 1.5 Limits of this arithmetic
It is a Brownian sizing guide, not a forecast: real prices gap through stops, have fat tails and volatility clustering, stock tokens move mostly in US hours, and your engine settles exits minute by minute with each minute's recorded book cost. The prediction is testable on your own rows: bucket the 3.8M rows by sigma and barrier pair and compute (win rate - p0). If this arithmetic is right, the average lift is near 0 and net per trade near -c, and any real lift clusters in liquid, lower-volatility contracts with wider barriers.

---

## 2. Evidence by method

Each table: source · markets and years · out-of-sample? · edge and horizon · can it clear ~0.25% a trade at 15m-1d on liquid perps? · failure modes.

### 2.1 Time-series momentum and trend following

| Source | Markets, years | Out of sample? | Edge, horizon | Clears ~0.25% at 15m-1d? | Failure modes |
|---|---|---|---|---|---|
| [Moskowitz, Ooi & Pedersen 2012, JFE 104(2)](https://doi.org/10.1016/j.jfineco.2011.11.003) [read] ([PDF](https://fairmodel.econ.yale.edu/ec439/jpde.pdf)) | 58 futures (indices, FX, commodities, bonds), 1985-2009 | Yes: 1966-1985 sample Sharpe 1.1 ("strong out-of-sample evidence"); all 58 positive, 52 significant | 12-month lookback, 1-month hold; diversified Sharpe > 1; alpha about 1.58%/month vs Fama-French + UMD | Only on low-vol contracts held days to weeks (Table 2) | trends reverse beyond ~12 months; results are volatility-scaled |
| [Hurst, Ooi & Pedersen 2017, JPM 44(1)](https://www.TrendFollowing.com/whitepaper/Century_Evidence_Trend_Following.pdf) [abs/sec] | 67 markets, 1880-2016 | 137 years | 1-, 3-, 12-month signals combined; positive in every decade [sec] | Same as above | long flat spells |
| [Lemperiere et al. 2014, J. Investment Strategies](https://arxiv.org/abs/1404.3274) [abs] | commodities, FX, indices, bonds; futures since 1960, spot since 1800 | t about 5 since 1960, about 10 since 1800 | long trends show no degradation; **short trends have weakened**; saturation for very large signals | Favors daily/weekly regimes over intraday | short-horizon decay; over-extended moves |
| [Szakmary, Shen & Sharma 2010, JBF 34(2)](https://ideas.repec.org/a/eee/jbfina/v34y2010i2p409-426.html) [abs] | 28 commodity futures, 48 years, monthly | robust to data-mining adjustments, net of costs | dual-MA and **channel** rules positive in >= 22 of 28 markets | monthly horizon only | — |
| [Huang, Li, Wang & Zhou 2020, JFE 135(3)](https://profiles.wustl.edu/en/publications/time-series-momentum-is-it-there/) [abs] (against) | MOP-type universe | in and out of sample | little asset-by-asset predictability; pooled t-stat unreliable; a sample-mean rule does about as well | Warns single-contract trend is weak | — |
| [Kim, Tse & Wald 2016, JFM 30](https://ideas.repec.org/a/eee/finmar/v30y2016icp103-124.html) [sec] (against) | MOP-type futures | — | alpha 1.27%/month volatility-scaled vs 0.41% unscaled; unscaled is close to buy-and-hold | Your $100 size cannot be scaled, so expect the weaker version | — |
| [Liu & Tsyvinski 2021, RFS 34(6)](https://ideas.repec.org/a/oup/rfinst/v34y2021i6p2689-2727..html) [abs; WP figure sec] | BTC, ETH, XRP, ~2011-2018 | in-sample | strong time-series momentum at daily/weekly frequency; working paper: one-SD weekly BTC return → +3.16% next week | weekly horizon fits 1-10 day holds | early-market sample |
| [Liu, Tsyvinski & Wu 2022, JF 77(2)](https://papers.ssrn.com/abstract=3379131) ([WP read](https://cowles.yale.edu/sites/default/files/2022-10/LiuTsyvinskiWu2019%20COMMON%20RISK%20FACTORS.pdf)) | 1,707 coins, 2014-2018 | in-sample | cross-sectional 1-4-week momentum 2.5-4.1%/week long-short (3-week strongest); **only above-median size: 4.2%/week vs 0.6% insignificant** | large coins, weekly | bubble-era sample; costs not modeled |
| [Han, Kang & Ryu 2023, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565) [abs; cost details sec] | crypto, 2017-Aug 2023, 15 bps costs, portfolios liquidated on daily swings | realistic-friction test | **time-series momentum strong, cross-sectional weak**; concentrated in large winners; **losers rebound** | supports long-side trend | short squeezes |
| [Zarattini, Pagani & Barbon 2025](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/) [abs]; method via [CXO](https://www.cxoadvisory.com/technical-trading/crypto-asset-trend-following-strategies/) [sec] | BTC, then top-20 liquid coins, survivorship-free, 2015-Mar 2025 | in-sample; costs of 0.10/0.25/0.50% tested | Donchian ensemble on closes (5-360 days), long-only, trailing stop at the channel mid-point, 25% volatility target; net Sharpe > 1.5, alpha 10.8%/yr vs BTC | holds of days-weeks; a fixed TP caps the right tail it relies on | needs trailing exits and volatility sizing, which you do not have |
| [Grobys et al. 2025, FMPM](https://osuva.uwasa.fi/handle/10024/20018) [abs] | large-cap coins | — | crypto momentum crash-prone; one coin can make it insignificant; volatility management helps | — | crashes |
| [Grobys & Sapkota 2019, Econ. Letters 180](https://osuva.uwasa.fi/handle/11111/2278) [abs] | 143 coins, 2014-2018, monthly | — | no significant momentum | — | — |
| [Shen, Urquhart & Wang 2022, Financial Review 57(2)](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/) [abs] | BTC intraday, volume clock | — | first half-hour predicts last half-hour; strongest in high-volume/high-volatility sessions | No: basis points per trade | liquidity-driven |
| [Gao, Han, Li & Zhou 2018, JFE 129(2)](https://doi.org/10.1016/j.jfineco.2018.05.009) [abs]; [Baltussen, Da, Lammers & Martens 2021, JFE 142](https://repub.eur.nl/pub/131621) [abs] | SPY 1993-2013; 60+ futures 1974-2020 | — | last 30 minutes predicted by the rest of the day (option-dealer gamma hedging); reverts over the next days | No (basis points) | — |
| [Zarattini, Aziz & Barbon 2024](https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content) [read] | SPY, 2007-2024 | in-sample | intraday momentum: 19.6%/yr net at $0.0035 + $0.001 per share (~0.1 bp a side); **12 bps per day, hit ratio 43%** | No: 12 bps < your 23 bps round trip | — |

So what: trend following is the only family with A-grade, out-of-sample, many-market evidence, and it lives at daily-to-monthly horizons. Crypto adds strong but in-sample, decaying results, concentrated in large coins and on the long side. Intraday momentum is real but measured in basis points.

### 2.2 Breakouts (Donchian/turtle, range breaks, volatility channels) and their filters

| Source | Markets, years | Out of sample? | Finding | Clears ~0.25%? |
|---|---|---|---|---|
| [Brock, Lakonishok & LeBaron 1992, JF 47(5)](https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html) [abs] | DJIA 1897-1986 | in-sample, bootstrap nulls | MA and trading-range-break rules reject random walk, AR(1), GARCH-M, EGARCH | — |
| [Sullivan, Timmermann & White 1999, JF](https://www.fmg.ac.uk/publications/discussion-papers/data-snooping-technical-trading-rule-performance-and-bootstrap) [abs/sec] | same rules, wider universe, 100 years | Reality Check; 1987-1996 out of sample | best rule significant in-sample; out of sample 8.63%/yr before costs, insignificant [sec] | No |
| [Park & Irwin 2007, J. Econ. Surveys 21(4)](https://ideas.repec.org/a/bla/jecsur/v21y2007i4p786-826.html) [abs/sec] | survey | — | rules profited in many markets until the early 1990s; many studies flawed by snooping and ex-post selection | — |
| [Neely, Weller & Ulrich 2009, JFQA 44(2)](https://doi.org/10.1017/S0022109009090103) [abs] | FX | yes | filter/MA profits gone by the early 1990s (adaptive markets) | — |
| [Bajgrowicz & Scaillet 2012, JFE 106(3)](https://ideas.repec.org/a/eee/jfinec/v106y2012i3p473-491.html) [abs] | DJIA 1897-2011 | false-discovery-rate + persistence tests | low costs erase in-sample gains; **the future best rules could never be picked in advance** | No |
| [Gerritsen et al. 2020, FRL 34](https://ideas.repec.org/a/eee/finlet/v34y2020ics1544612319303770.html) [abs] | BTC daily 2010-2019 | bootstrap | trading-range breakouts forecast and beat buy-and-hold on Sharpe; **most value in strongly trending markets** | daily, maybe |
| [Corbet et al. 2019, FRL 31](https://ideas.repec.org/a/eee/finlet/v31y2019icp32-37.html) [abs] | BTC high-frequency | — | variable-length MA rules best | — |
| [Hudson & Urquhart 2021, Ann. Oper. Res. 297](https://link.springer.com/article/10.1007/s10479-019-03357-1) [abs] | ~15,000 rules, BTC + 3 coins | multiple-testing controls | significant in-sample, high break-even costs; **no out-of-sample predictability for BTC** | — |
| [Svogun & Bazan-Palomino 2022, JIFMIM 79](https://ideas.repec.org/a/eee/intfin/v79y2022ics1042443122000816.html) [abs] | 69 MA/breakout rules, daily and 1-minute, 2016-2021 | — | bubbles help ETH/XRP/LTC rules, not BTC | — |
| [Deprez & Frommel 2024, IREF 93](https://ideas.repec.org/a/eee/reveco/v93y2024ipbp858-874.html) [abs] | 75,360 rules, daily + intraday BTC | rules picked after costs by a multiple-hypothesis procedure, tested out of sample | beat buy-and-hold out of sample, mainly on risk | small |
| [Li, Wang, Wang & Yang 2023, J. Acct. & Finance 23(4)](https://articlegateway.com/index.php/JAF/article/view/6453) [abs] | BTC/ETH 2022-2023 | Reality Check | **no profitable rule** in either sample | No |
| [Anghel 2021, FRL 39](https://ideas.repec.org/a/eee/finlet/v39y2021ics1544612320304414.html) [abs] | crypto, ML vs technical rules | data-snooping + frictions | significant excess returns rare; returns look like risk premia | No |

Filters:
- **Bigger-timeframe trend filter:** no peer-reviewed test of a multi-timeframe filter was found. Indirect support: long trends are the robust ones (Lemperiere et al.); momentum pays after up markets ([Cooper, Gutierrez & Hameed 2004, JF 59(3)](https://academicnewsletter.sufe.edu.cn/info/361185) [abs]: 0.93%/month after up markets vs -0.37% after down, US 1929-1995); range breaks add most in trending regimes (Gerritsen et al.).
- **Volatility regime:** SPY intraday momentum earned **22 bps/day after NR4 days and 16 after NR7, vs 12 unconditional and -2 after "trend days"** (Zarattini et al. 2024, Table 5 [read], in-sample, one market).
- Keltner/ATR channels and Larry Williams volatility breakouts: no peer-reviewed test found (practitioner only).

So what: breakouts are the most-tested technical family. In-sample wins are common; out-of-sample persistence after costs is the exception, in crypto especially after 2020.

### 2.3 Volatility regimes (scaled positions and stops, compression breakouts, volatility filters)

| Source | Markets, years | Out of sample? | Finding | Use for you |
|---|---|---|---|---|
| Engle 1982 (Econometrica 50(4)); Bollerslev 1986 (J. Econometrics 31(3)) | all asset classes since | decades of replication | volatility clusters and mean-reverts, so it is forecastable; direction is not | A-grade basis for volatility GATES (family #3) |
| [Moreira & Muir 2017, JF 72(4)](https://www.nber.org/papers/w22208.pdf) [abs] | equity factors, FX carry | in-sample spanning tests | cutting exposure when volatility is high raises factor Sharpe ratios | sizing only — your size is fixed |
| [Cederburg, O'Doherty, Wang & Yan 2020, JFE 138](https://www.lehigh.edu/~xuy219/research/COWY.pdf) [abs/sec] | 103 equity strategies | real-time out of sample | managed versions usually do NOT beat unmanaged ones (72 of 103 lose [sec]) | caution on volatility timing |
| [Harvey et al. 2018, JPM 45(1)](https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf) [abs/sec] | 60+ assets, from 1926 | long history | volatility targeting raises Sharpe for equities and credit and cuts the left tail; not for commodities/bonds [sec] | — |
| [Daniel & Moskowitz 2016, JFE 122(2)](https://www.nber.org/papers/w20439) [abs] | US equity momentum, 1927+ | — | momentum crashes come in "panic" states (after declines, high volatility) during rebounds; dynamic scaling about doubles Sharpe | avoid momentum shorts after crashes (#5) |
| [Grobys et al. 2025](https://osuva.uwasa.fi/handle/10024/20018) [abs] | large-cap coins | — | volatility management mitigates crypto momentum crashes | same |
| Barroso & Santa-Clara 2015 (JFE 116(1); from memory, not re-checked) | US momentum | — | managing momentum's own volatility nearly removes crashes | — |
| [Hachemian, Tavernier & Van Royen 2013](https://www.cxoadvisory.com/technical-trading/higher-measurement-frequency-and-stop-losses-for-trend-followers) [sec] | 39 liquid futures, 2000-2012 | — | daily vs weekly trend signals: 5.3% vs 5.0%/yr net; stops cut max drawdown ~17% but drag on the best strategies | — |
| Squeeze / compression | — | — | no peer-reviewed directional test found; Bollinger's squeeze is practitioner; NR4/NR7 SPY result above (in-sample) | C-grade (#9) |

So what: you cannot scale the $100 position, so use volatility to decide WHICH trades fit your fixed barriers (#3) and to stay out of momentum in panic states (#5). Compression predicts that volatility will rise, not which way.

### 2.4 Mean reversion that is documented, and where it fails

| Source | Markets, years | Finding |
|---|---|---|
| Jegadeesh 1990 (JF); Lehmann 1990 (QJE) | US stocks | weekly/monthly reversal (classic) |
| [Nagel 2012, RFS 25(7)](https://www.nber.org/papers/w17653) [abs] | US stocks, industries | reversal returns are pay for providing liquidity; **high when VIX is high** |
| [Khandani & Lo 2011, J. Financial Markets 14(1)](https://www.nber.org/papers/w14465) [abs] | US equities | a simple market-making (reversal) strategy took heavy losses in the week of Aug 06, 2007, during deleveraging |
| [Lou, Polk & Skouras 2019, JFE 134(1)](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf) [abs] | US stocks | strategy profits fall entirely overnight or entirely intraday, often with opposite signs |
| Connors & Alvarez (books); [Pandey & Joshi 2023, arXiv](https://arxiv.org/abs/2306.12434) [abs] | equity ETFs | RSI(2)/IBS: IBS < 0.2 tends to rise next day, > 0.8 to fall; costs a concern; equity-ETF evidence only |
| [Kosc, Sakowski & Slepaczuk 2019, Physica A 523](https://ideas.repec.org/a/eee/phsmap/v523y2019icp691-701.html) [abs] | top-100 coins (2017-era) | short-term contrarian beats momentum |
| [Kozlowski, Puleo & Zhou 2021, Appl. Econ. Letters 28](https://fairfield.elsevierpure.com/en/publications/cryptocurrency-return-reversals/) [abs] | 200 coins, 2015-2019 | reversal at daily, weekly, monthly; **strongest in small, illiquid coins** |
| [Zaremba et al. 2021, IRFA 78](https://ideas.repec.org/a/eee/finana/v78y2021ics1057521921002349.html) [abs] | 3,600+ coins, daily | previous-day reversal driven by illiquidity; **the few largest coins show daily momentum instead** |
| [Bianchi, Babiak & Dickerson 2022, JBF 142](https://ideas.repec.org/a/eee/jbfina/v142y2022ics0378426622001418.html) [abs] | USD pairs, Mar 2017-Mar 2022 | reversal = liquidity provision, concentrated in low-activity pairs (adverse selection) |
| [Ficura 2023, FFA WP 5:003](https://wp.ffu.vse.cz/artkey/wps-202301-0003_impact-of-size-and-volume-on-cryptocurrency-momentum-and-reversal.php) [abs] | crypto, weekly | reversal in small/illiquid coins (t = -7.31), momentum in large/liquid (t = 2.33); closeness to the 1-week high predicts + for large (t = 4.93), - for small (t = -9.03) |
| [Dobrynskaya 2023, J. Alt. Investments](https://www.hse.ru/en/news/research/559533243.html) [sec] | ~2,000 coins, 2014-2020 | momentum up to ~2 weeks, reversal from 4-6 weeks |

Why it does not fit you: mean reversion's natural payoff is a small target, a wide stop and a high win rate, the opposite of "2:1 after fees"; in crypto the premium sits in illiquid coins whose spreads exceed your 0.23% average; and liquid coins show momentum, not reversal, at the daily horizon. It fails in trends, on news, and in deleveraging cascades (Aug 2007).

### 2.5 Crypto-specific data: funding, basis, open interest, liquidations

| Source | Finding | Horizon | Grade as a 15m-1d signal |
|---|---|---|---|
| [Schmeling, Schrimpf & Todorov 2023, BIS WP 1087](https://www.bis.org/publ/work1087.pdf) [abs] | carry (futures over spot) up to 60%/yr, >10% average for BTC/ETH; **high carry predicts future price crashes**; driven by trend-chasing small investors and scarce arbitrage capital | weeks-months | crash-risk filter: C+/B- |
| [He, Manela, Ross & von Wachter, arXiv 2212.06888](https://arxiv.org/abs/2212.06888) [abs] | perp prices deviate from no-arbitrage far more than in FX; deviations co-move across coins and shrink as markets mature; arbitrage Sharpe high even at top Binance fees | days | carry, not direction |
| [Christin, Routledge, Soska & Zetlin-Jones 2022](https://www.andrew.cmu.edu/user/azj/files/CarryTrade.v1.0.pdf) [abs] | crypto carry trade (spot long, perp short) in-sample Sharpe 7-10 | — | needs a spot leg |
| [arXiv 2510.14435](https://arxiv.org/pdf/2510.14435) [sec] | carry Sharpe 4.06 in 2024, negative in 2025 | — | decaying |
| [Inan 2025, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5576424) [abs] | the funding rate itself is forecastable out of sample (Binance, Bybit) | 8h | not a price forecast |
| Open interest | no peer-reviewed predictive study found | — | C (watch list) |
| [Soska et al. 2021, WWW '21](https://dl.acm.org/doi/fullHtml/10.1145/3442381.3450059) [abs/sec] | 425,000+ BitMEX liquidations; descriptive (leverage, cascades) | minutes-hours | C |
| [Lim 2026, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6579278) [sec]; [arXiv 2607.27070](https://arxiv.org/html/2607.27070v1) [sec] | Oct 10, 2025 cascade: futures led, basis swung within ~8 minutes, BTC -12.6% in 10 minutes on Binance; early-warning signals differ by event type | minutes | C |
| [Kim & Hansen 2026, arXiv 2607.09426](https://arxiv.org/abs/2607.09426) [abs] | order imbalance at quarter-hour openings predicts returns 4-12 h ahead, out of sample, six Binance perps | 4-12 h | C (needs trade data; unreviewed) |
| [Cong, Li, Tang & Yang 2023, Management Science 69(11)](https://www.nber.org/papers/w30783) [abs] | >70% of reported volume on unregulated exchanges is wash trading | — | caution for any volume signal ranked across venues |
| [Huang, Sangiorgi & Urquhart 2024, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4825389) [abs] | volume-weighted time-series momentum not explained by market/size/momentum, not caused by wash trading | weekly | B-/C, possible future knob for #1 |

Data on Gate: funding history (`GET /futures/usdt/funding_rate`) and contract statistics with open interest, long/short liquidation sizes and taker long/short sizes (`GET /futures/usdt/contract_stats`) per the [API v4 docs](https://www.gate.com/docs/developers/apiv4/en/) [read]; the history depth is not stated there, so measure it before relying on it.

So what: funding and basis are well documented as carry and crash-risk measures. As a 15m-1d direction signal, nothing peer-reviewed. Use them as filters (#8), test last.

### 2.6 Time of day, day of week, sessions

| Source | Markets, years | Finding | Use |
|---|---|---|---|
| [Baur, Cahill, Godfrey & Liu 2019, FRL 31](https://quantpedia.com/are-there-any-simple-calendar-effects-in-bitcoin-market/) [sec] | BTC, 15M+ observations, 7 exchanges | time-of-day/day-of-week effects vary over time with no consistent pattern; lower weekend volume; higher Monday returns; more activity while US stocks trade | no direction edge |
| [Eross, McGroarty, Urquhart & Wolfe 2019, RIBAF 49](https://ideas.repec.org/a/eee/riibaf/v49y2019icp71-81.html) [abs] | BTC 5-minute, 4 years | volume builds through the day and falls from ~4pm to midnight; volatility and liquidity peak at the major stock-market opens; thin early morning | liquidity cycle |
| [Dyhrberg, Foley & Svec 2018, Econ. Letters 171](https://ideas.repec.org/a/eee/ecolet/v171y2018icp140-143.html) [abs] | BTC on 3 US exchanges | highest activity and volatility and **lowest spreads during US market hours** | cost gate (#7) |
| [Long, Zaremba et al. 2020, FRL 35](https://repository.up.ac.za/handle/2263/76329) [abs] | 151 coins, 2016-2019 | same-weekday cross-sectional seasonality | small, cross-sectional |
| [Concretum Group (Pagani)](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/) [sec] | BTC high-frequency trend, 2018-2025 | gross returns strongly positive from Sunday ~7:00pm New York for ~24 h ("Monday Asia open"); no costs, no holdout | C, practitioner |
| Gao et al. 2018; Baltussen et al. 2021; Heston, Korajczyk & Sadka 2010 (JF 65(4)) | US equities, futures | first/last half-hour momentum; half-hour periodicity | basis points |
| [Lou, Polk & Skouras 2019](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf) [abs] | US stocks | overnight vs intraday split of strategy profits | — |
| [Cong, Landsman, Rabetti, Zhang & Zhao 2026, slides](https://www.suomenpankki.fi/globalassets/bof/fi/ajankohtaista/tapahtumat/kalenteri/rabetti_sra2026.pdf) [sec] | tokenized stocks | off-hours token returns predict the stock's next open (1% → +0.28%): the token moved first | no token edge; matches your dead-book finding |

So what: return seasonality is measured in basis points and unstable, so reject it as direction. Liquidity seasonality is robust, so use it to cut cost (#7).

### 2.7 Exits: ATR stops and targets, time stops, trailing stops

| Source | Finding |
|---|---|
| [Kaminski & Lo 2014, J. Financial Markets 18](https://dspace.mit.edu/handle/1721.1/114876) [abs] | under a random walk, a stop-loss always lowers expected return; with momentum it can add value; empirically some stop rules raised return and cut volatility at longer sampling frequencies |
| [Lo & Remorov 2017, J. Financial Markets 34](https://dspace.mit.edu/handle/1721.1/107017) [abs/sec] | US stocks 1964-2014: tight stops underperform buy-and-hold because of costs and negative autocorrelation; performance is roughly linear in volatility and autocorrelation; wide stops help under regime switching |
| [Han, Zhou & Zhu, "Taming momentum crashes"](https://alphaarchitect.com/taming-the-momentum-roller-coaster-fact-or-fiction/) [sec] | a 10% stop on momentum stocks: worst month -49.79% → -11.34% (equal-weighted), Sharpe more than doubles, gross of costs |
| [Hachemian et al. 2013](https://www.cxoadvisory.com/technical-trading/higher-measurement-frequency-and-stop-losses-for-trend-followers) [sec] | stops cut trend-following drawdowns ~17% but drag on the best strategies |
| [Clare, Seaton, Smith & Thomas 2013, J. Asset Mgmt 14(3)](https://openaccess.city.ac.uk/17842) [abs] | S&P 500 1952-2011: simple trend rules beat buy-and-hold; complexity adds nothing for long signals |
| [Potters & Bouchaud 2005, arXiv](https://arxiv.org/abs/physics/0508104) [abs] | a trend follower's win fraction falls from 1/2 toward 0 as volatility rises; the win rate says nothing about reliability |
| [Zarattini, Aziz & Barbon 2024](https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content) [read] | tighter trailing stops: Sharpe 0.61 → 1.24, hit ratio 43%, skew -1.24 → +1.29, worst day -10.3% → -4.8% |
| [Carr & Lopez de Prado 2014, arXiv](https://arxiv.org/abs/1408.1159) [abs] | optimal profit-take/stop levels exist for mean-reverting (O-U) prices and can be computed without backtest tuning |
| Lopez de Prado 2018, *Advances in Financial Machine Learning* (Wiley) | the triple-barrier method (your fixed TP/SL is two of the three barriers) and meta-labeling |
| ATR-multiple exits, time stops | no peer-reviewed test found (practitioner books, e.g. Kestner 2003) |

So what for fixed TP/SL: trend families earn their money in the right tail, so they want the target far (3x the stop or more), accepting win rates of 20-30%. Mean reversion wants a near target and a wide stop, which "2:1 after fees" forbids. Time stops are unstudied, and your engine has none.

### 2.8 Validation practice (details and numbers in section 4)

| Source | What it gives you |
|---|---|
| [White 2000, Econometrica 68(5)](https://arch.readthedocs.io/en/latest/multiple-comparison/multiple-comparison-reference.html); [Hansen 2005, JBES 23](https://ideas.repec.org/p/wyi/wpaper/002018.html); [Romano & Wolf 2005, Econometrica 73(4)](https://uzh.ch/cmsssl/econ/dam/jcr:ffffffff-935a-b0d6-ffff-ffffa286d4d1/etca.pdf) [abs] | Reality Check / SPA: is the best of N variants better than a benchmark after accounting for the search? StepM: which variants survive |
| [Hsu, Hsu & Kuan 2010, J. Empirical Finance 17(3)](https://ideas.repec.org/a/eee/empfin/v17y2010i3p471-484.html) [abs] | stepwise SPA applied to technical rules |
| [Bailey & Lopez de Prado 2014, JPM 40(5), Deflated Sharpe Ratio](https://papers.ssrn.com/abstract=2460551) [abs] | deflates a Sharpe ratio for the number of trials and non-normal returns |
| [Bailey, Borwein, Lopez de Prado & Zhu 2017, J. Comp. Finance 20(4), PBO](https://papers.ssrn.com/abstract=2326253) [abs] | probability of backtest overfitting via combinatorially symmetric cross-validation (CSCV) |
| [Bailey et al. 2014, Notices of the AMS, "Pseudo-Mathematics"](https://carmamaths.org/jon/backtest.pdf) [abs] | minimum backtest length: with 5 years of data, try no more than 45 independent configurations, or an in-sample Sharpe of 1 is expected by luck |
| [Bailey & Lopez de Prado 2012, J. Risk 15(2)](https://www.risk.net/journal-risk/2223785/sharpe-ratio-efficient-frontier) [abs] | probabilistic Sharpe ratio, minimum track-record length |
| [Lopez de Prado & Bailey 2021, Amer. Math. Monthly 128(9)](https://escholarship.org/content/qt95t7k79q/qt95t7k79q.pdf) [abs] | False Strategy Theorem: the best of enough backtests looks great with zero true skill |
| [Harvey & Liu 2015, JPM](https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF) [abs]; [Harvey, Liu & Zhu 2016, RFS 29(1)](https://nber.org/papers/w20592) [abs] | Sharpe haircuts for multiple testing (a flat 50% is too lenient for low Sharpe ratios); t > 3.0 for a new factor |
| [Bajgrowicz & Scaillet 2012](https://ideas.repec.org/a/eee/jfinec/v106y2012i3p473-491.html) [abs] | the false-discovery-rate approach and the persistence test that past-best rules failed |
| Aronson 2006, *Evidence-Based Technical Analysis* (Wiley) | practitioner guide to Reality Check and Monte Carlo permutation tests for rules |

---

## 3. Proposed strategy families (ranked by evidence AND fit)

Conventions for every family:
- Entries on the CLOSE of the named candle; one position per coin; exits only by the fixed TP/SL, settled by the minute as your engine does.
- Barriers satisfy "2:1 after fees" with the row's own cost: **TP >= 2 x SL + 3 x c_row**. At c = 0.23%: SL 1.5% → TP 3.69%, SL 2% → TP 4.69%.
- Barrier pairs are your existing grid dimension, not a family knob, but **pre-register only the pairs listed** and count them in N (section 4).
- Stops stay inside your own limits: 2% for rooms (watcher `max_sl`), and 80% of the 20x liquidation distance (about 3.6% at a 0.5% maintenance rate; each Gate contract has its own rate).
- "Liquid tier" = rank by 30-day median daily quote volume on Gate, recomputed daily from past data only. sigma_d = standard deviation of the last 20 daily log returns (24/7 daily candles).

| Rank | Family | Kind | Evidence | Fit | New data? | Variants |
|---|---|---|---|---|---|---|
| 1 | Trend-gated closing breakout | entry rule | B (A for the mechanism in futures) | high | no | 8 |
| 2 | Time-series momentum on Gate's TradFi perps | entry rule | A | medium (37 contracts, funding) | no | 8 |
| 3 | Hold-time gate (barriers that fit volatility) | gate on any rule | B | very high | no | 6 |
| 4 | Liquidity-tier split (trend rules up top, reversal rules below) | gate on any rule | B | high | no | 12 |
| 5 | BTC market-state gate for altcoin signals | gate | B- | high | no | 12 |
| 6 | Cross-sectional strength gate | gate | B-/C+ | high | no | 12 |
| 7 | Session / spread gate (cost cut) | gate | B (mechanism; small effect) | high | no (your minute book) | 12 |
| 8 | Funding-crowding filter | gate | C+ | high | funding (on hand) | 12 |
| 9 | Compression breakout with trend agreement | entry rule | C+ | medium | no | 8 |
| 10 | Abnormal-day continuation, liquid tier | entry rule | C+ | medium | no | 12 |
| 11 | Liquidation-flush rebound | entry rule | C | low-medium | liquidation history | 8 |

Suggested test order: #3 and #4 first on the rules you already have (no new code paths), then #1 and #2, then the other gates on whichever entry rule survives, then #9-#11.

### #1 Trend-gated closing breakout — Evidence B · Fit high
- **Universe:** crypto perps in the liquid top 100, plus any contract that passes #3.
- **Timeframe:** 4h or 1d.
- **LONG** at the close of bar t when both hold:
  1. close(t) > highest CLOSE of bars t-1 ... t-N (Donchian channel on closes, as in Zarattini, Pagani & Barbon 2025);
  2. the L-day return (last closed daily close / daily close L days earlier - 1) > 0 (time-series momentum, MOP 2012).
- **SHORT** when close(t) < lowest close of bars t-1 ... t-N and the L-day return < 0.
- After an exit, a new entry needs a fresh breakout.
- **Knobs (8 variants):** N ∈ {20, 55} bars (Donchian/Turtle defaults) · L ∈ {30, 90} days (crypto momentum is strongest at 1-4 weeks per LTW 2022; 1-3 months per Hurst et al. 2017) · timeframe ∈ {4h, 1d}.
- **Pre-registered barriers:** SL 2.0% / TP 4.69% (net 2.0:1) and SL 2.0% / TP 6.0% (net 2.59:1).
- **What it adds:** your donchian20, turtle and nhigh50 read one timeframe; this adds a daily time-series-momentum gate and a closing-price channel, and with #3 it trades only where the barriers can collect drift.
- **Data:** OHLCV (funding charged as today).
- **Pre-registered expectation:**
  - Pessimistic (no edge): win about 29.9% / 25.0% (the random rate), net about -0.23% minus funding per trade.
  - If a literature-sized edge holds (in-trade S 1-2 on a 35-50%-volatility coin): win 32.7-35.5% (TP 4.69%) / 28-31% (TP 6%); break-even 33.3% / 27.9%; net -0.04% to +0.31% per trade.
  - Longs should beat shorts (losers rebound: Han, Kang & Ryu 2023; crashes during rebounds: Daniel & Moskowitz 2016).
  - Mood: persistent trends with rising volatility. Fails in ranges, whipsaws and V-shaped reversals.
  - Holding: about 1-3 days on 35-60%-volatility coins (Table 2).
  - Kill rule: pooled walk-forward win rate below break-even after >= 1,100 trades (TP 4.69%) or >= 1,500 (TP 6%).
- **Evidence:** A for trend following in diversified futures (MOP 2012 [read]; Hurst et al. 2017; Lemperiere et al. 2014; Szakmary et al. 2010). B in crypto (Liu & Tsyvinski 2021; Han, Kang & Ryu 2023; Zarattini et al. 2025; Gerritsen et al. 2020). Against: Hudson & Urquhart 2021 (no out-of-sample BTC predictability), Li et al. 2023 (nothing in 2022-23), Huang et al. 2020, Kim, Tse & Wald 2016. Net grade **B**.

### #2 Time-series momentum on Gate's TradFi perps — Evidence A · Fit medium
- **Universe:** contracts Gate lists as metals (12), indices (18), forex (4), commodities (3): 37 by your `venue.kind` count. Optional control: BTC, ETH.
- **Timeframe:** 1d, entry at the 12:00am UTC daily close.
- **LONG** when flat and every chosen lookback return is > 0; **SHORT** when every one is < 0; otherwise nothing.
- **Knobs (8 variants):** lookbacks ∈ {30 d; 90 d; 30 d and 90 d agree; 30 d, 90 d and 180 d agree} (Hurst et al. combine 1-, 3- and 12-month signals; MOP use 12 months; use whatever history each perp has) · re-entry ∈ {next close if the state still holds; only after the state flips}.
- **Pre-registered barriers:** SL 1.5% / TP 3.69%, SL 2.0% / TP 4.69%, SL 2.0% / TP 6.0%.
- **What it adds:** the family with the strongest literature, on the only Gate contracts it was measured on. Low volatility lets <= 2% barriers stay open long enough to collect the drift (S needed 0.25-0.49 at 10-20% volatility, Table 2).
- **Data:** daily OHLCV; **funding history is decisive** (holds of about 5-35 days; at 0.01% per 8 hours a 15-day hold pays about 0.45%). Check each perp's history depth first.
- **Pre-registered expectation:**
  - Pessimistic: win about 29.9% (SL 2% / TP 4.69%), net about -0.23% minus funding (about -0.7% on a 15-day hold that pays 0.01% per 8 hours).
  - If the per-contract Sharpe MOP measured (0.4-0.8, volatility-scaled, gross, 1985-2009) carries over unscaled: win 33.6-37.4%, gross +0.25% to +0.50%, net +0.02% to +0.27% before funding.
  - About 400-1,500 trades a year pooled across 37 contracts.
  - Mood: persistent macro trends; fails in choppy ranges and sharp policy reversals.
- **Evidence:** **A**: MOP 2012 [read] (all 58 contracts positive, 52 significant, 1966-1985 out-of-sample Sharpe 1.1); Hurst et al. 2017 (1880-2016, 67 markets); Lemperiere et al. 2014 (t about 5 since 1960); Szakmary et al. 2010 (net of costs in >= 22 of 28 commodities). Cautions: Huang et al. 2020 (weak asset by asset); Kim, Tse & Wald 2016 (unscaled alpha 0.41%/month vs 1.27% scaled [sec]); you cannot scale size, so expect the weaker unscaled version; perps add funding and closed-market hours.

### #3 Hold-time gate (make fixed barriers fit volatility) — Evidence B · Fit very high
- **Rule (any rule, long or short):** expected hold **E[T] = TP x SL / sigma_d^2** days (TP, SL as fractions). Take the signal only if T_min <= E[T] <= T_max.
- Examples: SL 2% / TP 4.69% with T_min = 1 day keeps only contracts with sigma_d <= 3.06% (about 58% a year). SL 1% / TP 2.69% with T_min = 1 day needs sigma_d <= 1.64% (about 31% a year).
- **Knobs (6 variants):** [T_min, T_max] ∈ {[0.5, 5], [1, 10], [2, 20]} days · sigma estimator ∈ {last 20 daily returns; last 7 days of hourly returns x sqrt(24)}.
- **What it adds:** volatility awareness for your fixed-% grid without changing the engine. It drops trades that end before any drift can pay the fee, and trades that would sit for weeks paying funding.
- **Data:** OHLCV.
- **Pre-registered expectation:** a gate cannot create an edge. On a rule with no drift, kept trades still lose about c each. On a rule with drift, kept trades should beat dropped trades by >= 0.05 points net per trade. Trade count falls 30-70% on alt-heavy rules. Works in every mood; matters most in wild markets.
- **Evidence:** **B**. The mechanism is arithmetic (Wald; Brownian barrier odds; simulation in 1.4). Lo & Remorov 2017: tight stops lose after costs, performance about linear in volatility and autocorrelation. Kaminski & Lo 2014. MOP 2012 scale every position by its own volatility. Harvey et al. 2018.

### #4 Liquidity-tier split — Evidence B · Fit high
- **Rule:** rank crypto perps by liquidity each day (past data only).
  - Momentum-type rules (breakouts, new highs, trend, momentum: your donchian20, nhigh50, turtle, bbbreak, relvolbrk, mom6, mom15, supertrend; families #1, #9, #10) fire only for coins ranked <= K.
  - Reversal-type rules (your rsi2, ibs, zscore20, fade15, crsi, willr14, stochrsi, vwaprev, gapfade) fire only for coins ranked > K **and** whose row's measured round-trip cost <= c_max.
- **Knobs (12 variants):** K ∈ {30, 100, 200} · liquidity measure ∈ {30-day median quote volume; 30-day median open interest} · c_max ∈ {0.25%, 0.35%}.
- **What it adds:** it chooses the rule TYPE by liquidity, the one cross-sectional pattern that repeats across crypto studies; your library applies every rule to every coin.
- **Data:** OHLCV volume (open interest optional).
- **Pre-registered expectation:** momentum rules in the top tier gain +1 to +3 points of win rate vs the same rules on all coins. Reversal rules in the low tier improve gross, but the pre-registered expectation is that costs eat it (the reversal premium is pay for supplying liquidity, earned where spreads are wide). Mood: the momentum side in trending, high-dispersion markets; the reversal side in wild, illiquid conditions, exactly when spreads are widest.
- **Evidence:** **B**: LTW 2022 [read] (momentum only above median size: 4.2% vs 0.6% a week); Zaremba et al. 2021 (3,600+ coins: daily reversal from illiquidity; the largest coins show daily momentum); Ficura 2023 (weekly reversal in small/illiquid, t = -7.31; momentum in large/liquid, t = 2.33); Begusic & Kostanjcar 2019 ([arXiv](https://arxiv.org/abs/1904.00890), strong momentum in the most liquid coins); Bianchi et al. 2022; Kozlowski et al. 2021; Grobys et al. 2025. All cross-sectional, daily/weekly, mostly before 2022.

### #5 BTC market-state gate for altcoin signals — Evidence B- · Fit high
- **Rule:** an altcoin LONG is allowed only if BTC's last closed daily close is above BTC's daily SMA(L); an altcoin SHORT only if it is below. Applies to #1, #4's momentum side, #9, #10 and your breakout/trend rules.
- **Knobs (12 variants):** L ∈ {20, 50, 100} · sides gated ∈ {longs only; both} · BTC state ∈ {close vs SMA(L); sign of BTC's L-day return}.
- **What it adds:** the crypto market factor as a regime filter; your rules read one coin at a time.
- **Data:** BTC daily OHLCV.
- **Pre-registered expectation:** trades -30% to -50%; win +1 to +3 points on the side kept; misses the first days of each BTC turn; hurts coin-specific runs. Mood: helps in clear BTC trends, hurts at turning points.
- **Evidence:** **B-**: LTW 2022 (a crypto market factor is one of the three that price the cross-section); Cooper, Gutierrez & Hameed 2004 (US momentum 0.93%/month after up markets vs -0.37% after down, 1929-1995); Daniel & Moskowitz 2016 (momentum crashes in panic states, during rebounds); Grobys et al. 2025 (crypto momentum crash-prone). No crypto test of this exact gate was found.

### #6 Cross-sectional strength gate — Evidence B-/C+ · Fit high
- **Rule:** each day rank the liquid top K by a strength measure; allow LONG signals only for coins in the top q, SHORT signals only for the bottom q.
- **Knobs (12 variants):** measure ∈ {7-day return; 21-day return; close / 7-day high} · q ∈ {20%, 30%} · K ∈ {50, 100}.
- **What it adds:** relative strength across coins; your rules are all single-coin.
- **Data:** OHLCV of the whole universe.
- **Pre-registered expectation:** win +1 to +3 points on longs; shorts weaker (losers rebound); fails in momentum crashes (sharp market rebounds), so pair it with #5. Mood: trending, high-dispersion markets. Works with any entry timeframe; the rank is daily.
- **Evidence:** For: LTW 2022 (1-4-week momentum 2.5-4.1%/week long-short, 3-week strongest), Dobrynskaya 2023 [sec] (peaks at 2 weeks, reverses from 4-6 weeks), Ficura 2023 (closeness to the 1-week high predicts + for large/liquid coins, t = 4.93), [Fieberg et al. 2025, JFQA 60(7)](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178) [abs] (an ML-combined trend signal over 3,000+ coins survives costs and persists in big, liquid coins). Against: Grobys & Sapkota 2019 (none, monthly), Kosc et al. 2019 (contrarian dominates), Han, Kang & Ryu 2023 (cross-sectional weak after costs), Grobys et al. 2025.

### #7 Session / spread gate (cost cut) — Evidence B for the mechanism, small effect · Fit high
- **Rule:** take a signal only if (a) its candle closes inside window W and (b) the entry minute's recorded spread (your per-minute book store) is at or below the coin's own P-th percentile of the last 30 days.
- **Knobs (12 variants):** W ∈ {all hours; 12:00pm-9:00pm UTC; for stock tokens, the US cash session 9:30am-4:00pm New York} · P ∈ {50, 75} · weekends ∈ {allowed; skipped}.
- **What it adds:** a cost filter. Your killzone is a direction idea and your daytime rule covers stock tokens' dead hours; neither keys on the spread you will actually pay.
- **Data:** your per-minute cost store; OHLCV.
- **Pre-registered expectation:** win rate unchanged; cost per trade down by an amount to be measured (pessimistic 0; plausible 0.01-0.04 points); trades -30% to -60%. All moods.
- **Evidence:** **B**: Dyhrberg, Foley & Svec 2018 (lowest spreads and highest activity in US hours); Eross et al. 2019 (liquidity highest at major exchange opens, thin early morning); Baur et al. 2019 [sec] (lower weekend volume, no consistent return pattern). Caution from Cong et al. 2023: rank liquidity on Gate's own book, not on other venues' reported volume.

### #8 Funding-crowding filter — Evidence C+ · Fit high
- **Rule:** skip a LONG when the coin's latest funding rate, annualized, is at or above its own P-th percentile over the last D days AND at least +20% a year; skip a SHORT when it is at or below the (100-P)-th percentile AND at most -20% a year.
- **Knobs (12 variants):** P ∈ {80, 90, 95} · D ∈ {30, 90} days · sides ∈ {longs only; both}.
- **What it adds:** positioning that only perps reveal, used to keep OTHER rules off the crowded side (your cf_fundfade trades the extreme itself).
- **Data:** per-contract funding history (`/futures/usdt/funding_rate`), which your cost model already reads.
- **Pre-registered expectation:** skips 5-15% of trades; the skipped trades should show lower win rates and larger losses than the kept ones. If they do not, out of sample, drop it. Mood: protects in euphoric, leveraged markets; idle when quiet.
- **Evidence:** **C+**: BIS WP 1087 (high carry predicts future crashes); He et al. (large, co-moving deviations that shrink as markets mature); Christin et al. 2022 (carry Sharpe 7-10 in-sample) and arXiv 2510.14435 [sec] (4.06 in 2024, negative in 2025); Han, Kang & Ryu 2023 (losers rebound, i.e. short squeezes). No peer-reviewed test of funding as a 15m-1d direction filter was found.

### #9 Compression breakout with trend agreement — Evidence C+ · Fit medium
- **Timeframe:** 1h or 4h.
- **Compression:** Bollinger bandwidth of BB(20, 2), i.e. (upper - lower) / middle, at or below its own q-th percentile of the last 120 bars.
- **Box:** highest high and lowest low of the last K bars.
- **LONG** if, within 5 bars after a compression bar, close > box high and the daily 30-day return > 0. **SHORT** if close < box low and the 30-day return < 0. One trade per compression episode.
- **Knobs (8 variants):** q ∈ {10%, 20%} · K ∈ {10, 20} · timeframe ∈ {1h, 4h}.
- **What it adds:** a per-coin, percentile-defined squeeze (your squeeze, nr7 and TTM rules use fixed thresholds) plus the daily trend filter; a low sigma at entry also lengthens holds (#3).
- **Data:** OHLCV.
- **Pre-registered expectation:** pessimistic = the random win rate; target +0 to +4 points; many false breaks back into the box. Mood: quiet turning to trending; fails in long ranges and on news spikes that reverse.
- **Evidence:** **C+**: volatility clustering is A (Engle 1982; Bollerslev 1986), but the direction of the break is not established; SPY intraday momentum earned 22 bps/day after NR4 days vs 12 unconditional (Zarattini et al. 2024 [read], in-sample, one market); the squeeze itself is practitioner lore.

### #10 Abnormal-day continuation, liquid tier — Evidence C+ · Fit medium
- **Rule (1d close):** daily return r >= +k x sigma_d(60) → LONG; r <= -k x sigma_d(60) → SHORT; only coins ranked <= K by liquidity.
- **Knobs (12 variants):** k ∈ {1.5, 2.0, 2.5} · K ∈ {20, 50} · volume confirmation ∈ {off; day volume >= 1.5 x its 20-day mean}.
- **What it adds:** liquidity conditioning and an abnormal-move threshold on top of your mom6/mom15.
- **Data:** OHLCV.
- **Pre-registered expectation:** pessimistic = the random win rate; target +0 to +3 points. Mood: news-driven trends; fails after liquidation spikes, which partly revert (pair with #8).
- **Evidence:** **C+**: Zaremba et al. 2021 (the largest coins show daily momentum); Liu & Tsyvinski 2021 (daily/weekly momentum); [Caporale & Plastun 2020, FMPM 34](https://bura.brunel.ac.uk/bitstream/2438/20686/6/FullText.pdf) [read]: their next-day strategy won 37-59% of 38-58 trades per coin and was significant for 1 of 3 coins, before costs; their same-day results need to know the day is abnormal before it ends.

### #11 Liquidation-flush rebound — Evidence C · Fit low-medium (data)
- **Rule (15m or 1h, liquid top 20 only):** LONG at the close of a candle whose long-liquidation notional (Gate `contract_stats`) is at or above its own P-th percentile of the last 30 days AND whose return <= -m x sigma (20 candles of the same timeframe). SHORT, mirrored, on short-liquidation spikes with return >= +m x sigma.
- **Knobs (8 variants):** P ∈ {95, 99} · m ∈ {2, 3} · timeframe ∈ {15m, 1h}.
- **What it adds:** actual liquidation data; your volclimax only infers it from volume.
- **Data:** per-contract liquidation history; depth unknown, so measure it first and shelve the family if it is under ~6 months.
- **Pre-registered expectation:** pessimistic = the random win rate or worse (cascades continue); target +0 to +5 points; high variance. "2:1" is a poor fit because rebounds are often partial. Mood: wild, capitulation phases.
- **Evidence:** **C**: Soska et al. 2021 (BitMEX liquidations, descriptive); Nagel 2012 (liquidity-provision returns rise with volatility); Khandani & Lo 2011 (liquidity provision lost heavily in a deleveraging week); Lim 2026 [sec] (Oct 10, 2025 cascade).

---

## 4. Validation: how many trades, and how to correct for many variants

### 4.1 Count what you tried
N is every variant you looked at, including the ones you threw away. Your 3.8 million backtests are N in the millions. They are correlated, so the effective N is smaller, but still large. The 11 families above add about 110 knob variants, roughly 300 with 2-3 barrier pairs each. Test each GATE on ONE pre-registered base set (for example #1 plus your top five breakout rules pooled), not on all 75 rules separately, or N explodes again.

### 4.2 What luck alone produces at your scale (`luck_counts.py`, exact binomial)
Best win rate expected among N variants when every variant's true win rate is 30% (2:1-type barriers):

| N variants | 20 trades | 30 trades | 50 trades | 100 trades | 300 trades |
|---|---|---|---|---|---|
| 100 | 55.9% | 51.2% | 46.4% | 41.6% | 36.7% |
| 10,000 | 69.6% | 62.3% | 55.0% | 47.7% | 40.2% |
| 1,000,000 | 79.9% | 70.7% | 61.5% | 52.3% | 42.9% |
| 3,800,000 | 82.5% | 72.9% | 63.2% | 53.5% | 43.6% |

When TP is close to SL (true win rate 45-50%), the count of pure-luck rows showing >= 80% wins among 3.8M variants is 5,817-22,454 at 20 trades, 366-2,719 at 30 trades and 2-45 at 50 trades. That is the arithmetic behind "past winners on 15-30-day windows did not persist", and it is the same thing Bajgrowicz & Scaillet (2012) found over a century of DJIA rules: the future best rules could not be picked in advance. (These counts assume independent variants; correlation lowers them, it does not remove them.)

### 4.3 Trades needed to show a real lift (one-sided 5%, 80% power, base win rate ~30%)

| Lift over random | 1 test | 100 variants | 10,000 variants | 1,000,000 variants |
|---|---|---|---|---|
| 2.4 pts (SL 3% / TP 6.69%) | 2,254 | 6,225 | 10,083 | 13,872 |
| 3.4 pts (SL 2% / TP 4.69%) | 1,123 | 3,102 | 5,024 | 6,912 |
| 4.4 pts (SL 1.5% / TP 3.69%) | 671 | 1,852 | 3,000 | 4,127 |
| 6.2 pts (SL 1% / TP 2.69%) | 338 | 933 | 1,511 | 2,079 |
| 10.5 pts (SL 0.5% / TP 1.69%) | 118 | 325 | 527 | 725 |

A gate (gated vs ungated arms, same base signals) needs 25,967 trades per arm to show +1 point, 6,492 for +2, 2,885 for +3. Trades on the same day across coins move together, so cluster by day (block bootstrap); the effective count is smaller than the raw count. Conclusion: per-coin, per-30-day evidence can never reach these numbers; only POOLED families across many coins and months can.

### 4.4 Protocol (pre-registered, in this order)
1. **Write down before testing:** family, knobs, barrier pairs, universe, timeframes, kill rule and accept rule. Log N.
2. **Split twice:** by time (monthly walk-forward; keep the most recent 3 months untouched as a final holdout) and by coins (choose on one half, confirm on the other; you already compute halves).
3. **Benchmark:** random entries on the same coins, the same hours and the same barriers give the empirical random win rate, drift and cost. Test the family's lift against it with a day-clustered bootstrap.
4. **Many variants:** Hansen's SPA (or White's Reality Check) over all variants of a family against that benchmark, on daily net P&L with a stationary bootstrap; Romano-Wolf StepM to keep the survivors; Benjamini-Hochberg-Yekutieli across families (as in Harvey, Liu & Zhu 2016).
5. **Overfitting checks:** PBO by CSCV with 16 time blocks (reject a family if PBO > 0.5, prefer < 0.2); Deflated Sharpe Ratio with N = variants tried; minimum backtest length (5 years of data supports about 45 independent trials at Sharpe 1).
6. **Report haircut Sharpe** (Harvey & Liu 2015): a flat 50% haircut is too lenient for low Sharpe ratios.
7. **Accept** only if the lower 95% bound of the pooled out-of-sample win rate is above break-even; **kill** if the pooled win rate is below break-even once the trade counts in 4.3 are reached.
8. **Forward check:** a practice room with frozen rules, compared trade by trade with the backtest (you already audit practice against backtest), before any real money.
9. **Re-check monthly**, judging families, never single rows.

---

## 5. Looked at and rejected

| Method | Why rejected |
|---|---|
| Intraday market momentum on stock tokens (first/last half-hour; noise-band intraday momentum) | Real but tiny: about 12 bps/day on SPY at ~0.1 bp costs (Zarattini et al. 2024 [read]); Gao et al. 2018; Baltussen et al. 2021. Cannot pay 23 bps a round trip. |
| Opening-range breakout on "stocks in play" | Already in your library (orb); the published edges assume equity commissions of fractions of a basis point. |
| Short-term cross-sectional reversal as its own family | Premium sits in small, illiquid coins where spreads exceed your average cost (Bianchi et al. 2022; Zaremba et al. 2021; Kozlowski et al. 2021); payoff shape conflicts with 2:1. Kept only as #4's low tier. |
| RSI(2) / IBS | Equity-ETF evidence (Connors; Pandey & Joshi 2023); already in your library; large coins show daily momentum instead; 2:1 conflict. |
| Pullback-in-uptrend (RSI(2) dip inside a daily uptrend) | No peer-reviewed test found (an AI-assisted ETF study and one continuous-time model only). Revisit only after #1 and #3 pass. |
| Calendar effects as direction (day of week, month, Monday Asia open, same weekday) | No consistent pattern (Baur et al. 2019); same-weekday effect is small and cross-sectional (Long et al. 2020); the Monday Asia-open result is gross, in-sample, practitioner. |
| Cash-and-carry funding harvest | Needs a spot leg; returns decaying (Sharpe 4.06 in 2024, negative in 2025 [sec]). |
| Volatility-managed position sizing | Your size is fixed; real-time evidence mixed (Cederburg et al. 2020). Volatility is used as a gate (#3) instead. |
| Post-earnings drift on stock tokens | Gone for large caps since 2006 ([Martineau 2022, Critical Finance Review 11](https://cfr.ivo-welch.info/published/papers/martineau2021rest.pdf) [abs], disputed in 2025); needs an earnings calendar; holds of weeks. |
| BTC → altcoin lead-lag at 15m+ | Intraday traders "can barely exploit" BTC-ETH price discovery at hourly/daily frequency ([Sifat, Mohamad & Mohamed Shariff 2019, RIBAF 50](https://ideas.repec.org/a/eee/riibaf/v50y2019icp306-321.html) [abs]). |
| Order-flow imbalance at quarter-hour marks | Interesting and out-of-sample (Kim & Hansen 2026), but needs trade-level data and is unreviewed. Watch list. |
| Open interest + price | No peer-reviewed predictive evidence found; Gate history depth unknown. Watch list (also a knob in #4). |
| ML entry models, meta-labeling | CTREND (Fieberg et al. 2025) shows ML-combined trend signals can survive costs cross-sectionally, weekly; at your variant count the overfitting risk is extreme. Revisit once CSCV/PBO is in place. |
| Pairs / statistical arbitrage | Two legs; your engine holds one position per coin. |
| Tokenized-stock off-hours signals | The token moves first and predicts the stock's next open (Cong et al. 2026 slides [sec]); books go dead while the home market is shut (your own finding). |
| Larry Williams volatility breakout, Keltner/ATR channels, ATR-multiple exits | No peer-reviewed test found (practitioner only); the testable part is folded into #9. |
| Volume-weighted time-series momentum | Promising (Huang, Sangiorgi & Urquhart 2024 [abs]) but details unpublished; candidate future knob for #1. |
| Unreviewed crypto trend preprint ([arXiv 2602.11708](https://arxiv.org/abs/2602.11708)) | Claims Sharpe 2.41 on 6-hour trend, 2022-2024; cost model not stated on the abstract page; not used. |

---

## 6. Data each family needs

| Data | Families | On hand? |
|---|---|---|
| OHLCV 15m-1d, all contracts | all | yes |
| BTC daily OHLCV | #5 | yes |
| 30-day median quote volume per coin (from OHLCV) | #4, #6, #10, liquid tier | yes |
| Funding history per contract | #2 (decisive), #8, cost model | yes (your funding reads) |
| Per-minute spread / book cost | #7 | yes (your minute cost store) |
| Open interest history | #4 (optional knob) | Gate `contract_stats`; depth to measure |
| Liquidation history | #11 | Gate `contract_stats`; depth to measure |
| Trade-level order flow | rejected (order-flow imbalance) | no |

---

## 7. If you want "a strategy per coin"

Assign families by coin TRAITS measured before the test, never by each coin's own backtest winners (section 4.2 shows why those do not persist):

| Trait, measured on past data | Families | Why |
|---|---|---|
| Yearly volatility up to ~30% (metals, indices, FX, the calmest large stock tokens in US hours) | #2; #1 with SL 1.5-2% | the only zone where stops of 2% or less leave room for documented edges (Table 2) |
| Volatility 30-60% and liquid top 100 | #1, #9, #10 with gates #3, #5, #6, #8 | trend and breakout in liquid coins (#4) |
| Volatility above ~60% | none at SL <= 2% unless a signal shows in-trade S above ~2; at most #11 on majors | arithmetic (Table 2) |
| Illiquid tail | no trend rules; reversal only where the measured cost <= c_max | #4 |

Stock tokens: Lo & Remorov 2017 found negative short-horizon autocorrelation in US single stocks, which makes tight-stop breakouts lose; keep stock tokens to the calmest large caps, SL near 2%, US hours only.

---

## 8. Ten-line summary

1. With fixed TP/SL and no edge, a trade wins SL/(TP+SL) of the time and earns $0 before costs; that is your 3.8M-row average, so an edge is a win rate above that line.
2. The lift you need is cost/(TP+SL): 6.2 points at SL 1%, 3.4 at SL 2% under "2:1 after fees"; gross per trade is about S x TP x SL / volatility.
3. Only trend following (time-series momentum) has A-grade, out-of-sample, many-market evidence; its single-contract Sharpe of ~0.4-0.8 pays the cost only on low/moderate-volatility contracts with stops near your 2% cap.
4. Inside SL <= 1% / TP <= 3%, documented edges cover only the calmest contracts (volatility ~10-20%); on 50-150% alts no published OHLCV signal is strong enough.
5. Crypto papers agree that liquid coins trend and illiquid coins revert, and the reversal premium is paid where your costs are highest.
6. Funding, open interest and liquidations are documented as carry and crash-risk measures, not as 15m-1d direction signals: filters only, tested last.
7. Time-of-day return effects are basis points; liquidity cycles are robust, so use sessions and spreads to cut cost, not to pick direction.
8. Ranked families: #1 trend-gated closing breakout, #2 trend on TradFi perps, #3 hold-time gate, #4 liquidity split, #5 BTC regime gate, #6 relative-strength gate, #7 session/spread gate, #8 funding filter, #9 compression breakout, #10 abnormal-day continuation, #11 liquidation rebound.
9. Past-winner failure is luck at scale: 3.8M variants with 30 trades each give a best chance-only win rate of ~73% when the truth is 30%.
10. Judge families pooled and out of sample (walk-forward plus coin halves) against a random-entry benchmark, with SPA/StepM, Deflated Sharpe and PBO; expect to need ~1,000-7,000 trades per family.

---

**Gates** — 1: every source tagged [read]/[abs]/[sec]; full text read for MOP 2012 (section 4, Fig. 2), Liu-Tsyvinski-Wu 2019 working paper, Zarattini-Aziz-Barbon 2024 (Table 5, section 4.6, trailing-stop section), Caporale-Plastun 2020 (strategy tables); every family leads with its no-edge (pessimistic) figure | 2: N/A for orders (no repo file, no engine code, no order path touched); the Brownian arithmetic's gaps against your minute-settled engine are named in 1.5 | 3: formulas re-checked by a 20,000-trade minute-step Monte Carlo (win 29.4% vs 29.9% formula, hold 0.99 d vs 0.95 d, Sharpe-2 gross +0.346% vs +0.313% formula); luck tables are exact binomial sums (`luck_counts.py`).

---

## References (grouped; links as used above)

**Trend / time-series momentum**
- Moskowitz, Ooi & Pedersen (2012), Time series momentum, JFE 104(2): 228-250. https://doi.org/10.1016/j.jfineco.2011.11.003 · PDF https://fairmodel.econ.yale.edu/ec439/jpde.pdf · data https://www.aqr.com/insights/datasets/time-series-momentum-original-paper-data
- Hurst, Ooi & Pedersen (2017), A century of evidence on trend-following investing, JPM 44(1). https://www.TrendFollowing.com/whitepaper/Century_Evidence_Trend_Following.pdf
- Lemperiere, Deremble, Seager, Potters & Bouchaud (2014), Two centuries of trend following, J. Investment Strategies. https://arxiv.org/abs/1404.3274
- Szakmary, Shen & Sharma (2010), Trend-following trading strategies in commodity futures: a re-examination, JBF 34(2): 409-426. https://ideas.repec.org/a/eee/jbfina/v34y2010i2p409-426.html
- Huang, Li, Wang & Zhou (2020), Time series momentum: Is it there?, JFE 135(3): 774-794. https://profiles.wustl.edu/en/publications/time-series-momentum-is-it-there/
- Kim, Tse & Wald (2016), Time series momentum and volatility scaling, J. Financial Markets 30: 103-124. https://ideas.repec.org/a/eee/finmar/v30y2016icp103-124.html
- Liu & Tsyvinski (2021), Risks and returns of cryptocurrency, RFS 34(6): 2689-2727. https://ideas.repec.org/a/oup/rfinst/v34y2021i6p2689-2727..html · NBER WP https://www.nber.org/papers/w24877
- Liu, Tsyvinski & Wu (2022), Common risk factors in cryptocurrency, JF 77(2): 1133-1177. https://papers.ssrn.com/abstract=3379131 · WP https://cowles.yale.edu/sites/default/files/2022-10/LiuTsyvinskiWu2019%20COMMON%20RISK%20FACTORS.pdf
- Han, Kang & Ryu (2023), Time-series and cross-sectional momentum in the cryptocurrency market under realistic assumptions, SSRN. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565
- Zarattini, Pagani & Barbon (2025), Catching crypto trends. https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/ · https://ideas.repec.org/p/chf/rpseri/rp2580.html · summary https://www.cxoadvisory.com/technical-trading/crypto-asset-trend-following-strategies/
- Grobys, Kolari, Sandretto, Shahzad & Aijo (2025), Cryptocurrency momentum has (not) its moments, FMPM. https://osuva.uwasa.fi/handle/10024/20018
- Grobys & Sapkota (2019), Cryptocurrencies and momentum, Economics Letters 180: 6-10. https://osuva.uwasa.fi/handle/11111/2278
- Borgards (2021), Dynamic time series momentum of cryptocurrencies, NAJEF 57. https://ideas.repec.org/a/eee/ecofin/v57y2021ics1062940821000590.html
- Shen, Urquhart & Wang (2022), Bitcoin intraday time series momentum, Financial Review 57(2): 319-344. https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/
- Gao, Han, Li & Zhou (2018), Market intraday momentum, JFE 129(2): 394-414. https://doi.org/10.1016/j.jfineco.2018.05.009
- Baltussen, Da, Lammers & Martens (2021), Hedging demand and market intraday momentum, JFE 142: 377-403. https://repub.eur.nl/pub/131621
- Zarattini, Aziz & Barbon (2024), Beat the market: an effective intraday momentum strategy for SPY, SFI WP 24-97. https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content

**Breakouts and technical rules**
- Brock, Lakonishok & LeBaron (1992), JF 47(5): 1731-1764. https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html
- Sullivan, Timmermann & White (1999), JF 54(5): 1647-1691. https://www.fmg.ac.uk/publications/discussion-papers/data-snooping-technical-trading-rule-performance-and-bootstrap
- Park & Irwin (2007), J. Economic Surveys 21(4): 786-826. https://ideas.repec.org/a/bla/jecsur/v21y2007i4p786-826.html
- Neely, Weller & Ulrich (2009), JFQA 44(2): 467-488. https://doi.org/10.1017/S0022109009090103
- Bajgrowicz & Scaillet (2012), JFE 106(3): 473-491. https://ideas.repec.org/a/eee/jfinec/v106y2012i3p473-491.html
- Gerritsen, Bouri, Ramezanifar & Roubaud (2020), FRL 34. https://ideas.repec.org/a/eee/finlet/v34y2020ics1544612319303770.html
- Corbet, Eraslan, Lucey & Sensoy (2019), FRL 31: 32-37. https://ideas.repec.org/a/eee/finlet/v31y2019icp32-37.html
- Hudson & Urquhart (2021), Annals of Operations Research 297: 191-220. https://link.springer.com/article/10.1007/s10479-019-03357-1
- Svogun & Bazan-Palomino (2022), JIFMIM 79. https://ideas.repec.org/a/eee/intfin/v79y2022ics1042443122000816.html
- Deprez & Frommel (2024), IREF 93: 858-874. https://ideas.repec.org/a/eee/reveco/v93y2024ipbp858-874.html
- Li, Wang, Wang & Yang (2023), J. Accounting and Finance 23(4). https://articlegateway.com/index.php/JAF/article/view/6453
- Anghel (2021), FRL 39. https://ideas.repec.org/a/eee/finlet/v39y2021ics1544612320304414.html
- Cooper, Gutierrez & Hameed (2004), Market states and momentum, JF 59(3): 1345-1365. https://academicnewsletter.sufe.edu.cn/info/361185

**Volatility**
- Moreira & Muir (2017), JF 72(4): 1611-1644. https://www.nber.org/papers/w22208.pdf
- Cederburg, O'Doherty, Wang & Yan (2020), JFE 138: 95-117. https://www.lehigh.edu/~xuy219/research/COWY.pdf
- Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert (2018), JPM 45(1): 14-33. https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf
- Daniel & Moskowitz (2016), Momentum crashes, JFE 122(2): 221-247. https://www.nber.org/papers/w20439
- Engle (1982), Econometrica 50(4); Bollerslev (1986), J. Econometrics 31(3); Barroso & Santa-Clara (2015), JFE 116(1) (cited from memory, not re-checked).
- Hachemian, Tavernier & Van Royen (2013), via https://www.cxoadvisory.com/technical-trading/higher-measurement-frequency-and-stop-losses-for-trend-followers

**Mean reversion and crypto cross-section**
- Nagel (2012), Evaporating liquidity, RFS 25(7): 2005-2039. https://www.nber.org/papers/w17653
- Khandani & Lo (2011), J. Financial Markets 14(1): 1-46. https://www.nber.org/papers/w14465
- Lou, Polk & Skouras (2019), JFE 134(1): 192-213. https://personal.lse.ac.uk/polk/research/TugOfWar.pdf
- Pandey & Joshi (2023), IBS on country ETFs, arXiv. https://arxiv.org/abs/2306.12434
- Kosc, Sakowski & Slepaczuk (2019), Physica A 523: 691-701. https://ideas.repec.org/a/eee/phsmap/v523y2019icp691-701.html
- Kozlowski, Puleo & Zhou (2021), Applied Economics Letters 28. https://fairfield.elsevierpure.com/en/publications/cryptocurrency-return-reversals/
- Zaremba, Bilgin, Long, Mercik & Szczygielski (2021), IRFA 78: 101908. https://ideas.repec.org/a/eee/finana/v78y2021ics1057521921002349.html
- Bianchi, Babiak & Dickerson (2022), JBF 142: 106547. https://ideas.repec.org/a/eee/jbfina/v142y2022ics0378426622001418.html
- Ficura (2023), FFA Working Papers 5:003. https://wp.ffu.vse.cz/artkey/wps-202301-0003_impact-of-size-and-volume-on-cryptocurrency-momentum-and-reversal.php
- Dobrynskaya (2023), Cryptocurrency momentum and reversal, J. Alternative Investments. https://www.hse.ru/en/news/research/559533243.html
- Begusic & Kostanjcar (2019), Momentum and liquidity in cryptocurrencies, arXiv. https://arxiv.org/abs/1904.00890
- Fieberg, Liedtke, Poddig, Walker & Zaremba (2025), JFQA 60(7): 3116-3153. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178
- Caporale & Plastun (2020), FMPM 34: 251-266. https://link.springer.com/doi/10.1007/s11408-020-00357-1 · PDF https://bura.brunel.ac.uk/bitstream/2438/20686/6/FullText.pdf
- Huang, Sangiorgi & Urquhart (2024), Cryptocurrency volume-weighted time series momentum, SSRN. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4825389

**Crypto derivatives data**
- Schmeling, Schrimpf & Todorov (2023), Crypto carry, BIS WP 1087. https://www.bis.org/publ/work1087.pdf
- He, Manela, Ross & von Wachter, Fundamentals of perpetual futures, arXiv 2212.06888. https://arxiv.org/abs/2212.06888
- Christin, Routledge, Soska & Zetlin-Jones (2022), The crypto carry trade. https://www.andrew.cmu.edu/user/azj/files/CarryTrade.v1.0.pdf
- Cryptocurrency as an investable asset class: coming of age, arXiv 2510.14435. https://arxiv.org/pdf/2510.14435
- Ackerer, Hugonnier & Jermann, Perpetual futures pricing, NBER WP 32936. https://www.nber.org/system/files/working_papers/w32936/w32936.pdf
- Inan (2025), Predictability of funding rates, SSRN. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5576424
- Soska, Dong, Khodaverdian, Zetlin-Jones, Routledge & Christin (2021), WWW '21: 45-57. https://dl.acm.org/doi/fullHtml/10.1145/3442381.3450059
- Lim (2026), Anatomy of a crypto cascade, SSRN. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6579278
- Early-warning signals across seven crypto-perpetual liquidation cascades, arXiv 2607.27070. https://arxiv.org/html/2607.27070v1
- Kim & Hansen (2026), The quarter-hour effect, arXiv 2607.09426. https://arxiv.org/abs/2607.09426
- Cong, Li, Tang & Yang (2023), Crypto wash trading, Management Science 69(11): 6427-6454. https://www.nber.org/papers/w30783
- Gate API v4 documentation. https://www.gate.com/docs/developers/apiv4/en/

**Sessions and calendar**
- Baur, Cahill, Godfrey & Liu (2019), FRL 31: 78-92 (summary) https://quantpedia.com/are-there-any-simple-calendar-effects-in-bitcoin-market/
- Eross, McGroarty, Urquhart & Wolfe (2019), RIBAF 49: 71-81. https://ideas.repec.org/a/eee/riibaf/v49y2019icp71-81.html
- Dyhrberg, Foley & Svec (2018), Economics Letters 171: 140-143. https://ideas.repec.org/a/eee/ecolet/v171y2018icp140-143.html
- Long, Zaremba, Demir, Szczygielski & Vasenin (2020), FRL 35: 101566. https://repository.up.ac.za/handle/2263/76329
- Concretum Group (Pagani), Seasonality in Bitcoin intraday trend trading. https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/
- Cong, Landsman, Rabetti, Zhang & Zhao (2026), tokenized stocks, conference slides. https://www.suomenpankki.fi/globalassets/bof/fi/ajankohtaista/tapahtumat/kalenteri/rabetti_sra2026.pdf
- Martineau (2022), Rest in peace post-earnings announcement drift, Critical Finance Review 11(3-4): 613-646. https://cfr.ivo-welch.info/published/papers/martineau2021rest.pdf
- Sifat, Mohamad & Mohamed Shariff (2019), RIBAF 50: 306-321. https://ideas.repec.org/a/eee/riibaf/v50y2019icp306-321.html

**Exits**
- Kaminski & Lo (2014), J. Financial Markets 18: 234-254. https://dspace.mit.edu/handle/1721.1/114876
- Lo & Remorov (2017), J. Financial Markets 34: 1-15. https://dspace.mit.edu/handle/1721.1/107017
- Han, Zhou & Zhu, Taming momentum crashes (summary). https://alphaarchitect.com/taming-the-momentum-roller-coaster-fact-or-fiction/
- Clare, Seaton, Smith & Thomas (2013), J. Asset Management 14(3): 182-194. https://openaccess.city.ac.uk/17842
- Potters & Bouchaud (2005), Trend followers lose more often than they gain, arXiv. https://arxiv.org/abs/physics/0508104
- Carr & Lopez de Prado (2014), Determining optimal trading rules without backtesting, arXiv. https://arxiv.org/abs/1408.1159
- Lopez de Prado (2018), Advances in Financial Machine Learning, Wiley.

**Validation**
- White (2000), Econometrica 68(5): 1097-1126; Hansen (2005), JBES 23: 365-380 https://ideas.repec.org/p/wyi/wpaper/002018.html; Romano & Wolf (2005), Econometrica 73(4): 1237-1282 https://uzh.ch/cmsssl/econ/dam/jcr:ffffffff-935a-b0d6-ffff-ffffa286d4d1/etca.pdf; implementations https://arch.readthedocs.io/en/latest/multiple-comparison/multiple-comparison-reference.html
- Hsu, Hsu & Kuan (2010), J. Empirical Finance 17(3): 471-484. https://ideas.repec.org/a/eee/empfin/v17y2010i3p471-484.html
- Bailey & Lopez de Prado (2014), The deflated Sharpe ratio, JPM 40(5): 94-107. https://papers.ssrn.com/abstract=2460551
- Bailey, Borwein, Lopez de Prado & Zhu (2017), The probability of backtest overfitting, J. Computational Finance 20(4). https://papers.ssrn.com/abstract=2326253
- Bailey, Borwein, Lopez de Prado & Zhu (2014), Pseudo-mathematics and financial charlatanism, Notices of the AMS 61(5). https://carmamaths.org/jon/backtest.pdf
- Bailey & Lopez de Prado (2012), The Sharpe ratio efficient frontier, J. Risk 15(2). https://www.risk.net/journal-risk/2223785/sharpe-ratio-efficient-frontier
- Lopez de Prado & Bailey (2021), The false strategy theorem, American Mathematical Monthly 128(9). https://escholarship.org/content/qt95t7k79q/qt95t7k79q.pdf
- Harvey & Liu (2015), Backtesting, Journal of Portfolio Management. https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF
- Harvey, Liu & Zhu (2016), ...and the cross-section of expected returns, RFS 29(1): 5-68. https://nber.org/papers/w20592
- Aronson (2006), Evidence-Based Technical Analysis, Wiley.
