import asyncio
import io
import json
import logging
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib as mpl
import matplotlib.font_manager as fm
import requests
from telegram import Update
from telegram.ext import ContextTypes
from bs4 import BeautifulSoup

# Setup Font (run once at import time or lazily)
try:
    # Use config-defined font setup or robust system fallback
    mpl.rc("font", family="sans-serif") 
    # Proper font setup logic can be here
except Exception:
    pass

logger = logging.getLogger(__name__)

def generate_stock_charts(stock_code: str, hist) -> list:
    """Generate Day, Week, and Month K-line charts in memory (non-blocking thread)."""
    charts = []
    for label, resample, color in [("日K線", "D", "blue"), ("週K線", "W", "green"), ("月K線", "ME", "red")]:
        try:
            data = hist["Close"].resample(resample).mean()
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(data, label=label, color=color)
            ax.set_title(f"{stock_code} {label}")
            ax.legend()
            ax.grid(True, linestyle="--", alpha=0.7)
            
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            charts.append((label, buf.getvalue()))
        except Exception as e:
            logger.error(f"Error generating chart for {label}: {e}")
            plt.close('all')
    return charts

async def stock_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/s 2330.TW 或 /s TSLA")
        return

    stock_code = context.args[0].upper()
    try:
        # Offload blocking yfinance call to thread
        loop = asyncio.get_running_loop()
        
        def fetch_data():
            t = yf.Ticker(stock_code)
            h = t.history(period="6mo")
            i = t.info
            return t, h, i
            
        stock, hist, info = await loop.run_in_executor(None, fetch_data)

        if hist.empty:
            await update.message.reply_text(f"⚠️ 無法找到 {stock_code} 的股價數據，請確認股票代碼是否正確。")
            return

        current_price = info.get("currentPrice", hist["Close"].iloc[-1])
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

        # Generate Charts in worker thread (non-blocking)
        charts = await loop.run_in_executor(None, generate_stock_charts, stock_code, hist)
        for label, chart_bytes in charts:
            await update.message.reply_photo(photo=chart_bytes, caption=f"📊 {label}")

    except Exception as e:
        logger.error(f"Stock info error: {e}")
        await update.message.reply_text(f"❌ 查詢股價時發生錯誤：{str(e)}")

async def safe_reply_news(update: Update, text: str):
    """Safely reply with Markdown, falling back to plain text if syntax issues occur."""
    try:
        await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception:
        await update.message.reply_text(text, disable_web_page_preview=True)


def _split_telegram_text(text: str, limit: int = 3900) -> list[str]:
    """Split long tool output without exceeding Telegram's 4096-char limit."""
    if len(text) <= limit:
        return [text]
    chunks = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def safe_reply_analysis(update: Update, text: str):
    """Send analysis in bounded chunks, falling back when Markdown is invalid."""
    for chunk in _split_telegram_text(text):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception:
            await update.message.reply_text(chunk, disable_web_page_preview=True)


def _format_analysis(title: str, result) -> str:
    if isinstance(result, dict):
        payload = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    else:
        payload = str(result)
    return f"📊 **{title}**\n```json\n{payload}\n```"


async def _run_analysis_command(update: Update, tool_fn, args: dict, title: str):
    await update.message.reply_text("⏳ 正在取得市場資料並計算，請稍候...")
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, tool_fn.invoke, args)
        await safe_reply_analysis(update, _format_analysis(title, result))
    except Exception as exc:
        logger.error("%s command error: %s", title, exc)
        await update.message.reply_text(f"❌ {title} 執行失敗：{exc}")


async def sepa_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/sepa TSLA")
        return
    from tools.stock_analysis import get_sepa_analysis
    await _run_analysis_command(update, get_sepa_analysis, {"ticker": context.args[0]}, "SEPA 趨勢與 VCP 分析")


async def valuation_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/val AAPL")
        return
    from tools.stock_analysis import get_dcf_valuation
    await _run_analysis_command(update, get_dcf_valuation, {"ticker": context.args[0]}, "DCF 內在價值分析")


