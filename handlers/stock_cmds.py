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


def format_sepa_card(res: dict) -> str:
    stock_name = res.get("stock", "")
    if "error" in res and not res.get("rules"):
        err = res.get("error", "")
        return f"❌ **【{stock_name}】SEPA 分析失敗**\n{err}"
    
    stage = res.get("stage", "未確認")
    stage_emoji = "🟢" if "Stage 2" in stage else "🟡"
    template_score = res.get("template_score", "0/8")
    metrics = res.get("metrics", {})
    price = metrics.get("price", 0)
    ma50 = metrics.get("ma50", 0)
    ma150 = metrics.get("ma150", 0)
    ma200 = metrics.get("ma200", 0)
    low52 = metrics.get("52_week_low", 0)
    high52 = metrics.get("52_week_high", 0)
    rel3m = metrics.get("relative_3m_return")
    spy3m = metrics.get("spy_3m_return")

    rules = res.get("rules", [])
    stops = res.get("risk_stops", {})
    pivot = res.get("pivot_entry", 0)
    stop7 = stops.get("7_percent_stop", 0)
    stop_atr = stops.get("2_atr_stop", 0)
    vcp = res.get("vcp", {})

    lines = [
        f"📊 **【{stock_name}】Mark Minervini SEPA 趨勢與 VCP 分析**",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{stage_emoji} **趨勢階段**：`{stage}` (符合度：`{template_score}`)",
        f"💰 **最新股價**：`${price:,.2f}`",
        f"📈 **均線系統**：MA50 `${ma50:,.2f}` | MA150 `${ma150:,.2f}` | MA200 `${ma200:,.2f}`",
        f"🏔️ **52 週區間**：最低 `${low52:,.2f}` ~ 最高 `${high52:,.2f}`",
    ]
    if rel3m is not None:
        lines.append(f"⚡ **近 3 月報酬 vs SPY**：`{rel3m}%` (SPY: `{spy3m}%`)")

    lines.append("\n📋 **SEPA 8 項趨勢模板檢驗清單**：")
    for r in rules:
        status_icon = "✅" if r.get("passed") else "❌"
        rule_num = r.get("rule")
        crit = r.get("criterion")
        lines.append(f"  {status_icon} Rule {rule_num}: {crit}")

    lines.append("\n🎯 **關鍵進出場與風險控管**：")
    lines.append(f"  • **突破買點 (Pivot Entry)**：`${pivot:,.2f}`")
    lines.append(f"  • **7% 硬停損價位**：`${stop7:,.2f}`")
    lines.append(f"  • **2 ATR 停損價位**：`${stop_atr:,.2f}`")

    vcp_status = "✅ 偵測到波動度收縮 (VCP 特徵符合)" if vcp.get("detected") else "ℹ️ 未出現明顯 VCP 收縮 (需確認型態)"
    lines.append(f"\n🌀 **VCP 波動收縮診斷**：{vcp_status}")
    v_ratio = vcp.get("volume_10d_vs_50d")
    if v_ratio is not None:
        lines.append(f"  • 10日/50日量比：`{v_ratio}` (收縮量通常 < 1.0)")

    return "\n".join(lines)


