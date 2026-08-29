## Purpose

Provides quantitative market analysis tools including Mark Minervini SEPA momentum template checks, DCF/WACC intrinsic valuation modeling, earnings briefings with surprise history, and multi-asset correlation matrices.

## ADDED Requirements

### Requirement: SEPA Trend Template and Momentum Evaluation
The system SHALL evaluate a stock against Mark Minervini's 8-point SEPA trend template criteria and Volatility Contraction Pattern (VCP) indicators using historical price and moving average data.

#### Scenario: Stock meets Stage 2 criteria
- **WHEN** user requests SEPA analysis for a stock in a confirmed Stage 2 uptrend (price > 50MA > 150MA > 200MA with rising 200MA)
- **THEN** system returns Stage 2 confirmation, passes all 8 template rules, identifies key pivot entry price, and calculates risk-adjusted stop-loss levels.

#### Scenario: Stock fails trend template
- **WHEN** user requests SEPA analysis for a stock in Stage 4 downtrend or Stage 1 basing
- **THEN** system identifies specific failing conditions (e.g., price below 200MA, negative 200MA slope) and advises defensive caution.

### Requirement: Intrinsic Valuation and Sensitivity Modeling
The system SHALL compute intrinsic company value using 5-year Discounted Free Cash Flow (DCF), live 10-year US Treasury yield (^TNX) anchored WACC, relative peer multiples, and Bull/Base/Bear sensitivity ranges.

#### Scenario: Successful DCF valuation with live risk-free rate
- **WHEN** user queries valuation or intrinsic fair value for a profitable company
- **THEN** system calculates WACC based on live ^TNX, projects 5-year free cash flows, computes terminal value, and provides implied share price along with a sensitivity matrix.

#### Scenario: Valuation fallback for early-stage or loss-making firms
- **WHEN** free cash flow is negative or historical data is insufficient for standard DCF
- **THEN** system falls back to relative revenue multiples (EV/Revenue, P/S) and explicitly notes the valuation limitation.

### Requirement: Pre-Earnings and Post-Earnings Briefings
The system SHALL provide pre-earnings expectations and post-earnings recaps including upcoming dates, consensus EPS/revenue estimates, high/low analyst spreads, and past 4-quarter beat/miss surprise track records.

#### Scenario: Pre-earnings briefing request
- **WHEN** user asks for upcoming earnings details or pre-earnings analysis for a ticker
- **THEN** system returns scheduled report date, consensus EPS and revenue estimates, year-over-year growth expectations, and historical 4-quarter beat/miss percentages.

### Requirement: Multi-Stock Correlation and Beta Analysis
The system SHALL compute daily return correlation coefficients and S&P 500 Beta values across 2 to 5 user-provided tickers over 90 trading days.

#### Scenario: Multi-ticker correlation query
- **WHEN** user submits multiple tickers (e.g., TSLA, NVDA, AAPL)
- **THEN** system returns a correlation matrix table and relative Beta metrics indicating co-movement and diversification strength.
