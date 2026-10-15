# Proposal: ToBid Advanced Taiwan Government Procurement Intelligence

## Background & Problem
In the initial release of the ToBid integration (`v2.18.0`), the system added basic procurement overview (`get_company_government_tenders`), specific winning tenders (`get_company_winning_tenders`), and compliance checks (`check_vendor_procurement_compliance`).
However, real-world user testing on Telegram revealed critical missing capabilities and misrouting:
1. **Missing Deep Competitor Intelligence**: When a user asks "漢翔在標案上主要競爭對手是？", the conversational agent previously routed to `get_company_winning_tenders` (which has no competitor data) and falsely concluded that competitor information was unavailable, even though ToBid provides rich competitor win rates, head-to-head records, and relative win percentages.
2. **Missing Reserve Price & Margin Intelligence**: ToBid tracks actual reserve price distributions (`reserve_profile` / `reserve`: 底價占預算, 決標占底價, 決標占預算) and contract negotiation headroom across hundreds of historical tenders.
3. **Missing Category & Core Product Profiles**: ToBid tracks category distributions (勞務類, 財物類, 工程類) and core procurement keywords (e.g. UH, 直升機, 航材, 修理, 黑鷹, 發動機).
4. **Missing Head-to-Head Vendor Comparison**: ToBid provides a dedicated `compare_vendors` tool to answer questions like "漢翔跟亞航誰比較強？" or "中鼎跟工信誰得標比較多？".
5. **Missing Government Client Unit Intelligence**: ToBid provides a dedicated `unit_report` tool to inspect procurement volumes, top suppliers, and supplier concentration for public agencies (e.g. 國防部空軍司令部, 台灣電力公司).

## Proposed Solution
1. **Dedicated Competitor Tool (`get_company_procurement_rivals`)**:
   - Provide complete rankings of rival bidders, face-to-face match counts, win/loss stats, relative win rates (`相對勝率 %`), and battle strength categories (🔴 遭遇強敵 < 35%, 🟡 勢均力敵 35~65%, 🟢 絕對優勢 > 65%).
   - Include recent lost tenders (`lost_recent`) with rival winners, bid gaps, and official rejection reasons.
2. **Comprehensive Upgrade to `get_company_government_tenders`**:
   - Include bottom price profile (`reserve_profile`: 最低標/最有利標之底價占預算、決標占底價、決標占預算與議價空間評估).
   - Include category distribution (勞務類, 財物類, 工程類件數與佔比).
   - Include core procurement products/keywords (`main_products`).
   - Expand top client agencies to Top 10 with contract amount and share (%).
   - Include top 5 rival summary and recent lost tender warnings.
3. **New Head-to-Head Comparison Tool (`compare_procurement_vendors`)**:
   - Compares two vendors side-by-side using ToBid `compare_vendors`.
4. **New Unit Intelligence Tool (`get_procurement_unit_report`)**:
   - Inspects client agencies (e.g. 空軍司令部) using ToBid `unit_report` to show total tenders, known award totals, fail rates, and top supplier rankings.
5. **Enhanced LangGraph System Prompt & Routing in `ai_core.py`**:
   - Explicitly guide the conversational LLM to route questions about "競爭對手/同場競標/誰常跟某公司搶標/輸給誰/勝率" to `get_company_procurement_rivals`.
   - Route comparison questions ("A vs B 誰強") to `compare_procurement_vendors`.
   - Route agency questions ("某機關主要供應商") to `get_procurement_unit_report`.
6. **Documentation & Architecture Sync**:
   - Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` per project requirements.