def format_dcf_card(res: dict) -> str:
    stock_name = res.get("stock", "")
    if "error" in res and res.get("method") != "relative_revenue_fallback":
        err = res.get("error", "")
        return f"❌ **【{stock_name}】DCF 估值失敗**\n{err}"

    price = res.get("current_price", 0)
    if res.get("method") == "relative_revenue_fallback":
        rev = res.get("revenue") or 0
        ps = res.get("price_to_sales", 0)
        err = res.get("error", "")
        lim = res.get("limitation", "")
        lines = [
            f"💰 **【{stock_name}】估值分析報告 (相對營收倍數法)**",
            "━━━━━━━━━━━━━━━━━━━━",
            f"💵 **最新市價**：`${price:,.2f}`",
            f"🏢 **年度營收**：`${rev/1e9:,.2f}B USD`",
            f"📊 **市銷率 (P/S Multiple)**：`{ps:,.2f}x`",
            "\n⚠️ **DCF 限制說明**：",
            f"{err}",
            f"💡 *{lim}*"
        ]
        return "\n".join(lines)

    scenarios = res.get("projected_fair_value_per_share", {})
    mos = res.get("margin_of_safety_at_base")
    mos_text = f"`{mos:+,.1f}%`" if mos is not None else "N/A"
    mos_emoji = "🟢" if (mos or 0) > 0 else "🔴"
    wacc = res.get("wacc", 0)
    rf = res.get("risk_free_rate", 0)
    beta = res.get("beta", 0)
    bear = scenarios.get("bear", 0)
    base = scenarios.get("base", 0)
    bull = scenarios.get("bull", 0)

    lines = [
        f"💰 **【{stock_name}】五年 FCFF 折現估值模型 (DCF)**",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💵 **當前市價**：`${price:,.2f}`",
        f"📈 **折現率 (WACC)**：`{wacc}%` (無風險利率: `{rf}%`, Beta: `{beta}`)",
        "━━━━━━━━━━━━━━━━━━━━",
        "🎯 **情境公允價值預估 (Fair Value)**：",
        f"  🐻 **保守悲觀 (Bear)**：`${bear:,.2f}`",
        f"  ⚖️ **基準中性 (Base)**：`${base:,.2f}`",
        f"  🐂 **樂觀進取 (Bull)**：`${bull:,.2f}`",
        f"\n{mos_emoji} **基準安全邊際 (Margin of Safety)**：{mos_text}",
        "💡 *安全邊際為正代表目前市價低於基準內在價值，具備折價保護空間。*"
    ]
    return "\n".join(lines)


def format_earn_card(res: dict) -> str:
    stock_name = res.get("stock", "")
    if "error" in res:
        err = res.get("error", "")
        return f"❌ **【{stock_name}】財報簡報失敗**\n{err}"

    con = res.get("consensus", {})
    hist = res.get("last_four_quarters", [])
    beat_rate = res.get("beat_rate_last_four")
    next_date = res.get("upcoming_earnings_date") or "即將公布"

    lines = [
        f"🗓️ **【{stock_name}】財報預期與盈餘驚喜簡報**",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📅 **下次財報預計發布日**：`{next_date}`",
    ]
    if con.get("eps") is not None:
        eps_val = con["eps"]
        lines.append(f"🎯 **市場共識 EPS 預估**：`${eps_val:,.2f}`")
    if con.get("revenue") is not None:
        rev = con["revenue"]
        rev_b = rev / 1e9 if rev > 1e6 else rev
        lines.append(f"💰 **市場共識營收預估**：`${rev_b:,.2f}B`")
    if con.get("analyst_target_mean") is not None:
        mean_p = con["analyst_target_mean"]
        low_p = con.get("analyst_target_low", 0)
        high_p = con.get("analyst_target_high", 0)
        lines.append(f"🎯 **分析師平均目標價**：`${mean_p:,.2f}` (區間: `${low_p:,.2f}` ~ `${high_p:,.2f}`)")

    if beat_rate is not None:
        lines.append(f"\n🔥 **過去四季擊敗預期率 (Beat Rate)**：`{beat_rate}%`")

    if hist:
        lines.append("\n📋 **最近季度財報驚喜紀錄**：")
        for q in hist:
            d = q.get("date") or "N/A"
            rep_eps = q.get("reported_eps")
            est_eps = q.get("eps_estimate")
            surp = q.get("surprise_percent")
            surp_text = f"{surp:+.1f}%" if surp is not None else "N/A"
            icon = "🟢" if (surp or 0) > 0 else "🔴"
            lines.append(f"  • `{d}`: EPS `${rep_eps}` (預估: `${est_eps}`) ➔ {icon} 驚喜度 `{surp_text}`")

    return "\n".join(lines)


