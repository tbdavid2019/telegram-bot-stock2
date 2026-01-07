import os
import asyncio
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib as mpl
import matplotlib.font_manager as fm
import tempfile
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Update, BotCommand, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    ContextTypes,
    MessageHandler, 
    filters
)
import time
import logging
import json

# -------------- Fundamental Analysis 部分 ----------------
import datetime as dt
import pandas as pd
import traceback

from typing import Union, Dict, TypedDict, Annotated

# langchain / langgraph 相關
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph.message import add_messages
from langchain_core.tools import tool

# 載入 .env
load_dotenv()


# DIFY LLM API 配置 
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "http://llm.glsoft.ai/v1/chat-messages")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")  # 確保在 .env 文件中添加 DIFY_API_KEY

# 基本面分析 Prompt（繁體中文）

FUNDAMENTAL_ANALYST_PROMPT = """
You are a professional Fundamental Analyst who evaluates a company's investment value based on stock prices, technical indicators, financial data, news trends, industry environment, and competitor analysis.

You can use the following tools to gather necessary data:
1. get_stock_prices: Retrieve stock price data and technical indicators (such as RSI, MACD, VWAP, Stochastic Oscillator).
2. get_financial_metrics: Obtain key financial indicators (such as P/E, P/B, Debt-to-Equity, Profit Margin, etc.).
3. get_financial_news: Extract the latest news reports and analyze their impact on market sentiment.

Company Overview:
- Business scope and core products/services of {company}.
- Founded year, headquarters location, main markets, and regions.
- Company vision and development strategy.

Market Assessment:
- Stock Symbol: {ticker}
- Market Capitalization: {market_cap} USD/TWD
- Industry: {industry}

Competitor Analysis:
- Major competitors include {competitor A, competitor B}.

Technical Analysis:
Recent Stock Price Trends:
- Analyze the price trend of {company} over the past three months to determine if it is in an upward, downward, or sideways trend.
- Identify key support/resistance levels and assess market momentum changes.

Technical Indicators:
- RSI (Relative Strength Index): Above 70 indicates overbought, below 30 indicates oversold.
- MACD (Moving Average Convergence Divergence): Identifies potential trend changes.
- VWAP (Volume Weighted Average Price): Observes capital flow of institutional investors.
- Stochastic Oscillator: Determines price momentum shifts.

Technical Summary:
- Current technical indicators suggest that {company} is in an (upward/downward/sideways) trend, with short-term price movements expected to (increase/decrease/consolidate).

Fundamental Analysis:
Financial Health:
- Revenue Performance:
  - Total Revenue: {value}
  - Revenue Growth Rate: {value}%
- Profitability:
  - Gross Profit Margin: {value}%
  - Operating Profit Margin: {value}%
  - Net Profit Margin: {value}%
  - Conclusion: The company's profitability is (excellent/good/average/poor).
- Financial Stability:
  - Current Ratio: {value}
  - Quick Ratio: {value}
  - Debt-to-Equity Ratio: {value}
  - Conclusion: The company's financial structure is (stable/high-risk/high-leverage), and its short-term debt-paying ability is (good/average/poor).

Market Valuation:
- P/E Ratio: {value}, representing market expectations for the company’s future earnings.
- Forward P/E Ratio: {value}, indicating the estimated future profitability of the company.
- P/B Ratio: {value}, assessing whether the company's valuation is reasonable.
- Dividend Yield: {value}%, indicating investor returns from dividends.
- Conclusion: Based on the above valuation indicators, the company’s current valuation is (undervalued/reasonable/overvalued).

Financial Summary:
- The company’s current financial status is (stable/growing/under financial pressure). Investors should (focus on profitability/evaluate debt levels/consider valuation rationality).

Latest News and Market Sentiment:
Recent Major News:
1. {News Title 1} - Source: {source}
   - Summary: {news summary}
   - Impact Analysis: This may have a (positive/negative/neutral) impact on {company}’s (stock price/market sentiment/earnings forecast).

2. {News Title 2} - Source: {source}
   - Summary: {news summary}
   - Impact Analysis: {impact description}

3. {News Title 3} - Source: {source}
   - Summary: {news summary}
   - Impact Analysis: {impact description}

Market Sentiment Summary:
- The current market sentiment towards {company} is (optimistic/neutral/pessimistic), with short-term fluctuation expected to be within (X%).

Industry and Competitor Analysis:
Industry Trends:
- The growth potential of this industry is (high/medium/low), with key trends including (technological innovation/regulatory changes/demand fluctuations).
- Major competitors include {competitor A, competitor B}, and {company} is (advantaged/disadvantaged/in a competitive position) in terms of (market share/technological innovation/financial stability).

Investment Recommendations:
Short-term Investment Recommendations:
- Recommended entry timing: (Technical analysis indicates oversold conditions, presenting a short-term rebound opportunity).
- Risk factors: (High stock price volatility/Weak market sentiment).
- Predicted short-term price fluctuation range: (X% ~ Y%).

Medium-to-Long-Term Investment Recommendations:
- Suitable investor type: (Value investors/Growth investors/Short-term traders).
- Risk factors: (Fierce industry competition/Unstable financial status).
- Recommended strategy: (Buy on dips/Observe/Reduce holdings/Sell).

Final Conclusion:
Considering technical factors, financial conditions, market sentiment, and industry trends, the investment rating for {company} is:
- (Buy/Hold/Reduce/Sell)
- Short-term target price: X
- Medium-to-long-term estimated price: Y
- Recommended holding period: (Short-term/Mid-term/Long-term)

Please generate the response in Traditional Chinese  請用繁體中文輸出.
"""