async def earnings_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/earn NVDA")
        return
    from tools.stock_analysis import get_earnings_briefing
    await _run_analysis_command(update, get_earnings_briefing, {"ticker": context.args[0]}, "財報與盈餘簡報")


async def correlation_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2 and "," not in "".join(context.args):
        await update.message.reply_text("❌ 請提供 2 至 5 個代碼，例如：/corr TSLA,NVDA,AAPL")
        return
    from tools.stock_analysis import get_correlation_analysis
    symbols = ",".join(context.args)
    await _run_analysis_command(update, get_correlation_analysis, {"tickers": symbols}, "多股相關性與 SPY Beta")

async def stock_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/n TSLA 或 /n NVDA")
        return
        
    stock_code = context.args[0].upper()
    await update.message.reply_text(f"🔍 正在為您檢索 {stock_code} 最新美股新聞...")
    
    try:
        from tools.news import fetch_2md_news, get_financial_news
        loop = asyncio.get_running_loop()
        
        def get_us_news():
            # 1. Try 2MD Search
            news_items = fetch_2md_news(f"{stock_code} stock market news", limit=5)
            if not news_items:
                # 2. Fallback to general tool
                tool_res = get_financial_news.invoke({"ticker": stock_code})
                news_items = tool_res.get('news', [])
            return news_items

        news_list = await loop.run_in_executor(None, get_us_news)
        
        if not news_list:
            await update.message.reply_text(f"⚠️ 找不到 {stock_code} 的相關新聞。")
            return
            
        reply_text = f"📰 **{stock_code} 美股即時新聞**：\n━━━━━━━━━━━━━━━━━━━━\n"
        for idx, item in enumerate(news_list[:5]):
            title = item.get('title', '新聞連結').replace("[", "(").replace("]", ")")
            link = item.get('link') or item.get('url') or '#'
            desc = item.get('description', '').strip()
            
            reply_text += f"{idx+1}. [{title}]({link})\n"
            if desc and len(desc) > 10:
                short_desc = desc[:120] + "..." if len(desc) > 120 else desc
                reply_text += f"   _{short_desc}_\n\n"
            else:
                reply_text += "\n"
        
        await safe_reply_news(update, reply_text)

    except Exception as e:
        logger.error(f"News error: {e}")
        await update.message.reply_text(f"❌ 查詢新聞時發生錯誤：{str(e)}")

async def taiwan_stock_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ny 2330.TW 或 /ny 2002.TW")
        return

    stock_code = context.args[0].upper()
    await update.message.reply_text(f"🔍 正在為您檢索 {stock_code} 最新台股中文新聞...")
    
    loop = asyncio.get_running_loop()
    
    def get_tw_news():
        from tools.news import fetch_2md_news
        # 1. Try 2MD Search for Taiwan Stock News
        tw_items = fetch_2md_news(f"{stock_code} 台灣 股票 新聞", limit=5)
        if tw_items:
            return tw_items
            
        # 2. Fallback to direct Yahoo News Scraper
        url = f"https://tw.news.yahoo.com/search?p={stock_code}"
        try:
            r = requests.get(url, timeout=8)
            soup = BeautifulSoup(r.text, "html.parser")
            news_links = []
            for item in soup.find_all("a", href=True):
                href = item["href"]
                if href.startswith("/"):
                    full_url = f"https://tw.news.yahoo.com{href}"
                    title = item.get_text(strip=True)
                    if title and full_url not in news_links:
                        news_links.append({"title": title, "link": full_url})
            return [it for it in news_links if "news" in it["link"]][:5]
        except Exception as e:
            logger.error(f"Yahoo scraping fallback error: {e}")
            return []

    try:
        valid_news = await loop.run_in_executor(None, get_tw_news)
        if not valid_news:
            await update.message.reply_text(f"⚠️ 找不到 {stock_code} 的相關新聞。")
            return
            
        reply_text = f"📰 **{stock_code} 台股即時新聞**：\n━━━━━━━━━━━━━━━━━━━━\n"
        for idx, item in enumerate(valid_news[:5]):
            title = item.get('title', '新聞連結').replace("[", "(").replace("]", ")")
            link = item.get('link') or item.get('url') or '#'
            desc = item.get('description', '').strip()
            
            reply_text += f"{idx+1}. [{title}]({link})\n"
            if desc and len(desc) > 10:
                short_desc = desc[:120] + "..." if len(desc) > 120 else desc
                reply_text += f"   _{short_desc}_\n\n"
            else:
                reply_text += "\n"
                
        await safe_reply_news(update, reply_text)
    except Exception as e:
        logger.error(f"TW News error: {e}")
        await update.message.reply_text(f"❌ 抓取新聞時發生錯誤：{str(e)}")