def format_corr_card(res: dict) -> str:
    if "error" in res:
        err = res.get("error", "")
        return f"❌ **多股相關性分析失敗**\n{err}"

    tickers = res.get("tickers", [])
    obs = res.get("observations", 0)
    matrix = res.get("correlation_matrix", {})
    betas = res.get("spy_beta", {})

    lines = [
        "🔗 **多股 90 日日報酬相關性與 SPY Beta**",
        f"📅 **樣本期間**：最近 `{obs}` 個交易日",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 **相關係數矩陣 (Correlation Matrix)**："
    ]
    header = "標的\t" + "\t".join(tickers)
    lines.append(f"`{header}`")
    for t1 in tickers:
        row_vals = [f"{matrix.get(t1, {}).get(t2, 0):.2f}" for t2 in tickers]
        lines.append(f"`{t1}\t" + "\t".join(row_vals) + "`")

    lines.append("\n📈 **相對於 S&P 500 (SPY) 的市場波動 Beta**：")
    for t, b in betas.items():
        desc = "波動大於大盤" if (b or 0) > 1 else "波動小於大盤"
        lines.append(f"  • **{t}**：`{b}` ({desc})")

    lines.append("\n💡 *解讀*：相關係數 > 0.7 為高度正相關（同向波動），< 0.3 具備良好資產分散效益。")
    return "\n".join(lines)


async def sepa_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/sepa TSLA")
        return
    ticker = context.args[0].strip().split()[0].upper()
    processing_msg = await update.message.reply_text(f"⏳ 正在分析 {ticker} 之 SEPA 趨勢與 VCP 型態，請稍候...")
    from tools.stock_analysis import get_sepa_analysis
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, get_sepa_analysis.invoke, {"ticker": ticker})
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await safe_reply_analysis(update, format_sepa_card(res))
    except Exception as exc:
        logger.error("SEPA command error: %s", exc)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ SEPA 分析失敗：{exc}")


async def valuation_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/val AAPL")
        return
    ticker = context.args[0].strip().split()[0].upper()
    processing_msg = await update.message.reply_text(f"⏳ 正在計算 {ticker} 之 DCF 折現估值模型，請稍候...")
    from tools.stock_analysis import get_dcf_valuation
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, get_dcf_valuation.invoke, {"ticker": ticker})
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await safe_reply_analysis(update, format_dcf_card(res))
    except Exception as exc:
        logger.error("DCF command error: %s", exc)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ DCF 估值失敗：{exc}")


async def earnings_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/earn NVDA")
        return
    ticker = context.args[0].strip().split()[0].upper()
    processing_msg = await update.message.reply_text(f"⏳ 正在整理 {ticker} 之財報預期與盈餘簡報，請稍候...")
    from tools.stock_analysis import get_earnings_briefing
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, get_earnings_briefing.invoke, {"ticker": ticker})
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await safe_reply_analysis(update, format_earn_card(res))
    except Exception as exc:
        logger.error("Earn command error: %s", exc)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 財報簡報失敗：{exc}")


async def correlation_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2 and "," not in "".join(context.args):
        await update.message.reply_text("❌ 請提供 2 至 5 個代碼，例如：/corr TSLA,NVDA,AAPL")
        return
    symbols = ",".join(context.args)
    processing_msg = await update.message.reply_text("⏳ 正在計算多股相關係數與 SPY Beta，請稍候...")
    from tools.stock_analysis import get_correlation_analysis
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, get_correlation_analysis.invoke, {"tickers": symbols})
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await safe_reply_analysis(update, format_corr_card(res))
    except Exception as exc:
        logger.error("Corr command error: %s", exc)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 相關性分析失敗：{exc}")

def is_taiwan_stock(symbol: str, query: str) -> bool:
    s = symbol.upper()
    if s.endswith(".TW") or s.endswith(".TWO"):
        return True
    if re.fullmatch(r"\d{4,6}", s):
        return True
    if any("\u4e00" <= c <= "\u9fff" for c in query):
        tw_keywords = ["台積電", "聯發科", "鴻海", "長榮", "廣達", "富邦金", "國泰金", "台股", "鈊象", "元太", "大立光", "欣興", "技嘉"]
        if any(k in query for k in tw_keywords):
            return True
    return False


