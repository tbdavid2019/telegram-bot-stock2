# 📜 變更紀錄 (CHANGELOG)

All notable changes to the `telegram-bot-stock2` project are documented in this file.

## [2.4.0] - 2026-08-30

### 📐 對沖基金量化研究工具
- 新增 `tools/stock_analysis.py`：Mark Minervini SEPA 8 項 Trend Template、Stage 2/VCP 診斷、pivot 與風險停損。
- 新增五年 FCFF DCF：以即時 `^TNX` 10 年期殖利率估算風險自由利率與 WACC，提供 Bull/Base/Bear 情境及 WACC/終值成長敏感度矩陣。
- 新增 Earnings Briefing：財報日期、EPS/營收共識、分析師目標價及最近四季 beat/miss 紀錄；資料缺失時保留限制。
- 新增 2 至 5 檔股票的 90 日報酬相關矩陣與 S&P 500 Beta 分析。

### 🧭 2MD Smart Money 與社群情報
- 新增 `tools/market_intel.py`：Dataroma/WhaleWisdom 13F、OpenInsider/Finviz/SEC Form 4、short squeeze/借券費率及 Reddit WSB/StockTwits 情緒工具。
- 所有外部情報查詢依序使用 `2md.aiurl.tw`、`2md.glsoft.ai`、`create360.ai`，保留來源摘錄並在資料不足時明確回報。

### 🤖 Agent 與 Telegram 整合
- 將八項新工具註冊至 LangGraph 主對話 Agent，並加入量化資料不完整時不得猜測的提示規則。
- 新增 `/sepa`、`/val`、`/earn`、`/corr` 快速指令與 `/help` 說明指令；同步更新 Telegram 官方指令選單 (`set_my_commands`)。
- 優化 `/start` 與 `/help` 說明文字（加入量化與 13F/內部人自然語言範例）與底部快捷鍵盤 (`ReplyKeyboardMarkup`)。
- 新指令將 yfinance、計算與 JSON 報告透過 executor 執行，並以 4096 字元限制及 Markdown fallback 安全傳送。

## [2.3.0] - 2026-08-28

### 🌐 David888 Wiki 智能發布工具鏈整合 (David888 Wiki Publisher)
- **實作 `publish_to_wiki` LangGraph Tool**：遵循 `wiki.david888.com` 最新規範，嚴格遵守「開頭第一行必為 `# Document Title`、移除前置客套對話、自動配置 `[TOC]` 與美化主題（支援 `claude-canvas`、`retro`、`tokyo-night` 等）」，並保證永遠回傳公開閱讀連結 `shareUrl`。
- **主對話 Agent 自主長文發布**：LLM 大腦在產出深度研究報告、跨公司比較或使用者要求生成分享網址時，可自主調用 `publish_to_wiki` 生成高階排版 Wiki 網頁。
- **`/ai2` 14 位大師投資委員會全自動 Wiki 發布**：在執行 `/ai2` 時，自動在背景將 14 位投資大師個別深入論點、圓桌會議辯論共識/分歧、建議倉位與執行理由打包發布至 David888 Wiki，並於 Telegram 訊息末尾提供一鍵網頁閱讀連結。

---

## [2.2.0] - 2026-08-27

### ⚡ 全面非阻塞併發升級 (Non-Blocking Concurrency)
- **PTB 全局並發更新引擎**：啟用 `concurrent_updates=True`，使每個使用者的訊息與指令皆作為獨立 `asyncio.Task` 平行處理，徹底解決請求排隊卡死瓶頸。
- **背景執行緒池擴容**：配置 32 個並發 worker (`ThreadPoolExecutor(max_workers=32)`)，支撐多人同時查詢 yfinance、新聞爬蟲與 Prophet 運算。
- **圖表繪製非阻塞與記憶體化**：`/s`（日/週/月 K 線）與 `/p`（Prophet 預測圖）繪圖運算全面移至背景執行緒，並改用 `io.BytesIO` 記憶體串流傳輸，不再凍結事件迴圈。
- **思考狀態提示與自動刪除**：LLM 處理期間發送 `⏳ 思考與處理中，請稍候...` 提示，回應完成後自動刪除，保持聊天室清爽。

### 💬 自然語言深度整合與指令精簡
- **整合 `/ai` 與 `/llm` 至主對話代理**：使用者可直接以自然語言詢問（如「分析 2330.TW 基本面與技術面」），系統自動調用即時行情、財務指標、新聞與 2MD 搜尋，並具備上下文記憶。
- **Telegram 指令選單與鍵盤清理**：從 Telegram 左下角選單與底部鍵盤中清理冗餘的 `/ai` 與 `/llm`，專注於自然語言對話與核心指令 (`/ai2`, `/s`, `/p`, `/n`, `/ny`, `/h`, `/start`)，並對舊指令維持向後相容。

### 🛠️ CI/CD 自動化建置工作流
- **GitHub Actions 自動建置與雙架構推送**：新增 `.github/workflows/docker-publish.yml`，在每次 `git push` 到 master 時自動在 GitHub 雲端環境打包 **`linux/amd64` (x64) 與 `linux/arm64` (ARM64)** 雙架構 Docker 映像檔並推送至 Docker Hub (`tbdavid2019/telegram-bot-stock2:latest`)，真正打通跨平台與 Watchtower 自動拉取無縫重啟流程。

---

## [2.1.0] - 2026-08-27

### 🚀 新增功能與自動化運維 (DevOps & Automation)
- **Watchtower 無人值守自動更新整合**：
  - 新增 `docker-compose.yml` 配置 `watchtower` 服務（定時自動拉取 Docker Hub 最新映像檔並重啟）。
  - 新增 `start-watchtower.sh` 快速啟動 Watchtower 容器。
  - 在 `Dockerfile` 中加入 `LABEL com.centurylinklabs.watchtower.enable="true"` 支援標籤過濾更新。
- **yfinance 自主排程檢查與 Docker 自動重建**：
  - 新增 `check_and_update_yfinance.sh`，可藉由 cron 定期排程檢查 PyPI 上的 `yfinance` 最新版本。
  - 若有新版本自動 bump `requirements.txt`、commit & push 到 Git，並觸發 `docker build --no-cache` 與映像檔推送。
- **2MD 搜尋引擎即時檢索與全域零幻覺鐵律實裝**：
  - 全面整合 `2md.aiurl.tw`、`2md.glsoft.ai` 與 `create360.ai` 即時財經新聞與全網實體檢索。
  - 在主對話代理人中加入 `search_financial_web` 工具，避免公司上市/IPO狀態、代號或時事產生模型幻覺。

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
