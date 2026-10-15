# Design

## Context

The bot currently orchestrates multiple financial tools in `ai_core.py` (LangGraph StateGraph). We are integrating curated data from ToBid's MCP endpoint (`https://api.tobid.tw/mcp`) without pulling all 17 tender bidding tools into the LLM context. See `proposal.md` for background motivation.

## Goals / Non-Goals

**Goals:**
- Provide 2 high-leverage LangChain tools (`get_company_government_tenders`, `check_vendor_procurement_compliance`) in `tools/tw_tenders.py`.
- Implement ticker and company name normalization using TW stock lists and ToBid's `find_entity` as fallback.
- Protect the upstream public endpoint with `tools/cache_util.py` TTLCache (1 hour for tenders, 2 hours for compliance) and SingleFlight coalescing.
- Provide bilingual / Traditional Chinese formatted summaries suitable for Telegram messages and AI hedge fund analysis.

**Non-Goals:**
- Exposing tender bidding tools (such as `price_analysis`, `committee_member`, `unit_report`) that are exclusively meant for bidding contractors rather than equity investors.
- Building a full bid submission or bidding document generation workflow.

## Decisions

### Decision 1: Direct JSON-RPC HTTP POST over installing MCP client dependencies
- **Choice**: Call `https://api.tobid.tw/mcp` directly via standard `requests` or `aiohttp` using JSON-RPC 2.0 payloads (`method: "tools/call"`).
- **Rationale**: Keeps Docker image lightweight; avoids adding `mcp` client libraries or process subprocess daemons.
- **Alternative considered**: Running an MCP client process or subprocess — rejected due to excessive overhead and operational complexity.

### Decision 2: Curated 2-Tool LangChain Interface
- **Choice**: Expose only `get_company_government_tenders` and `check_vendor_procurement_compliance`.
- **Rationale**: Keeps LLM tool selection crisp and prevents prompt bloat or hallucinated parameters.
- **Alternative considered**: Exposing all 17 ToBid tools — rejected as it clutters the LLM tool space and degrades routing accuracy.

### Decision 3: SingleFlight & Tiered TTLCache in `tools/cache_util.py`
- **Choice**: Use 60-minute TTL for tender track records and 120-minute TTL for compliance checks, guarded by `SingleFlight`.
- **Rationale**: Government procurement data updates at most once daily; caching prevents thundering herds and IP rate limiting.

## Risks / Trade-offs

- [Risk: Upstream ToBid endpoint unavailable or rate limited] → Mitigation: 8-second request timeout, SingleFlight deduplication, and graceful degradation returning an informative status message.
- [Risk: User provides ticker number instead of full company name] → Mitigation: Entity mapping lookup dictionary of popular TW defense, tech, construction tickers + ToBid `find_entity` fallback.
