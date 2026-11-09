"""Unit tests for Company Network URL defensive sanitization and anti-test pollution."""

import copy
import unittest
from unittest import mock
from urllib.parse import quote

from tools.stockdata_quant import (
    _sanitize_company_network_payload,
    _is_invalid_network_url,
    fetch_company_network,
    get_company_network_tool,
    _company_network_cache,
)


class TestCompanyNetworkSanitizer(unittest.TestCase):
    def setUp(self):
        _company_network_cache.clear()

    def test_is_invalid_network_url_boundaries(self):
        """測試 _is_invalid_network_url 的各項邊界條件與真假陽性判定。"""
        # 無效情境
        self.assertTrue(_is_invalid_network_url(None))
        self.assertTrue(_is_invalid_network_url(12345))
        self.assertTrue(_is_invalid_network_url(""))
        self.assertTrue(_is_invalid_network_url("   "))
        self.assertTrue(_is_invalid_network_url("not-a-url"))
        self.assertTrue(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph?company=test"))
        self.assertTrue(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph?company=TEST"))
        self.assertTrue(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph?company=undefined"))
        self.assertTrue(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph?company=null"))
        self.assertTrue(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph?company="))

        # 圖譜 URL 缺失 company 參數（P2-2 審查發現點）
        self.assertTrue(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph"))
        self.assertTrue(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph?other=123"))

        # 重複 query 參數包含佔位符情境（Codex P2 審查點）
        self.assertTrue(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph?company=2330&company=test"))
        self.assertTrue(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph?company=test&company=2330"))

        # 合法情境
        self.assertFalse(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph?company=%E5%8F%B0%E7%A9%8D%E9%9B%BB"))
        self.assertFalse(_is_invalid_network_url("https://taiwan-company-network.david888.com/graph?company=2330"))

        # 真實公司名稱含 Test（如德律科技 Test Research, Inc.，P2-3 審查發現點）
        test_research_url = f"https://taiwan-company-network.david888.com/graph?company={quote('Test Research')}"
        self.assertFalse(_is_invalid_network_url(test_research_url))

    def test_sanitize_payload_fixes_company_test_url(self):
        """測試 1：傳入包含 company=test 的 payload，驗證 web_url 被自動修正為含有正確公司名 URL-encode 的連結。"""
        company_name = "台灣積體電路製造股份有限公司"
        encoded_name = quote(company_name, safe="")
        expected_url = f"https://taiwan-company-network.david888.com/graph?company={encoded_name}"

        payload = {
            "name": company_name,
            "ticker": "2330",
            "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
            "image_url": "https://taiwan-company-network.david888.com/images/test.png",
            "relationships": [
                {
                    "name": "創意電子",
                    "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
                    "image_url": "https://taiwan-company-network.david888.com/images/test_sub.png",
                }
            ],
        }

        sanitized = _sanitize_company_network_payload(payload, "2330.TW")

        self.assertEqual(sanitized["web_url"], expected_url)
        self.assertNotIn("company=test", sanitized["web_url"])
        self.assertIsNone(sanitized["image_url"])

        # Check relationships sub-URLs
        rel = sanitized["relationships"][0]
        expected_rel_url = f"https://taiwan-company-network.david888.com/graph?company={quote('創意電子', safe='')}"
        self.assertEqual(rel["web_url"], expected_rel_url)
        self.assertIsNone(rel["image_url"])

    def test_sanitize_payload_relationships_dict_format(self):
        """測試線上真實 relationships 結構（upstream 與 downstream 字典）的清洗防禦（P2-1 審查點）。"""
        payload = {
            "name": "台積電",
            "ticker": "2330",
            "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
            "relationships": {
                "upstream": [
                    {
                        "name": "行政院國發基金",
                        "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
                        "image_url": "https://taiwan-company-network.david888.com/img/test.jpg",
                    }
                ],
                "downstream": [
                    {
                        "name": "創意電子股份有限公司",
                        "code": "3443",
                        "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
                        "image_url": "https://taiwan-company-network.david888.com/img/test2.jpg",
                    }
                ],
            },
        }

        sanitized = _sanitize_company_network_payload(payload, "2330.TW")

        # 頂層 web_url 校正
        self.assertIn(quote("台積電", safe=""), sanitized["web_url"])

        # 子關聯 upstream / downstream 校正
        up_item = sanitized["relationships"]["upstream"][0]
        self.assertEqual(
            up_item["web_url"],
            f"https://taiwan-company-network.david888.com/graph?company={quote('行政院國發基金', safe='')}",
        )
        self.assertIsNone(up_item["image_url"])

        down_item = sanitized["relationships"]["downstream"][0]
        self.assertEqual(
            down_item["web_url"],
            f"https://taiwan-company-network.david888.com/graph?company={quote('創意電子股份有限公司', safe='')}",
        )
        self.assertIsNone(down_item["image_url"])

    def test_sanitize_integer_ticker_type_safety(self):
        """測試 ticker 或 data['ticker'] 為整數型別時不會噴 AttributeError（P2-1 Codex 審查點）。"""
        # Case A: ticker 參數為 int
        payload_a = {"name": "聯發科", "web_url": "https://taiwan-company-network.david888.com/graph?company=test"}
        res_a = _sanitize_company_network_payload(payload_a, 2454)
        self.assertIn(quote("聯發科", safe=""), res_a["web_url"])

        # Case B: data['ticker'] 為 int 且外部 ticker 為空
        payload_b = {
            "ticker": 2330,
            "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
        }
        res_b = _sanitize_company_network_payload(payload_b, "")
        self.assertEqual(res_b["web_url"], "https://taiwan-company-network.david888.com/graph?company=2330")

    def test_cache_immutability_deepcopy(self):
        """測試深拷貝機制：確保傳入的快取字典不會被就地原地修改（P2-4 審查點）。"""
        raw_cache_data = {
            "name": "台積電",
            "ticker": "2330",
            "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
            "relationships": [
                {
                    "name": "創意電子",
                    "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
                }
            ],
        }
        cloned_cache = copy.deepcopy(raw_cache_data)

        sanitized = _sanitize_company_network_payload(raw_cache_data, "2330.TW")

        # 原始快取資料中的 web_url 不應被污染或原地覆寫
        self.assertEqual(raw_cache_data, cloned_cache)
        self.assertEqual(raw_cache_data["web_url"], "https://taiwan-company-network.david888.com/graph?company=test")
        self.assertNotEqual(sanitized["web_url"], raw_cache_data["web_url"])

    def test_extreme_fallback_when_empty(self):
        """測試極端空值情況下 web_url 置為 None，而不應造假出 company=company（P3-2 審查點）。"""
        empty_payload = {
            "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
        }
        res = _sanitize_company_network_payload(empty_payload, "")
        self.assertIsNone(res["web_url"])

    def test_sanitize_payload_generates_url_when_none_or_empty(self):
        """測試傳入 web_url 為 None 或空的 payload，驗證自動產生正確連結。"""
        # Case a: web_url is None with company name
        name_foxconn = "鴻海精密工業股份有限公司"
        payload_none = {
            "name": name_foxconn,
            "web_url": None,
        }
        res_none = _sanitize_company_network_payload(payload_none, "2317")
        expected_foxconn_url = f"https://taiwan-company-network.david888.com/graph?company={quote(name_foxconn, safe='')}"
        self.assertEqual(res_none["web_url"], expected_foxconn_url)

        # Case b: web_url is empty string and name missing, fallback to clean ticker
        payload_empty = {
            "web_url": "",
        }
        res_empty = _sanitize_company_network_payload(payload_empty, "2454.TW")
        expected_mtk_url = "https://taiwan-company-network.david888.com/graph?company=2454"
        self.assertEqual(res_empty["web_url"], expected_mtk_url)

        # Case b2: OTC .TWO ticker stripping (Codex P2: 環球晶 6488.TWO 不會被誤切為 6488O)
        res_otc = _sanitize_company_network_payload(payload_empty, "6488.TWO")
        expected_otc_url = "https://taiwan-company-network.david888.com/graph?company=6488"
        self.assertEqual(res_otc["web_url"], expected_otc_url)

        # Case c: web_url is whitespace or company=
        payload_blank_param = {
            "name": "台達電",
            "web_url": "https://taiwan-company-network.david888.com/graph?company=",
        }
        res_blank = _sanitize_company_network_payload(payload_blank_param, "2308")
        expected_delta_url = f"https://taiwan-company-network.david888.com/graph?company={quote('台達電', safe='')}"
        self.assertEqual(res_blank["web_url"], expected_delta_url)

    def test_sanitize_payload_preserves_valid_url(self):
        """測試傳入本就合法的 URL，驗證保留不被誤改。"""
        valid_url = f"https://taiwan-company-network.david888.com/graph?company={quote('台積電', safe='')}"
        valid_img = "https://taiwan-company-network.david888.com/images/2330.png"
        payload = {
            "name": "台積電",
            "ticker": "2330",
            "web_url": valid_url,
            "image_url": valid_img,
        }

        sanitized = _sanitize_company_network_payload(payload, "2330.TW")

        self.assertEqual(sanitized["web_url"], valid_url)
        self.assertEqual(sanitized["image_url"], valid_img)

        # 驗證包含 Test 單詞的合法企業圖片名稱不會被誤殺（Codex P2 審查點）
        legit_test_img = "https://assets.david888.com/logos/test-research-inc.png"
        payload_test_company = {
            "name": "德律科技",
            "ticker": "3030",
            "image_url": legit_test_img,
        }
        res_test_co = _sanitize_company_network_payload(payload_test_company, "3030")
        self.assertEqual(res_test_co["image_url"], legit_test_img)

    def test_fetch_company_network_sanitizes_upstream_response(self):
        """驗證 fetch_company_network 從上游取得污染資料時自動校正。"""
        upstream_mock = {
            "success": True,
            "data": {
                "name": "台積電",
                "ticker": "2330",
                "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
            },
        }
        with mock.patch("tools.stockdata_quant._get_json", return_value=upstream_mock):
            data = fetch_company_network("2330.TW")

        expected_url = f"https://taiwan-company-network.david888.com/graph?company={quote('台積電', safe='')}"
        self.assertEqual(data.get("web_url"), expected_url)

    def test_get_company_network_tool_includes_root_web_url(self):
        """驗證 get_company_network_tool 回傳頂層含有乾淨合法 web_url 供 LLM 直接引用。"""
        upstream_mock = {
            "success": True,
            "data": {
                "name": "台積電",
                "ticker": "2330",
                "web_url": "https://taiwan-company-network.david888.com/graph?company=test",
            },
        }
        with mock.patch("tools.stockdata_quant._get_json", return_value=upstream_mock):
            tool_output = get_company_network_tool.invoke({"ticker": "2330.TW"})

        self.assertIn("web_url", tool_output)
        self.assertNotIn("company=test", tool_output["web_url"])
        self.assertIn(quote("台積電", safe=""), tool_output["web_url"])
        self.assertEqual(tool_output["ticker"], "2330.TW")
        self.assertIn("company_network", tool_output)
        self.assertEqual(tool_output["web_url"], tool_output["company_network"]["web_url"])


if __name__ == "__main__":
    unittest.main()
