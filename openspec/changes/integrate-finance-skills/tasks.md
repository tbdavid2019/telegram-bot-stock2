## 1. Quantitative Analysis Tools Module (`tools/stock_analysis.py`)

- [x] 1.1 Implement Mark Minervini SEPA 8-point Trend Template and VCP pattern diagnostic tool in `tools/stock_analysis.py` and verify via test script
- [x] 1.2 Implement DCF intrinsic valuation model with live 10Y UST (`^TNX`) WACC, 5-year FCFF projection, and sensitivity matrix in `tools/stock_analysis.py`
- [x] 1.3 Implement Earnings Briefing tool (calendar date, consensus EPS/revenue, 4-quarter beat/miss surprises) in `tools/stock_analysis.py`
- [x] 1.4 Implement Multi-stock Correlation Matrix and S&P 500 Beta calculation tool in `tools/stock_analysis.py`

## 2. 2MD Market Intelligence Module (`tools/market_intel.py`)

- [x] 2.1 Implement Superinvestor 13F Holding Tracker via Dataroma scraping with 2MD cluster failover in `tools/market_intel.py`
- [x] 2.2 Implement SEC Form 4 Insider Trading Tracker via OpenInsider/Finviz extraction in `tools/market_intel.py`
- [x] 2.3 Implement Short Squeeze & Borrow Fee Rate intelligence tool in `tools/market_intel.py`
- [x] 2.4 Implement Retail Social Sentiment tool (Reddit WSB / StockTwits via 2MD SERP) in `tools/market_intel.py`

## 3. LangGraph Agent & Telegram Handler Integration

- [x] 3.1 Register all new tools in `ai_core.py` and enhance system prompt with hedge-fund-level quantitative skills
- [x] 3.2 Add dedicated Telegram slash commands (`/sepa`, `/val`, `/earn`, `/corr`) in `handlers/stock_cmds.py` and register in `main.py` & `handlers/general.py`
- [x] 3.3 Ensure non-blocking execution via `run_in_executor` and robust Markdown length/formatting fallback

## 4. Verification, Documentation & Release

- [x] 4.1 Run Python syntax validation (`python3 -m py_compile`) across all modules
- [x] 4.2 Update `README.md` and `CHANGELOG.md` with complete documentation of new quant tools, 2MD intelligence scrapers, and slash commands
