from telegram import Update, BotCommand, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, Application
import logging

logger = logging.getLogger(__name__)

from ai_core import clear_context
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Reset conversation context
    thread_id = str(update.effective_chat.id)
    await clear_context(thread_id)

    help_message = (
        "🎉 **歡迎使用 DAVID888 股票資訊與 AI 投資分析機器人！**\n\n"
        "*(您的對話記憶已重置，現在是一個全新的開始)*\n\n"
        "💬 **自然語言智能對話（直接傳送文字即可）**：\n"
        "機器人已整合即時股價、財務指標、技術指標（RSI/MACD/VWAP）、2MD 連網搜尋與即時新聞。您可以像真人對話一樣直接詢問：\n"
        "  • *「分析台積電 2330.TW 的基本面與技術面」*\n"
        "  • *「SpaceX 最近有什麼重大進展？上市了嗎？」*\n"
        "  • *「比較 NVDA 與 TSLA 的近期營收與成長率」*\n\n"
        "📌 **專屬量化與委員會指令**：\n"
        "• `/ai2 股票代碼` - 🏛️ 14 位投資大師 AI 對沖基金委員會與圓桌辯論 (範例：`/ai2 NVDA`)\n"
        "• `/s 股票代碼` - 📈 查詢即時股價與 日/週/月 K 線圖 (範例：`/s 2330.TW`)\n"
        "• `/p 股票代碼` - 🔮 Prophet 時間序列預測未來 5 天股價區間 (範例：`/p META`)\n"
        "• `/n 股票代碼` - 📰 查詢美股即時英文新聞 (範例：`/n AAPL`)\n"
        "• `/ny 股票代碼` - 📰 查詢台股即時中文新聞 (範例：`/ny 2330.TW`)\n"
        "• `/h` - 🛠️ 顯示其他外部量化預測工具連結\n"
        "• `/start` - 🔄 重置並清空當前對話記憶"
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("分析 2330.TW 基本面與技術面"), KeyboardButton("/s 2330.TW 查詢股價K線圖")],
            [KeyboardButton("/ai2 NVDA 14大師圓桌辯論"), KeyboardButton("/p META Prophet預測")],
            [KeyboardButton("/ny 2330.TW 台股新聞"), KeyboardButton("/n TSLA 美股新聞")]
        ],
        resize_keyboard=True
    )
    await update.message.reply_text(help_message, reply_markup=keyboard, parse_mode="Markdown")

async def tools_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "🛠 **其他股票與量化工具**\n\n"
        "📊 台股預測 (LSTM)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/twStock-predict)\n"
        "📈 美股台股潛力股預測 (LSTM)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/twStock-Underdogs)\n"
        "🔮 美股台股預測 (Prophet)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/Stock-Predict-Prophet)\n"
        "🏛️ AI 對沖基金 (14位投資大師與圓桌辯論)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/ai-hedge-fund)"
    )
    await update.message.reply_text(message, parse_mode="Markdown")


from ai_core import process_chat_message

async def default_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle regular text messages by passing them to the Main LLM Agent.
    This enables natural language interaction (e.g., 'How is TSLA doing?').
    """
    user_input = update.message.text
    if not user_input:
        return

    # Notify user that bot is typing and send temporary status message
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    processing_msg = await update.message.reply_text("⏳ 思考與處理中，請稍候...")
    
    try:
        # Process message via Main Agent with conversation memory
        thread_id = str(update.effective_chat.id)
        response = await process_chat_message(user_input, thread_id=thread_id)
        
        # Delete the temporary processing message
        try:
            await processing_msg.delete()
        except Exception:
            pass

        try:
            await update.message.reply_text(response, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Default message handler error: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 處理訊息時發生錯誤：{str(e)}")


async def reset_commands(application: Application):
    commands = [
        BotCommand("start", "啟動機器人與重置對話記憶"),
        BotCommand("ai2", "14位投資大師圓桌辯論 (AI對沖基金)"),
        BotCommand("s", "查詢即時股價和日/週/月 K 線圖"),
        BotCommand("p", "Prophet 模型預測未來 5 天股價"),
        BotCommand("n", "查詢美股即時新聞"),
        BotCommand("ny", "查詢台股即時新聞"),
        BotCommand("h", "顯示量化預測工具連結")
    ]
    await application.bot.set_my_commands(commands)