# --------------- Tools ---------------
@tool
def get_stock_prices(ticker: str) -> Dict:
    """Fetches historical stock price data and technical indicators for a given ticker."""
    print(f"=== [Tool] get_stock_prices called with ticker: {ticker}")
    try:
        data = yf.download(
            ticker,
            start=dt.datetime.now() - dt.timedelta(weeks=13),
            end=dt.datetime.now(),
            interval='1d'
        )
        df = data.copy()
        if len(df.columns) > 0 and isinstance(df.columns[0], tuple) and len(df.columns[0]) > 1:
            df.columns = [i[0] for i in df.columns]
        data.reset_index(inplace=True)
        data.Date = data.Date.astype(str)

        from ta.momentum import RSIIndicator, StochasticOscillator
        from ta.trend import MACD
        from ta.volume import volume_weighted_average_price

        # 計算技術指標
        indicators = {}

        # RSI
        rsi_series = RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
        indicators["RSI"] = round(rsi_series, 2)

        # Stochastic Oscillator
        sto_series = StochasticOscillator(df['High'], df['Low'], df['Close'], window=14).stoch().iloc[-1]
        indicators["Stochastic_Oscillator"] = round(sto_series, 2)

        # MACD
        macd = MACD(df['Close'])
        macd_series = macd.macd().iloc[-1]
        macd_signal_series = macd.macd_signal().iloc[-1]
        indicators["MACD"] = round(macd_series, 2)
        indicators["MACD_Signal"] = round(macd_signal_series, 2)

        # VWAP
        vwap_series = volume_weighted_average_price(
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            volume=df['Volume'],
        ).iloc[-1]
        indicators["VWAP"] = round(vwap_series, 2)

        return {
            "stock": ticker,
            "latest_close_price": round(df['Close'].iloc[-1], 2),
            "indicators": indicators
        }
    except Exception as e:
        return {"error": f"無法獲取技術分析數據: {str(e)}"}

@tool
def get_financial_metrics(ticker: str) -> Dict:
    """Fetches key financial ratios for a given ticker."""
    print(f"=== [Tool] get_financial_metrics called with ticker: {ticker}")
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # 獲取營收增長率，使用yfinance直接提供的數據
        revenue_growth = info.get('revenueGrowth', 'N/A')
        if revenue_growth is not None and revenue_growth != 'N/A':
            revenue_growth = round(revenue_growth * 100, 2)
        
        # 注意：yfinance並不直接提供確定的競爭對手信息，這裡我們省略這部分
        
        return {
            "stock": ticker,
            "company_info": {
                "name": info.get('longName', 'N/A'),
                "sector": info.get('sector', 'N/A'),
                "industry": info.get('industry', 'N/A'),
                "market_cap": info.get('marketCap', 'N/A'),
                "market_cap_billions": round(info.get('marketCap', 0) / 1e9, 2) if info.get('marketCap') else 'N/A'
            },
            "revenue_data": {
                "total_revenue": info.get('totalRevenue', 'N/A'),
                "revenue_growth": revenue_growth
            },
            "profitability_ratios": {
                "gross_profit_margin": info.get('grossMargins', 'N/A'),
                "operating_profit_margin": info.get('operatingMargins', 'N/A'),
                "net_profit_margin": info.get('profitMargins', 'N/A')
            },
            "financial_health": {
                "current_ratio": info.get('currentRatio', 'N/A'),
                "quick_ratio": info.get('quickRatio', 'N/A'),
                "debt_to_equity": info.get('debtToEquity', 'N/A')
            },
            "market_ratios": {
                "pe_ratio": info.get('trailingPE', 'N/A'),
                "forward_pe": info.get('forwardPE', 'N/A'),
                "price_to_book": info.get('priceToBook', 'N/A'),
                "dividend_yield": info.get('dividendYield', 'N/A')
            }
        }
    except Exception as e:
        return {"error": f"無法獲取財務指標數據: {str(e)}"}


