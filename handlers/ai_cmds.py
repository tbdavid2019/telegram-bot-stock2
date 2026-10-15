import json
import logging
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from ai_core import process_chat_message
from tools.ai_hedge_fund import (
    ALL_ANALYST_KEYS,
    ANALYST_PERSONAS,
    HedgeFundAPIClient,
    HedgeFundAPIError,
    build_analysis_payload,
    build_backtest_payload,
    build_round_table_payload,
    get_symbol_entry,
    split_message,
)
from tools.wiki import publish_wiki_report

logger = logging.getLogger(__name__)

async def safe_reply_markdown(update: Update, text: str):
    """Safely reply with Markdown, falling back to plain text if parse error occurs."""
    for chunk in split_message(text):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Markdown send failed ({e}), falling back to plain text")
            await update.message.reply_text(chunk)


def _resolve_tickers(args: list[str]) -> list[str]:
    """Resolve comma-separated or space-separated user symbols consistently."""

    from tools.stock import resolve_ticker

    raw_symbols = [part.strip() for arg in args for part in arg.split(",") if part.strip()]
    return [resolve_ticker(symbol) for symbol in raw_symbols]


async def _resolve_tickers_async(args: list[str]) -> list[str]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _resolve_tickers, args)


def _format_round_table(ticker: str, round_table: dict) -> str:
    lines = [f"🗣️ **{ticker} 圓桌委員會辯論**"]
    if round_table.get("signal"):
        lines.append(f"🎯 **委員會信號**：{round_table['signal']}")
    if round_table.get("confidence") is not None:
        lines.append(f"📊 **委員會信心度**：`{round_table['confidence']}%`")
    for label, key in (("共識", "consensus_view"), ("分歧", "dissenting_opinions"), ("討論摘要", "discussion_summary"), ("辯論逐字紀錄", "conversation_transcript")):
        if round_table.get(key):
            lines.append(f"📝 **{label}**：\n{round_table[key]}")
    return "\n\n".join(lines)


def _format_analysis_messages(data: dict, tickers: list[str], initial_cash: float | None = None) -> tuple[str, str, int]:
    """Format v2 analysis response without mixing data between symbols."""

    decisions = data.get("decisions") if isinstance(data.get("decisions"), dict) else {}
    round_tables = data.get("round_table") if isinstance(data.get("round_table"), dict) else {}
    signals = data.get("analyst_signals") if isinstance(data.get("analyst_signals"), dict) else {}
    signal_map = {"bullish": "🟢 看多 (Bullish)", "bearish": "🔴 看空 (Bearish)", "neutral": "⚪ 中立 (Neutral)"}

    decision_parts = []
    for ticker in tickers:
        decision = get_symbol_entry(decisions, ticker)
        if not isinstance(decision, dict):
            continue
        action_map = {"buy": "🟢 買入 (BUY)", "sell": "🔴 賣出 (SELL)", "hold": "⚪ 持有 (HOLD)", "short": "🔻 做空 (SHORT)"}
        action = str(decision.get("action", "hold")).lower()
        section = [
            f"🏛️ **{ticker} AI 對沖基金委員會決策報告**",
            f"🎯 **最終決策**：{action_map.get(action, action.upper())}",
            f"📊 **信心度**：`{decision.get('confidence', 0)}%`",
        ]
        if initial_cash is not None:
            section.append(f"💰 **期初配置資金**：`${initial_cash:,.2f}`")
        section.extend([
            f"📦 **建議配置數量**：`{decision.get('quantity', 0)}` 股",
            f"💡 **執行理由**：\n{decision.get('reasoning', '無詳細說明')}",
        ])
        round_table = get_symbol_entry(round_tables, ticker)
        if isinstance(round_table, dict):
            section.append(_format_round_table(ticker, round_table))
        point_in_time = data.get("point_in_time")
        if isinstance(point_in_time, dict):
            section.append(
                "🕒 **Point-in-time 資料聲明**：\n"
                f"截止時間：{point_in_time.get('cutoff_time') or point_in_time.get('decision_cutoff', 'API 回傳')}"
            )
            if point_in_time.get("source_coverage"):
                section.append(f"資料覆蓋：{point_in_time['source_coverage']}")
            if point_in_time.get("exclusions"):
                section.append(f"排除來源：{point_in_time['exclusions']}")
        decision_parts.append("\n\n".join(section))

    analyst_parts = []
    analyst_count = 0
    for ticker in tickers:
        ticker_lines = [f"👥 **{ticker} 投資大師與專家觀點速覽**", "━━━━━━━━━━━━━━━━━━━━"]
        ticker_count = 0
        for analyst_key in ALL_ANALYST_KEYS:
            emoji, display_name = ANALYST_PERSONAS[analyst_key]
            agent_payload = get_symbol_entry(signals, analyst_key) or get_symbol_entry(signals, f"{analyst_key}_agent")
            info = get_symbol_entry(agent_payload, ticker)
            if not isinstance(info, dict):
                continue
            signal = str(info.get("signal", "neutral")).lower()
            reason = str(info.get("reasoning", ""))
            if len(reason) > 240:
                reason = reason[:240] + "..."
            ticker_lines.append(
                f"\n{emoji} **{display_name}**\n"
                f"   • 信號：{signal_map.get(signal, signal)} | 信心：`{info.get('confidence', 'N/A')}%`\n"
                f"   • 觀點：{reason}"
            )
            ticker_count += 1
            analyst_count += 1
        if ticker_count:
            analyst_parts.append("\n".join(ticker_lines))

    return "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(decision_parts), "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(analyst_parts), analyst_count


