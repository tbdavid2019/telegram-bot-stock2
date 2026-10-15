# Proposal

## Why

Many Taiwanese listed companies in defense/aerospace, IT services/cybersecurity, construction/civil engineering, water resources, and green energy rely heavily on government procurement tenders for 50% to 80%+ of their revenues. Currently, the bot provides technicals, chip tracking, financial metrics, and US/TW news, but lacks insight into government contract awards, historical win rates, major client agencies, and regulatory debarment risks (Article 101 blacklists). Integrating curated Taiwan government procurement intelligence from ToBid via lightweight MCP JSON-RPC provides critical leading revenue indicators and black swan compliance risk checking.

## What Changes

- Add curated Taiwan government procurement intelligence tools:
  - `get_company_government_tenders`: Query a TW listed stock's government contract track record (wins, win rate, total award amount, top client agencies, top rivals, recent major awards).
  - `check_vendor_procurement_compliance`: Query whether a company or vendor has Article 101 debarment records / government procurement blacklist status.
- Implement robust entity mapping from TW stock tickers (e.g. `2634`, `6214`) and common names to registered legal entity names.
- Protect upstream ToBid endpoint with `tools/cache_util.py` (SingleFlight request coalescing + TTLCache) to prevent upstream abuse and rate limits.
- Register tools in `ai_core.py` LangGraph main conversational agent so it can answer natural language queries about public tenders and contracts.
- Update project documentation (`README.md`, `CHANGELOG.md`, `AGENTS.md`) in compliance with repository standards.

## Capabilities

### New Capabilities
- `tw-procurement-intelligence`: Taiwan government procurement contract awards tracking, vendor win records, agency distribution, and Article 101 compliance blacklist screening for Taiwanese listed corporations.

### Modified Capabilities
<!-- None -->

## Impact

- **New files**: `tools/tw_tenders.py`
- **Modified files**: `ai_core.py`, `README.md`, `CHANGELOG.md`
- **APIs**: Public ToBid MCP JSON-RPC endpoint (`https://api.tobid.tw/mcp`)
- **Dependencies**: No heavy external dependencies added; uses existing `aiohttp`/`requests` or standard library `urllib`/`asyncio`.