@tool
def get_financial_news(ticker: str) -> Dict:
    """Fetches the latest financial news related to a given ticker using multiple strategies."""
    print(f"=== [Tool] get_financial_news called with ticker: {ticker}")
    try:
        # 方法1: 嘗試使用yfinance
        stock = yf.Ticker(ticker)
        news = stock.news
        latest_news = []
        
        if news and len(news) > 0:
            for idx, article in enumerate(news[:5]):
                try:
                    # 檢查是否有 content 字段
                    if 'content' in article:
                        # 嘗試解析 content 字段
                        content = article['content']
                        print(f"=== [Debug] News {idx+1} content type: {type(content)}")
                        if isinstance(content, dict):
                            # 從內容字典中提取標題
                            title = content.get('title', "無標題")
                            # 嘗試從各種可能的地方獲取連結
                            link = "#"
                            if 'clickThroughUrl' in content and isinstance(content['clickThroughUrl'], dict) and 'url' in content['clickThroughUrl']:
                                link = content['clickThroughUrl']['url']
                            elif 'canonicalUrl' in content and isinstance(content['canonicalUrl'], dict) and 'url' in content['canonicalUrl']:
                                link = content['canonicalUrl']['url']
                            elif 'url' in content:
                                link = content['url']
                            elif 'link' in content:
                                link = content['link']
                            
                            publisher = article.get('publisher', '未知來源')
                            published_date = article.get('providerPublishTime', int(time.time()))
                            
                            latest_news.append({
                                "title": title,
                                "publisher": publisher,
                                "link": link,
                                "published_date": published_date
                            })
                        elif isinstance(content, str):
                            # 如果是字符串，嘗試解析為 JSON
                            try:
                                content_json = json.loads(content)
                                title = content_json.get('title', "無標題")
                                link = content_json.get('url', "#")
                                publisher = article.get('publisher', '未知來源')
                                published_date = article.get('providerPublishTime', int(time.time()))
                                
                                latest_news.append({
                                    "title": title,
                                    "publisher": publisher,
                                    "link": link,
                                    "published_date": published_date
                                })
                            except json.JSONDecodeError:
                                print(f"=== [Debug] 無法解析 content 字符串為 JSON")
                                continue
                    else:
                        # 直接使用標準欄位
                        title = article.get('title', '標題不可用')
                        publisher = article.get('publisher', '未知來源')
                        link = article.get('link', '#')
                        published_date = article.get('providerPublishTime', int(time.time()))
                        
                        latest_news.append({
                            "title": title,
                            "publisher": publisher,
                            "link": link,
                            "published_date": published_date
                        })
                except Exception as article_error:
                    print(f"=== [Debug] 解析新聞項目 {idx+1} 時出錯: {str(article_error)}")
                    continue
        
        # 方法2: 如果yfinance無法獲取，使用網頁爬取
        if not latest_news:
            print(f"=== [Debug] 使用備用方案抓取新聞...")
            try:
                url = f"https://finance.yahoo.com/quote/{ticker}/news"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                response = requests.get(url, headers=headers)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 找出新聞標題和連結
                news_items = []
                
                # 尋找包含新聞的元素
                for article in soup.select('div.Ov\(h\)'):
                    title_elem = article.select_one('a')
                    if title_elem and title_elem.text:
                        title = title_elem.text.strip()
                        link = title_elem.get('href', '')
                        if link.startswith('/'):
                            link = f"https://finance.yahoo.com{link}"
                        if title and link:
                            news_items.append((title, link))
                
                if not news_items:  # 如果找不到特定結構，使用更通用的搜索
                    for link in soup.find_all('a', href=True):
                        if '/news/' in link.get('href', '') and link.text:
                            title = link.text.strip()
                            href = link['href']
                            full_url = f"https://finance.yahoo.com{href}" if href.startswith('/') else href
                            if title and len(title) > 15:  # 過濾可能不是標題的短文本
                                news_items.append((title, full_url))
                
                # 移除重複的新聞項目
                news_items = list(set(news_items))
                
                # 添加到回覆中
                for i, (title, link) in enumerate(news_items[:5]):
                    latest_news.append({
                        "title": title,
                        "publisher": "Yahoo Finance",
                        "link": link,
                        "published_date": int(time.time())
                    })
            except Exception as scrape_error:
                print(f"=== [Error] 備用爬蟲失敗: {str(scrape_error)}")
                import traceback
                traceback.print_exc()
        
        # 如果仍然沒有新聞，提供一個默認回應
        if not latest_news:
            latest_news.append({
                "title": f"無法找到 {ticker} 的相關新聞",
                "publisher": "系統通知",
                "link": f"https://finance.yahoo.com/quote/{ticker}",
                "published_date": int(time.time())
            })
            
        return {"stock": ticker, "news": latest_news}
    
    except Exception as e:
        print(f"=== [Error] 獲取新聞失敗: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "stock": ticker, 
            "news": [{
                "title": f"獲取 {ticker} 新聞時發生錯誤",
                "publisher": "系統通知",
                "link": f"https://finance.yahoo.com/quote/{ticker}",
                "published_date": int(time.time())
            }]
        }

# --------------- LangGraph / State ---------------
class State(TypedDict):
    messages: Annotated[list, add_messages]
    stock: str

graph_builder = StateGraph(State)

# 把三個工具都放入
tools = [get_stock_prices, get_financial_metrics, get_financial_news]

# 初始化 ChatOpenAI - 從環境變數讀取模型和 base_url
# 預設使用 gpt-4o，可透過 .env 設定 OPENAI_MODEL 來更改
openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
openai_base_url = os.getenv("OPENAI_BASE_URL", None)

# 建立 ChatOpenAI 配置
llm_config = {
    "model_name": openai_model,
    "openai_api_key": os.getenv("OPENAI_API_KEY"),
    "temperature": 0
}

# 如果有設定 base_url，則加入配置
if openai_base_url and openai_base_url.strip():
    llm_config["base_url"] = openai_base_url
    print(f"✅ 使用自訂 OpenAI Base URL: {openai_base_url}")

llm = ChatOpenAI(**llm_config)
print(f"✅ 使用 OpenAI 模型: {openai_model}")
print(f"✅ DIFY Base URL: {DIFY_BASE_URL}")

llm_with_tool = llm.bind_tools(tools)