def _split_command_options(args: list[str]) -> tuple[list[str], dict[str, str]]:
    symbols: list[str] = []
    options: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            options[key.strip().lower()] = value.strip()
        else:
            symbols.append(arg)
    return symbols, options


def _option_bool(options: dict[str, str], key: str, default: bool = False) -> bool:
    if key not in options:
        return default
    value = options[key].lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise HedgeFundAPIError(f"{key} 必須是 true 或 false")
    return value in {"true", "1", "yes"}


def _extract_cash_option(options: dict[str, str], default: float = 100000.0) -> float:
    import math

    cash_aliases = ("initial_cash", "initialcash", "initialcapital", "capital", "cash")
    found_values: dict[str, float] = {}
    for alias in cash_aliases:
        if alias in options:
            val = options[alias].strip()
            try:
                parsed = float(val)
            except (ValueError, TypeError):
                raise HedgeFundAPIError(f"期初資金 (initialCash) 格式不正確：{options[alias]}")
            if not math.isfinite(parsed):
                raise HedgeFundAPIError(f"期初資金 (initialCash) 必須為有限數值：{options[alias]}")
            found_values[alias] = parsed

    if not found_values:
        return default

    unique_values = set(found_values.values())
    if len(unique_values) > 1:
        details = ", ".join(f"{k}={v}" for k, v in found_values.items())
        raise HedgeFundAPIError(f"偵測到多個互相矛盾的期初資金參數 ({details})，請只保留一個")

    return next(iter(found_values.values()))

