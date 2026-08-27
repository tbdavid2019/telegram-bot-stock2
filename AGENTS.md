# AGENTS.md - Repository Guidelines for AI Coding Agents (Codex / AGY / Antigravity)

This document contains instructions, architectural rules, code conventions, and constraints for AI coding agents (such as Antigravity / AGY, Codex, Claude Code, and Cursor) working within the `telegram-bot-stock2` repository.

---

## 🎯 Project Overview & Core Mission

`telegram-bot-stock2` is an asynchronous Telegram bot built with Python (`python-telegram-bot` v20+) providing real-time stock quotes, technical K-line charts, Prophet time-series forecasts, fundamental indicator evaluations, and an **AI Hedge Fund Investment Committee** powered by 14 legend investor personas with multi-round round table debates.

- **Primary Repository**: `https://github.com/tbdavid2019/telegram-bot-stock2.git`
- **Default Git Author**: `tbdavid2019 <tbdavid2019@gmail.com>`
- **Docker Image**: `tbdavid2019/telegram-bot-stock2:latest`

---

## 🏗️ Repository Structure & Module Responsibilities

```
telegram-bot-stock2/
├── main.py                   # Application entry point; registers PTB command & message handlers
├── config.py                 # Environment variables loader & service URL constants
├── ai_core.py                # LangGraph StateGraph engine (Main Conversational Agent + Memory + Tools)
├── handlers/
│   ├── ai_cmds.py            # Handlers for /ai (fundamentals), /ai2 (14 gurus), /llm (conversational)
│   ├── stock_cmds.py         # Handlers for /s (K-lines), /n (US news), /ny (TW news), /p (Prophet)
│   └── general.py            # Handlers for /start (memory reset + keyboard), /h (tools help), text routing
├── tools/
│   ├── stock.py              # LangChain tools: get_stock_prices, get_financial_metrics
│   └── news.py               # LangChain tool: get_financial_news (yfinance + Yahoo + Google fallback)
├── news.py                   # Standalone Taiwan Yahoo news scraper helper
├── auto_update_yfinance.sh   # Automated cron script to bump yfinance version from PyPI & redeploy
├── deploy.sh                 # Docker build, tag, run, and push script
├── docker-run.sh             # Local Docker launch script using .env
├── Dockerfile                # Debian-slim Python 3.13 image with gcc/g++ for Prophet
├── requirements.txt          # Python dependencies
├── AGENTS.md                 # Agent instructions (this file)
├── CHANGELOG.md              # Detailed version history
└── README.md                 # User-facing documentation
```

---

## 🚨 Critical Rules for AI Agents (MUST FOLLOW)

### 1. ❌ Dify API is Permanently Discontinued
- The external Dify service (`http://llm.glsoft.ai/v1/chat-messages`) has been decommissioned.
- **NEVER** re-introduce Dify API calls, `DIFY_API_KEY`, or `DIFY_BASE_URL` into this repository.
- Natural language queries (`/llm` or plain text messages) are routed through the **LangGraph Main Conversational Agent** in `ai_core.py`.

### 2. 🏛️ AI Hedge Fund API (`/ai2`) Standards
- **Endpoint**: `http://dns.glsoft.ai:6000/api/analysis` (configurable via `AI2_API_URL` / `AI2_BASE_URL`).
- **All 14 Analyst Personas**:
  - `warren_buffett`, `charlie_munger`, `ben_graham`, `cathie_wood`, `bill_ackman`, `nancy_pelosi`, `michael_burry`, `peter_lynch`, `phil_fisher`, `wsb`, `technical_analyst`, `fundamentals_analyst`, `sentiment_analyst`, `valuation_analyst`.
- **Request Payload Parameters**:
  - `tickers`: Ticker symbol (e.g., `"TSLA"`, `"2330.TW"`, `"0001.HK"`).
  - `selectedAnalysts`: Array containing the analyst persona keys.
  - `enableRoundTable`: Must be set to `true` to generate the committee debate.
  - `roundTableRounds`: `2` (integer between 1 and 3).
  - `initialCash`: `100000`.
- **Response Structure**:
  - `decisions`: Execution action (`buy`, `sell`, `short`, `hold`), confidence score, share quantity, and rationale.
  - `round_table`: Committee `consensus_view`, `dissenting_opinions`, and `discussion_summary`.
  - `analyst_signals`: Individual signals, confidence, and reasoning per persona.
- **Language**: Output is bilingual (English and Traditional Chinese `【繁體中文解析】`). Responses sent to Telegram users should emphasize Traditional Chinese.

### 3. ⚡ Async & Event Loop Safety (python-telegram-bot v20+)
- PTB handlers are `async def`.
- Any blocking synchronous operations (e.g. `yf.download`, `t.history`, `t.info`, `matplotlib` plotting, `Prophet.fit/predict`, `BeautifulSoup` network scraping) **MUST NEVER** be run directly in the async handler.
- Always use `await loop.run_in_executor(None, synchronous_fn)` to offload blocking tasks to worker threads.

### 4. 📈 yfinance & Pandas MultiIndex Compatibility
- Modern versions of `yfinance` (>=0.2.44, 1.6.0+) often return DataFrames with `pd.MultiIndex` columns (e.g. `('Close', 'TSLA')`).
- Always flatten columns immediately after `yf.download`:
  ```python
  if isinstance(df.columns, pd.MultiIndex):
      df.columns = df.columns.get_level_values(0)
  elif len(df.columns) > 0 and isinstance(df.columns[0], tuple):
      df.columns = [i[0] for i in df.columns]
  ```