async def ai2_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """使用投資大師智能分析 API 進行股票分析"""
    
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ai2 TSLA")
        return
    
    ticker = context.args[0].upper()
    
    try:
        # 發送請求到 API
        await update.message.reply_text(f"🔍 正在分析 {ticker}，這可能需要幾秒鐘...")
        
        api_url = "http://dns.glsoft.ai:6000/api/analysis"
        headers = {"Content-Type": "application/json"}
        payload = {
            "tickers": ticker.lower(),  # API 需要小寫的股票代碼
            "selectedAnalysts": [
                "ben_graham", "bill_ackman", "cathie_wood", "charlie_munger", "michael_burry", "peter_lynch",
                "phil_fisher", "nancy_pelosi", "warren_buffett", "wsb", "technical_analyst",
                "fundamentals_analyst", "sentiment_analyst", "valuation_analyst"
            ],
            "modelName": "gpt-4o"
        }
        
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()  # 如果請求失敗，拋出異常
        
        # 解析 API 回應
        data = response.json()
        
        # 提取目標股票的數據
        ticker_data = data["analyst_signals"]
        decisions = data["decisions"][ticker.lower()]
        
        # 準備回覆內容
        reply = f"📊 **{ticker} 多位投資大師分析結果**\n\n"
        
        # 添加決策摘要
        action_dict = {
            "buy": "買入",
            "sell": "賣出",
            "hold": "持有",
            "short": "做空"
        }
        action_trans = action_dict.get(decisions['action'].lower(), decisions['action'].upper())
        reply += f"**最終決策**: {action_trans} (信心度: {decisions['confidence']}%)\n"
        reply += f"**建議數量**: {decisions['quantity']} 股\n"
        reply += f"**理由**: {decisions['reasoning']}\n\n"
        
        # 添加各個分析師的觀點
        reply += "**各投資大師觀點**:\n"
        
        # 定義重要分析師列表和他們的中文名字
        key_analysts = {
            "warren_buffett_agent": "👴 華倫·巴菲特 (Warren Buffett)",
            "cathie_wood_agent": "👩‍💼 凱西·伍德 (Cathie Wood)",
            "charlie_munger_agent": "🧓 查理·蒙格 (Charlie Munger)",
            "ben_graham_agent": "📚 班傑明·葛拉漢 (Ben Graham)",
            "bill_ackman_agent": "👨‍💼 比爾·阿克曼 (Bill Ackman)",
            "nancy_pelosi_agent": "👵 南希·佩洛西 (Nancy Pelosi)",
            "michael_burry_agent": "😏 麥可·貝瑞 (Michael Burry)",
            "peter_lynch_agent": "🤠 彼得·林區 (Peter Lynch)",
            "phil_fisher_agent": "📖 菲爾·費雪 (Phil Fisher)",
            "wsb_agent": "🦍 華爾街賭場 (WallStreetBets)",
            "fundamentals_agent": "📈 基本面分析師 (Fundamentals Analyst)",
            "technical_analyst_agent": "📉 技術分析師 (Technical Analyst)",
            "valuation_agent": "💰 估值分析師 (Valuation Analyst)",
            "sentiment_agent": "🔍 情緒分析師 (Sentiment Analyst)"
        }
        
        # 信號中文翻譯
        signal_dict = {
            "bearish": "看空",
            "bullish": "看多",
            "neutral": "中立"
        }
        
        # 添加每個分析師的意見（只包含重要分析師）
        for agent_name, data in ticker_data.items():
            if agent_name in key_analysts and ticker.lower() in data:
                analyst_info = data[ticker.lower()]
                if "signal" in analyst_info:
                    signal = analyst_info["signal"]
                    signal_emoji = "🔴" if signal == "bearish" else "🟢" if signal == "bullish" else "⚪"
                    signal_trans = signal_dict.get(signal, signal.capitalize())
                    
                    confidence = analyst_info.get("confidence", "N/A")
                    reason_short = analyst_info.get("reasoning", "未提供")
                    if isinstance(reason_short, dict):
                        # 如果 reasoning 是字典，嘗試提取關鍵信息
                        reason_short = "詳細分析請查看原始數據"
                    elif isinstance(reason_short, str) and len(reason_short) > 100:
                        # 如果是長文本，截取前部分
                        reason_short = reason_short[:100] + "..."
                    
                    reply += f"{key_analysts[agent_name]}: {signal_emoji} {signal_trans} (信心度: {confidence}%)\n"
        
        # 發送回應
        await update.message.reply_text(reply, parse_mode="Markdown")
        
    except Exception as e:
        error_msg = f"❌ 分析時發生錯誤：{str(e)}"
        print(f"=== [Error] {error_msg}")
        traceback.print_exc()
        await update.message.reply_text(error_msg)