async def ai_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unified /ai command: Forward to Main Conversational Agent with tools & memory."""
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ai TSLA 或 /ai 2330.TW\n💡 提示：您也可以直接傳送文字「分析 TSLA 基本面」與機器人對話！")
        return

    ticker = (await _resolve_tickers_async([context.args[0].strip()]))[0]
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    processing_msg = await update.message.reply_text(f"📊 正在為您全面診斷 {ticker}（整合即時行情、財務指標、技術分析與新聞），請稍候...")
    
    prompt = f"請針對 {ticker} 進行全面的基本面財務指標、技術面指標（如 RSI/MACD/VWAP）與近期即時新聞綜合評估診斷，並給出清晰的投資策略分析。"
    
    try:
        thread_id = str(update.effective_chat.id)
        response = await process_chat_message(prompt, thread_id=thread_id)

        # Delete processing status message
        try:
            await processing_msg.delete()
        except Exception:
            pass

        await safe_reply_markdown(update, response)

    except Exception as e:
        logger.error(f"AI Analysis Forward Error: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 分析時發生錯誤：{str(e)}")

async def ai2_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run the v2 16-persona analysis and multi-round committee debate."""

    if not context.args:
        await update.message.reply_text(
            "❌ 請提供股票代碼，例如：/ai2 TSLA,NVDA 或 /ai2 2330.TW\n"
            "💡 亦可自訂期初資金（預設 $100,000，最低門檻 $100）：\n"
            "• `/ai2 TSLA cash=50000`\n"
            "• `/ai2 2330.TW initial_cash=200000`\n"
            "• `/ai2 NVDA capital=80000 analysts=warren_buffett,decision_model,technical_analyst`",
            parse_mode="Markdown"
        )
        return

    try:
        symbol_args, options = _split_command_options(context.args)
        tickers = await _resolve_tickers_async(symbol_args)
        selected_analysts = options.get("analysts")
        analyst_keys = selected_analysts.split(",") if selected_analysts else None
        portfolio = json.loads(options["portfolio"]) if options.get("portfolio") else None
        initial_cash = _extract_cash_option(options)

        payload = build_analysis_payload(
            tickers,
            selected_analysts=analyst_keys,
            model_name=options.get("model", "openai/gpt-oss-20b"),
            model_provider=options.get("provider", "Groq"),
            round_table_rounds=int(options.get("rounds", "2")),
            initial_cash=initial_cash,
            portfolio=portfolio,
            point_in_time=_option_bool(options, "point_in_time"),
            start_date=options.get("start"),
            end_date=options.get("end"),
        )
    except (HedgeFundAPIError, ValueError) as exc:
        await update.message.reply_text(f"❌ 請求格式錯誤：{exc}")
        return

    ticker_label = ", ".join(tickers)
    analyst_label = len(payload["selectedAnalysts"])
    processing_msg = await update.message.reply_text(
        f"🏛️ 正在召開 {analyst_label} 位投資大師委員會與圓桌辯論分析 {ticker_label}，請稍候..."
    )
    try:
        data = await HedgeFundAPIClient().analyze(payload)
        decision_message, analyst_message, analyst_count = _format_analysis_messages(data, tickers, initial_cash=initial_cash)
        try:
            await processing_msg.delete()
        except Exception:
            pass

        if not decision_message:
            await update.message.reply_text(f"⚠️ API 未回傳 {ticker_label} 的決策資料。")
            return
        await safe_reply_markdown(update, decision_message)

        if analyst_count:
            wiki_md = (
                f"# 🏛️ {ticker_label} AI 對沖基金 {analyst_label} 位投資大師深度投資報告\n\n"
                "> 本報告由 AI Hedge Fund API v2 產生，內容僅供研究參考。\n\n"
                "[TOC]\n\n"
                f"## 投資委員會決策\n\n{decision_message}\n\n"
                f"## {analyst_label} 位分析師觀點\n\n{analyst_message}\n"
            )
            try:
                loop = asyncio.get_running_loop()
                wiki_title = f"{ticker_label} AI 對沖基金 {analyst_label} 位投資大師深度投資分析報告"
                share_url = await loop.run_in_executor(
                    None, publish_wiki_report, wiki_title, wiki_md, "claude-canvas"
                )
                if share_url:
                    analyst_message += f"\n\n🌐 **[在 David888 Wiki 閱讀完整報告]({share_url})**"
            except Exception as wiki_err:
                logger.warning("Failed to publish /ai2 report to David888 Wiki: %s", wiki_err)
            await safe_reply_markdown(update, analyst_message)
    except HedgeFundAPIError as exc:
        logger.error("AI2 API error: %s", exc, exc_info=True)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        status = f" HTTP {exc.status_code}" if exc.status_code else ""
        await update.message.reply_text(f"❌ AI Hedge Fund API 失敗{status}：{exc}")
    except Exception as exc:
        logger.error("AI2 error: %s", exc, exc_info=True)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 分析失敗：{exc}")