# Prophet prediction (Simplified - imports inside to avoid overhead if not used)
async def prophet_predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/p META")
        return
    stock_code = context.args[0].upper()
    await update.message.reply_text("🔮 正在進行預測，請稍候...")
    
    loop = asyncio.get_running_loop()
    
    def run_prophet():
        try:
            df = yf.download(stock_code, period="1y")
            if df.empty: return None, None
            
            import pandas as pd
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            elif len(df.columns) > 0 and isinstance(df.columns[0], tuple):
                df.columns = [i[0] for i in df.columns]
                
            data = df.reset_index()[['Date', 'Close']]
            # Fix for timezone naive/aware if needed, Prophet usually handles it
            if data['Date'].dt.tz is not None:
                data['Date'] = data['Date'].dt.tz_localize(None)
                
            data.columns = ['ds', 'y']
            
            from prophet import Prophet
            model = Prophet(daily_seasonality=True)
            model.fit(data)
            future = model.make_future_dataframe(periods=5)
            forecast = model.predict(future)
            
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.plot(data['ds'], data['y'], label='Actual')
            ax.plot(forecast['ds'], forecast['yhat'], label='Predicted')
            ax.set_title(f'{stock_code} Price Prediction')
            ax.legend()
            ax.grid(True, linestyle="--", alpha=0.7)
            
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            
            return forecast.tail(5)[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].to_string(), buf.getvalue()
        except Exception as e:
            logger.error(f"Prophet error: {e}")
            plt.close('all')
            return None, None

    try:
        forecast_text, chart_bytes = await loop.run_in_executor(None, run_prophet)
        
        if chart_bytes:
            await update.message.reply_photo(photo=chart_bytes, caption=f"📊 **{stock_code} 5 Day Forecast**")
            await update.message.reply_text(f"```{forecast_text}```", parse_mode="Markdown")
        else:
             await update.message.reply_text("❌ 預測失敗或無法獲取數據")
             
    except Exception as e:
        await update.message.reply_text(f"❌ 預測時發生錯誤：{str(e)}")