async def stock_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Unified smart stock news handler (/n).
    Automatically routes Taiwan (2330, 台積電, 2330.TW) vs US/Global (TSLA, 特斯拉, IBM, NVDA).
    """
    if not context.args:
        await update.message.reply_text("💡 請提供股票代碼或公司名稱，例如：`/n 2330`、`/n 台積電`、`/n TSLA` 或 `/n 特斯拉`", parse_mode="Markdown")
        return

    raw_query = " ".join(context.args).strip()
    processing_msg = await update.message.reply_text(f"🔍 正在為您智慧檢索 【{raw_query}】 即時財經新聞...")

    from tools.stock import resolve_ticker
    from tools.news import fetch_2md_news, get_financial_news

    loop = asyncio.get_running_loop()

    def fetch_news():
        resolved = resolve_ticker(raw_query)
        is_tw = is_taiwan_stock(resolved, raw_query)
        
        # 1. 2MD Fast Multi-Endpoint Search
        if is_tw:
            search_query = f"{raw_query} {resolved} 台灣 股票 新聞 財經"
        else:
            search_query = f"{resolved} {raw_query} stock news 財經 新聞"

        items = fetch_2md_news(search_query, limit=5)
        if items:
            return resolved, is_tw, items[:5]

        # 2. Fallbacks
        if is_tw:
            url = f"https://tw.news.yahoo.com/search?p={raw_query}"
            try:
                r = requests.get(url, timeout=6)
                soup = BeautifulSoup(r.text, "html.parser")
                news_links = []
                for item in soup.find_all("a", href=True):
                    href = item["href"]
                    if href.startswith("/"):
                        full_url = f"https://tw.news.yahoo.com{href}"
                        title = item.get_text(strip=True)
                        if title and full_url not in news_links:
                            news_links.append({"title": title, "link": full_url})
                tw_news = [it for it in news_links if "news" in it["link"]][:5]
                if tw_news:
                    return resolved, is_tw, tw_news
            except Exception:
                pass

        # US / General fallback
        tool_res = get_financial_news.invoke({"ticker": resolved})
        return resolved, is_tw, tool_res.get("news", [])[:5]

    try:
        resolved_ticker, is_tw, news_list = await loop.run_in_executor(None, fetch_news)
        try:
            await processing_msg.delete()
        except Exception:
            pass

        if not news_list:
            await update.message.reply_text(f"⚠️ 找不到 【{raw_query}】 的相關新聞。")
            return

        market_label = "台股" if is_tw else "美股/全球"
        display_name = f"{raw_query} ({resolved_ticker})" if raw_query.upper() != resolved_ticker.upper() else resolved_ticker
        reply_text = f"📰 **【{display_name}】{market_label}即時財經新聞**：\n━━━━━━━━━━━━━━━━━━━━\n"
        
        for idx, item in enumerate(news_list[:5]):
            title = item.get("title", "新聞連結").replace("[", "(").replace("]", ")")
            link = item.get("link") or item.get("url") or "#"
            desc = item.get("description", "").strip()

            reply_text += f"{idx+1}. [{title}]({link})\n"
            if desc and len(desc) > 10:
                short_desc = desc[:120] + "..." if len(desc) > 120 else desc
                reply_text += f"   _{short_desc}_\n\n"
            else:
                reply_text += "\n"

        await safe_reply_news(update, reply_text)

    except Exception as e:
        logger.error(f"Unified stock news error: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 查詢新聞時發生錯誤：{str(e)}")


async def taiwan_stock_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy alias: forward /ny to unified smart news /n."""
    await stock_news(update, context)

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
    """Fetch top breaking news from 財聯社 (cls), 華爾街見聞 (wallstreetcn), 雪球 (xueqiu), or Investing.com."""
    raw_source = context.args[0].lower() if context.args else "cls"
    # Friendly alias mapping
    source_map = {
        "cls": "cls",
        "wallstreetcn": "wallstreetcn",
        "wcn": "wallstreetcn",
        "xueqiu": "xueqiu",
        "xq": "xueqiu",
        "investing": "investing",
        "inv": "investing",
        "investing_hk": "investing_hk",
        "inv_hk": "investing_hk",
        "hk": "investing_hk",
        "commodities": "investing_commodities",
        "oil": "investing_commodities",
        "gold": "investing_commodities",
        "investing_commodities": "investing_commodities",
        "bonds": "investing_bonds",
        "bond": "investing_bonds",
        "rates": "investing_bonds",
        "rate": "investing_bonds",
        "investing_bonds": "investing_bonds",
        "forex": "investing_forex",
        "fx": "investing_forex"
    }
    source_id = source_map.get(raw_source, "cls")

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
        url = item.get("url") or item.get("link", "")
        if url:
            reply_text += f"{rank}. [{title}]({url})\n\n"
        else:
            reply_text += f"{rank}. {title}\n\n"
            
    reply_text += "💡 *來源切換：`/hot cls`、`/hot wallstreetcn`、`/hot investing_hk` (繁中焦點)、`/hot commodities` (大宗商品)、`/hot bonds` (美債利率)*"
    
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


