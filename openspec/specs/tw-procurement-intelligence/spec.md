# tw-procurement-intelligence Specification

## Purpose
Provides comprehensive Taiwan government procurement tender intelligence, award history, client agency distribution, and Article 101 compliance blacklist screening for Taiwanese listed corporations and contractors.

## Requirements

### Requirement: Listed Company Government Tender Track Record
The system SHALL retrieve and summarize a company's historical government procurement participations, award wins, win rate percentage, total award value, top client agencies, and primary competitors.

#### Scenario: Successful tender track record retrieval
- **WHEN** user or agent requests tender statistics for a listed company by ticker or name
- **THEN** system resolves the company entity name, queries the procurement engine, and returns total wins, win rate, award amount in NTD, top government agencies, and major competitors.

#### Scenario: Company not found or no public tender history
- **WHEN** user queries a company that has zero government tender participations
- **THEN** system returns an informative message indicating no government procurement records exist for that entity without raising unhandled errors.

### Requirement: Procurement Debarment and Article 101 Compliance Check
The system SHALL check whether a target company or vendor is currently debarred under Government Procurement Act Article 101 or listed on official tender rejection blacklists.

#### Scenario: Clean compliance check
- **WHEN** user or agent verifies compliance for a listed company in good standing
- **THEN** system confirms that the vendor is not currently debarred and lists zero active debarment sanctions.

#### Scenario: Active debarment or penalty found
- **WHEN** user verifies a vendor with past or active Article 101 debarment cases
- **THEN** system explicitly flags the debarment status, issuing agencies, case details, and warning of black swan contract risk.

### Requirement: Anti-Thundering-Herd Caching and Rate Protection
The system SHALL cache procurement queries with TTLCache and coalesce concurrent requests using SingleFlight to protect upstream public MCP endpoints from rate limits.

#### Scenario: Concurrent identical tender queries
- **WHEN** multiple users or agent sub-tasks query the same stock's procurement record simultaneously
- **THEN** system executes a single upstream request and returns cached results to subsequent callers within TTL window.
