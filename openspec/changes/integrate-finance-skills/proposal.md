# Proposal: Integrate Finance Skills and 2MD Market Intelligence

## Why

The Telegram stock bot currently provides basic quotes, K-line charts, Prophet forecasts, and 14-analyst committee opinions. However, it lacks deep quantitative valuation (DCF, WACC, SOTP), momentum screening (Minervini SEPA), pre-earnings briefings, multi-stock correlation, and real-time smart money tracking (13F superinvestor holdings, insider trading, and short squeeze metrics).

By internalizing key capabilities from the `finance-skills` framework and replacing paid third-party APIs (such as Fintel and Adanos) with our high-speed, zero-cost `2md.aiurl.tw` scraping and search engine, we can empower the bot with hedge-fund-grade quantitative and fundamental research capabilities without incurring ongoing API costs.

## What Changes

- **Quant Market Analysis Engine**:
  - Add Mark Minervini SEPA (Specific Entry Point Analysis) 8-point Trend Template & VCP (Volatility Contraction Pattern) diagnostic tool.
  - Add DCF (Discounted Cash Flow), FCFF, live WACC (via `^TNX` 10Y US Treasury rate), and relative peer multiple valuation tools with Bull/Base/Bear scenarios.
  - Add Earnings briefing tool (calendar date, consensus EPS/revenue estimates, 4-quarter beat/miss surprises, analyst price targets).
  - Add Multi-ticker correlation matrix & Beta calculation tool.
- **2MD-Powered Smart Money & Sentiment Intelligence**:
  - Add Superinvestor 13F tracking tool (Dataroma scraping via 2MD) to view top fund manager buys/sells.
  - Add SEC Form 4 Insider Trading tracking tool (OpenInsider / Finviz scraping via 2MD) to monitor CEO/CFO transactions.
  - Add Short Squeeze & Borrow Fee rate analysis tool (via `yfinance` + 2MD web search).
  - Add Social & Retail Sentiment tool (Reddit WSB / StockTwits sentiment analysis via 2MD search).
- **LangGraph Agent & Command Integration**:
  - Register all new tools to the LangGraph conversational agent (`ai_core.py`) for natural language invocation.
  - Expose optional shortcut slash commands (`/sepa`, `/val`, `/earn`, `/corr`) in Telegram handlers.
  - Support automatic David888 Wiki report generation for in-depth valuation and SEPA screening reports.

## Capabilities

### New Capabilities
- `quant-market-analysis`: Quantitative market analysis covering Minervini SEPA momentum diagnostics, DCF/WACC intrinsic valuation, pre/post-earnings briefings, and multi-asset correlation matrices.
- `web-market-intelligence`: 2MD-driven market intelligence extracting 13F institutional superinvestor positions, SEC Form 4 insider transactions, short squeeze metrics, and retail sentiment without paid APIs.

### Modified Capabilities
*(None - first version of OpenSpec capabilities)*

## Impact

- **Affected Code**: `tools/` (new tools `tools/stock_analysis.py` and `tools/market_intel.py`), `ai_core.py` (tool registration and system prompt enhancement), `handlers/stock_cmds.py` (new commands), `handlers/general.py` (bot command list), `README.md`, `CHANGELOG.md`.
- **Dependencies**: No new heavy external dependencies; utilizes existing `yfinance`, `pandas`, `numpy`, `scipy` (if needed), `aiohttp`, `langchain-core`, and `2md.aiurl.tw`.
- **APIs**: Replaces paid APIs (Fintel, Adanos) with `2md.aiurl.tw` multi-node cluster failover.
