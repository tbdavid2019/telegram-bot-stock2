"""Taiwan Government Procurement Tenders & Compliance Intelligence Tool.

Interfaces with the ToBid Government Procurement MCP Endpoint (https://api.tobid.tw/mcp)
to track listed companies' public tender awards, client distribution, win rates, and
Article 101 debarment / blacklist risk assessments.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

try:
    from config import TOBID_MCP_URL
except ImportError:
    TOBID_MCP_URL = "https://api.tobid.tw/mcp"

from tools.cache_util import SingleFlight, TTLCache

logger = logging.getLogger(__name__)

# SSL context for HTTPS requests with standard verification
SSL_CONTEXT = ssl.create_default_context()

# HTTP Headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Cache configurations
_tender_cache = TTLCache(default_ttl=3600.0, max_size=200)       # 1 hour TTL
_compliance_cache = TTLCache(default_ttl=7200.0, max_size=200)   # 2 hours TTL
_entity_cache = TTLCache(default_ttl=86400.0, max_size=500)      # 24 hours TTL
_single_flight = SingleFlight()

# Common Taiwan listed companies heavily active in government procurement
TW_STOCK_TENDER_MAPPING: Dict[str, str] = {
    # Defense & Aerospace / 軍工與航太
    "2634": "漢翔航空工業股份有限公司",
    "2630": "亞洲航空股份有限公司",
    "6753": "龍德造船工業股份有限公司",
    "8033": "雷虎科技股份有限公司",
    "5222": "全訊科技股份有限公司",
    # IT Services & Cybersecurity / 資訊軟服與資安
    "6214": "精誠資訊股份有限公司",
    "3029": "零壹科技股份有限公司",
    "6112": "邁達特數位股份有限公司",
    "2453": "凌群電腦股份有限公司",
    "2471": "資通電腦股份有限公司",
    "6690": "安碁資訊股份有限公司",
    "6752": "叡揚資訊股份有限公司",
    "6874": "倍力資訊股份有限公司",
    "6811": "宏碁資訊服務股份有限公司",
    "2427": "三商電腦股份有限公司",
    "5203": "訊連科技股份有限公司",
    # Engineering & Civil Construction / 營造與工程
    "9933": "中鼎工程股份有限公司",
    "3703": "欣陸投資控股股份有限公司",
    "5521": "工信工程股份有限公司",
    "8473": "山林水環境工程股份有限公司",
    "8936": "國統國際股份有限公司",
    "9930": "中聯資源股份有限公司",
    "2515": "中華工程股份有限公司",
    "2597": "潤弘精密工程事業股份有限公司",
    "2535": "達欣工程股份有限公司",
    # Power & Green Energy / 重電與綠能
    "1519": "華城電機股份有限公司",
    "1503": "士林電機廠股份有限公司",
    "1513": "中興電工機械股份有限公司",
    "1514": "亞力電機股份有限公司",
    "2371": "大同股份有限公司",
    "6869": "雲豹能源科技股份有限公司",
    "6873": "泓德能源科技股份有限公司",
    "6806": "森崴能源股份有限公司",
    # Telecommunication / 電信三雄
    "2412": "中華電信股份有限公司",
    "3045": "台灣大哥大股份有限公司",
    "4904": "遠傳電信股份有限公司",
}


def _format_currency(amount: Optional[float | int]) -> str:
    """Format large NTD amounts into human-readable units (億/萬)."""
    if not amount or amount <= 0:
        return "0 元"
    if amount >= 100_000_000:
        return f"{amount / 100_000_000:,.2f} 億元 NTD"
    if amount >= 10_000:
        return f"{amount / 10_000:,.1f} 萬元 NTD"
    return f"{amount:,.0f} 元 NTD"


def _call_tobid_mcp(tool_name: str, arguments: Dict[str, Any], timeout: int = 10) -> Optional[Dict[str, Any]]:
    """Execute a tool call via the ToBid JSON-RPC 2.0 MCP endpoint."""
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
        "id": int(time.time() * 1000),
    }

    try:
        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(TOBID_MCP_URL, data=data_bytes, headers=HEADERS, method="POST")
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            raw_body = resp.read().decode("utf-8")
            res_json = json.loads(raw_body)
            if "error" in res_json:
                logger.warning(f"ToBid MCP returned error: {res_json['error']}")
                return None
            result = res_json.get("result", {})
            if result.get("isError"):
                logger.warning(f"ToBid MCP returned tool execution error for {tool_name}: {result}")
                return None
            content = result.get("content", [])
            if content and isinstance(content, list) and "text" in content[0]:
                text = content[0]["text"]
                try:
                    return json.loads(text)
                except Exception:
                    logger.debug(f"ToBid MCP text is not JSON: {text[:200]}")
                    return {"raw_text": text}
            return result
    except Exception as e:
        logger.warning(f"ToBid MCP request failed for {tool_name}: {e}")
        return None


def resolve_company_name(query: str) -> str:
    """Resolve stock ticker or partial name to standard company legal name."""
    clean_q = query.strip()
    ticker_match = re.search(r"(\d{4,6})", clean_q)
    if ticker_match:
        ticker = ticker_match.group(1)
        if ticker in TW_STOCK_TENDER_MAPPING:
            return TW_STOCK_TENDER_MAPPING[ticker]

    # Check direct name matches in mapping
    for code, name in TW_STOCK_TENDER_MAPPING.items():
        if clean_q in name or name in clean_q:
            return name

    # Check entity cache first
    cached_entity = _entity_cache.get(clean_q)
    if cached_entity:
        return cached_entity

    def _resolve_remote() -> str:
        # Fallback to ToBid find_entity MCP tool
        entity_data = _call_tobid_mcp("find_entity", {"q": clean_q}, timeout=6)
        if entity_data and isinstance(entity_data, dict):
            vendors = entity_data.get("vendors", [])
            if vendors and isinstance(vendors, list) and len(vendors) > 0:
                top_vendor = vendors[0]
                if isinstance(top_vendor, dict) and "name" in top_vendor:
                    resolved = top_vendor["name"]
                    _entity_cache.set(clean_q, resolved)
                    return resolved
        _entity_cache.set(clean_q, clean_q)
        return clean_q

    return _single_flight.run(f"entity:{clean_q}", _resolve_remote)


@tool
def get_company_government_tenders(ticker_or_company: str) -> str:
    """查詢台灣上市櫃公司的政府公標案得標戰報、歷史勝率、累計得標金額、最大客戶機關與近期重大得標案件。
    
    非常適合用於軍工國防 (漢翔/龍德/雷虎)、資訊軟服 (精誠/零壹/邁達特/凌群)、營造公共工程 (中鼎/工信/欣陸/山林水)、
    重電綠能 (華城/士電/泓德/雲豹) 等高度依賴政府公標案的個股，作為營收先行指標。

    Args:
        ticker_or_company: 台灣股票代號 (例: 2634, 6214, 9933) 或公司簡稱/全稱 (例: 漢翔, 精誠資訊, 中鼎)。
    """
    company_name = resolve_company_name(ticker_or_company)
    cache_key = f"tenders:{company_name}"

    cached = _tender_cache.get(cache_key)
    if cached:
        return cached

    def _fetch_report() -> str:
        # 1. Fetch vendor report with 15s timeout
        report = _call_tobid_mcp("vendor_report", {"name": company_name}, timeout=15)
        
        # If vendor_report returned valid structure
        if report and isinstance(report, dict) and "participations" in report:
            name = report.get("name", company_name)
            tax_id = report.get("tax_id", "-")
            participations = report.get("participations", 0)
            wins = report.get("wins", 0)
            win_rate_pct = report.get("win_rate_pct", 0.0)
            known_award_total = report.get("known_award_total", 0)
            sole_bid_rate_pct = report.get("sole_bid_rate_pct", 0.0)
            web_link = report.get("web", f"https://tobid.tw/?vendor={name}")

            lines = [
                f"🏛️ **【{name}】政府標案得標戰報**",
                f"• 統一編號：`{tax_id}`",
                f"• 歷史投標次數：`{participations:,}` 次",
                f"• 累計得標次數：`{wins:,}` 次（得標率 **{win_rate_pct:.1f}%**）",
                f"• 單一投標獨得率：`{sole_bid_rate_pct:.1f}%`",
                f"• 歷史已知決標總額：**{_format_currency(known_award_total)}**",
                "",
            ]

            # Top client agencies
            top_clients = report.get("top_clients", [])
            if top_clients:
                lines.append("🏢 **前五大發包政府機關：**")
                for c in top_clients[:5]:
                    c_unit = c.get("unit", "未知機關")
                    c_wins = c.get("wins", 0)
                    c_amt = _format_currency(c.get("amount", 0))
                    lines.append(f"  - **{c_unit}**：得標 {c_wins} 次，累計 {c_amt}")
                lines.append("")

            # Top rivals
            top_rivals = report.get("top_rivals", [])
            if top_rivals:
                lines.append("⚔️ **主要公標案競爭對手：**")
                for r in top_rivals[:3]:
                    r_name = r.get("name", "同場對手")
                    r_met = r.get("met", 0)
                    r_wins = r.get("this_vendor_wins", 0)
                    rival_wins = r.get("rival_wins", 0)
                    lines.append(f"  - **{r_name}**：同場交手 {r_met} 次（本公司 {r_wins} 勝 vs 對手 {rival_wins} 勝）")
                lines.append("")

            # 2. Fetch recent major award cases (using vendor filter)
            recent_cases = _call_tobid_mcp("search_tenders", {"vendor": company_name, "kind": "award"}, timeout=10)
            if recent_cases and isinstance(recent_cases, dict):
                results = recent_cases.get("results", [])
                if results:
                    lines.append(f"📜 **近期代表性決標標案（共收錄 {recent_cases.get('total', len(results)):,} 筆）：**")
                    for r in results[:4]:
                        title = r.get("title", "未命名標案")
                        unit = r.get("unit_name", "")
                        unit_id = r.get("unit_id", "")
                        job_number = r.get("job_number", "")
                        budget = _format_currency(r.get("budget", 0))
                        award_amt = _format_currency(r.get("award_amount", 0))
                        date_val = str(r.get("date", ""))
                        if len(date_val) == 8:
                            date_str = f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:]}"
                        else:
                            date_str = date_val
                        case_url = f"https://tobid.tw/?case={unit_id}|{job_number}" if (unit_id and job_number) else web_link
                        lines.append(f"  • [{title}]({case_url})")
                        lines.append(f"    - 機關：{unit} | 案號：`{job_number}` | 日期：{date_str}")
                        lines.append(f"    - 決標金額：**{award_amt}**（預算：{budget}）")
                    lines.append("")

            lines.append(f"🔗 [點此查看 ToBid 完整標案明細與歷程]({web_link})")
            lines.append("*(數據來源：行政院公共工程委員會政府電子採購網，由 ToBid 即時分析引擎驅動)*")
            return "\n".join(lines)

        # Stale cache fallback if report failed
        stale = _tender_cache.get_stale(cache_key)
        if stale:
            return stale + "\n\n*(⚠️ 目前 ToBid 上游回應延遲，此為快取歷史資料)*"

        # If vendor_report returned no participations, try searching tenders by vendor
        tenders = _call_tobid_mcp("search_tenders", {"vendor": company_name, "kind": "award"}, timeout=10)
        search_kw = company_name.replace("股份有限公司", "").replace("科技", "").replace("工業", "").strip()[:4]
        raw_tenders = None
        if tenders is None or (isinstance(tenders, dict) and tenders.get("total", 0) == 0):
            raw_tenders = _call_tobid_mcp("search_tenders", {"q": search_kw, "kind": "award"}, timeout=10)
            if raw_tenders and isinstance(raw_tenders, dict):
                filtered = [
                    r for r in raw_tenders.get("results", [])
                    if any(company_name in w or search_kw in w for w in r.get("winners", []))
                ]
                if filtered:
                    tenders = {"total": len(filtered), "results": filtered}

        if report is None and tenders is None and raw_tenders is None:
            return f"⚠️ 目前查詢【{company_name}】政府標案時連線逾時或上游暫時無法取得數據，請稍後再試。"

        if tenders and isinstance(tenders, dict) and tenders.get("total", 0) > 0:
            results = tenders.get("results", [])
            lines = [
                f"🏛️ **【{company_name}】相關政府決標標案（搜尋到 {tenders.get('total', len(results))} 筆）：**",
                "",
            ]
            for r in results[:5]:
                title = r.get("title", "未命名標案")
                unit = r.get("unit_name", "")
                budget = _format_currency(r.get("budget", 0))
                award_amt = _format_currency(r.get("award_amount", 0))
                lines.append(f"• **{title}** ({unit}) - 決標金額：{award_amt}")
            lines.append("")
            lines.append(f"🔗 [前往 ToBid 搜尋更多標案](https://tobid.tw/?q={search_kw})")
            return "\n".join(lines)

        return f"ℹ️ 查無【{company_name}】的公開政府標案紀錄，該公司可能非政府公標案主要投標廠商，或以其他轉投資特許子公司名義投標。"

    result_text = _single_flight.run(cache_key, _fetch_report)
    if not result_text.startswith("⚠️"):
        _tender_cache.set(cache_key, result_text)
    return result_text


@tool
def check_vendor_procurement_compliance(ticker_or_company: str) -> str:
    """查詢上市櫃公司或得標廠商是否有政府採購法第 101 條停權、列入拒絕往來廠商黑名單等重大法規風險。
    
    若公司被政府機關刊登為「拒絕往來廠商（停權）」，在停權期間不得參與任何公共工程標案，
    對國防軍工、營造水資源、資服系統整合等倚賴政府標案之企業屬於重大基本面黑天鵝風險。

    Args:
        ticker_or_company: 台灣股票代號 (例: 2634, 6214, 9933) 或公司名稱。
    """
    company_name = resolve_company_name(ticker_or_company)
    cache_key = f"compliance:{company_name}"

    cached = _compliance_cache.get(cache_key)
    if cached:
        return cached

    def _fetch_compliance() -> str:
        data = _call_tobid_mcp("vendor_compliance", {"name": company_name}, timeout=10)
        if data is None:
            stale = _compliance_cache.get_stale(cache_key)
            if stale:
                return stale + "\n\n*(⚠️ 目前 ToBid 上游回應延遲，此為快取歷史資料)*"
            return f"⚠️ 查詢【{company_name}】政府採購法合規與停權紀錄時連線逾時或上游暫時無法取得數據，無法確認停權狀態，請稍後再試。"

        if not isinstance(data, dict) or "raw_text" in data or "error" in data or "name" not in data:
            return f"⚠️ 查詢【{company_name}】政府採購法合規與停權紀錄時資料格式異常，無法確認停權狀態，請稍後再試。"

        name = data.get("name", company_name)
        currently_debarred = data.get("currently_debarred")
        debarments = data.get("debarments", [])
        article_101_cases = data.get("article_101_cases", [])
        revoked = data.get("revoked", [])
        web_link = data.get("web", f"https://tobid.tw/?vendor={name}")

        lines = [
            f"🛡️ **【{name}】政府採購法合規與停權風控查核**",
            "",
        ]

        if currently_debarred is True:
            lines.append("🚨 **【重大風險警示】目前遭政府列為「拒絕往來廠商（停權生效中）」！**")
            lines.append("⚠️ **投資警語**：停權期間該公司依法不得參與任何政府採購與公共工程投標，恐重創未來標案營收！")
            lines.append("")
        elif currently_debarred is False:
            lines.append("✅ **【合規狀態良好】目前「未」名列政府拒絕往來（停權）黑名單。**")
            lines.append("")
        else:
            lines.append("⚠️ **【查核狀態未明】資料庫回傳紀錄中缺少目前停權狀態旗標，建議人工至主管機關複核。**")
            lines.append("")

        if debarments:
            lines.append(f"📋 **歷史停權紀錄（共 {len(debarments)} 筆）：**")
            for d in debarments[:3]:
                unit = d.get("unit_name", "機關")
                period = d.get("period", "期間")
                reason = d.get("reason", "採購法違規事項")
                lines.append(f"  • 機關：{unit} | 期間：{period}")
                lines.append(f"    事由：{reason}")
            lines.append("")

        if article_101_cases:
            lines.append(f"⚖️ **採購法第 101 條爭議案件（共 {len(article_101_cases)} 筆）：**")
            for c in article_101_cases[:3]:
                c_unit = c.get("unit_name", "")
                c_title = c.get("title", "")
                c_status = c.get("status", "")
                lines.append(f"  • {c_unit} - {c_title} ({c_status})")
            lines.append("")

        if revoked:
            lines.append(f"📝 **曾註銷之拒絕往來案（共 {len(revoked)} 筆）：**")
            for r in revoked[:2]:
                r_unit = r.get("unit_name", "")
                r_title = r.get("title", "")
                lines.append(f"  • {r_unit} - {r_title}")
            lines.append("")

        lines.append(f"🔗 [點此查看 ToBid 官方詳細法規合規與停權履歷]({web_link})")
        lines.append("*(資料來源：行政院公共工程委員會政府採購網黑名單與申訴審議公開資訊)*")

        return "\n".join(lines)

    result_text = _single_flight.run(cache_key, _fetch_compliance)
    if not result_text.startswith("⚠️"):
        _compliance_cache.set(cache_key, result_text)
    return result_text


@tool
def get_company_winning_tenders(ticker_or_company: str, limit: int = 5) -> str:
    """查詢特定台灣上市櫃公司實際得標的政府公標案明細清單（包含標案名稱、招標機關、標案案號、決標金額、預算金額、決標日期與 ToBid 案件連結）。
    
    當使用者明確詢問「某公司最近拿到什麼政府標案？」、「列出得標標案明細」或「查詢特定公司的得標標案」時調用。

    Args:
        ticker_or_company: 台灣股票代號 (例: 2634, 6214, 9933) 或公司簡稱/全稱 (例: 漢翔, 精誠資訊, 中鼎)。
        limit: 欲取得的得標標案筆數 (預設 5 筆，範圍 1~10)。
    """
    company_name = resolve_company_name(ticker_or_company)
    clamped_limit = max(1, min(int(limit), 10))
    cache_key = f"winning_tenders:{company_name}:{clamped_limit}"

    cached = _tender_cache.get(cache_key)
    if cached:
        return cached

    def _fetch_winning() -> str:
        data = _call_tobid_mcp("search_tenders", {"vendor": company_name, "kind": "award"}, timeout=12)
        raw_data = None
        if not data or not isinstance(data, dict) or data.get("total", 0) == 0:
            # Fallback to search by keyword, but strictly verify that company name appears in winners
            search_kw = company_name.replace("股份有限公司", "").replace("科技", "").replace("工業", "").strip()[:4]
            raw_data = _call_tobid_mcp("search_tenders", {"q": search_kw, "kind": "award"}, timeout=10)
            if raw_data and isinstance(raw_data, dict):
                filtered_results = [
                    r for r in raw_data.get("results", [])
                    if any(company_name in w or search_kw in w for w in r.get("winners", []))
                ]
                if filtered_results:
                    data = {"total": len(filtered_results), "results": filtered_results}

        if data is None and raw_data is None:
            return f"⚠️ 目前查詢【{company_name}】政府得標標案清單時連線逾時或上游暫時無法取得數據，請稍後再試。"

        if not data or not isinstance(data, dict) or data.get("total", 0) == 0:
            return f"ℹ️ 查無【{company_name}】的公開政府得標案件紀錄。該公司可能近期無新決標標案，或以其他特許子公司名義投標。"

        total = data.get("total", 0)
        results = data.get("results", [])
        lines = [
            f"📜 **【{company_name}】最新政府得標標案清單（資料庫共收錄 {total:,} 筆）**",
            "",
        ]

        for idx, r in enumerate(results[:clamped_limit], 1):
            title = r.get("title", "未命名標案")
            unit = r.get("unit_name", "未知機關")
            unit_id = r.get("unit_id", "")
            job_number = r.get("job_number", "")
            budget = _format_currency(r.get("budget", 0))
            award_amt = _format_currency(r.get("award_amount", 0))
            date_val = str(r.get("date", ""))
            if len(date_val) == 8:
                date_str = f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:]}"
            else:
                date_str = date_val or "近期"

            case_url = f"https://tobid.tw/?case={unit_id}|{job_number}" if (unit_id and job_number) else f"https://tobid.tw/?vendor={company_name}"
            winners = r.get("winners", [])
            winner_str = "、".join([w.split(" (")[0] for w in winners[:2]]) if winners else company_name

            lines.append(f"{idx}. **[{title}]({case_url})**")
            lines.append(f"   • 發包機關：`{unit}`")
            lines.append(f"   • 標案案號：`{job_number}` | 決標日期：`{date_str}`")
            lines.append(f"   • 決標金額：**{award_amt}**（招標預算：{budget}）")
            lines.append(f"   • 得標廠商：{winner_str}")
            lines.append("")

        lines.append(f"🔗 [前往 ToBid 查看更多【{company_name}】歷年得標標案](https://tobid.tw/?vendor={company_name})")
        lines.append("*(數據來源：行政院公共工程委員會政府電子採購網，由 ToBid 即時分析引擎驅動)*")
        return "\n".join(lines)

    result_text = _single_flight.run(cache_key, _fetch_winning)
    if not result_text.startswith("⚠️"):
        _tender_cache.set(cache_key, result_text)
    return result_text
