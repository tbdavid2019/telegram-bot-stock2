## Purpose

Provides zero-cost market intelligence by scraping and searching public financial filings and web portals via 2md.aiurl.tw, covering 13F superinvestor positions, SEC Form 4 insider transactions, short squeeze metrics, and retail sentiment.

## ADDED Requirements

### Requirement: Superinvestor 13F Holding Tracking
The system SHALL retrieve top legendary investor holdings (e.g., Berkshire Hathaway, Michael Burry, Li Lu) and their recent quarterly portfolio changes for a given ticker via 2MD web extraction.

#### Scenario: Superinvestor holding query
- **WHEN** user queries smart money, institutional ownership, or superinvestor activity for a stock
- **THEN** system fetches latest 13F filing summaries from Dataroma/WhaleWisdom via 2MD, detailing which legendary funds bought, sold, or held shares and their portfolio weight.

### Requirement: SEC Form 4 Insider Trading Activity
The system SHALL extract recent insider transactions (CEO, CFO, Director open-market purchases and sales) from SEC Form 4 filings via 2MD reader.

#### Scenario: Insider transaction query
- **WHEN** user asks for insider buying or selling activity
- **THEN** system retrieves recent transaction dates, officer names, transaction types (Buy/Sell/Option), share amounts, and price levels, distinguishing true open-market purchases from automatic option exercises.

### Requirement: Short Squeeze and Borrow Fee Rate Analytics
The system SHALL analyze short interest percentage of float, days to cover (short ratio), and estimated borrow fee rates without requiring paid Fintel subscriptions.

#### Scenario: Short squeeze potential analysis
- **WHEN** user asks about short interest or short squeeze setup for a stock
- **THEN** system combines yfinance short float data with 2MD web search on borrow fee rates to output short interest levels, days to cover, and short squeeze risk indicators.

### Requirement: Retail and Community Sentiment Scanning
The system SHALL extract community discussions and sentiment signals from Reddit (r/WallStreetBets) and StockTwits via 2MD SERP and Web Reader.

#### Scenario: Social sentiment query
- **WHEN** user asks about retail sentiment, buzz, or WSB trends for a ticker
- **THEN** system searches live community mentions via 2MD, extracts discussion snippets, and summarizes prevailing bullish/bearish tone and discussion catalysts.
