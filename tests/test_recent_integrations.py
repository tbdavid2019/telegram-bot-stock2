import json
import unittest
from pathlib import Path
from unittest import mock

from tools import polymarket, stockdata_quant


def _market(question="Will the Fed cut rates?", volume=100.0):
    return {
        "question": question,
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.6", "0.4"]),
        "volume24hr": volume,
        "volumeNum": volume,
        "liquidityNum": 10,
        "slug": "fed-cut",
    }


class RecentIntegrationTests(unittest.TestCase):
    def test_polymarket_top_is_treated_as_unfiltered(self):
        with mock.patch.object(polymarket, "_fetch_polymarket_api", return_value=[_market()]):
            polymarket._pm_cache.clear()
            markets = polymarket.fetch_polymarket_markets("top", limit=1)

        self.assertEqual(len(markets), 1)

    def test_calendar_formatter_renders_target_rates(self):
        text = stockdata_quant.format_calendar_markdown(
            {
                "fed": {
                    "meeting_date": "2026-09-16",
                    "updated_at": "2026-09-10",
                    "target_rates": [
                        {"rate_range": "3.50 - 3.75", "current_probability": "62.1%"}
                    ],
                }
            },
            cat="fed",
        )

        self.assertIn("3.50 - 3.75", text)
        self.assertIn("62.1%", text)

    def test_calendar_category_aliases(self):
        for alias, expected in (
            ("macro", "econ"),
            ("economic", "econ"),
            ("commodities", "comm"),
            ("rate", "fed"),
        ):
            with self.subTest(alias=alias):
                self.assertEqual(stockdata_quant.normalize_calendar_category(alias), expected)

    def test_timesfm_can_fetch_one_ticker_from_prediction_history(self):
        response = {
            "success": True,
            "data": [
                {
                    "ticker": "2330.TW",
                    "model_name": "TimesFM",
                    "timestamp": "2026-09-09T00:00:00",
                    "potential": 1.2,
                },
                {
                    "ticker": "2330.TW",
                    "model_name": "LSTM",
                    "timestamp": "2026-09-10T00:00:00",
                    "potential": 9.9,
                },
                {
                    "ticker": "2330.TW",
                    "model_name": "TimesFM",
                    "timestamp": "2026-09-10T00:00:00",
                    "potential": 2.4,
                },
            ],
        }
        with mock.patch.object(stockdata_quant, "_get_json", return_value=response):
            stockdata_quant._timesfm_cache.clear()
            items = stockdata_quant.fetch_timesfm_predictions(
                action="bullish", limit=10, ticker="2330.TW"
            )

        self.assertEqual([item["potential"] for item in items], [2.4, 1.2])
        self.assertTrue(all(item["model_name"] == "TimesFM" for item in items))

    def test_macro_formatter_uses_requested_market_when_api_ignores_market(self):
        response = {
            "success": True,
            "market": "US",
            "exposure": 0.5,
            "vix": 20.0,
            "spy_above_ma60": True,
            "twii_above_ma60": True,
            "sox_above_ma60": True,
            "warnings": [],
        }
        with mock.patch.object(stockdata_quant, "_get_json", return_value=response):
            stockdata_quant._macro_cache.clear()
            data = stockdata_quant.fetch_macro_regime("tw")

        text = stockdata_quant.format_macro_regime_markdown(data)
        self.assertIn("台股市場", text)
        self.assertIn("API 市場欄位不一致", text)

    def test_uploaded_document_prompt_limits_and_isolates_document_text(self):
        from tools.file_intel import build_document_analysis_prompt

        prompt = build_document_analysis_prompt(
            file_name="report.txt",
            doc_type="TXT",
            label="txt",
            score=1.0,
            file_size_kb=1.0,
            user_caption="請摘要",
            extracted_text="A" * 20,
            max_chars=10,
        )

        self.assertIn("<untrusted_document_data>", prompt)
        self.assertIn("不可信的文件資料", prompt)
        self.assertIn("後續內容已省略", prompt)
        self.assertNotIn("A" * 11, prompt)

    def test_xls_support_is_declared(self):
        requirements = Path(__file__).parents[1] / "requirements.txt"
        self.assertTrue(
            any(line.strip().startswith("xlrd") for line in requirements.read_text().splitlines())
        )

    def test_corrupt_xls_is_returned_as_a_safe_parse_error(self):
        import xlrd

        from tools import file_intel

        with mock.patch.object(
            file_intel.pd,
            "ExcelFile",
            side_effect=xlrd.biffh.XLRDError("corrupt workbook"),
        ):
            result = file_intel.extract_excel_content(b"corrupt")

        self.assertFalse(result["success"])
        self.assertIn(".xls", result["error"])

    def test_broker_formatter_includes_buyers_and_sellers(self):
        text = stockdata_quant.format_broker_summary_markdown(
            {
                "ticker": "2330.TW",
                "days": 20,
                "top_buyers": [
                    {"broker_name": "Buyer", "total_net": 10, "total_buy": 20, "total_sell": 10}
                ],
                "top_sellers": [
                    {"broker_name": "Seller", "total_net": -10, "total_buy": 10, "total_sell": 20}
                ],
            }
        )

        self.assertIn("Buyer", text)
        self.assertIn("Seller", text)


if __name__ == "__main__":
    unittest.main()
