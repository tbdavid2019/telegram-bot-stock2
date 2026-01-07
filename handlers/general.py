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
        "🎉 歡迎使用DAVID888股票資訊機器人！\n\n"
        "*(您的對話記憶已重置，現在是一個全新的開始)*\n\n"
        "本 Bot 提供以下功能：\n"
        "• `/ai 股票代碼` - 綜合分析該公司股票值不值得購入投資 (範例：`/ai TSLA`)\n"
        "• `/ai2 股票代碼` - 多位投資大師集體分析股票 (範例：`/ai2 AMD`)\n"
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

async def tools_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "🛠 **其他股票工具**\n\n"
        "📊 台股預測 (LSTM)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/twStock-predict)\n"
        "📈 美股台股潛力股預測 (LSTM)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/twStock-Underdogs)\n"
        "🔮 美股台股預測 (Prophet)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/Stock-Predict-Prophet)\n"
        "🔮 多位投資大師集體分析股票：[點擊使用](https://huggingface.co/spaces/tbdavid2019/ai-hedge-fund)"
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
    
    await update.message.reply_text(response, parse_mode="Markdown")


async def reset_commands(application: Application):
    commands = [
        BotCommand("start", "啟動機器人"),
        BotCommand("s", "查詢股價和K線圖"),
        BotCommand("n", "查詢美股新聞"),
        BotCommand("ny", "查詢台股新聞"),
        BotCommand("p", "預測公司股價 (5 天區間)"),
        BotCommand("ai", "綜合基本面分析"),
        BotCommand("ai2", "多位投資大師集體分析"), 
        BotCommand("llm", "自由問答"),
        BotCommand("h", "顯示其他工具連結")
    ]
    await application.bot.set_my_commands(commands)
