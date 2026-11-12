import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

# Ensure optional external dependencies don't block formatter card unit tests
for mod_name in [
    "telegram", "telegram.ext", "yfinance", "matplotlib", "matplotlib.pyplot", "matplotlib.font_manager", "bs4",
    "pandas", "ai_core", "langgraph", "langgraph.graph", "langchain_core", "langchain_openai", "pypdf", "xlrd", "magika"
]:
    if mod_name not in sys.modules:
        try:
            __import__(mod_name)
        except (ImportError, ModuleNotFoundError):
            sys.modules[mod_name] = MagicMock()

from tools.telegram_formatter import (
    format_card,
    build_inline_keyboard,
    parse_html_button_rows,
    _balance_html_tags,
    strip_html_and_markdown_tags,
    split_telegram_text,
    safe_reply_formatted,
)
from tools.stockdata_quant import (
    format_macro_regime_markdown,
    format_resonance_markdown,
    format_timesfm_markdown,
    format_xuantie_markdown,
    format_broker_summary_markdown,
    format_calendar_markdown,
)
from handlers.stock_cmds import (
    format_sepa_card,
    format_dcf_card,
    format_earn_card,
    format_corr_card,
)


class TestTelegramFormatterCards(unittest.TestCase):
    """Unit tests for Telegram <pre><code> card formatting and rich buttons."""

    def test_format_card_structure(self):
        title = "2330.TW 即時行情"
        pre_content = "現價: 1,080.00\n開盤: 1,075.00"
        footer = "資料來源：TWSE"

        card = format_card(title, pre_content, emoji="📊", footer=footer)

        self.assertIn("<b>📊 2330.TW 即時行情</b>", card)
        self.assertIn("<pre><code>現價: 1,080.00\n開盤: 1,075.00</code></pre>", card)
        self.assertIn("<i>資料來源：TWSE</i>", card)

    def test_format_card_html_escaping(self):
        title = "A & B <Test>"
        pre_content = "P/E < 15 & Growth > 20%"
        footer = "Note: A < B & C > D"

        card = format_card(title, pre_content, emoji="📊", footer=footer)

        self.assertIn("<b>📊 A &amp; B &lt;Test&gt;</b>", card)
        self.assertIn("<pre><code>P/E &lt; 15 &amp; Growth &gt; 20%</code></pre>", card)
        self.assertIn("<i>Note: A &lt; B &amp; C &gt; D</i>", card)

    def test_format_card_no_duplicate_emoji(self):
        title = "📊 已包含 Emoji 標題"
        card = format_card(title, "內文", emoji="📊")
        self.assertIn("<b>📊 已包含 Emoji 標題</b>", card)
        self.assertNotIn("<b>📊 📊", card)

    def test_format_card_extra_blocks(self):
        extra = ["區塊 1", "區塊 2"]
        card = format_card("標題", "內容", extra_blocks=extra)
        self.assertIn("區塊 1", card)
        self.assertIn("區塊 2", card)

    def test_build_inline_keyboard(self):
        buttons = [
            [
                {"text": "按鈕 1", "callback_data": "/cmd1"},
                {"text": "按鈕 2", "url": "https://example.com"}
            ],
            [
                ("按鈕 3", "/cmd3")
            ]
        ]
        markup = build_inline_keyboard(buttons)
        self.assertIsNotNone(markup)
        self.assertTrue(hasattr(markup, "inline_keyboard"))
        self.assertEqual(len(markup.inline_keyboard), 2)
        self.assertEqual(len(markup.inline_keyboard[0]), 2)
        self.assertEqual(len(markup.inline_keyboard[1]), 1)

    def test_build_inline_keyboard_long_callback(self):
        long_data = "/very_long_command_" + "x" * 100
        buttons = [[{"text": "Long", "callback_data": long_data}]]
        markup = build_inline_keyboard(buttons)
        btn = markup.inline_keyboard[0][0]
        # Should be hashed with p: prefix to stay <= 64 bytes
        self.assertLessEqual(len(btn.callback_data.encode("utf-8")), 64)

    def test_parse_html_button_rows(self):
        html_text = (
            "<b>卡片內容</b>\n\n"
            "<tg-button-row>"
            '<tg-button text="查詢籌碼" callback_data="/chip 2330.TW"></tg-button>'
            '<tg-button text="風控" callback_data="/macro"></tg-button>'
            "</tg-button-row>"
        )
        cleaned, markup = parse_html_button_rows(html_text)

        self.assertNotIn("<tg-button-row>", cleaned)
        self.assertNotIn("</tg-button-row>", cleaned)
        self.assertIn("<b>卡片內容</b>", cleaned)
        self.assertIsNotNone(markup)
        self.assertEqual(len(markup.inline_keyboard), 1)
        self.assertEqual(len(markup.inline_keyboard[0]), 2)

    def test_parse_html_button_rows_self_closing(self):
        html_text = (
            "<b>卡片內容</b>\n\n"
            "<tg-button-row>"
            '<tg-button text="即時行情" callback_data="/s 2330.TW" />'
            '<tg-button text="大盤風控" callback_data="/macro" />'
            "</tg-button-row>"
        )
        cleaned, markup = parse_html_button_rows(html_text)

        self.assertNotIn("<tg-button-row>", cleaned)
        self.assertNotIn("<tg-button", cleaned)
        self.assertIn("<b>卡片內容</b>", cleaned)
        self.assertIsNotNone(markup)
        self.assertEqual(len(markup.inline_keyboard), 1)
        self.assertEqual(len(markup.inline_keyboard[0]), 2)
        self.assertEqual(markup.inline_keyboard[0][0].text, "即時行情")
        self.assertEqual(markup.inline_keyboard[0][1].text, "大盤風控")

    def test_balance_html_tags(self):
        broken = "<b>未閉合粗體<pre><code>代碼未閉合"
        balanced = _balance_html_tags(broken)
        self.assertTrue(balanced.endswith("</code></pre></b>") or ("</pre>" in balanced and "</b>" in balanced))

    def test_strip_html_and_markdown_tags(self):
        raw = "<b>粗體</b> <i>斜體</i> `code` <pre><code>block</code></pre> **markdown**"
        clean = strip_html_and_markdown_tags(raw)
        self.assertNotIn("<b>", clean)
        self.assertNotIn("</b>", clean)
        self.assertNotIn("<pre>", clean)
        self.assertNotIn("`", clean)
        self.assertNotIn("**", clean)
        self.assertIn("粗體", clean)
        self.assertIn("斜體", clean)
        self.assertIn("markdown", clean)

    def test_safe_reply_formatted_html_priority(self):
        async def run_test():
            msg = AsyncMock()
            msg.reply_text = AsyncMock()
            card = format_card("測試標題", "內容", emoji="📊")

            await safe_reply_formatted(msg, card)

            msg.reply_text.assert_called_once()
            call_kwargs = msg.reply_text.call_args.kwargs
            self.assertEqual(call_kwargs.get("parse_mode"), "HTML")

        asyncio.run(run_test())

    def test_safe_reply_formatted_fallback_to_markdown_and_plain(self):
        async def run_test():
            msg = AsyncMock()
            # First call (HTML) raises Telegram 400 Bad Request
            # Second call (Markdown) also raises
            # Third call (Plain text) succeeds
            msg.reply_text = AsyncMock(side_effect=[
                Exception("Bad Request: can't parse entities in HTML"),
                Exception("Bad Request: can't parse entities in Markdown"),
                None
            ])
            card = format_card("標題", "內容", emoji="📊")

            await safe_reply_formatted(msg, card)

            self.assertEqual(msg.reply_text.call_count, 3)
            # Third call must not have parse_mode
            last_call_kwargs = msg.reply_text.call_args.kwargs
            self.assertNotIn("parse_mode", last_call_kwargs)

        asyncio.run(run_test())

    def test_safe_reply_formatted_auto_button_extraction(self):
        async def run_test():
            msg = AsyncMock()
            msg.reply_text = AsyncMock()
            text_with_buttons = (
                "<b>分析報告</b>\n"
                "<pre><code>數據...</code></pre>\n"
                "<tg-button-row>"
                '<tg-button text="查看風控" callback_data="/macro"></tg-button>'
                "</tg-button-row>"
            )

            await safe_reply_formatted(msg, text_with_buttons)

            msg.reply_text.assert_called_once()
            call_args = msg.reply_text.call_args
            call_text = call_args.args[0] if call_args.args else call_args.kwargs.get("text")
            markup = call_args.kwargs.get("reply_markup")

            self.assertNotIn("<tg-button-row>", call_text)
            self.assertIsNotNone(markup)
            self.assertEqual(len(markup.inline_keyboard), 1)

        asyncio.run(run_test())

    # --- Stock commands card format tests ---
    def test_format_sepa_card(self):
        res = {
            "stock": "2330.TW",
            "stage": "Stage 2 向上趨勢",
            "template_score": "8/8",
            "metrics": {
                "price": 1080.0,
                "ma50": 1020.0,
                "ma150": 960.0,
                "ma200": 920.0,
                "52_week_low": 750.0,
                "52_week_high": 1100.0,
                "relative_3m_return": 18.2,
                "spy_3m_return": 4.5,
            },
            "rules": [{"rule": 1, "passed": True, "criterion": "現價高於 MA150 與 MA200"}],
            "risk_stops": {"7_percent_stop": 1004.4, "2_atr_stop": 1015.2},
            "pivot_entry": 1090.0,
            "vcp": {"detected": True, "volume_10d_vs_50d": 0.72},
        }
        card = format_sepa_card(res)
        self.assertIn("<b>📊 2330.TW SEPA 趨勢與 VCP 分析</b>", card)
        self.assertIn("<pre><code>", card)
        self.assertIn("</pre>", card)
        self.assertIn("突破買點 (Pivot): $1,090.00", card)

    def test_format_dcf_card(self):
        res = {
            "stock": "TSLA",
            "current_price": 250.0,
            "wacc": 9.5,
            "risk_free_rate": 4.2,
            "beta": 1.45,
            "projected_fair_value_per_share": {"bear": 180.0, "base": 280.0, "bull": 350.0},
            "margin_of_safety_at_base": 12.0,
        }
        card = format_dcf_card(res)
        self.assertIn("<b>💰 TSLA 5年 FCFF 折現估值模型 (DCF)</b>", card)
        self.assertIn("<pre><code>", card)
        self.assertIn("基準中性 (Base): $280.00", card)

    def test_format_earn_card(self):
        res = {
            "stock": "NVDA",
            "upcoming_earnings_date": "2026-11-20",
            "consensus": {"eps": 0.75, "revenue": 32500000000, "analyst_target_mean": 160.0},
            "beat_rate_last_four": 100.0,
            "last_four_quarters": [{"date": "2026-08-28", "reported_eps": 0.68, "eps_estimate": 0.64, "surprise_percent": 6.25}],
        }
        card = format_earn_card(res)
        self.assertIn("<b>🗓️ NVDA 財報預期與盈餘驚喜簡報</b>", card)
        self.assertIn("<pre><code>", card)
        self.assertIn("市場共識 EPS 預估:  $0.75", card)

    def test_format_corr_card(self):
        res = {
            "tickers": ["TSLA", "NVDA"],
            "observations": 90,
            "correlation_matrix": {"TSLA": {"TSLA": 1.0, "NVDA": 0.72}, "NVDA": {"TSLA": 0.72, "NVDA": 1.0}},
            "spy_beta": {"TSLA": 1.85, "NVDA": 2.1},
        }
        card = format_corr_card(res)
        self.assertIn("<b>🔗 多股 90 日日報酬相關性與 SPY Beta</b>", card)
        self.assertIn("<pre><code>", card)
        self.assertIn("TSLA", card)
        self.assertIn("NVDA", card)

    # --- Stockdata quant format tests ---
    def test_format_macro_regime_markdown(self):
        data = {
            "success": True,
            "market": "TW",
            "requested_market": "TW",
            "regime_name": "多頭趨勢",
            "exposure": 0.8,
            "vix": 16.5,
            "twii_above_ma60": True,
            "spy_above_ma60": True,
            "sox_above_ma60": True,
            "warnings": ["留意高檔獲利了結"],
        }
        card = format_macro_regime_markdown(data)
        self.assertIn("<b>🛡️ 大盤風控制度與部位曝險指南", card)
        self.assertIn("<pre><code>", card)
        self.assertIn("建議曝險: [████████░░] 80%", card)

    def test_format_resonance_markdown(self):
        picks = [{
            "ticker": "2330",
            "name": "台積電",
            "current_price": 1080.0,
            "predicted_price": 1250.0,
            "potential": 15.7,
            "model_name": "TimesFM",
            "strategy_type": "玄鐵",
            "pe": 22.5,
            "risk_reward_ratio": 2.1,
            "trust_net_5d": 1200,
            "foreign_net_5d": 3500,
        }]
        card = format_resonance_markdown(picks, title="台灣50 多模型交集共振選股推薦")
        self.assertIn("<b>👑 台灣50 多模型交集共振選股推薦</b>", card)
        self.assertIn("<pre><code>", card)
        self.assertIn("2330 台積電", card)

    def test_format_timesfm_markdown(self):
        items = [{
            "ticker": "2330",
            "name": "台積電",
            "current_price": 1080.0,
            "predicted_price": 1140.0,
            "potential": 5.6,
            "risk_reward_ratio": 2.4,
            "pe": 22.5,
        }]
        card = format_timesfm_markdown(items, is_bearish=False)
        self.assertIn("<b>🧠 Google TimesFM 5日時序大模型看漲榜</b>", card)
        self.assertIn("<pre><code>", card)
        self.assertIn("現價: 1,080.0 ➔ 5日目標: 1,140.0 (+5.6%)", card)

    def test_format_xuantie_markdown(self):
        items = [{
            "ticker": "2330",
            "name": "台積電",
            "current_price": 1080.0,
            "predicted_price": 1200.0,
            "potential": 11.1,
            "pullback_type": "季線支撐",
            "ma60": 1050.0,
            "ma120": 980.0,
        }]
        card = format_xuantie_markdown(items)
        self.assertIn("<b>🗡️ 玄鐵重劍：MA60/120 均線波段回踩買點</b>", card)
        self.assertIn("<pre><code>", card)
        self.assertIn("2330 台積電 (季線支撐)", card)

    def test_format_broker_summary_markdown(self):
        data = {
            "ticker": "2330.TW",
            "days": 20,
            "start_date": "2026-10-15",
            "end_date": "2026-11-10",
            "top_buyers": [{"broker_name": "台灣摩根", "total_net": 18250, "total_buy": 20100, "total_sell": 1850}],
            "top_sellers": [{"broker_name": "元大台北", "total_net": -9420, "total_buy": 1200, "total_sell": 10620}],
        }
        card = format_broker_summary_markdown(data)
        self.assertIn("<b>🏢 2330.TW 近 20 日券商主力關鍵分點排行</b>", card)
        self.assertIn("<pre><code>", card)
        self.assertIn("台灣摩根 +18,250張", card)

    def test_format_calendar_markdown(self):
        data = {
            "fed": {"meeting_date": "2026-12-18", "updated_at": "2026-11-10", "probabilities": [{"rate_range": "4.25%-4.50%", "probability": "78.5%"}]},
            "earnings": [{"ticker": "NVDA", "name": "輝達", "date": "2026-11-20", "eps_forecast": "0.75"}],
            "economic": [{"country": "US", "time": "20:30", "event": "CPI 年增率"}],
            "commodities": {"wti": {"name": "WTI原油", "daily_change": "1.8", "indicator": "反彈"}},
        }
        card = format_calendar_markdown(data)
        self.assertIn("<b>📅 全球總經與美股重磅行事曆</b>", card)
        self.assertIn("<pre><code>", card)
        self.assertIn("CME 聯準會利率路徑", card)
        self.assertIn("NVDA 輝達", card)

    def test_safe_reply_formatted_target_unwrapping(self):
        async def run_test():
            # 1. Update with effective_message (without direct reply_text)
            update_obj = MagicMock(spec=["effective_message"])
            eff_msg = AsyncMock()
            eff_msg.reply_text = AsyncMock()
            update_obj.effective_message = eff_msg

            await safe_reply_formatted(update_obj, "<b>測試訊息</b>")
            eff_msg.reply_text.assert_called_once()

            # 2. Update with callback_query.message (without direct reply_text)
            cb_update = MagicMock(spec=["callback_query"])
            cb_msg = AsyncMock()
            cb_msg.reply_text = AsyncMock()
            cb_query = MagicMock()
            cb_query.message = cb_msg
            cb_update.callback_query = cb_query

            await safe_reply_formatted(cb_update, "<b>Callback 訊息</b>")
            cb_msg.reply_text.assert_called_once()

            # 3. None message
            await safe_reply_formatted(None, "空訊息")

        asyncio.run(run_test())

    def test_defensive_null_handling_all_formatters(self):
        # 1. format_macro_regime_markdown
        card = format_macro_regime_markdown(None)
        self.assertIn("無大盤風控資料", card)
        card = format_macro_regime_markdown({})
        self.assertIn("無大盤風控資料", card)
        card = format_macro_regime_markdown({"success": True, "macro_exposure_limit": None, "vix": None})
        self.assertIn("建議曝險: [░░░░░░░░░░] 0%", card)

        # 2. format_resonance_markdown
        card = format_resonance_markdown(None)
        self.assertIn("目前市場暫無觸發共振門檻", card)
        card = format_resonance_markdown([])
        self.assertIn("目前市場暫無觸發共振門檻", card)
        card = format_resonance_markdown([{"current_price": None, "predicted_price": None, "potential": None}])
        self.assertIn("現價: 0.0 ➔ 預期: 0.0 (+0.0%)", card)

        # 3. format_timesfm_markdown
        card = format_timesfm_markdown(None)
        self.assertIn("查無相關預測數據", card)
        card = format_timesfm_markdown([])
        self.assertIn("查無相關預測數據", card)
        card = format_timesfm_markdown([{"current_price": None, "predicted_price": None, "potential": None}])
        self.assertIn("現價: 0.0 ➔ 5日目標: 0.0 (+0.0%)", card)

        # 4. format_xuantie_markdown
        card = format_xuantie_markdown(None)
        self.assertIn("目前市場無回踩季線/半年線支撐之標的", card)
        card = format_xuantie_markdown([])
        self.assertIn("目前市場無回踩季線/半年線支撐之標的", card)
        card = format_xuantie_markdown([{"current_price": None, "predicted_price": None, "potential": None}])
        self.assertIn("現價: 0.0 ➔ 預期: 0.0 (+0.0%)", card)

        # 5. format_broker_summary_markdown
        card = format_broker_summary_markdown(None)
        self.assertIn("查無該標的近期的券商分點買賣資料", card)
        card = format_broker_summary_markdown({})
        self.assertIn("查無該標的近期的券商分點買賣資料", card)
        card = format_broker_summary_markdown({
            "ticker": "2330.TW",
            "top_buyers": [{"broker_name": "測試券商", "total_net": None, "total_buy": None, "total_sell": None}],
            "top_sellers": [{"broker_name": "測試賣家", "total_net": None, "total_buy": None, "total_sell": None}],
        })
        self.assertIn("測試券商 0張", card)

        # 6. format_calendar_markdown
        card = format_calendar_markdown(None)
        self.assertIn("無行事曆資料", card)
        card = format_calendar_markdown({})
        self.assertIn("無行事曆資料", card)

        # 7. format_sepa_card
        card = format_sepa_card(None)
        self.assertIn("無分析資料", card)
        card = format_sepa_card({})
        self.assertIn("無分析資料", card)

        # 8. format_dcf_card
        card = format_dcf_card(None)
        self.assertIn("無估值資料", card)
        card = format_dcf_card({})
        self.assertIn("無估值資料", card)

        # 9. format_earn_card
        card = format_earn_card(None)
        self.assertIn("無財報資料", card)
        card = format_earn_card({})
        self.assertIn("無財報資料", card)

        # 10. format_corr_card
        card = format_corr_card(None)
        self.assertIn("無相關性資料", card)
        card = format_corr_card({})
        self.assertIn("無相關性資料", card)

    def test_callback_prompt_handler_fast_routing(self):
        from unittest.mock import patch
        from handlers.general import callback_prompt_handler, PROMPT_CACHE

        async def run_test():
            routed = {}

            async def mock_stock_info(u, c): routed["stock_info"] = c.args
            async def mock_val(u, c): routed["val"] = c.args
            async def mock_sepa(u, c): routed["sepa"] = c.args
            async def mock_chip(u, c): routed["chip"] = c.args
            async def mock_macro(u, c): routed["macro"] = c.args
            async def mock_pick(u, c): routed["pick"] = c.args
            async def mock_tfm(u, c): routed["tfm"] = c.args
            async def mock_xt(u, c): routed["xt"] = c.args
            async def mock_broker(u, c): routed["broker"] = c.args
            async def mock_cal(u, c): routed["cal"] = c.args
            async def mock_pm(u, c): routed["pm"] = c.args

            with patch("handlers.stock_cmds.stock_info", mock_stock_info), \
                 patch("handlers.stock_cmds.valuation_analysis", mock_val), \
                 patch("handlers.stock_cmds.sepa_analysis", mock_sepa), \
                 patch("handlers.stock_cmds.institutional_chip_analysis", mock_chip), \
                 patch("handlers.stock_cmds.macro_regime_query", mock_macro), \
                 patch("handlers.stock_cmds.resonance_picks_query", mock_pick), \
                 patch("handlers.stock_cmds.timesfm_predictions_query", mock_tfm), \
                 patch("handlers.stock_cmds.xuantie_pullback_query", mock_xt), \
                 patch("handlers.stock_cmds.broker_trades_query", mock_broker), \
                 patch("handlers.stock_cmds.calendar_query", mock_cal), \
                 patch("handlers.stock_cmds.polymarket_query", mock_pm):

                commands_to_test = [
                    ("/s 2330.TW", "stock_info", ["2330.TW"]),
                    ("/dcf TSLA", "val", ["TSLA"]),
                    ("/sepa 2330.TW", "sepa", ["2330.TW"]),
                    ("/chip 2330.TW", "chip", ["2330.TW"]),
                    ("/macro", "macro", []),
                    ("/pick", "pick", []),
                    ("/tfm top", "tfm", ["top"]),
                    ("/xt", "xt", []),
                    ("/broker 2330.TW", "broker", ["2330.TW"]),
                    ("/cal earn", "cal", ["earn"]),
                    ("/pm fed", "pm", ["fed"]),
                ]

                for raw_cmd, key, expected_args in commands_to_test:
                    update = MagicMock()
                    update.callback_query = AsyncMock()
                    update.callback_query.data = raw_cmd
                    context = MagicMock()

                    await callback_prompt_handler(update, context)
                    self.assertIn(key, routed)
                    self.assertEqual(routed[key], expected_args)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
