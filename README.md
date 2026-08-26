# 🤖 Telegram 股票資訊與 AI 投資分析機器人 (Stock Bot 2.0)

這是一個基於 Python 與 `python-telegram-bot` 開發的高效能 **Telegram 股票與 AI 投資分析機器人**。提供即時台股/美股行情、多週期 K 線圖、Prophet 股價預測、基本面技術面評估，以及強大的 **14 位投資大師 AI 對沖基金委員會與圓桌會議辯論**。

---

## 📸 功能展示

![Overview](image-3.png)
![Charts](image.png)
![Forecast](image-1.png)
![Guru Analysis](image-2.png)

---

## 🌟 核心功能一覽

### 1. 🏛️ AI 對沖基金投資委員會 (`/ai2 股票代碼`)
- **14 位傳奇投資大師與專家 Persona**：
  - 👴 **巴菲特** (護城河/內在價值)、🧓 **蒙格** (定價權/逆向思維)、📚 **葛拉漢** (淨流動資產/深價值)、👩‍💼 **伍德** (破壞性創新)、🦈 **艾克曼** (催化劑/積極主義)、🏛️ **裴洛西** (國會交易揭露)、👁️ **貝瑞** (反向放空/隱性負債)、🛍️ **林區** (十倍股/生活選股)、🔍 **費雪** (15項質化調查)、🦍 **WSB** (散戶熱度/軋空)、📉 **技術分析師**、📈 **基本面分析師**、🌐 **情緒分析師**、⚖️ **估值分析師**。
- **圓桌辯論 (Round Table Debate)**：大師們就「成長 vs 估值」展開激烈多輪辯論，產出委員會共識 (`Consensus`) 與分歧觀點 (`Dissenting Opinions`)。
- **配置建議**：輸出最終操作決策（買入 / 賣出 / 做空 / 持有）、建議股數與信心度評分（支援中英雙語解析）。

### 2. 📊 綜合基本面與技術指標評估 (`/ai 股票代碼`)
- 整合 LangGraph 工具鏈，自動抓取 RSI、MACD、VWAP、Stochastic Oscillator、P/E、P/B、負債比率、利潤率與即時新聞，產出結構化投資報告。

### 3. 📈 即時股價與 K 線圖 (`/s 股票代碼`)
- 查詢即時最新成交價、開高低收、成交量，並自動繪製產生 **日K、週K、月K 線圖**。
- 支援美股（例如 `TSLA`、`NVDA`、`AAPL`）與台股（例如 `2330.TW`、`2002.TW`、`0050.TW`）。

### 4. 🔮 Prophet 股價時間序列預測 (`/p 股票代碼`)
- 採用 Facebook Prophet 模型預測未來 5 個交易日之價格趨勢走勢圖與信賴區間數據。

### 5. 📰 即時美股與台股新聞 (`/n` / `/ny`)
- `/n 股票代碼`：查詢美股最新即時英文財經新聞。
- `/ny 股票代碼`：查詢 Yahoo 台灣最新即時中文新聞。

### 6. 🤖 智能對話與即時金融工具 (`/llm 問題` 或 直接傳送訊息)
- **對話記憶 (Memory)**：具備短期記憶，能自動追蹤對話上下文。
- **工具自動調用**：在自然語言對話中即時查詢股價、指標與新聞回答您的問題。
- **重置記憶**：輸入 `/start` 即可重置對話上下文。

### 7. 🛠️ 其他量化工具連結 (`/h`)
- 提供台股 LSTM 預測、潛力股預測模型與 HuggingFace 空間快速入口。

---

## ⌨️ 指令速查表 (Command Reference)

| 指令 | 說明 | 範例 |
| :--- | :--- | :--- |
| `/start` | 啟動機器人並重置對話記憶 | `/start` |
| `/ai2` | 🏛️ 14 位投資大師 AI 委員會與圓桌辯論 | `/ai2 NVDA` 或 `/ai2 2330.TW` |
| `/ai` | 📊 基本面、技術指標與財務綜合分析 | `/ai TSLA` |
| `/s` | 📈 查詢即時股價與日/週/月 K 線圖 | `/s 2330.TW` |
| `/p` | 🔮 Prophet 模型預測未來 5 天股價區間 | `/p META` |
| `/n` | 📰 查詢美股即時英文新聞 | `/n AAPL` |
| `/ny` | 📰 查詢台股即時中文新聞 | `/ny 2330.TW` |
| `/llm` | 🤖 金融助理自由問答 (帶記憶與即時工具) | `/llm 2330.TW 近期營收成長與估值如何？` |
| `/h` | 🛠️ 顯示其他機器學習模型與工具連結 | `/h` |

---

## 🏗️ 系統架構

詳細架構設計與 14 位 Persona 規範請參閱 [AGENTS.md](AGENTS.md)。

- **核心框架**：Python 3.12+ / 3.13, `python-telegram-bot`
- **Agent 與工具鏈**：`LangGraph`, `LangChain`
- **市場數據與圖表**：`yfinance` (支援 1.6.0+ 與 MultiIndex 欄位展平), `matplotlib`, `prophet`, `pandas`, `ta`
- **2MD 財經即時搜尋 (Web Reader & SERP)**：
  - 主力：`https://2md.aiurl.tw/`
  - 備援 1：`https://2md.glsoft.ai/`
  - 備援 2：`https://create360.ai/`
- **AI 對沖基金後端**：`http://dns.glsoft.ai:6000` (支援 RFC 8259 嚴格 JSON 規範與雙語輸出)

---

## 🚀 部署教學 (Deployment)

### 方式 A：使用 Docker 執行 (推薦)

1. **建立 `.env` 檔案**：
```bash
cp .env.example .env
```
編輯 `.env` 填入您的金鑰：
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

# AI Hedge Fund API (選填，預設為 http://dns.glsoft.ai:6000)
AI2_BASE_URL=http://dns.glsoft.ai:6000

# 2MD 搜尋引擎端點 (選填，具備三組自動切換備援)
TWOMD_PRIMARY_URL=https://2md.aiurl.tw
TWOMD_BACKUP1_URL=https://2md.glsoft.ai
TWOMD_BACKUP2_URL=https://create360.ai

# 基本面分析 (/ai)
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o

# 主對話助理 (/llm & 自由問答，支援 Groq / DeepSeek / OpenAI 等)
LLM_API_KEY=your_llm_api_key
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama3-70b-8192
```

2. **使用部署腳本一鍵啟動**：
```bash
bash docker-run.sh
```

或手動執行 Docker：
```bash
docker build -t telegram-bot-stock2 .
docker run -d --name telegram-bot-stock2 --restart unless-stopped --env-file .env telegram-bot-stock2
```

---

### 方式 B：本機 Python 執行

1. **安裝依賴套件**：
```bash
pip install -r requirements.txt
```

2. **啟動機器人**：
```bash
python main.py
```

---

## 📚 相關文件
- 架構與代理人規範：[AGENTS.md](AGENTS.md)
- 版本變更紀錄：[CHANGELOG.md](CHANGELOG.md)

---

## 📄 License
本專案採用 GPL-3.0 License 授權。