# ----------- 修正版 fundamental_analyst 函數 -----------
def fundamental_analyst(state: State):
    """使用工具鏈進行基本面分析"""
    print("=== [Debug] Enter fundamental_analyst with state:", state)
    
    # 1. 先檢查是否已經有 AI 回覆，避免重複處理
    if state["messages"] and any(isinstance(msg, AIMessage) for msg in state["messages"]):
        # 如果已經有 AI 回覆，直接返回最後一條 AI 訊息
        for msg in reversed(state["messages"]):
            if isinstance(msg, AIMessage):
                print("=== [Debug] Found existing AI response, returning it")
                return {"messages": [msg]}
    
    # 2. 準備 prompt 和使用者問題
    prompt = FUNDAMENTAL_ANALYST_PROMPT.replace("{company}", state['stock'])
    stock = state['stock']
    user_question = state['messages'][0].content if state['messages'] else "Should I buy this stock?"
    
    # 3. 直接使用工具進行分析，而不是再次呼叫 graph.stream
    try:
        # 3.1 股價和技術指標
        print(f"=== [Debug] Getting stock prices for {stock}")
        price_data = get_stock_prices.invoke({"ticker": stock})
        
        # 3.2 財務指標
        print(f"=== [Debug] Getting financial metrics for {stock}")
        metrics = get_financial_metrics.invoke({"ticker": stock})
        
        # 3.3 新聞
        print(f"=== [Debug] Getting financial news for {stock}")
        news = get_financial_news.invoke({"ticker": stock})
        
        # 3.4 整合資料，讓 LLM 生成最終分析
        analysis_prompt = f"""
        根據以下 {stock} 的資料，進行全面的基本面分析並回答使用者問題："{user_question}"
        
        股價與技術指標資料：
        {price_data}
        
        財務指標：
        {metrics}
        
        相關新聞：
        {news}
        
        {prompt}
        """
        
        # 3.5 使用 LLM 生成最終分析
        response = llm.invoke(analysis_prompt)
        
        print("=== [Debug] LLM analysis generated")
        # 3.6 返回 AI 的回應
        return {"messages": [AIMessage(content=response.content)]}
        
    except Exception as e:
        error_msg = f"分析過程中發生錯誤: {str(e)}"
        print(f"=== [Error] {error_msg}")
        traceback.print_exc()
        return {"messages": [AIMessage(content=error_msg)]}

# 建立節點與連線
graph_builder.add_node('fundamental_analyst', fundamental_analyst)

# 讓 START -> fundamental_analyst
graph_builder.add_edge(START, 'fundamental_analyst')

# 新增 ToolNode
graph_builder.add_node(ToolNode(tools))

# 若 LLM 要呼叫工具，就進入 tools_condition，否則直接結束
graph_builder.add_conditional_edges('fundamental_analyst', tools_condition)
graph_builder.add_conditional_edges('tools', tools_condition)

# 從 tools -> fundamental_analyst，並在不再呼叫工具時結束
graph_builder.add_edge('tools', 'fundamental_analyst')
graph_builder.add_edge('fundamental_analyst', END)

graph = graph_builder.compile()

# ---------------------------------------------------------
# -------------- Telegram Bot 部分 ----------------

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s - %(levelname)s - %(message)s"
# )

