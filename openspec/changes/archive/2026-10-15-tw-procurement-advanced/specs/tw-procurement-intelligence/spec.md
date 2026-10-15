# Spec Delta: Advanced Taiwan Procurement Intelligence

## ADDED Requirements

### Requirement: Tender Competitor Intelligence
The system SHALL provide a dedicated tool `get_company_procurement_rivals` that accepts a Taiwan stock ticker or company name and returns:
1. Complete list of top rival bidders who have participated in the same tenders.
2. Head-to-head match count, vendor win count, rival win count, and relative win rate percentage (`相對勝率 = my_wins / (my_wins + rival_wins)` or ToBid `win_rate_vs`).
3. Explicit competitive assessment tag per rival (🔴 遭遇強敵 < 35%, 🟡 勢均力敵 35~65%, 🟢 絕對優勢 > 65%).
4. List of recent lost tenders (`lost_recent`), including award date, tender title, client agency, rival winner, award amount, bidder's price, and official reason for loss.

#### Scenario: User queries company procurement competitors
- GIVEN a user asks "漢翔在標案上主要競爭對手是？" or calls `get_company_procurement_rivals("漢翔")`
- WHEN the tool executes
- THEN it SHALL return Hanxiang's top rivals (e.g. 亞洲航空 49.5%, 長榮航太 36.4%, 偉潤科技 16.7%), match counts, relative win rates, and recent lost tenders with competitor winners and price comparisons.

### Requirement: Reserve Price Margin & Category Profile in Tender Overview
The system SHALL enrich `get_company_government_tenders` to include:
1. Bottom price profile (`reserve_profile` / `reserve`): award method, reserve of budget %, award of reserve %, award of budget %, and negotiation headroom interpretation.
2. Category distribution (`main_categories` / `cats`): service, goods, and civil engineering counts and shares.
3. Core procurement product keywords (`main_products` / `products`).
4. Expanded top client agencies (up to 10) with tender count, share percentage, and total award amounts.
5. Top rival summary and recent lost tender warnings.

#### Scenario: User queries company government procurement overview
- GIVEN a user queries `get_company_government_tenders("2634")`
- WHEN the tool executes
- THEN it SHALL return the comprehensive dossier including reserve margin percentage, category distribution, core product terms, and top 10 client agencies alongside historical win rates.

### Requirement: Head-to-Head Vendor Comparison
The system SHALL provide a tool `compare_procurement_vendors(company_a, company_b)` that queries ToBid `compare_vendors` and returns head-to-head competition metrics between two government procurement vendors.

#### Scenario: User compares two competitors
- GIVEN a user asks "漢翔跟亞航誰在標案上比較強？"
- WHEN `compare_procurement_vendors("漢翔", "亞航")` executes
- THEN it SHALL return head-to-head match count, wins per vendor, relative win rates, and comparative assessment.

### Requirement: Procurement Agency Unit Intelligence
The system SHALL provide a tool `get_procurement_unit_report(unit_name)` that queries ToBid `unit_report` and returns procurement intelligence for public agencies, including total tenders, known award totals, fail rates, average bidders, and top suppliers.

#### Scenario: User queries agency procurement intelligence
- GIVEN a user asks "空軍司令部的主要標案得標廠商是誰？"
- WHEN `get_procurement_unit_report("國防部空軍司令部")` executes
- THEN it SHALL return procurement metrics and top vendor rankings for the agency.
