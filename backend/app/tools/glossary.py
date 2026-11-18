# ruff: noqa: E501
"""Plain-language market terms for the assistant. Mirrors frontend/src/lib/glossary.ts;
a test keeps the two in step."""

GLOSSARY: dict[str, tuple[str, str, str]] = {  # key -> (term, group, text)
    "market order": (
        "Market order",
        "Orders",
        "Buy or sell right away at the best price available. Fast and certain to fill, but you do not control the exact price.",
    ),
    "limit order": (
        "Limit order",
        "Orders",
        "Buy only at or below a price you set (or sell at or above it). You control the price, but the order may never fill.",
    ),
    "stop-loss": (
        "Stop-loss",
        "Orders",
        "An order that sells automatically if the price falls to a level you choose, to cap a loss. Decide it before buying, when you are calm.",
    ),
    "target": (
        "Target",
        "Orders",
        "A price at which you plan to take profit. Here it becomes a limit sell order once your buy fills; if the stop-loss fills first, the target is cancelled.",
    ),
    "AMO": (
        "After-market order (AMO)",
        "Orders",
        "An order placed while the market is closed. It waits and is executed when trading opens at 9:15 IST, at whatever price the stock opens near.",
    ),
    "GTC": (
        "Good till cancelled",
        "Orders",
        "An order that stays open across days until it fills or you cancel it. A day order ends when the session closes at 3:30 pm.",
    ),
    "delivery": (
        "Delivery trade",
        "Orders",
        "Buying shares to keep them in your demat account, as opposed to intraday trading where positions are closed the same day.",
    ),
    "FIFO": (
        "FIFO",
        "Orders",
        "First in, first out: when you sell, the shares you bought earliest are treated as sold first. Indian tax rules use this to work out your gain and holding period.",
    ),
    "STT": (
        "Securities Transaction Tax (STT)",
        "Costs and tax",
        "A tax of 0.1% on both the buy and the sell value of delivery trades, collected by the exchange. It is not deductible when computing capital gains.",
    ),
    "stamp duty": (
        "Stamp duty",
        "Costs and tax",
        "A state levy of 0.015% on the buy value of delivery trades.",
    ),
    "DP charge": (
        "DP charge",
        "Costs and tax",
        "A fixed fee (about ₹16 including GST) charged by the depository and broker each day you sell a stock from your demat account, whatever the amount.",
    ),
    "break-even": (
        "Break-even price",
        "Costs and tax",
        "The sell price at which you get back exactly what you spent, after charges on both the buy and the sell. Below it you lose money even if the price rose a little.",
    ),
    "STCG": (
        "Short-term capital gains",
        "Costs and tax",
        "Profit on shares held 12 months or less, taxed at 20%.",
    ),
    "LTCG": (
        "Long-term capital gains",
        "Costs and tax",
        "Profit on shares held more than 12 months, taxed at 12.5% on gains above ₹1.25 lakh in a financial year.",
    ),
    "realised P&L": (
        "Realised vs unrealised",
        "Costs and tax",
        "Realised profit is locked in by selling. Unrealised profit is on shares you still hold and can still disappear.",
    ),
    "NIFTY 50": (
        "NIFTY 50",
        "Markets",
        "An index of 50 large Indian companies on the NSE. Holding it through an index fund is the simplest benchmark: a stock pick has to beat it to be worth the effort.",
    ),
    "benchmark": (
        "Benchmark",
        "Markets",
        "What you compare your result with. Making 8% sounds good until the market made 15% over the same dates.",
    ),
    "sector index": (
        "Sector index",
        "Markets",
        "An index of companies in one industry, like NIFTY IT or NIFTY Bank. It shows whether a stock moved because of its industry or its own news.",
    ),
    "circuit limit": (
        "Circuit limit",
        "Markets",
        "The most a stock may rise or fall in a day (for example 5%, 10% or 20%). At the limit, trading can freeze because no one will sell (or buy).",
    ),
    "ex-dividend": (
        "Ex-dividend date",
        "Markets",
        "From this date a new buyer does not get the declared dividend, so the price usually drops by about the dividend amount. Shareholders before it receive the cash.",
    ),
    "diversification": (
        "Diversification",
        "Markets",
        "Spreading money across several stocks and sectors so one bad pick cannot sink the whole account.",
    ),
    "IPO": (
        "IPO",
        "IPOs",
        "Initial public offering: a company sells shares to the public for the first time and then lists on the exchange.",
    ),
    "QIB": (
        "QIB",
        "IPOs",
        "Qualified institutional buyers: mutual funds, insurers, banks and foreign funds. Their demand in an IPO has historically been the best single guide to how it lists.",
    ),
    "NII": (
        "NII (HNI)",
        "IPOs",
        "Non-institutional investors: individuals and companies bidding more than ₹2 lakh.",
    ),
    "RII": (
        "Retail investor",
        "IPOs",
        "Individuals bidding up to ₹2 lakh. When the retail portion is heavily oversubscribed, lots are allotted by lottery.",
    ),
    "subscription": (
        "Times subscribed",
        "IPOs",
        "Shares bid for divided by shares offered. 20x means bids for twenty times the shares on offer.",
    ),
    "listing gain": (
        "Listing gain",
        "IPOs",
        "How far the opening price on the first trading day is above (or below) the issue price.",
    ),
    "lot size": (
        "Lot size",
        "IPOs",
        "The minimum number of shares you can bid for in an IPO, and the step size for larger bids.",
    ),
    "moving average": (
        "Moving average",
        "Indicators",
        "The average closing price over the last N days. Price above its 200-day average is a common sign of a long uptrend.",
    ),
    "RSI": (
        "RSI",
        "Indicators",
        "Relative Strength Index (0-100) compares recent gains with recent losses. Below 30 is often called oversold, above 70 overbought; neither is a guarantee.",
    ),
    "52-week high": (
        "52-week high",
        "Indicators",
        "The highest price of the past year. Distance from it shows how far a stock has fallen, or how close it is to a breakout.",
    ),
    "volatility": (
        "Volatility",
        "Indicators",
        "How much the price swings. Higher volatility means larger gains and losses are both more likely.",
    ),
    "P/E": (
        "P/E ratio",
        "Indicators",
        "Share price divided by earnings per share: how many years of current profit the price pays for. Compare it with similar companies, not across industries.",
    ),
    "backtest": (
        "Backtest",
        "Measuring results",
        "Running a set of rules on past prices to see how they would have done. Useful for rejecting bad ideas; a good backtest does not promise future results.",
    ),
    "out-of-sample": (
        "Out-of-sample check",
        "Measuring results",
        "Testing rules on a later period kept aside. Rules that only work on the years they were tuned on are probably fitted to noise.",
    ),
    "drawdown": (
        "Maximum drawdown",
        "Measuring results",
        "The largest fall from a peak to a later low. It is the pain you would have had to sit through.",
    ),
    "CAGR": (
        "CAGR",
        "Measuring results",
        "Compound annual growth rate: the steady yearly return that would turn the starting amount into the final one.",
    ),
    "win rate": (
        "Win rate",
        "Measuring results",
        "The share of closed trades that made money. A low win rate can still be profitable if the winners are much bigger than the losers.",
    ),
    "profit factor": (
        "Profit factor",
        "Measuring results",
        "Money made on winning trades divided by money lost on losing ones. Above 1 means you are ahead.",
    ),
    "exposure": (
        "Time in the market",
        "Measuring results",
        "The share of days a strategy held shares. Low exposure means the money sat in cash most of the time.",
    ),
    "buy-and-hold": (
        "Buy and hold",
        "Measuring results",
        "Buying once and keeping the shares. Any trading strategy should be compared with simply holding the same stock.",
    ),
}
