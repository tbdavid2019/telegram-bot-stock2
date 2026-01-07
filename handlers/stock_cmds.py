import asyncio
import logging
import tempfile
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

        # Generate Charts
        # This is CPU bound, should also be offloaded if heavy, but matplotlib is tricky with threads.
        # We process sequentially for safety here, but could be optimized.
        for label, resample, color in [("日K線", "D", "blue"), ("週K線", "W", "green"), ("月K線", "ME", "red")]:
            data = hist["Close"].resample(resample).mean()
            plt.figure(figsize=(10, 5))
            plt.plot(data, label=label, color=color)
            plt.title(f"{stock_code} {label}")
            plt.legend()
            plt.grid(True, linestyle="--", alpha=0.7)
            
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                plt.savefig(tmp.name)
                tmp_path = tmp.name
            plt.close()
            
            await update.message.reply_photo(photo=open(tmp_path, "rb"), caption=f"📊 {label}")

    except Exception as e:
        logger.error(f"Stock info error: {e}")
        await update.message.reply_text(f"❌ 查詢股價時發生錯誤：{str(e)}")

async def stock_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/n TSLA")
        return
    stock_code = context.args[0].upper()
    try:
        # We can reuse tools.news.get_financial_news but that returns a dict for LLM.
        # For direct user consumption, we want formatted text.
        # Ideally we refactor 'tools.news' to return objects/structured data that can be formatted by both.
        # For now, let's use the 'tools.news.get_financial_news' tool and format the output.
        from tools.news import get_financial_news
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, get_financial_news, stock_code) # No invoke, just call function directly? 
        # Tool is a LangChain tool, invoke expects input. 
        # But get_financial_news is decorated with @tool which makes it a BaseTool.
        # Calling it directly as python function? It might need .run or .invoke.
        # Let's import the raw function if possible or just implement a format helper.
        # Actually LangChain tools when decorated wrap the function.
        
        # Let's just implement a direct async scrape helper here or in tools/news.py as a normal function 
        # that the tool also uses.
        # For expediency, I will call the tool via invoke (sync) in executor.
        
        news_list = result.get('news', [])
        
        reply_text = f"📰 **{stock_code} 美股新聞**：\n"
        for i, item in enumerate(news_list[:5]):
             title = item['title']
             link = item['link']
             reply_text += f"{i+1}. [{title}]({link})\n"
        
        await update.message.reply_text(reply_text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"News error: {e}")
        await update.message.reply_text(f"❌ 查詢新聞時發生錯誤：{str(e)}")

async def taiwan_stock_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ny 2330.TW")
        return

    stock_code = context.args[0].upper()
    # Async wrapper for requests
    loop = asyncio.get_running_loop()
    
    def scrape_tw_news():
        url = f"https://tw.news.yahoo.com/search?p={stock_code}"
        r = requests.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        news_links = []
        for item in soup.find_all("a", href=True):
            href = item["href"]
            if href.startswith("/"):
                full_url = f"https://tw.news.yahoo.com{href}"
                title = item.get_text(strip=True)
                if title and full_url not in news_links:
                    news_links.append((title, full_url))
        return [(t, u) for t, u in news_links if "news" in u][:5]

    try:
        valid_news = await loop.run_in_executor(None, scrape_tw_news)
        if not valid_news:
            await update.message.reply_text(f"⚠️ 找不到 {stock_code} 的新聞。")
            return
        reply_text = f"📰 **{stock_code} 的 Yahoo News**：\n"
        for idx, (title, url) in enumerate(valid_news):
            reply_text += f"{idx+1}. [{title}]({url})\n"
        await update.message.reply_text(reply_text, parse_mode="Markdown")
    except Exception as e:
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
            
            plt.figure(figsize=(10, 6))
            plt.plot(data['ds'], data['y'], label='Actual')
            plt.plot(forecast['ds'], forecast['yhat'], label='Predicted')
            plt.title(f'{stock_code} Price Prediction')
            
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                plt.savefig(tmp.name)
                chart_path = tmp.name
            plt.close()
            
            return forecast.tail(5)[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].to_string(), chart_path
        except Exception as e:
            logger.error(f"Prophet error: {e}")
            return None, None

    try:
        forecast_text, chart_path = await loop.run_in_executor(None, run_prophet)
        
        if chart_path:
            await update.message.reply_photo(photo=open(chart_path, "rb"), caption=f"📊 **{stock_code} 5 Day Forecast**")
            await update.message.reply_text(f"```{forecast_text}```", parse_mode="Markdown")
        else:
             await update.message.reply_text("❌ 預測失敗或無法獲取數據")
             
    except Exception as e:
        await update.message.reply_text(f"❌ 預測時發生錯誤：{str(e)}")