# Financial Transmission Chain Analysis (/chain)
async def chain_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyze financial logic transmission chain for macro/industry events."""
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供要分析的事件或主題，例如：/chain 聯準會降息 或 /chain 中東局勢升溫")
        return

    topic = " ".join(context.args)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    processing_msg = await update.message.reply_text(f"⛓️ 正在解析【{topic}】的三級金融邏輯傳導鏈與受惠/受害標的，請稍候...")

    from ai_core import process_chat_message
    prompt = (
        f"請針對【{topic}】進行深入的「三級金融邏輯傳導鏈 (Transmission Chain Analysis)」與因果推導分析：\n"
        f"1. 一級直接影響 (利率/匯率/原物料/供需)\n"
        f"2. 二級產業鏈傳導 (成本、毛利、庫存週期)\n"
        f"3. 三級受惠與受害台美股標的 (列出具體代碼如 2330.TW, NVDA 等)\n"
        f"4. 邏輯證偽條件 (什麼情況下此邏輯失效)\n"
        f"5. 繪製標準 Mermaid 流程圖 (使用 ```mermaid\\nflowchart LR\\n``` 且節點文字加雙引號)"
    )

    try:
        thread_id = str(update.effective_chat.id)
        response = await process_chat_message(prompt, thread_id=thread_id)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        try:
            await update.message.reply_text(response, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Chain analysis error: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 分析傳導鏈時發生錯誤：{str(e)}")

# Real-time Breaking Financial News (/hot)
async def hot_news_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch top breaking news from 財聯社 (cls), 華爾街見聞 (wallstreetcn), or 雪球 (xueqiu)."""
    source_id = context.args[0].lower() if context.args else "cls"
    if source_id not in ["cls", "wallstreetcn", "xueqiu"]:
        source_id = "cls"

    from tools.news import get_hot_financial_news, NEWSNOW_SOURCES
    source_name = NEWSNOW_SOURCES.get(source_id, source_id)
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    items = get_hot_financial_news(source_id=source_id, count=8)
    
    if not items:
        await update.message.reply_text(f"⚠️ 目前暫時無法獲取 {source_name} 的即時快訊，請稍後重試。")
        return

    reply_text = f"🔥 **即時重大財經快訊 - {source_name}**\n━━━━━━━━━━━━━━━━━━━━\n"
    for item in items:
        rank = item.get("rank", "")
        title = item.get("title", "")
        url = item.get("url", "")
        if url:
            reply_text += f"{rank}. [{title}]({url})\n\n"
        else:
            reply_text += f"{rank}. {title}\n\n"
            
    reply_text += "💡 *輸入 `/hot cls`、`/hot wallstreetcn` 或 `/hot xueqiu` 切換不同快訊來源*"
    
    try:
        await update.message.reply_text(reply_text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception:
        await update.message.reply_text(reply_text, disable_web_page_preview=True)

# Fama-French Multi-Factor Analysis (/ff)
async def fama_french_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run Fama-French multi-factor risk attribution for a ticker."""
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ff NVDA 或 /ff TSLA")
        return

    ticker = context.args[0].upper().strip()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    processing_msg = await update.message.reply_text(f"📐 正在計算【{ticker}】的 Fama-French 多因子模型與超額報酬 Alpha 歸因，請稍候...")

    loop = asyncio.get_running_loop()
    from tools.us_fddk import compute_fama_french_factors
    
    def run_ff():
        return compute_fama_french_factors(ticker)

    try:
        res = await loop.run_in_executor(None, run_ff)
        try:
            await processing_msg.delete()
        except Exception:
            pass

        if "error" in res:
            await update.message.reply_text(f"❌ {res['error']}")
            return

        alpha_sign = "+" if res["annualized_alpha_pct"] > 0 else ""
        alpha_emoji = "🟢" if res["annualized_alpha_pct"] > 0 else "🔴"

        reply_text = (
            f"📊 **【{ticker}】Fama-French 多因子風險歸因模型**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{alpha_emoji} **年化超額報酬 (Annualized Alpha)**：`{alpha_sign}{res['annualized_alpha_pct']}%`\n"
            f"📈 **市場因子曝險 (Market Beta β_mkt)**：`{res['beta_market']}`\n"
            f"🏢 **市值因子曝險 (Size SMB β_smb)**：`{res['beta_size_smb']}` ({res['style_profile']['size']})\n"
            f"💎 **估值因子曝險 (Value HML β_hml)**：`{res['beta_value_hml']}` ({res['style_profile']['value_growth']})\n"
            f"🚀 **動能因子曝險 (Momentum UMD β_umd)**：`{res['beta_momentum_umd']}` ({res['style_profile']['momentum']})\n\n"
            f"🎯 **模型解釋力 (Adj. R²)**：`{res['adj_r_squared'] * 100:.1f}%` (樣本數：{res['sample_days']} 個交易日)\n\n"
            f"💡 *因子解讀*：\n"
            f"• **Alpha > 0**：代表扣除大盤、市值、價值與動能因子後，個股具備實質超額選股能力。\n"
            f"• **HML < 0**：偏向高估值/高成長科技股；**HML > 0** 偏向低估值/傳統價值股。\n"
            f"• **SMB < 0**：偏向巨型權值股；**SMB > 0** 偏向中小型股。"
        )

        try:
            await update.message.reply_text(reply_text, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(reply_text)

    except Exception as e:
        logger.error(f"Fama-French handler error: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 計算因子模型時發生錯誤：{str(e)}")


