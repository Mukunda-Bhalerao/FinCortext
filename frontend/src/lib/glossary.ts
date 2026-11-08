/** Plain-language explanations of market terms, shown on hover and on the Learn page.
 * Rates and rules are those in force for Indian equity delivery trades since 2024. */

export interface GlossaryEntry {
  term: string;
  group: "Orders" | "Costs and tax" | "Markets" | "IPOs" | "Indicators" | "Measuring results";
  text: string;
}

export const GLOSSARY: Record<string, GlossaryEntry> = {
  "market order": {
    term: "Market order",
    group: "Orders",
    text: "Buy or sell right away at the best price available. Fast and certain to fill, but you do not control the exact price.",
  },
  "limit order": {
    term: "Limit order",
    group: "Orders",
    text: "Buy only at or below a price you set (or sell at or above it). You control the price, but the order may never fill.",
  },
  "stop-loss": {
    term: "Stop-loss",
    group: "Orders",
    text: "An order that sells automatically if the price falls to a level you choose, to cap a loss. Decide it before buying, when you are calm.",
  },
  target: {
    term: "Target",
    group: "Orders",
    text: "A price at which you plan to take profit. Here it becomes a limit sell order once your buy fills; if the stop-loss fills first, the target is cancelled.",
  },
  AMO: {
    term: "After-market order (AMO)",
    group: "Orders",
    text: "An order placed while the market is closed. It waits and is executed when trading opens at 9:15 IST, at whatever price the stock opens near.",
  },
  GTC: {
    term: "Good till cancelled",
    group: "Orders",
    text: "An order that stays open across days until it fills or you cancel it. A day order ends when the session closes at 3:30 pm.",
  },
  delivery: {
    term: "Delivery trade",
    group: "Orders",
    text: "Buying shares to keep them in your demat account, as opposed to intraday trading where positions are closed the same day.",
  },
  FIFO: {
    term: "FIFO",
    group: "Orders",
    text: "First in, first out: when you sell, the shares you bought earliest are treated as sold first. Indian tax rules use this to work out your gain and holding period.",
  },
  STT: {
    term: "Securities Transaction Tax (STT)",
    group: "Costs and tax",
    text: "A tax of 0.1% on both the buy and the sell value of delivery trades, collected by the exchange. It is not deductible when computing capital gains.",
  },
  "stamp duty": {
    term: "Stamp duty",
    group: "Costs and tax",
    text: "A state levy of 0.015% on the buy value of delivery trades.",
  },
  "DP charge": {
    term: "DP charge",
    group: "Costs and tax",
    text: "A fixed fee (about ₹16 including GST) charged by the depository and broker each day you sell a stock from your demat account, whatever the amount.",
  },
  "break-even": {
    term: "Break-even price",
    group: "Costs and tax",
    text: "The sell price at which you get back exactly what you spent, after charges on both the buy and the sell. Below it you lose money even if the price rose a little.",
  },
  STCG: {
    term: "Short-term capital gains",
    group: "Costs and tax",
    text: "Profit on shares held 12 months or less, taxed at 20%.",
  },
  LTCG: {
    term: "Long-term capital gains",
    group: "Costs and tax",
    text: "Profit on shares held more than 12 months, taxed at 12.5% on gains above ₹1.25 lakh in a financial year.",
  },
  "realised P&L": {
    term: "Realised vs unrealised",
    group: "Costs and tax",
    text: "Realised profit is locked in by selling. Unrealised profit is on shares you still hold and can still disappear.",
  },
  "NIFTY 50": {
    term: "NIFTY 50",
    group: "Markets",
    text: "An index of 50 large Indian companies on the NSE. Holding it through an index fund is the simplest benchmark: a stock pick has to beat it to be worth the effort.",
  },
  benchmark: {
    term: "Benchmark",
    group: "Markets",
    text: "What you compare your result with. Making 8% sounds good until the market made 15% over the same dates.",
  },
  "sector index": {
    term: "Sector index",
    group: "Markets",
    text: "An index of companies in one industry, like NIFTY IT or NIFTY Bank. It shows whether a stock moved because of its industry or its own news.",
  },
  "circuit limit": {
    term: "Circuit limit",
    group: "Markets",
    text: "The most a stock may rise or fall in a day (for example 5%, 10% or 20%). At the limit, trading can freeze because no one will sell (or buy).",
  },
  "ex-dividend": {
    term: "Ex-dividend date",
    group: "Markets",
    text: "From this date a new buyer does not get the declared dividend, so the price usually drops by about the dividend amount. Shareholders before it receive the cash.",
  },
  diversification: {
    term: "Diversification",
    group: "Markets",
    text: "Spreading money across several stocks and sectors so one bad pick cannot sink the whole account.",
  },
  IPO: {
    term: "IPO",
    group: "IPOs",
    text: "Initial public offering: a company sells shares to the public for the first time and then lists on the exchange.",
  },
  QIB: {
    term: "QIB",
    group: "IPOs",
    text: "Qualified institutional buyers: mutual funds, insurers, banks and foreign funds. Their demand in an IPO has historically been the best single guide to how it lists.",
  },
  NII: {
    term: "NII (HNI)",
    group: "IPOs",
    text: "Non-institutional investors: individuals and companies bidding more than ₹2 lakh.",
  },
  RII: {
    term: "Retail investor",
    group: "IPOs",
    text: "Individuals bidding up to ₹2 lakh. When the retail portion is heavily oversubscribed, lots are allotted by lottery.",
  },
  subscription: {
    term: "Times subscribed",
    group: "IPOs",
    text: "Shares bid for divided by shares offered. 20x means bids for twenty times the shares on offer.",
  },
  "listing gain": {
    term: "Listing gain",
    group: "IPOs",
    text: "How far the opening price on the first trading day is above (or below) the issue price.",
  },
  "lot size": {
    term: "Lot size",
    group: "IPOs",
    text: "The minimum number of shares you can bid for in an IPO, and the step size for larger bids.",
  },
  "moving average": {
    term: "Moving average",
    group: "Indicators",
    text: "The average closing price over the last N days. Price above its 200-day average is a common sign of a long uptrend.",
  },
  RSI: {
    term: "RSI",
    group: "Indicators",
    text: "Relative Strength Index (0-100) compares recent gains with recent losses. Below 30 is often called oversold, above 70 overbought; neither is a guarantee.",
  },
  "52-week high": {
    term: "52-week high",
    group: "Indicators",
    text: "The highest price of the past year. Distance from it shows how far a stock has fallen, or how close it is to a breakout.",
  },
  volatility: {
    term: "Volatility",
    group: "Indicators",
    text: "How much the price swings. Higher volatility means larger gains and losses are both more likely.",
  },
  "P/E": {
    term: "P/E ratio",
    group: "Indicators",
    text: "Share price divided by earnings per share: how many years of current profit the price pays for. Compare it with similar companies, not across industries.",
  },
  backtest: {
    term: "Backtest",
    group: "Measuring results",
    text: "Running a set of rules on past prices to see how they would have done. Useful for rejecting bad ideas; a good backtest does not promise future results.",
  },
  "out-of-sample": {
    term: "Out-of-sample check",
    group: "Measuring results",
    text: "Testing rules on a later period kept aside. Rules that only work on the years they were tuned on are probably fitted to noise.",
  },
  drawdown: {
    term: "Maximum drawdown",
    group: "Measuring results",
    text: "The largest fall from a peak to a later low. It is the pain you would have had to sit through.",
  },
  CAGR: {
    term: "CAGR",
    group: "Measuring results",
    text: "Compound annual growth rate: the steady yearly return that would turn the starting amount into the final one.",
  },
  "win rate": {
    term: "Win rate",
    group: "Measuring results",
    text: "The share of closed trades that made money. A low win rate can still be profitable if the winners are much bigger than the losers.",
  },
  "profit factor": {
    term: "Profit factor",
    group: "Measuring results",
    text: "Money made on winning trades divided by money lost on losing ones. Above 1 means you are ahead.",
  },
  exposure: {
    term: "Time in the market",
    group: "Measuring results",
    text: "The share of days a strategy held shares. Low exposure means the money sat in cash most of the time.",
  },
  "buy-and-hold": {
    term: "Buy and hold",
    group: "Measuring results",
    text: "Buying once and keeping the shares. Any trading strategy should be compared with simply holding the same stock.",
  },
};
