# Design: Integrate Finance Skills and 2MD Market Intelligence

## Context

See `proposal.md` for the business motivation. The current bot runs on Python 3.13 and `python-telegram-bot` v20+ with an asynchronous LangGraph agent (`ai_core.py`) and existing tools in `tools/stock.py`, `tools/news.py`, and `tools/wiki.py`.

All quantitative calculations and web scrapers must adhere to the non-blocking execution standard (`asyncio.to_thread` / `run_in_executor`) and zero-tolerance secret/security guidelines.

## Goals / Non-Goals

**Goals:**
- Implement modular quantitative models (SEPA 8-point template, VCP, DCF valuation with live `^TNX` WACC, earnings briefings, and multi-asset correlation matrices) in pure Python.
- Implement zero-cost 2MD-driven market intelligence tools (13F Dataroma superinvestors, OpenInsider SEC Form 4, short squeeze metrics, and WSB/Reddit sentiment) with triple-endpoint failover.
- Register all tools into the LangGraph Main Conversational Agent (`ai_core.py`) with updated system prompts.
- Provide direct Telegram slash command shortcuts (`/sepa`, `/val`, `/earn`, `/corr`) for quick user access.
- Support seamless export to David888 Wiki for comprehensive analysis reports.

**Non-Goals:**
- Automated trade execution or broker order routing.
- Integration of paid proprietary subscriptions (e.g., Fintel Pro, Adanos API, TradingView Desktop CDP).
- Heavy external ML/C++ libraries beyond existing Python packages.

## Decisions

### Decision 1: Modular Split into `tools/stock_analysis.py` and `tools/market_intel.py`
- **Choice**: Separate quantitative/algorithmic computations (`tools/stock_analysis.py`) from external web scraping & intelligence gathering (`tools/market_intel.py`).
- **Rationale**: Keeps quantitative models clean, deterministic, and fast, while isolating web extraction, HTTP retries, and markdown parsing logic in `market_intel.py`.
- **Alternatives Considered**: Putting everything in `tools/stock.py` would create an overly bloated single file.

### Decision 2: 2MD Web Extraction with 3-Node Cluster Failover
- **Choice**: Route all external intelligence scraping (Dataroma, OpenInsider, Finviz, Reddit) through `https://2md.aiurl.tw` with fallback to `https://2md.glsoft.ai` and `https://create360.ai`.
- **Rationale**: Eliminates the need for paid API subscriptions. 2MD handles headless browser execution and HTML-to-Markdown conversion, returning clean, token-efficient text for the LLM.
- **Alternatives Considered**: Direct local BeautifulSoup scraping often fails due to JavaScript rendering or IP rate-limiting.

### Decision 3: Dual Access Mode (LangGraph Tool Calling + Dedicated Slash Commands)
- **Choice**: Equip the LangGraph conversational agent with the new tools while also binding dedicated Telegram slash handlers (`/sepa`, `/val`, `/earn`, `/corr`).
- **Rationale**: Power users get instant 1-second results via slash commands, while general conversational users can trigger the exact same tools naturally via chat (e.g., "幫我算 NVDA 估值" or "TSLA 現在是 Stage 2 嗎？").

### Decision 4: Asynchronous & Thread-Safe Execution
- **Choice**: Wrap all synchronous yfinance and numpy calculations with `await loop.run_in_executor(None, fn)` in command handlers, and use asynchronous `aiohttp` for 2MD calls.
- **Rationale**: Ensures the Telegram event loop remains 100% responsive without lagging user interactions.

## Risks / Trade-offs

- **[Risk] yfinance upstream schema drift or missing fields (e.g. quarterly estimates missing for small caps)**
  - *Mitigation*: Graceful fallbacks in `stock_analysis.py` that degrade to relative multiples or note missing data clearly rather than throwing exceptions.
- **[Risk] Target websites (e.g. Dataroma, OpenInsider) changing layout**
  - *Mitigation*: 2MD AnyDoc engine extracts semantic markdown; tools use robust regex/line parsing and fallback to 2MD SERP search queries if direct page extraction fails.
- **[Risk] Telegram 4096-character limit for long reports**
  - *Mitigation*: Format outputs into clean, compact summaries with Markdown tables, and offer the `/wiki` tool/link for full-length whitepapers.

## Migration & Deployment Plan

1. Create `tools/stock_analysis.py` (SEPA, DCF, Earnings, Correlation).
2. Create `tools/market_intel.py` (13F Superinvestors, Insider, Short Squeeze, Sentiment via 2MD).
3. Register tools in `ai_core.py` and enrich the system prompt.
4. Add slash command handlers in `handlers/stock_cmds.py` and register in `main.py` & `handlers/general.py`.
5. Update `README.md` and `CHANGELOG.md`.
6. Run full syntax validation (`py_compile`) and test handlers.
