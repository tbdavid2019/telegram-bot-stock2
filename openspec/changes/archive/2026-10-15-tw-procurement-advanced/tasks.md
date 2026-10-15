# Tasks

## 1. Implementation in `tools/tw_tenders.py`
- [ ] 1.1 Implement hybrid data fetcher `_get_vendor_full_data` with REST primary and MCP fallback, normalizing rivals, clients, reserve profiles, categories, and recent losses.
- [ ] 1.2 Implement `get_company_procurement_rivals` with competitor win rates, battle status emojis, and recent loss breakdown.
- [ ] 1.3 Upgrade `get_company_government_tenders` with bottom price reserve margins, category breakdowns, core product terms, and top 10 clients.
- [ ] 1.4 Implement `compare_procurement_vendors` using ToBid `compare_vendors`.
- [ ] 1.5 Implement `get_procurement_unit_report` using ToBid `unit_report`.

## 2. Agent & System Prompt Integration in `ai_core.py`
- [ ] 2.1 Register new tools in `main_agent_tools` in `ai_core.py`.
- [ ] 2.2 Strengthen LLM system prompt with explicit routing rules for competitors, comparisons, and agency unit reports.

## 3. Verification & Quality Assurance
- [ ] 3.1 Verify Python compilation with `python3 -m py_compile`.
- [ ] 3.2 Run test script validating competitor outputs for 2634 (漢翔) and head-to-head comparison for 漢翔 vs 亞航.
- [ ] 3.3 Run `codex review --uncommitted` to ensure zero defects.

## 4. Documentation & Deployment
- [ ] 4.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md`.
- [ ] 4.2 Archive OpenSpec change `tw-procurement-advanced`.
- [ ] 4.3 Git commit and push to master to deploy via Docker CI/CD.
