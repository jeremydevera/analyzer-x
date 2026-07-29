"""Curated ticker universe for the web UI dropdown.

TradingAgents works with any symbol Yahoo Finance covers (tens of thousands),
so an exhaustive dropdown would be unusable. This is a broad curated set of the
most-traded names across sectors, major ETFs, crypto, and a sampling of
international tickers (with exchange suffixes). The UI also offers a free-text
field for any symbol not listed here.

Format helper renders each as "TICKER (Company Name)" so the company is obvious.
"""

from __future__ import annotations

# ticker -> full company / instrument name
TICKERS: dict[str, str] = {
    # Mega-cap tech
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "GOOGL": "Alphabet Inc. (Class A)",
    "GOOG": "Alphabet Inc. (Class C)",
    "AMZN": "Amazon.com Inc.",
    "NVDA": "NVIDIA Corp.",
    "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.",
    "AVGO": "Broadcom Inc.",
    "ORCL": "Oracle Corp.",
    "ADBE": "Adobe Inc.",
    "CRM": "Salesforce Inc.",
    "AMD": "Advanced Micro Devices Inc.",
    "INTC": "Intel Corp.",
    "QCOM": "Qualcomm Inc.",
    "CSCO": "Cisco Systems Inc.",
    "IBM": "International Business Machines Corp.",
    "TXN": "Texas Instruments Inc.",
    "MU": "Micron Technology Inc.",
    "AMAT": "Applied Materials Inc.",
    "LRCX": "Lam Research Corp.",
    "ARM": "Arm Holdings plc",
    "PLTR": "Palantir Technologies Inc.",
    "SNOW": "Snowflake Inc.",
    "NOW": "ServiceNow Inc.",
    "PANW": "Palo Alto Networks Inc.",
    "CRWD": "CrowdStrike Holdings Inc.",
    "DELL": "Dell Technologies Inc.",
    "SMCI": "Super Micro Computer Inc.",
    "MRVL": "Marvell Technology Inc.",
    "UBER": "Uber Technologies Inc.",
    "ABNB": "Airbnb Inc.",
    "SHOP": "Shopify Inc.",
    "SPOT": "Spotify Technology S.A.",
    "NFLX": "Netflix Inc.",
    "DIS": "The Walt Disney Co.",
    "WBD": "Warner Bros. Discovery Inc.",
    "ROKU": "Roku Inc.",
    "SQ": "Block Inc.",
    "PYPL": "PayPal Holdings Inc.",
    "COIN": "Coinbase Global Inc.",
    "HOOD": "Robinhood Markets Inc.",
    "SOFI": "SoFi Technologies Inc.",

    # Financials
    "JPM": "JPMorgan Chase & Co.",
    "BAC": "Bank of America Corp.",
    "WFC": "Wells Fargo & Co.",
    "C": "Citigroup Inc.",
    "GS": "The Goldman Sachs Group Inc.",
    "MS": "Morgan Stanley",
    "SCHW": "Charles Schwab Corp.",
    "BLK": "BlackRock Inc.",
    "BX": "Blackstone Inc.",
    "AXP": "American Express Co.",
    "V": "Visa Inc.",
    "MA": "Mastercard Inc.",
    "BRK-B": "Berkshire Hathaway Inc. (Class B)",
    "BRK-A": "Berkshire Hathaway Inc. (Class A)",
    "PYPL2": "PayPal Holdings Inc.",

    # Healthcare / pharma
    "UNH": "UnitedHealth Group Inc.",
    "JNJ": "Johnson & Johnson",
    "LLY": "Eli Lilly and Co.",
    "PFE": "Pfizer Inc.",
    "MRK": "Merck & Co. Inc.",
    "ABBV": "AbbVie Inc.",
    "TMO": "Thermo Fisher Scientific Inc.",
    "ABT": "Abbott Laboratories",
    "DHR": "Danaher Corp.",
    "BMY": "Bristol-Myers Squibb Co.",
    "AMGN": "Amgen Inc.",
    "GILD": "Gilead Sciences Inc.",
    "CVS": "CVS Health Corp.",
    "MRNA": "Moderna Inc.",
    "NVO": "Novo Nordisk A/S (ADR)",

    # Consumer
    "WMT": "Walmart Inc.",
    "COST": "Costco Wholesale Corp.",
    "PG": "Procter & Gamble Co.",
    "KO": "The Coca-Cola Co.",
    "PEP": "PepsiCo Inc.",
    "MCD": "McDonald's Corp.",
    "SBUX": "Starbucks Corp.",
    "NKE": "Nike Inc.",
    "HD": "The Home Depot Inc.",
    "LOW": "Lowe's Companies Inc.",
    "TGT": "Target Corp.",
    "LULU": "Lululemon Athletica Inc.",
    "CMG": "Chipotle Mexican Grill Inc.",
    "MDLZ": "Mondelez International Inc.",
    "PM": "Philip Morris International Inc.",

    # Industrials / autos / aero
    "BA": "The Boeing Co.",
    "CAT": "Caterpillar Inc.",
    "GE": "GE Aerospace",
    "HON": "Honeywell International Inc.",
    "LMT": "Lockheed Martin Corp.",
    "RTX": "RTX Corp.",
    "DE": "Deere & Co.",
    "UPS": "United Parcel Service Inc.",
    "FDX": "FedEx Corp.",
    "F": "Ford Motor Co.",
    "GM": "General Motors Co.",
    "RIVN": "Rivian Automotive Inc.",
    "LCID": "Lucid Group Inc.",

    # Energy
    "XOM": "Exxon Mobil Corp.",
    "CVX": "Chevron Corp.",
    "COP": "ConocoPhillips",
    "SLB": "Schlumberger Ltd.",
    "OXY": "Occidental Petroleum Corp.",
    "ENPH": "Enphase Energy Inc.",
    "FSLR": "First Solar Inc.",

    # Comms / telecom
    "T": "AT&T Inc.",
    "VZ": "Verizon Communications Inc.",
    "TMUS": "T-Mobile US Inc.",
    "CMCSA": "Comcast Corp.",

    # ETFs / indices
    "SPY": "SPDR S&P 500 ETF Trust",
    "VOO": "Vanguard S&P 500 ETF",
    "IVV": "iShares Core S&P 500 ETF",
    "QQQ": "Invesco QQQ Trust (Nasdaq-100)",
    "DIA": "SPDR Dow Jones Industrial Average ETF",
    "IWM": "iShares Russell 2000 ETF",
    "VTI": "Vanguard Total Stock Market ETF",
    "ARKK": "ARK Innovation ETF",
    "SMH": "VanEck Semiconductor ETF",
    "XLF": "Financial Select Sector SPDR Fund",
    "XLE": "Energy Select Sector SPDR Fund",
    "XLK": "Technology Select Sector SPDR Fund",
    "GLD": "SPDR Gold Shares",
    "SLV": "iShares Silver Trust",
    "TLT": "iShares 20+ Year Treasury Bond ETF",
    "VXX": "iPath Series B S&P 500 VIX Short-Term Futures ETN",

    # Crypto (Yahoo format)
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
    "BNB-USD": "BNB",
    "XRP-USD": "XRP",
    "ADA-USD": "Cardano",
    "DOGE-USD": "Dogecoin",
    "AVAX-USD": "Avalanche",

    # International (exchange-suffixed, as Yahoo lists them)
    "0700.HK": "Tencent Holdings Ltd. (Hong Kong)",
    "9988.HK": "Alibaba Group (Hong Kong)",
    "7203.T": "Toyota Motor Corp. (Tokyo)",
    "6758.T": "Sony Group Corp. (Tokyo)",
    "AZN.L": "AstraZeneca plc (London)",
    "HSBA.L": "HSBC Holdings plc (London)",
    "SAP.DE": "SAP SE (Frankfurt)",
    "MC.PA": "LVMH Moet Hennessy Louis Vuitton (Paris)",
    "RELIANCE.NS": "Reliance Industries Ltd. (India NSE)",
    "TCS.NS": "Tata Consultancy Services Ltd. (India NSE)",
    "600519.SS": "Kweichow Moutai Co. (Shanghai)",
    "SHOP.TO": "Shopify Inc. (Toronto)",
    "BHP.AX": "BHP Group Ltd. (Australia)",
}


def label_for(ticker: str) -> str:
    """Return 'TICKER (Company Name)' for a known ticker, else just the ticker."""
    name = TICKERS.get(ticker)
    return f"{ticker} ({name})" if name else ticker


def options() -> list[str]:
    """Sorted 'TICKER (Company Name)' labels for the dropdown."""
    return [label_for(t) for t in sorted(TICKERS)]


def parse_ticker(label: str) -> str:
    """Extract the raw symbol from a 'TICKER (Company Name)' label.

    Falls back to the uppercased trimmed input so a free-typed symbol works too.
    """
    label = (label or "").strip()
    if "(" in label:
        return label.split("(", 1)[0].strip().upper()
    return label.upper()


def search(query: str) -> list[str]:
    """Curated labels matching `query` in the ticker OR company name (case-insensitive).
    Empty query returns the full list. Pure/testable."""
    q = (query or "").strip().lower()
    opts = options()
    if not q:
        return opts
    return [o for o in opts if q in o.lower()]
