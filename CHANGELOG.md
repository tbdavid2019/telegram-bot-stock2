# 📜 變更紀錄 (CHANGELOG)

All notable changes to the `telegram-bot-stock2` project are documented in this file.

---

## [2.0.0] - 2026-08-26

### 🚀 重大更新與架構升級 (Major Enhancements)

#### 1. 🏛️ 升級 AI 對沖基金 14 位投資大師委員會與圓桌辯論 (`/ai2`)
- **全新微服務 API 對接**：整合 `http://dns.glsoft.ai:6000/api/analysis` 全新架構。
- **14 位傳奇投資大師與專家陣容**：
  - 👴 華倫·巴菲特 (`warren_buffett`)：護城河、可預測現金流、ROE > 15%、安全邊際。
  - 🧓 查理·蒙格 (`charlie_munger`)：逆向思維、定價權、商業模式持續性。
  - 📚 班傑明·葛拉漢 (`ben_graham`)：淨清算價值 (Net-Net)、保守估值倍數。
  - 👩‍💼 凱西·伍德 (`cathie_wood`)：破壞性創新、5年 S 曲線、AI 與機器人高複合成長。
  - 🦈 比爾·艾克曼 (`bill_ackman`)：積極主義價值投資、高進入壁壘、營運催化劑。
  - 🏛️ 南西·裴洛西 (`nancy_pelosi`)：國會議員交易揭露、政策法案與補貼紅利。
  - 👁️ 邁克爾·貝瑞 (`michael_burry`)：反向深價值、自由現金流收益率、資產負債表隱性負債審查。
  - 🛍️ 彼得·林區 (`peter_lynch`)：生活選股、PEG < 1.0、十倍股成長潛力。
  - 🔍 菲利普·費雪 (`phil_fisher`)：15項質化調查、研發回報率、長期複利。
  - 🦍 華爾街賭場 (`wsb`)：散戶動能、軋空行情、選擇權 Gamma 擠壓、社群熱度。
  - 📉 技術分析師 (`technical_analyst`)：均線系統、RSI、MACD、布林通道與支撐壓力。
  - 📈 基本面分析師 (`fundamentals_analyst`)：財務報表審計、營收利潤率成長趨勢。
  - 🌐 市場情緒分析師 (`sentiment_analyst`)：全球新聞情緒評分、內部人 Form 4 交易。
  - ⚖️ 估值分析師 (`valuation_analyst`)：現金流折現 (DCF)、EV/EBITDA 與同業估值比率。
- **多輪委員會圓桌會議辯論 (Round Table Debate)**：
  - 支援多輪委員會內部辯論，呈現成長與估值之間的碰撞與分歧觀點。
  - 自動生成委員會共識報告 (`consensus_view`) 與分歧意見 (`dissenting_opinions`)。
- **全方位雙語輸出支援**：全面支援英文與繁體中文（【繁體中文解析】）。
- **訊息超長防禦與雙向排版**：針對 Telegram 單則 4096 字元限制進行自動分段發送，避免 Markdown 解析異常中斷。

#### 2. 🧹 移除 Dify API 依賴與清理
- 移除已失效的 Dify API 程式碼與測試檔案 (`dify2.py`)。
- 將 `/llm <問題>` 指令全面改由內建 **LangGraph 主對話代理人 (Main Conversational Agent)** 驅動：
  - 具備短期對話記憶 (`MemorySaver`)。
  - 整合即時工具鏈（股價查詢、技術指標計算、即時財報與新聞檢索）。
  - 支援 Groq, DeepSeek, OpenAI, Gemini 等任何相容 OpenAI 介面之模型。
- 清理 `.env.example`、`config.py`、`docker-run.sh`、`README.md` 中的 `DIFY_API_KEY` 與 `DIFY_BASE_URL` 設定。

#### 3. 📦 yfinance 與金融數據解析優化
- 相容最新版 `yfinance`（含 `1.6.0` / `0.2.x`）：
  - 強化 `MultiIndex` 欄位結構自動展平 (`get_level_values(0)`)，防止最新版本下載多級表頭時引發的計算例外。
  - 優化新聞結構解析器，同時支援最新 `clickThroughUrl`、`canonicalUrl` 與傳統格式。
  - 增強數值型態強制轉換與防空值機制。

#### 4. 🌐 引入 2MD 高速搜尋與 Web Reader 引擎 (多主機自動備援)
- 整合 2MD 高速網頁搜尋 API，大幅提升美股與台股即時新聞檢索品質並徹底規避傳統財經來源之 IP 頻率限制 (429 Too Many Requests)。
- 多主機自動容錯切換：
  - **主力端點**：`https://2md.aiurl.tw/`
  - **備援端點 1**：`https://2md.glsoft.ai/`
  - **備援端點 2**：`https://create360.ai/`
- 全面升級 `/n` (美股新聞)、`/ny` (台股新聞) 及 LangGraph 工具鏈 `get_financial_news`，提供標題、超連結及摘要預覽。

#### 5. 📄 系統文件與開發規格完備
- 新增 `AGENTS.md`：詳盡記錄整體系統架構、代理人節點、14位大師 Persona 規格、2MD 規範、API 端點及生命週期管理。
- 更新 `README.md`：全面同步最新指令、部署說明、架構圖與環境變數範例。
- 修正 Git 帳號環境為 `tbdavid2019`。
