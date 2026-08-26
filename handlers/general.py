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
        "📌 **主要指令功能**：\n"
        "• `/ai2 股票代碼` - 🏛️ 14 位投資大師 AI 對沖基金委員會與圓桌辯論 (範例：`/ai2 NVDA`)\n"
        "• `/ai 股票代碼` - 📊 綜合基本面與技術指標評估報告 (範例：`/ai TSLA`)\n"
        "• `/s 股票代碼` - 📈 查詢公司即時股價和日/週/月 K 線圖 (範例：`/s 2330.TW`)\n"
        "• `/p 股票代碼` - 🔮 Prophet 模型預測未來 5 天股價區間 (範例：`/p META`)\n"
        "• `/n 股票代碼` - 📰 查詢美股即時英文新聞 (範例：`/n AAPL`)\n"
        "• `/ny 股票代碼` - 📰 查詢台股即時中文新聞 (範例：`/ny 2330.TW`)\n"
        "• `/llm 問題` - 🤖 智能金融助理自由問答 (具備記憶與即時工具) (範例：`/llm 2330.TW 的前景如何？`)\n\n"
        "💡 *您也可以直接傳送文字訊息與機器人自然語言對話！*"
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("/s 2330.TW  查詢股價和K線圖"), KeyboardButton("/n TSLA 查詢美股新聞")],
            [KeyboardButton("/ny 2330.TW 查詢台股新聞"), KeyboardButton("/ai TSLA 綜合基本面分析")],
            [KeyboardButton("/ai2 NVDA 14大師圓桌辯論"), KeyboardButton("/llm 2330.TW 的技術面與營收分析")]
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

    # Notify user that bot is "typing" or thinking
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Process message via Main Agent with conversation memory
    thread_id = str(update.effective_chat.id)
    response = await process_chat_message(user_input, thread_id=thread_id)
    
    try:
        await update.message.reply_text(response, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(response)


async def reset_commands(application: Application):
    commands = [
        BotCommand("start", "啟動機器人與重置對話"),
        BotCommand("ai2", "14位投資大師圓桌辯論 (AI對沖基金)"),
        BotCommand("ai", "綜合基本面與技術面分析"),
        BotCommand("s", "查詢即時股價和K線圖"),
        BotCommand("p", "Prophet 預測未來 5 天股價"),
        BotCommand("n", "查詢美股新聞"),
        BotCommand("ny", "查詢台股新聞"),
        BotCommand("llm", "智能助理問答 (帶工具與記憶)"),
        BotCommand("h", "顯示量化與預測工具連結")
    ]
    await application.bot.set_my_commands(commands)
