# Tasks

## 1. Tool Implementation & Upstream Integration

- [x] 1.1 Create `tools/tw_tenders.py` with JSON-RPC 2.0 client for ToBid endpoint, company entity mapping, and implement `get_company_government_tenders` and `check_vendor_procurement_compliance`. Verify with `python3 -m py_compile tools/tw_tenders.py`.
- [x] 1.2 Integrate `SingleFlight` and `TTLCache` in `tools/tw_tenders.py` using `tools/cache_util.py` to prevent duplicate upstream queries. Verify through unit test execution.

## 2. Agent Registration & Integration

- [x] 2.1 Register `get_company_government_tenders` and `check_vendor_procurement_compliance` in `ai_core.py` LangGraph main conversational agent toolset and system prompt. Verify with `python3 -m py_compile ai_core.py`.
- [x] 2.2 Run end-to-end integration test querying defense/IT stocks (e.g. 2634 漢翔, 6214 精誠) to ensure formatted output adheres to Telegram formatting standards.

## 3. Documentation & Repository Sync

- [x] 3.1 Update `README.md` tool list, feature descriptions, and sample natural language prompts.
- [x] 3.2 Update `CHANGELOG.md` with version bump and feature highlights per AGENTS.md rules.