# 添加 DIFY LLM 查詢功能
async def llm_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """LLM API 查詢功能"""
    query = " ".join(context.args) if context.args else None
    if not query:
        await update.message.reply_text("❌ 請提供問題內容，例如：/llm AVGO 的股價前景如何？")
        return

    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": {},  # 空 inputs
        "query": query,
        "response_mode": "streaming",  # Streaming 模式
        "conversation_id": "",
        "user": str(update.effective_user.id)
    }

    try:
        await update.message.reply_text("🤖 正在生成回應，請稍候...")
        # 發送 POST 請求
        response = requests.post(DIFY_BASE_URL, headers=headers, json=payload, stream=True)
        response.raise_for_status()
        
        # 處理 Streaming 回應
        ai_response = ""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode("utf-8")
                if decoded_line.startswith("data:"):
                    try:
                        chunk = json.loads(decoded_line[5:].strip())
                        if "answer" in chunk:
                            ai_response += chunk["answer"]
                    except json.JSONDecodeError:
                        print(f"無法解析 JSON: {decoded_line}")
        
        # 發送完整 AI 回應
        if ai_response:
            await update.message.reply_text(f"🤖 **AI 回應**：\n\n{ai_response}", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ 收到空回應，請稍後再試。")
    
    except requests.exceptions.RequestException as e:
        await update.message.reply_text(f"❌ 發送請求時發生錯誤：{str(e)}")
    except Exception as e:
        print(f"LLM 查詢錯誤: {str(e)}")
        traceback.print_exc()
        await update.message.reply_text(f"❌ 發生未知錯誤：{str(e)}")


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 設定字體
def setup_font():
    try:
        url_font = "https://drive.google.com/uc?id=1eGAsTN1HBpJAkeVM57_C7ccp7hbgSz3_"
        response_font = requests.get(url_font)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ttf") as tmp_file:
            tmp_file.write(response_font.content)
            tmp_file_path = tmp_file.name
        fm.fontManager.addfont(tmp_file_path)
        mpl.rc("font", family="Taipei Sans TC Beta")
        print("✅ 字體設置成功：Taipei Sans TC Beta")
    except Exception as e:
        print(f"⚠️ 字體設置失敗: {str(e)}")
        mpl.rc("font", family="SimHei")

setup_font()

# --- 清除並重設 Bot 指令 ---
async def reset_commands(application):
    commands = [
        BotCommand("start", "啟動機器人"),
        BotCommand("s", "查詢股價和K線圖"),
        BotCommand("n", "查詢美股新聞"),
        BotCommand("ny", "查詢台股新聞"),
        BotCommand("p", "預測公司股價 (5 天區間)"),
        BotCommand("ai", "輸入股票代號 回答該公司股票值不值得購入投資"),
        BotCommand("ai2", "多位投資大師集體分析股票"), 
        BotCommand("llm", "使用 LLM 回答公司股票問題 可以配合 ai指令使用 "),
        BotCommand("h", "顯示其他股票工具連結")
    ]
    await application.bot.set_my_commands(commands)
    print("✅ 新指令設置成功！")

# --- 查詢股價與 K 線圖 ---
async def stock_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/s 2330.TW 或 /s TSLA")
        return

    stock_code = context.args[0].upper()
    try:
        stock = yf.Ticker(stock_code)
        hist = stock.history(period="6mo")
        if hist.empty:
            await update.message.reply_text(f"⚠️ 無法找到 {stock_code} 的股價數據，請確認股票代碼是否正確。")
            return

        current_price = stock.info.get("currentPrice", hist["Close"].iloc[-1])
        open_price = hist["Open"].iloc[-1]
        close_price = hist["Close"].iloc[-1]
        high_price = hist["High"].iloc[-1]
        low_price = hist["Low"].iloc[-1]
        volume = hist["Volume"].iloc[-1]

        message = (
            f"📊 **{stock_code} 股價資訊**\n\n"
            f"🔹 **現價 / 收盤價**：{current_price:.2f}\n"
            f"🔸 **開盤價**：{open_price:.2f}\n"
            f"🔺 **最高價**：{high_price:.2f}\n"
            f"🔻 **最低價**：{low_price:.2f}\n"
            f"📈 **成交量**：{volume:,}"
        )
        await update.message.reply_text(message, parse_mode="Markdown")

        # 繪製 K 線圖（日K、週K、月K）
        for label, resample, color in [
            ("日K線", "D", "blue"),
            ("週K線", "W", "green"),
            ("月K線", "ME", "red")
        ]:
            data = hist["Close"].resample(resample).mean()
            plt.figure(figsize=(10, 5))
            plt.plot(data, label=label, color=color)
            plt.title(f"{stock_code} {label}")
            plt.legend()
            plt.grid(True, linestyle="--", alpha=0.7)
            path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
            plt.savefig(path)
            plt.close()
            await update.message.reply_photo(photo=open(path, "rb"), caption=f"📊 {label}")

    except Exception as e:
        await update.message.reply_text(f"❌ 查詢股價時發生錯誤：{str(e)}")

# --- 查詢美股新聞 ---
async def stock_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/n TSLA")
        return
    stock_code = context.args[0].upper()
    try:
        print(f"=== [Debug] 正在查詢 {stock_code} 的新聞")
        stock = yf.Ticker(stock_code)
        news = stock.news
        
        # 詳細輸出新聞數據結構
        print(f"=== [Debug] News data structure for {stock_code}:")
        print(f"News type: {type(news)}, length: {len(news) if isinstance(news, list) else 'N/A'}")
        for i, item in enumerate(news[:2] if isinstance(news, list) else []):
            print(f"News item {i+1} type: {type(item)}")
            print(f"News item {i+1} keys: {item.keys() if hasattr(item, 'keys') else 'No keys'}")
            print(f"News item {i+1} full content: {item}")
            
        if not news:
            await update.message.reply_text(f"⚠️ 找不到 {stock_code} 的新聞。")
            return
        
        # 根據新的數據結構解析
        reply_text = f"📰 **{stock_code} 美股新聞**：\n"
        news_count = 0
        
        for idx, article in enumerate(news[:10]):  # 嘗試獲取更多，最多處理10條
            if news_count >= 5:  # 只顯示5條
                break
                
            try:
                # 檢查是否有 content 字段
                if 'content' in article:
                    # 嘗試解析 content 字段
                    content = article['content']
                    print(f"=== [Debug] News {idx+1} content type: {type(content)}")
                    
                    if isinstance(content, dict):
                        # 從內容字典中提取標題
                        title = content.get('title', "無標題")
                        
                        # 嘗試從各種可能的地方獲取連結
                        link = "#"
                        if 'clickThroughUrl' in content and isinstance(content['clickThroughUrl'], dict) and 'url' in content['clickThroughUrl']:
                            link = content['clickThroughUrl']['url']
                        elif 'canonicalUrl' in content and isinstance(content['canonicalUrl'], dict) and 'url' in content['canonicalUrl']:
                            link = content['canonicalUrl']['url']
                        elif 'url' in content:
                            link = content['url']
                        elif 'link' in content:
                            link = content['link']
                        
                        # 添加到回覆中
                        reply_text += f"{news_count+1}. [{title}]({link})\n"
                        news_count += 1
                    elif isinstance(content, str):
                        # 如果是字符串，嘗試解析為 JSON
                        try:
                            content_json = json.loads(content)
                            title = content_json.get('title', "無標題")
                            link = content_json.get('url', "#")
                            reply_text += f"{news_count+1}. [{title}]({link})\n"
                            news_count += 1
                        except json.JSONDecodeError:
                            print(f"=== [Debug] 無法解析 content 字符串為 JSON")
                            continue
                
            except Exception as article_error:
                print(f"=== [Debug] 解析新聞項目 {idx+1} 時出錯: {str(article_error)}")
                continue
                
        # 如果沒有成功解析任何新聞，嘗試使用備用方法
        if news_count == 0:
            # 直接使用網頁爬取作為備用方案
            print(f"=== [Debug] 使用備用方案抓取新聞...")
            try:
                url = f"https://finance.yahoo.com/quote/{stock_code}/news"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                response = requests.get(url, headers=headers)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 找出新聞標題和連結
                news_items = []
                # 尋找包含新聞的元素
                for article in soup.select('div.Ov\(h\)'):
                    title_elem = article.select_one('a')
                    if title_elem and title_elem.text:
                        title = title_elem.text.strip()
                        link = title_elem.get('href', '')
                        if link.startswith('/'):
                            link = f"https://finance.yahoo.com{link}"
                        if title and link:
                            news_items.append((title, link))
                
                if not news_items:  # 如果找不到特定結構，使用更通用的搜索
                    for link in soup.find_all('a', href=True):
                        if '/news/' in link.get('href', '') and link.text:
                            title = link.text.strip()
                            href = link['href']
                            full_url = f"https://finance.yahoo.com{href}" if href.startswith('/') else href
                            if title and len(title) > 15:  # 過濾可能不是標題的短文本
                                news_items.append((title, full_url))
                
                # 移除重複的新聞項目
                news_items = list(set(news_items))
                
                # 添加到回覆中
                for i, (title, link) in enumerate(news_items[:5]):
                    reply_text += f"{news_count+1}. [{title}]({link})\n"
                    news_count += 1
            
            except Exception as scrape_error:
                print(f"=== [Error] 備用爬蟲失敗: {str(scrape_error)}")
                traceback.print_exc()
        
        # 如果依然沒有新聞，嘗試第三種方法 - Google 財經新聞搜索
        if news_count == 0:
            print(f"=== [Debug] 嘗試使用 Google 財經新聞搜索...")
            try:
                google_url = f"https://www.google.com/search?q={stock_code}+stock+news&tbm=nws"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                response = requests.get(google_url, headers=headers)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Google 搜索結果通常在 div.g 或類似結構中
                news_items = []
                for result in soup.select('div.SoaBEf'):
                    title_elem = result.select_one('div.mCBkyc')
                    link_elem = result.select_one('a')
                    
                    if title_elem and link_elem:
                        title = title_elem.text.strip()
                        link = link_elem.get('href', '')
                        # Google 的連結通常包含重定向，需要提取實際 URL
                        if 'url=' in link:
                            link = link.split('url=')[1].split('&')[0]
                        if title and link:
                            news_items.append((title, link))
                
                # 添加到回覆中
                for i, (title, link) in enumerate(news_items[:5]):
                    reply_text += f"{news_count+1}. [{title}]({link})\n"
                    news_count += 1
            
            except Exception as google_error:
                print(f"=== [Error] Google 新聞搜索失敗: {str(google_error)}")
        
        # 最終結果
        if news_count > 0:
            await update.message.reply_text(reply_text, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ 無法獲取 {stock_code} 的相關新聞。可能原因：\n1. 股票代碼不正確\n2. 近期沒有相關新聞\n3. 資料源暫時無法訪問")
            
    except Exception as e:
        error_msg = f"❌ 查詢新聞時發生錯誤：{str(e)}"
        print(f"=== [Error] {error_msg}")
        traceback.print_exc()
        await update.message.reply_text(error_msg)



# --- 查詢 Yahoo 台股新聞 ---
async def taiwan_stock_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ny 2330.TW")
        return

    stock_code = context.args[0].upper()
    url = f"https://tw.news.yahoo.com/search?p={stock_code}"
    print(f"📡 正在抓取：{url}")

    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        news_links = []
        for item in soup.find_all("a", href=True):
            href = item["href"]
            if href.startswith("/"):
                full_url = f"https://tw.news.yahoo.com{href}"
                title = item.get_text(strip=True)
                if title and full_url not in news_links:
                    news_links.append((title, full_url))
        valid_news = [(title, url) for title, url in news_links if "news" in url][:5]
        if not valid_news:
            await update.message.reply_text(f"⚠️ 找不到 {stock_code} 的新聞。")
            return
        reply_text = f"📰 **{stock_code} 的 Yahoo News**：\n"
        for idx, (title, url) in enumerate(valid_news):
            reply_text += f"{idx+1}. [{title}]({url})\n"
        await update.message.reply_text(reply_text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ 抓取新聞時發生錯誤：{str(e)}")

# --- 基本面分析指令 (/ai) ---
async def ai_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    使用 fundamental_analyst 功能進行股票基本面分析 (多步驟工具呼叫)，
    請使用者傳入股票代碼，預設問題為 "Should I buy this stock?"
    """
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ai TSLA")
        return

    ticker = context.args[0].upper()
    try:
        state = {
            "stock": ticker, 
            "messages": [HumanMessage(content="Should I buy this stock?")]
        }
        result = fundamental_analyst(state)

        final_answer = "(No response)"
        if result["messages"]:
            final_answer = result["messages"][-1].content

        await update.message.reply_text(f"🤖 **基本面分析回應**：\n\n{final_answer}", parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ 基本面分析時發生錯誤：{str(e)}")

# --- 股價預測函數 (Prophet) ---
def predict_stock_price(stock_code, period, prediction_days):
    try:
        df = yf.download(stock_code, period=period)
        if df.empty:
            return "無法獲取股票數據", None
        
        data = df.reset_index()[['Date', 'Close']]
        data.columns = ['ds', 'y']
        
        from prophet import Prophet
        model = Prophet(daily_seasonality=True)
        model.fit(data)
        
        future = model.make_future_dataframe(periods=prediction_days)
        forecast = model.predict(future)
        
        plt.figure(figsize=(12, 6))
        plt.plot(data['ds'], data['y'], label='實際收盤價', color='blue')
        plt.plot(forecast['ds'], forecast['yhat'], label='預測收盤價', color='orange', linestyle='--')
        plt.fill_between(forecast['ds'], forecast['yhat_lower'], forecast['yhat_upper'], 
                         color='orange', alpha=0.2)
        plt.title(f'{stock_code} 股價預測', pad=20)
        plt.xlabel('日期')
        plt.ylabel('股價')
        plt.xticks(rotation=45)
        plt.legend()
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.tight_layout()
        
        return forecast.tail(prediction_days).to_string(), plt.gcf()
    except Exception as e:
        logging.error(f"預測過程發生錯誤: {str(e)}")
        return f"預測過程發生錯誤: {str(e)}", None

# --- 預測股價功能 (/p) ---
async def prophet_predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/p META")
        return

    stock_code = context.args[0].upper()
    try:
        forecast_text, chart = predict_stock_price(stock_code, period="1y", prediction_days=5)
        if chart:
            path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
            chart.savefig(path)
            plt.close()
            await update.message.reply_photo(photo=open(path, "rb"), caption=f"📊 **{stock_code} 預測 5 天股價區間**")
            await update.message.reply_text(f"```{forecast_text}```", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ 無法預測 {stock_code} 的股價。")
    except Exception as e:
        await update.message.reply_text(f"❌ 預測股價時發生錯誤：{str(e)}")

# --- 顯示其他工具連結 (/h) ---
async def tools_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "🛠 **其他股票工具**\n\n"
        "📊 台股預測 (LSTM)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/twStock-predict)\n"
        "📈 美股台股潛力股預測 (LSTM)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/twStock-Underdogs)\n"
        "🔮 美股台股預測 (Prophet)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/Stock-Predict-Prophet)\n"
        "🔮 多位投資大師集體分析股票：[點擊使用](https://huggingface.co/spaces/tbdavid2019/ai-hedge-fund)"
    )
    await update.message.reply_text(message, parse_mode="Markdown")

# --- 防呆提示功能：非指令訊息回覆提示 ---
async def default_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ 您好，請使用以下指令來操作本 Bot：\n\n"
        "• `/ai 股票代碼` - 綜合分析該公司股票值不值得購入投資\n"
        "   範例：`/ai TSLA`\n\n"
        "• `/ai2 股票代碼` - 多位投資大師集體分析股票\n"
        "   範例：`/ai2 TSLA`\n\n"
        "• `/s 股票代碼` - 查詢公司股價和K線圖\n"
        "   範例：`/s TSLA`\n\n"
        "• `/p 股票代碼` - 預測公司股價 (例如預測未來5天區間)\n"
        "   範例：`/p META`\n\n"
        "• `/n 股票代碼` - 查詢公司的英文新聞\n"
        "   範例：`/n AAPL`\n\n"
        "• `/ny 股票代碼` - 查詢公司的中文新聞\n"
        "   範例：`/ny 2002.TW`\n\n"
        "請以斜線 (/) 開頭的指令操作，謝謝！"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# --- 啟動指令 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_message = (
        "🎉 歡迎使用DAVID888股票資訊機器人！\n\n"
        "本 Bot 提供以下功能：\n"
        "• `/ai 股票代碼` - 綜合分析該公司股票值不值得購入投資 (範例：`/ai TSLA`)\n"
        "• `/ai2 股票代碼` - 多位投資大師集體分析股票 (範例：`/ai2 AMD`)\n"  # 添加新命令描述
        "• `/s 股票代碼` - 查詢公司股價和K線圖 (範例：`/s PLTR`)\n"
        "• `/p 股票代碼` - 預測公司股價 (範例：`/p META`)\n"
        "• `/n 股票代碼` - 查詢公司的英文新聞 (範例：`/n AAPL`)\n"
        "• `/ny 股票代碼` - 查詢台灣公司的中文新聞 (範例：`/ny 2002.TW`)\n\n"
        "• `/llm 問題` - 使用 LLM 回答任何問題 (範例：`/llm AAPL 的股價前景如何？`)\n\n"
        "請選擇以下功能："
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("/s 2330.TW  查詢股價和K線圖"), KeyboardButton("/n TSLA 查詢美股新聞")],
            [KeyboardButton("/ny 2330.TW 查詢台股新聞"), KeyboardButton("/ai TSLA 綜合分析")],
            [KeyboardButton("/ai2 TSLA 投資大師分析"),KeyboardButton("/llm 請介紹一下AMD如何 ")]
        ],
        resize_keyboard=True
    )
    await update.message.reply_text(help_message, reply_markup=keyboard)

# --- 主程式 ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("s", stock_info))
    app.add_handler(CommandHandler("n", stock_news))
    app.add_handler(CommandHandler("ny", taiwan_stock_news))
    app.add_handler(CommandHandler("p", prophet_predict))
    app.add_handler(CommandHandler("ai", ai_query))
    app.add_handler(CommandHandler("ai2", ai2_analysis))  
    app.add_handler(CommandHandler("llm", llm_query))
    app.add_handler(CommandHandler("h", tools_help))
    # 非指令文字訊息觸發防呆提示
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, default_message_handler))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(reset_commands(app))

    print("🚀 Bot 已啟動...")
    app.run_polling()

if __name__ == "__main__":
    main()