from tools.tw_institutional import get_tw_institutional_analysis

async def institutional_chip_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /chip command.
    Fetches TWSE/TPEX institutional investor breakdown (Foreign, Trust, Dealer),
    streaks (連買/連賣天數), and 5d accumulation.
    """
    if not context.args:
        await update.message.reply_text("💡 請提供台股代碼，例如：`/chip 2330.TW` 或 `/chip 3293.TWO` 或 `/chip 2603`", parse_mode="Markdown")
        return

    raw_ticker = context.args[0].strip().upper()
    processing_msg = await update.message.reply_text(f"⏳ 正在向證交所/櫃買中心取得 {raw_ticker} 三大法人籌碼資料，請稍候...")

    loop = asyncio.get_running_loop()

    def run_chip():
        return get_tw_institutional_analysis.invoke({"ticker": raw_ticker})

    try:
        res = await loop.run_in_executor(None, run_chip)
        try:
            await processing_msg.delete()
        except Exception:
            pass

        if "error" in res:
            await update.message.reply_text(f"❌ {res['error']}")
            return

        ld = res.get("latest_day", {})
        f_lots = ld.get("foreign_lots", 0)
        t_lots = ld.get("trust_lots", 0)
        d_lots = ld.get("dealer_lots", 0)
        d_self = ld.get("dealer_self_lots", 0)
        d_hedge = ld.get("dealer_hedge_lots", 0)
        total_lots = ld.get("total_lots", 0)
        f_ratio = ld.get("foreign_ratio")

        streaks = res.get("streaks", {})
        acc5 = res.get("accumulated_5d", {})

        def fmt_lot(val):
            if val is None:
                return "0 張"
            sign = "+" if val > 0 else ""
            return f"{sign}{val:,.1f} 張"

        reply_text = (
            f"📊 **【{res['stock']}】三大法人籌碼日報**\n"
            f"📅 **最新交易日**：`{res['latest_date']}` ({res['market']})\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏢 **外資法人**：`{fmt_lot(f_lots)}` ({streaks.get('foreign', '持平')})\n"
            f"🏛️ **投信基金**：`{fmt_lot(t_lots)}` ({streaks.get('trust', '持平')})\n"
            f"🏦 **自營商總計**：`{fmt_lot(d_lots)}` (自行: `{fmt_lot(d_self)}` | 避險: `{fmt_lot(d_hedge)}`)\n"
            f"🎯 **三大法人合計**：`{fmt_lot(total_lots)}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        if f_ratio is not None:
            reply_text += f"📈 **外資總持股比例**：`{f_ratio:.2f}%`\n"

        reply_text += (
            f"🗓️ **近 5 日累計買賣超**：\n"
            f"  • 外資：`{fmt_lot(acc5.get('foreign_lots', 0))}`\n"
            f"  • 投信：`{fmt_lot(acc5.get('trust_lots', 0))}`\n"
            f"  • 合計：`{fmt_lot(acc5.get('total_lots', 0))}`\n\n"
            f"💡 **籌碼評估**：{res.get('sentiment_evaluation', '中性觀望')}"
        )

        try:
            await update.message.reply_text(reply_text, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(reply_text)

    except Exception as e:
        logger.error(f"Institutional chip handler error: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 查詢籌碼資料時發生錯誤：{str(e)}")