async def round_table_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run the standalone round-table endpoint with caller-provided signals."""

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ 用法：/roundtable TSLA {\"warren_buffett\":{\"TSLA\":{\"signal\":\"bullish\"}}}"
        )
        return
    try:
        tickers = await _resolve_tickers_async([context.args[0]])
        analyst_signals = json.loads(" ".join(context.args[1:]))
        options = {}
        if isinstance(analyst_signals, dict) and "_options" in analyst_signals:
            options = analyst_signals.pop("_options") or {}
        payload = build_round_table_payload(
            tickers,
            analyst_signals,
            model_name=str(options.get("model", "gpt-4o")),
            num_rounds=int(options.get("rounds", 2)),
        )
        data = await HedgeFundAPIClient().round_table(payload)
        round_tables = data.get("round_table") if isinstance(data.get("round_table"), dict) else {}
        sections = []
        for ticker in tickers:
            entry = get_symbol_entry(round_tables, ticker)
            if isinstance(entry, dict):
                sections.append(_format_round_table(ticker, entry))
        await safe_reply_markdown(update, "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(sections) or json.dumps(data, ensure_ascii=False, indent=2))
    except (json.JSONDecodeError, TypeError, ValueError, HedgeFundAPIError) as exc:
        await update.message.reply_text(f"❌ 圓桌請求格式錯誤或 API 失敗：{exc}")
    except Exception as exc:
        logger.error("Standalone round table error: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ 圓桌分析失敗：{exc}")


async def backtest_grid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start or resume a v2 point-in-time backtest grid."""

    if len(context.args) < 4:
        await update.message.reply_text(
            "❌ 用法：/backtest RUN_ID TICKERS START_DATE END_DATE [policy=daily fee=0.001 slippage=0.0005]"
        )
        return
    processing_msg = None
    try:
        run_id, raw_tickers, start_date, end_date = context.args[:4]
        _, options = _split_command_options(context.args[4:])
        selected = options.get("analysts")
        portfolio = json.loads(options["portfolio"]) if options.get("portfolio") else None
        tickers = await _resolve_tickers_async([raw_tickers])
        initial_cash = _extract_cash_option(options)

        payload = build_backtest_payload(
            run_id=run_id,
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            cutoff_time_utc=options.get("cutoff", "16:00:00Z"),
            selected_analysts=selected.split(",") if selected else None,
            initial_cash=initial_cash,
            portfolio=portfolio,
            daily_rebalance_policy=options.get("policy", "daily"),
            transaction_fee_rate=float(options.get("fee", "0.001")),
            slippage_rate=float(options.get("slippage", "0.0005")),
            margin_ratio=float(options.get("margin", "0.5")),
        )
        processing_msg = await update.message.reply_text(f"🧪 正在執行回測網格 `{run_id}`，請稍候...")
        data = await HedgeFundAPIClient().backtest_grid(payload)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await safe_reply_markdown(update, f"🧪 **回測網格結果 `{run_id}`**\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```")
    except (TypeError, ValueError, json.JSONDecodeError, HedgeFundAPIError) as exc:
        if processing_msg is not None:
            try:
                await processing_msg.delete()
            except Exception:
                pass
        await update.message.reply_text(f"❌ 回測請求格式錯誤或 API 失敗：{exc}")
    except Exception as exc:
        logger.error("Backtest grid error: %s", exc, exc_info=True)
        if processing_msg is not None:
            try:
                await processing_msg.delete()
            except Exception:
                pass
        await update.message.reply_text(f"❌ 回測失敗：{exc}")


async def backtest_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Read a persisted backtest run manifest and result."""

    if not context.args:
        await update.message.reply_text("❌ 用法：/backtest_status RUN_ID")
        return
    try:
        data = await HedgeFundAPIClient().get_backtest_run(context.args[0])
        await safe_reply_markdown(
            update,
            f"🧪 **回測 `{context.args[0]}` 狀態**\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```",
        )
    except HedgeFundAPIError as exc:
        await update.message.reply_text(f"❌ 查詢回測失敗：{exc}")
    except Exception as exc:
        logger.error("Backtest status error: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ 查詢回測失敗：{exc}")


async def ai2_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the live AI Hedge Fund API health response."""

    try:
        data = await HedgeFundAPIClient().health()
        await safe_reply_markdown(update, f"💓 **AI Hedge Fund API**\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```")
    except HedgeFundAPIError as exc:
        await update.message.reply_text(f"❌ AI Hedge Fund API 健康檢查失敗：{exc}")
    except Exception as exc:
        logger.error("AI2 health error: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ 健康檢查失敗：{exc}")

async def llm_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Natural Language Assistant Query (/llm command) with conversation memory and live tools."""
    query = " ".join(context.args) if context.args else None
    if not query:
        await update.message.reply_text("❌ 請提供問題，例如：/llm 2330.TW 的近期營收與技術面如何？")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    processing_msg = await update.message.reply_text("⏳ 思考與處理中，請稍候...")
    
    try:
        thread_id = str(update.effective_chat.id)
        response = await process_chat_message(query, thread_id=thread_id)
        
        # Delete temporary processing message
        try:
            await processing_msg.delete()
        except Exception:
            pass

        await safe_reply_markdown(update, response)
    except Exception as e:
        logger.error(f"LLM Query Error: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 回應失敗: {str(e)}")