- Always ensure Series are coerced to numeric (`pd.to_numeric(..., errors='coerce')`) before calculating indicators or sending to `matplotlib`.

### 5. 🌐 2MD Web Reader & Financial Search Architecture
- **Purpose**: High-speed, rate-limit resilient news search & reader service for financial queries.
- **Endpoints Strategy**:
  - **Primary**: `https://2md.aiurl.tw/`
  - **Backup 1**: `https://2md.glsoft.ai/`
  - **Backup 2**: `https://create360.ai/`
- **Usage**:
  - Search: `GET {endpoint}/search?q={query}` with `headers={"Accept": "application/json"}`
  - Single page Markdown reader: `GET {endpoint}/{URL}` with `headers={"Accept": "text/plain"}`
- **Fallback Sequence**: Always prioritize 2MD Search -> yfinance news API -> Yahoo Finance direct scraper -> Google News.

### 6. 💬 Telegram Message Length & Markdown Fallback
- Telegram enforces a strict **4096 character limit** per message.
- For lengthy outputs (such as `/ai2` 14-guru breakdown and committee debate), split the content into logical sequential messages.
- Always wrap markdown sends in a try/except block to fallback to plain text if Markdown syntax errors occur (e.g. unescaped underscores or brackets from external data).

### 7. 📖 MANDATORY Documentation & Versioning Policy (嚴格執行 CHANGELOG.md 與 README.md 維護)
- **100% 同步鐵律 (Continuous Sync Rule)**：無論是新增功能、修改架構、修復 Bug、優化 Prompt、刪除或整併指令，**AI 代理人必須在同一輪改動中立即同步更新 `CHANGELOG.md` 與 `README.md`，絕對不可推延或遺漏！**
- **嚴禁殘留廢棄指令 (No Obsolete Syntax Residuals)**：當指令被整併或廢除（例如 `/ai`、`/llm` 改為自然語言直接對話），必須徹底清查 `README.md` 中的「功能一覽」、「指令速查表」、「環境變數範例」與「快速鍵盤說明」，絕不准出現相互矛盾或過期的指令文字。
- **標準化版本號與變更紀錄**：在 `CHANGELOG.md` 中詳細記錄每一次版本號（如 `[2.2.0]`）、分類（`⚡ 全面非阻塞併發升級`、`💬 自然語言深度整合`、`🛠️ CI/CD 自動化建置` 等）與改動條目。
- **CI/CD 與 DevOps 一致性**：任何與 Docker 映像檔標籤（`tbdavid2019/telegram-bot-stock2:latest`）、Watchtower 標籤、GitHub Actions 工作流相關的調整，皆須同步反映於 `README.md` 與 `AGENTS.md`。

---

## ⚙️ Environment Variables Reference

| Variable | Required | Default | Description |
| :--- | :---: | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | ✅ | - | Telegram Bot API Token from @BotFather |
| `AI2_BASE_URL` | ❌ | `http://dns.glsoft.ai:6000` | Base URL for AI Hedge Fund microservice |
| `AI2_API_URL` | ❌ | `http://dns.glsoft.ai:6000/api/analysis` | Full endpoint for AI2 analysis |
| `TWOMD_PRIMARY_URL` | ❌ | `https://2md.aiurl.tw` | Primary 2MD search & web reader endpoint |
| `TWOMD_BACKUP1_URL` | ❌ | `https://2md.glsoft.ai` | Backup 1 2MD search endpoint |
| `TWOMD_BACKUP2_URL` | ❌ | `https://create360.ai` | Backup 2 2MD search endpoint |
| `OPENAI_API_KEY` | ❌ | - | OpenAI API Key (Optional) |
| `OPENAI_MODEL` | ❌ | `gpt-4o` | Model name for OpenAI endpoint |
| `OPENAI_BASE_URL` | ❌ | `None` | Optional custom base URL for OpenAI endpoint |
| `LLM_API_KEY` | ❌ | - | API Key for Main Agent (NEN DeepSeek, Groq, OpenAI, Gemini) |
| `LLM_BASE_URL` | ❌ | `https://nen.com.tw/v1` | Base URL for Main Agent endpoint |
| `LLM_MODEL` | ❌ | `deepseek-v4-flash` | Model name for conversational agent |

---

## 🛠️ Build, Test & Deployment Commands

### Local Testing & Execution
```bash
# Verify Python syntax across all modules
python3 -m py_compile main.py config.py ai_core.py handlers/ai_cmds.py handlers/general.py handlers/stock_cmds.py tools/stock.py tools/news.py

# Run bot locally
python3 main.py
```

### Docker Execution
```bash
# Run with docker-run.sh
bash docker-run.sh

# Or manual Docker build & run
docker build -t tbdavid2019/telegram-bot-stock2:latest .
docker run -d --name telegram-bot-stock2 --restart unless-stopped --label "com.centurylinklabs.watchtower.enable=true" --env-file .env tbdavid2019/telegram-bot-stock2:latest
```

### Automated yfinance Update Cron
```bash
# Checks PyPI, bumps requirements.txt, commits, pushes, and rebuilds container if updated
bash check_and_update_yfinance.sh
```

---

## 📝 Conventions for Future Edits
- Keep dependencies updated and unpinned or loosely pinned in `requirements.txt`.
- When adding or modifying bot commands:
  1. Define handler in `handlers/<category>_cmds.py` (with async/run_in_executor pattern).
  2. Register `CommandHandler` in `main.py`.
  3. Update `BotCommand` list in `handlers/general.py` (`reset_commands`).
  4. **MANDATORY**: Fully update `README.md` (all sections) and `CHANGELOG.md` with version bump.
