"""Taiwan Government Procurement Tenders & Compliance Intelligence Tool.

Interfaces with ToBid Government Procurement platform (https://tobid.tw / https://api.tobid.tw)
to track listed companies' public tender awards, client distribution, win rates, competitor rankings,
reserve margin pricing profiles, and Article 101 debarment / blacklist risk assessments.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.parse
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

REST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://tobid.tw/",
    "Origin": "https://tobid.tw",
    "Accept": "application/json",
}

# Cache configurations
_tender_cache = TTLCache(default_ttl=3600.0, max_size=200)       # 1 hour TTL
_compliance_cache = TTLCache(default_ttl=7200.0, max_size=200)   # 2 hours TTL
_entity_cache = TTLCache(default_ttl=86400.0, max_size=500)      # 24 hours TTL
_unit_cache = TTLCache(default_ttl=7200.0, max_size=200)        # 2 hours TTL
_compare_cache = TTLCache(default_ttl=3600.0, max_size=200)     # 1 hour TTL
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
    "3703": "大陸工程股份有限公司",  # 欣陸投控核心公標案營造旗艦
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


TW_STOCK_ALIASES: Dict[str, str] = {
    # 航太軍工
    "漢翔": "漢翔航空工業股份有限公司",
    "亞航": "亞洲航空股份有限公司",
    "長榮航太": "長榮航太科技股份有限公司",
    "龍德": "龍德造船工業股份有限公司",
    "龍德造船": "龍德造船工業股份有限公司",
    "雷虎": "雷虎科技股份有限公司",
    "雷虎科技": "雷虎科技股份有限公司",
    "全訊": "全訊科技股份有限公司",
    "全訊科技": "全訊科技股份有限公司",
    # 營造與水資源公共工程
    "中鼎": "中鼎工程股份有限公司",
    "工信": "工信工程股份有限公司",
    "欣陸": "大陸工程股份有限公司",
    "欣陸投控": "大陸工程股份有限公司",
    "大陸工程": "大陸工程股份有限公司",
    "欣達環工": "欣達環工股份有限公司",
    "山林水": "山林水環境工程股份有限公司",
    "國統": "國統國際股份有限公司",
    "國統國際": "國統國際股份有限公司",
    "中聯資": "中聯資源股份有限公司",
    "中工": "中華工程股份有限公司",
    # 重電與綠能
    "華城": "華城電機股份有限公司",
    "士電": "士林電機廠股份有限公司",
    "中興電": "中興電工機械股份有限公司",
    "亞力": "亞力電機股份有限公司",
    "大同": "大同股份有限公司",
    "雲豹": "雲豹能源科技股份有限公司",
    "雲豹能源": "雲豹能源科技股份有限公司",
    "泓德": "泓德能源科技股份有限公司",
    "泓德能源": "泓德能源科技股份有限公司",
    "森崴": "森崴能源股份有限公司",
    "森崴能源": "森崴能源股份有限公司",
    # 資訊軟服與資安
    "精誠": "精誠資訊股份有限公司",
    "精誠資訊": "精誠資訊股份有限公司",
    "零壹": "零壹科技股份有限公司",
    "邁達特": "邁達特數位股份有限公司",
    "凌群": "凌群電腦股份有限公司",
    "安碁": "安碁資訊股份有限公司",
    "安碁資訊": "安碁資訊股份有限公司",
    "宏碁資訊": "宏碁資訊服務股份有限公司",
    "叡揚": "叡揚資訊股份有限公司",
    # 電信
    "中華電": "中華電信股份有限公司",
    "中華電信": "中華電信股份有限公司",
    "台哥大": "台灣大哥大股份有限公司",
    "遠傳": "遠傳電信股份有限公司",
}


def resolve_company_name(query: str) -> str:
    """Resolve stock ticker or partial name to standard company legal name."""
    clean_q = query.strip()
    if clean_q in TW_STOCK_ALIASES:
        return TW_STOCK_ALIASES[clean_q]

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


def _fetch_vendor_full_profile(company_name: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
    """Fetch complete vendor intelligence profile with REST primary and MCP fallback."""
    # 1. Try ToBid REST API endpoint
    try:
        url = "https://api.tobid.tw/api/vendor_report?name=" + urllib.parse.quote(company_name)
        req = urllib.request.Request(url, headers=REST_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, dict) and ("participations" in data or "wins" in data):
                return _normalize_vendor_data(data, company_name)
    except Exception as e:
        logger.debug(f"ToBid REST vendor_report failed for {company_name}: {e}, falling back to MCP")

    # 2. Fallback to MCP JSON-RPC
    mcp_data = _call_tobid_mcp("vendor_report", {"name": company_name}, timeout=timeout)
    if mcp_data and isinstance(mcp_data, dict) and ("participations" in mcp_data or "wins" in mcp_data):
        return _normalize_vendor_data(mcp_data, company_name)

    return None


def _normalize_vendor_data(d: Dict[str, Any], fallback_name: str) -> Dict[str, Any]:
    """Normalize REST and MCP vendor report responses into a unified structure."""
    name = d.get("name", fallback_name)
    tax_id = d.get("vid") or d.get("tax_id", "-")
    participations = d.get("participations", 0)
    wins = d.get("wins", 0)
    win_rate_pct = d.get("win_rate") if d.get("win_rate") is not None else d.get("win_rate_pct", 0.0)
    known_award_total = d.get("amount_sum") if d.get("amount_sum") is not None else d.get("known_award_total", 0)
    sole_bid_rate_pct = d.get("sole_rate") if d.get("sole_rate") is not None else d.get("sole_bid_rate_pct", 0.0)

    # Categories
    categories = []
    if "cats" in d and isinstance(d["cats"], list):
        for c in d["cats"]:
            if isinstance(c, list) and len(c) >= 2:
                categories.append({"category": str(c[0]), "count": int(c[1])})
    elif "main_categories" in d and isinstance(d["main_categories"], list):
        for c in d["main_categories"]:
            if isinstance(c, dict):
                categories.append({"category": c.get("category", ""), "count": c.get("n", 0)})

    # Top client agencies
    clients = []
    raw_clients = d.get("top_clients") or d.get("units", [])
    for c in raw_clients:
        if isinstance(c, dict):
            unit = c.get("unit_name") or c.get("unit", "未知機關")
            c_wins = c.get("wins", 0)
            c_amt = c.get("amount", 0)
            c_share = c.get("share", 0.0)
            clients.append({"unit": unit, "wins": c_wins, "amount": c_amt, "share": c_share})

    # Competitor rivals
    rivals = []
    raw_rivals = d.get("rivals") or d.get("top_rivals", [])
    for r in raw_rivals:
        if isinstance(r, dict):
            r_name = r.get("name", "同場對手")
            met = r.get("met", 0)
            my_w = r.get("my_wins") if r.get("my_wins") is not None else r.get("this_vendor_wins", 0)
            their_w = r.get("their_wins") if r.get("their_wins") is not None else r.get("rival_wins", 0)
            rate = r.get("win_rate_vs")
            if rate is None:
                total_w = my_w + their_w
                rate = round((my_w / total_w) * 100, 1) if total_w > 0 else 0.0
            rivals.append({
                "name": r_name,
                "met": met,
                "my_wins": my_w,
                "their_wins": their_w,
                "win_rate_vs": rate,
            })

    # Reserve price profile
    reserve_list = []
    if "reserve" in d and isinstance(d["reserve"], dict):
        for w in d["reserve"].get("ways", []):
            if isinstance(w, dict):
                reserve_list.append({
                    "way": w.get("way", "最低標"),
                    "n": w.get("n", 0),
                    "r_ba": w.get("r_ba", 0.0),
                    "r_ba_p25": w.get("r_ba_p25", 0.0),
                    "r_ab": w.get("r_ab", 0.0),
                    "r_ab_p25": w.get("r_ab_p25", 0.0),
                    "r_pb": w.get("r_pb", 0.0),
                    "r_pb_p25": w.get("r_pb_p25", 0.0),
                })
    elif "reserve_profile" in d and isinstance(d["reserve_profile"], dict):
        for w in d["reserve_profile"].get("by_award_method", []):
            if isinstance(w, dict):
                reserve_list.append({
                    "way": w.get("award_method", "最低標"),
                    "n": w.get("n", 0),
                    "r_ba": w.get("reserve_of_budget_pct", 0.0),
                    "r_ba_p25": 0.0,
                    "r_ab": w.get("award_of_reserve_pct", 0.0),
                    "r_ab_p25": 0.0,
                    "r_pb": w.get("award_of_budget_pct", 0.0),
                    "r_pb_p25": 0.0,
                })

    # Main products / terms
    products = []
    prod_data = d.get("products") or d.get("main_products", {})
    if isinstance(prod_data, dict):
        for t in prod_data.get("terms", []):
            if isinstance(t, dict) and "term" in t:
                products.append({"term": t.get("term", ""), "cases": t.get("cases", 0)})

    # Recent losses (deduplicate by title)
    losses = []
    seen_loss_titles = set()
    raw_losses = d.get("lost_recent") or d.get("recent_losses", [])
    for l in raw_losses:
        if isinstance(l, dict):
            l_title = l.get("title", "未命名標案")
            if l_title in seen_loss_titles:
                continue
            seen_loss_titles.add(l_title)
            amt = l.get("award_amount") or l.get("amount", 0)
            losses.append({
                "date": l.get("date"),
                "title": l_title,
                "unit": l.get("unit_name", ""),
                "winner": l.get("winner") or l.get("lost_to", "其他廠商"),
                "award_amount": amt,
                "amount": amt,
                "my_bid": l.get("my_bid") or l.get("its_bid"),
                "winning_bid": l.get("win_bid") or l.get("winning_bid"),
                "reason": l.get("reason") or l.get("lost_reason", "非得標廠商"),
            })

    return {
        "name": name,
        "tax_id": tax_id,
        "participations": participations,
        "wins": wins,
        "win_rate_pct": float(win_rate_pct),
        "known_award_total": known_award_total,
        "sole_bid_rate_pct": float(sole_bid_rate_pct),
        "categories": categories,
        "clients": clients,
        "rivals": rivals,
        "reserve": reserve_list,
        "products": products,
        "losses": losses,
        "web": f"https://tobid.tw/?vendor={name}",
    }


@tool
def get_company_procurement_rivals(ticker_or_company: str, limit: int = 12) -> str:
    """查詢特定台灣上市櫃公司在政府公標案上的「同場競爭對手排行榜」、交手紀錄、勝負次數、相對勝率 (%) 與近期落標案件。

    當使用者詢問「某公司在標案上主要競爭對手是誰？」、「誰常跟某公司搶標？」、「某公司常輸給誰？」或「競爭對手清單與勝率」時調用。

    Args:
        ticker_or_company: 台灣股票代號 (例: 2634, 6214, 9933) 或公司簡稱/全稱 (例: 漢翔, 精誠, 中鼎)。
        limit: 欲取得的競爭對手數量 (預設 12 家，範圍 3~20)。
    """
    company_name = resolve_company_name(ticker_or_company)
    clamped_limit = max(3, min(int(limit), 20))
    cache_key = f"rivals:{company_name}:{clamped_limit}"

    cached = _tender_cache.get(cache_key)
    if cached:
        return cached

    def _fetch_rivals() -> str:
        data = _fetch_vendor_full_profile(company_name, timeout=15)
        if not data:
            return f"⚠️ 目前查詢【{company_name}】公標案競爭對手情報時連線逾時或暫時無法取得數據，請稍後再試。"

        name = data.get("name", company_name)
        rivals = data.get("rivals", [])
        losses = data.get("losses", [])
        web_link = data.get("web", f"https://tobid.tw/?vendor={name}")

        if not rivals:
            return f"ℹ️ 查無【{name}】在政府採購網的同場競爭對手紀錄。該公司投標案件可能多為單一投標獨得，或以特許轉投資名義投標。"

        lines = [
            f"⚔️ **【{name}】政府公標案同場主要競爭對手排行榜**",
            "*(統計說明：相對勝率 = 雙方同時投標該案時，本公司獲勝的比例。低於 35% 代表面對該對手多半輸)*",
            "",
            "| 排名 | 同場競爭對手名稱 | 交手次數 | 本公司獲勝 | 對手獲勝 | 相對勝率 | 競爭戰力評估 |",
            "| :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
        ]

        for idx, r in enumerate(rivals[:clamped_limit], 1):
            r_name = r.get("name", "同場對手")
            met = r.get("met", 0)
            my_w = r.get("my_wins", 0)
            their_w = r.get("their_wins", 0)
            rate = r.get("win_rate_vs", 0.0)

            if rate < 35.0:
                eval_tag = "🔴 遭遇強敵 (多半輸)"
            elif rate <= 65.0:
                eval_tag = "🟡 勢均力敵 (五五波)"
            else:
                eval_tag = "🟢 絕對優勢 (多半贏)"

            lines.append(f"| {idx} | **{r_name}** | `{met}` 次 | `{my_w}` 勝 | `{their_w}` 勝 | **{rate:.1f}%** | {eval_tag} |")

        lines.append("")

        # Recent lost tenders breakdown
        if losses:
            lines.append("🚨 **近期落標（未得標）案件與競爭者搶標明細：**")
            for l in losses[:5]:
                title = l.get("title", "未命名標案")
                winner = l.get("winner", "未知得標廠商")
                unit = l.get("unit", "")
                date_val = str(l.get("date", ""))
                date_str = f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:]}" if len(date_val) == 8 else (date_val or "近期")
                amt_str = _format_currency(l.get("amount", 0))
                reason = l.get("reason", "未得標")
                my_bid = _format_currency(l.get("my_bid")) if l.get("my_bid") else "未公開"
                win_bid = _format_currency(l.get("winning_bid")) if l.get("winning_bid") else "未公開"

                unit_txt = f" ({unit})" if unit else ""
                lines.append(f"• **{title}**{unit_txt} - `{date_str}`")
                lines.append(f"  - 得標對手：**{winner}**（得標價：`{win_bid}` vs 本公司報價：`{my_bid}`）")
                lines.append(f"  - 決標金額：{amt_str} | 落標原因：*{reason}*")
            lines.append("")

        lines.append(f"🔗 [前往 ToBid 查看【{name}】完整標案對手與交手紀錄]({web_link})")
        lines.append("*(數據來源：行政院公共工程委員會政府電子採購網，由 ToBid 即時分析引擎驅動)*")
        return "\n".join(lines)

    result_text = _single_flight.run(cache_key, _fetch_rivals)
    if not result_text.startswith("⚠️"):
        _tender_cache.set(cache_key, result_text)
    return result_text


@tool
def get_company_government_tenders(ticker_or_company: str) -> str:
    """查詢台灣上市櫃公司的政府公標案完整得標戰報、歷史勝率、累計決標金額、主要客戶機關排行榜、承接類別、底價落點與議價空間分析。

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
        data = _fetch_vendor_full_profile(company_name, timeout=15)
        if not data:
            stale = _tender_cache.get_stale(cache_key)
            if stale:
                return stale + "\n\n*(⚠️ 目前 ToBid 上游回應延遲，此為快取歷史資料)*"
            # Fallback to raw awards search if vendor profile is temporarily unavailable
            raw_awards = _call_tobid_mcp("search_tenders", {"vendor": company_name, "kind": "award"}, timeout=10)
            if raw_awards and isinstance(raw_awards, dict) and raw_awards.get("results"):
                res_list = raw_awards.get("results", [])
                lines = [
                    f"🏛️ **【{company_name}】政府公標案資料（基本模式）**",
                    "*(⚠️ 目前廠商綜合統計資料庫暫時無完整戰報，改為顯示近期已決標標案清單)*",
                    "",
                ]
                for idx, r in enumerate(res_list[:5], 1):
                    title = r.get("title", "未命名標案")
                    unit = r.get("unit_name", "")
                    amt = _format_currency(r.get("award_amount", 0))
                    lines.append(f"• **{title}** ({unit}) - 決標金額：`{amt}`")
                lines.append("")
                lines.append(f"🔗 [點此查看 ToBid 完整標案明細](https://tobid.tw/?vendor={company_name})")
                return "\n".join(lines)
            return f"⚠️ 目前查詢【{company_name}】政府公標案戰報時連線逾時或暫時無法取得數據，請稍後再試。"

        name = data.get("name", company_name)
        tax_id = data.get("tax_id", "-")
        participations = data.get("participations", 0)
        wins = data.get("wins", 0)
        win_rate_pct = data.get("win_rate_pct", 0.0)
        known_award_total = data.get("known_award_total", 0)
        sole_bid_rate_pct = data.get("sole_bid_rate_pct", 0.0)
        web_link = data.get("web", f"https://tobid.tw/?vendor={name}")

        lines = [
            f"🏛️ **【{name}】政府公標案綜合得標戰報**",
            f"• 統一編號：`{tax_id}`",
            f"• 歷史投標次數：`{participations:,}` 次",
            f"• 累計得標次數：`{wins:,}` 次（得標率 **{win_rate_pct:.1f}%**）",
            f"• 單一投標獨得率：`{sole_bid_rate_pct:.1f}%` *(無其他對手競標直接拿下比例)*",
            f"• 歷史已知決標總額：**{_format_currency(known_award_total)}**",
            "",
        ]

        # Categories
        categories = data.get("categories", [])
        if categories:
            cat_strs = [f"`{c['category']}` {c['count']} 件" for c in categories]
            lines.append(f"📦 **承接標案類別：** " + " · ".join(cat_strs))
            lines.append("")

        # Core Products / Keywords
        products = data.get("products", [])
        if products:
            top_prods = [f"`{p['term']}` ({p['cases']}件)" for p in products[:8]]
            lines.append(f"🔧 **主力承接業務關鍵字：** " + " · ".join(top_prods))
            lines.append("")

        # Reserve Price Profile
        reserve = data.get("reserve", [])
        if reserve:
            lines.append("🎯 **得標時的底價落點與議價空間分析：**")
            for res_item in reserve[:2]:
                way = res_item.get("way", "最低標")
                n_cases = res_item.get("n", 0)
                r_ab = res_item.get("r_ab", 0.0)
                r_ba = res_item.get("r_ba", 0.0)
                r_pb = res_item.get("r_pb", 0.0)
                lines.append(f"  • **{way}**（共統計 {n_cases:,} 件已決標案實際底價）：")
                lines.append(f"    - 決標占底價：**{r_ab:.1f}%**（底價占預算：{r_ba:.1f}%，決標占預算：{r_pb:.1f}%）")
                if r_ab >= 98.0:
                    lines.append("    - *議價分析：決標價極度貼近底價，幾乎照底價拿下，機關議價空間極小。*")
                elif r_ab >= 90.0:
                    lines.append("    - *議價分析：決標價約落在底價 9 成以上，報價具競爭力但保有合理利潤空間。*")
            lines.append("")

        # Top client agencies (Top 8)
        clients = data.get("clients", [])
        if clients:
            lines.append("🏢 **主要發包政府客戶機關排行榜：**")
            for idx, c in enumerate(clients[:8], 1):
                c_unit = c.get("unit", "未知機關")
                c_wins = c.get("wins", 0)
                c_amt = _format_currency(c.get("amount", 0))
                c_share = c.get("share", 0.0)
                share_str = f"（佔比 `{c_share:.1f}%`）" if c_share > 0 else ""
                lines.append(f"  {idx}. **{c_unit}**：得標 `{c_wins}` 次{share_str}，累計金額 **{c_amt}**")
            lines.append("")

        # Top rivals summary
        rivals = data.get("rivals", [])
        if rivals:
            lines.append("⚔️ **主要公標案同場對手與勝率（Top 5）：**")
            for r in rivals[:5]:
                r_name = r.get("name", "同場對手")
                met = r.get("met", 0)
                my_w = r.get("my_wins", 0)
                their_w = r.get("their_wins", 0)
                rate = r.get("win_rate_vs", 0.0)
                tag = "🔴 弱勢" if rate < 35 else ("🟡 均勢" if rate <= 65 else "🟢 優勢")
                lines.append(f"  • **{r_name}**：交手 `{met}` 次（本公司 `{my_w}` 勝 vs 對手 `{their_w}` 勝，勝率 **{rate:.1f}%** 【{tag}】）")
            lines.append("  *(欲查看完整 15 家競爭對手與近期搶標明細，請詢問「競爭對手」)*")
            lines.append("")

        # Recent Losses
        losses = data.get("losses", [])
        if losses:
            lines.append("🚨 **近期落標提醒：**")
            for l in losses[:2]:
                title = l.get("title", "")
                winner = l.get("winner", "")
                amt = _format_currency(l.get("amount", 0))
                lines.append(f"  • *{title}*：輸給 `{winner}`（決標金額：{amt}）")
            lines.append("")

        # Recent Major Awards
        recent_cases = _call_tobid_mcp("search_tenders", {"vendor": company_name, "kind": "award"}, timeout=10)
        if recent_cases and isinstance(recent_cases, dict):
            results = recent_cases.get("results", [])
            if results:
                lines.append(f"📜 **近期代表性決標標案：**")
                for r in results[:3]:
                    title = r.get("title", "未命名標案")
                    unit = r.get("unit_name", "")
                    unit_id = r.get("unit_id", "")
                    job_number = r.get("job_number", "")
                    award_amt = _format_currency(r.get("award_amount", 0))
                    date_val = str(r.get("date", ""))
                    date_str = f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:]}" if len(date_val) == 8 else date_val
                    case_url = f"https://tobid.tw/?case={unit_id}|{job_number}" if (unit_id and job_number) else web_link
                    lines.append(f"  • [{title}]({case_url})")
                    lines.append(f"    - 機關：{unit} | 案號：`{job_number}` | 決標：**{award_amt}** ({date_str})")
                lines.append("")

        lines.append(f"🔗 [點此查看 ToBid 完整標案明細與歷程]({web_link})")
        lines.append("*(數據來源：行政院公共工程委員會政府電子採購網，由 ToBid 即時分析引擎驅動)*")
        return "\n".join(lines)

    result_text = _single_flight.run(cache_key, _fetch_report)
    if not result_text.startswith("⚠️"):
        _tender_cache.set(cache_key, result_text)
    return result_text


@tool
def compare_procurement_vendors(company_a: str, company_b: str) -> str:
    """比對兩家廠商或上市櫃公司在政府公標案上的「同場對戰紀錄」（交手次數、各自勝場次數、勝率比較與強弱評價）。

    當使用者詢問「A 跟 B 誰在標案上比較強？」、「比對漢翔與亞航的標案勝負」或「中鼎跟工信誰得標比較多」時調用。

    Args:
        company_a: 第一家公司股票代號或名稱 (例: 漢翔 或 2634)。
        company_b: 第二家公司股票代號或名稱 (例: 亞航 或 2630)。
    """
    name_a = resolve_company_name(company_a)
    name_b = resolve_company_name(company_b)

    cache_key = f"compare:{name_a}:{name_b}"
    cached = _compare_cache.get(cache_key)
    if cached:
        return cached

    def _fetch_compare() -> str:
        data = _call_tobid_mcp("compare_vendors", {"vendor_a": name_a, "vendor_b": name_b}, timeout=12)
        if not data or not isinstance(data, dict):
            return f"⚠️ 目前比對【{name_a}】與【{name_b}】的公標案對戰紀錄時連線逾時或暫時無法取得數據，請稍後再試。"

        met = data.get("met", 0)
        a_wins = data.get("a_wins", 0)
        b_wins = data.get("b_wins", 0)

        lines = [
            f"🥊 **【{name_a}】vs【{name_b}】政府公標案同場對戰分析**",
            "",
            f"• **雙方同場競標交手總次數**：`{met:,}` 次",
            f"• **【{name_a}】得標勝場**：`{a_wins:,}` 勝",
            f"• **【{name_b}】得標勝場**：`{b_wins:,}` 勝",
            "",
        ]

        if met == 0:
            lines.append("ℹ️ **對決分析**：這兩家廠商在歷史政府採購案件中**尚未有同場直接競標交手**的公開紀錄，雙方主力業務領域或目標招標機關可能有顯著區隔。")
        else:
            total_awarded_wins = a_wins + b_wins
            if total_awarded_wins > 0:
                win_rate_a = (a_wins / total_awarded_wins) * 100
                win_rate_b = (b_wins / total_awarded_wins) * 100
                lines.append(f"• **相對勝率對比**：`{name_a}` **{win_rate_a:.1f}%** vs `{name_b}` **{win_rate_b:.1f}%**")
            else:
                lines.append("• **勝負統計**：同場競標中雙方皆尚未取得決標勝場（可能由第三方獲勝或案件流標）。")
            lines.append("")
            if a_wins > b_wins:
                lead = a_wins - b_wins
                lines.append(f"🏆 **戰力評價**：【{name_a}】在同場對決中佔據明顯上風，領先對手 `{lead}` 場勝仗！")
            elif b_wins > a_wins:
                lead = b_wins - a_wins
                lines.append(f"🏆 **戰力評價**：【{name_b}】在同場對決中佔據明顯上風，領先對手 `{lead}` 場勝仗！")
            else:
                lines.append("⚖️ **戰力評價**：雙方旗鼓相當，同場勝場數完全平手！")

        lines.append("")
        lines.append(f"🔗 [前往 ToBid 查看【{name_a}】標案頁面](https://tobid.tw/?vendor={name_a}) · [查看【{name_b}】](https://tobid.tw/?vendor={name_b})")
        lines.append("*(數據來源：行政院公共工程委員會政府電子採購網，由 ToBid 即時分析引擎驅動)*")
        return "\n".join(lines)

    result_text = _single_flight.run(cache_key, _fetch_compare)
    if not result_text.startswith("⚠️"):
        _compare_cache.set(cache_key, result_text)
    return result_text


@tool
def get_procurement_unit_report(unit_name: str) -> str:
    """查詢台灣政府發包機關（如空軍司令部、台電、中油、鐵道局等）的採購情報、年度發包規模、流標率與主要得標承包廠商排行榜。

    當使用者詢問「某機關每年發包多少金額？」、「某公營單位的主要承包商有哪些？」或「某機關標案競爭程度」時調用。

    Args:
        unit_name: 發包機關名稱或代號 (例: 國防部空軍司令部, 台灣電力公司, 交通部鐵道局)。
    """
    clean_unit = unit_name.strip()
    cache_key = f"unit:{clean_unit}"

    cached = _unit_cache.get(cache_key)
    if cached:
        return cached

    def _fetch_unit() -> str:
        data = _call_tobid_mcp("unit_report", {"unit": clean_unit}, timeout=12)
        if not data or not isinstance(data, dict) or "unit_name" not in data:
            return f"⚠️ 查無發包機關【{clean_unit}】的採購情報，或上游暫時無法取得數據。請確認機關全名（例如：台灣電力公司股份有限公司、國防部空軍司令部）。"

        name = data.get("unit_name", clean_unit)
        unit_id = data.get("unit_id", "")
        total_notices = data.get("total_notices", 0)
        fail_rate_pct = data.get("fail_rate_pct", 0.0)
        avg_bidders = data.get("avg_bidders", 0.0)
        sole_bid_rate_pct = data.get("sole_bid_rate_pct", 0.0)
        top5_vendor_share_pct = data.get("top5_vendor_share_pct", 0.0)
        known_award_total = data.get("known_award_total", 0)
        web_link = data.get("web", f"https://tobid.tw/?unit={unit_id}")

        lines = [
            f"🏛️ **【{name}】政府採購發包機關情報報告**",
            f"• 歷史招標公告總數：`{total_notices:,}` 筆",
            f"• 歷史已知決標總額：**{_format_currency(known_award_total)}**",
            f"• 平均每案投標家數：`{avg_bidders:.2f}` 家",
            f"• 機關流標率：`{fail_rate_pct:.1f}%`",
            f"• 單一投標率：`{sole_bid_rate_pct:.1f}%` *(僅一家廠商前來投標即決標之比例)*",
            f"• 前 5 大供應商集中度：`{top5_vendor_share_pct:.1f}%`",
            "",
        ]

        # Top vendors
        top_vendors = data.get("top_vendors", [])
        if top_vendors:
            lines.append("🏆 **該機關主要得標承包廠商排行榜：**")
            for idx, v in enumerate(top_vendors[:8], 1):
                v_name = v.get("name", "得標廠商")
                wins = v.get("wins", 0)
                amount = _format_currency(v.get("amount", 0))
                lines.append(f"  {idx}. **{v_name}**：得標 `{wins}` 次，累計決標金額 **{amount}**")
            lines.append("")

        peak_months = data.get("peak_months", [])
        if peak_months:
            months_str = "、".join([f"{m}月" for m in peak_months])
            lines.append(f"📅 **歷史發案旺季月份：** `{months_str}`")
            lines.append("")

        lines.append(f"🔗 [前往 ToBid 查看【{name}】機關完整招標歷程與標案]({web_link})")
        lines.append("*(數據來源：行政院公共工程委員會政府電子採購網，由 ToBid 即時分析引擎驅動)*")
        return "\n".join(lines)

    result_text = _single_flight.run(cache_key, _fetch_unit)
    if not result_text.startswith("⚠️"):
        _unit_cache.set(cache_key, result_text)
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
            lines.append("⚠️ **【無法確認停權狀態】資料庫未明確標記停權狀態，建議點選下方連結進一步至公共工程委員會政府採購網查核。**")
            lines.append("")

        if debarments:
            lines.append(f"📋 **歷史停權紀錄（共 {len(debarments)} 筆）：**")
            for d in debarments[:3]:
                start_date = d.get("start_date")
                end_date = d.get("end_date")
                period = d.get("period")
                if period:
                    period_str = str(period)
                elif start_date and end_date:
                    period_str = f"{start_date} 至 {end_date}"
                elif start_date:
                    period_str = f"自 {start_date} 起"
                else:
                    period_str = "-"
                unit = d.get("unit_name") or d.get("unit", "未知機關")
                reason = d.get("reason", "採購法違規")
                lines.append(f"  • 機關：`{unit}` | 期間：`{period_str}` | 事由：{reason}")
            lines.append("")

        if article_101_cases:
            lines.append(f"⚖️ **採購法第 101 條爭議案件（共 {len(article_101_cases)} 筆）：**")
            for c in article_101_cases[:3]:
                title = c.get("title", "標案爭議")
                clause = c.get("clause", "101條")
                result = c.get("result") or c.get("status", "審議中/已結案")
                lines.append(f"  • 案件：{title} ({clause}) - 結果：`{result}`")
            lines.append("")

        if revoked:
            lines.append(f"↩️ **註銷停權／撤銷紀錄（共 {len(revoked)} 筆）：**")
            for r in revoked[:2]:
                title = r.get("title", "")
                unit = r.get("unit_name", "")
                lines.append(f"  • {title} ({unit})")
            lines.append("")

        lines.append(f"🔗 [點此查看 ToBid 官方詳細法規合規與停權履歷]({web_link})")
        lines.append("*(資料來源：行政院公共工程委員會政府採購網黑名單與申訴審議公開資訊)*")

        return "\n".join(lines)

    result_text = _single_flight.run(cache_key, _fetch_compliance)
    if not result_text.startswith("⚠️"):
        _compliance_cache.set(cache_key, result_text)
    return result_text


@tool
def search_government_procurement_tenders(
    query: str = "",
    unit: Optional[str] = None,
    kind: str = "all",
    limit: int = 5,
) -> str:
    """檢索台灣政府電子採購網的公開招標公告、已決標標案或近期採購預告。

    支援廣域搜尋與關鍵字探勘，例如：
    • 國防部近期公開招標標案有哪些？
    • 台灣電力公司有哪些發包採購案？
    • 關鍵字「無人機」、「變壓器」、「公共工程」相關標案搜尋。
    • 查詢特定機關或領域的未來採購預告 (procurement forecast)。

    Args:
        query: 標案搜尋關鍵字 (例: 無人機, 變壓器, 儲能系統, 航太, 雲端資安)。
        unit: 發包機關全稱或關鍵字 (例: 國防部, 國防部空軍司令部, 台灣電力公司, 中科院)。
        kind: 標案類別，可為 'tender' (正在公開招標/徵求中), 'award' (已決標), 'forecast' (未來採購預告), 'all' (預設綜合招標檢索)。
        limit: 欲回傳的標案數量 (預設 5 筆，範圍 1~10)。
    """
    clean_q = (query or "").strip()
    clean_unit = (unit or "").strip()
    clean_kind = (kind or "all").strip().lower()
    clamped_limit = max(1, min(int(limit), 10))

    cache_key = f"search:{clean_q}:{clean_unit}:{clean_kind}:{clamped_limit}"
    cached = _tender_cache.get(cache_key)
    if cached:
        return cached

    def _execute_search() -> str:
        # 1. If user specifically asks for forecast / 採購預告
        if clean_kind in ("forecast", "predict") or "預告" in clean_q:
            filter_q = clean_q.replace("採購預告", "").replace("預告", "").strip()
            args: Dict[str, Any] = {"limit": clamped_limit}
            if filter_q:
                args["q"] = filter_q
            if clean_unit:
                args["unit"] = clean_unit
            f_data = _call_tobid_mcp("procurement_forecast", args, timeout=12)
            f_failed = False
            if not f_data or not isinstance(f_data, dict) or (not f_data.get("items") and not filter_q):
                # Fallback to include past if empty or initial failed
                args["include_past"] = True
                f_data_past = _call_tobid_mcp("procurement_forecast", args, timeout=10)
                if f_data_past and isinstance(f_data_past, dict):
                    f_data = f_data_past
                elif f_data is None or not isinstance(f_data, dict):
                    f_failed = True

            if f_failed:
                stale = _tender_cache.get_stale(cache_key)
                if stale:
                    return stale + "\n\n*(⚠️ 目前 ToBid 上游回應延遲，此為快取歷史資料)*"
                return "⚠️ 查詢政府採購預告時連線逾時或上游暫時無法取得數據，請稍後再試。"

            items = f_data.get("items", []) if isinstance(f_data, dict) else []
            if items:
                lines = [
                    f"🔮 **【未來政府採購預告】情報清單（共取得 {len(items)} 筆預告）**",
                    "*(說明：採購預告為機關正式公開招標前提前公告之預算與時程規劃，通常早 1~3 個月公布)*",
                    "",
                ]
                for idx, item in enumerate(items[:clamped_limit], 1):
                    i_title = item.get("title", "未命名預告")
                    i_unit = item.get("unit_name", clean_unit or "政府機關")
                    i_month = item.get("tender_month", "預計近期")
                    i_budget = _format_currency(item.get("budget", 0))
                    i_way = item.get("tender_way", "未載明")
                    i_cat = item.get("category", "")
                    i_url = item.get("official_url") or "https://tobid.tw/"
                    lines.append(f"{idx}. **[{i_title}]({i_url})**")
                    lines.append(f"   • 發包機關：`{i_unit}`")
                    lines.append(f"   • 預計招標時程：`{i_month}` | 招標方式：`{i_way}`")
                    lines.append(f"   • 預估預算金額：**{i_budget}**" + (f" ({i_cat})" if i_cat else ""))
                    lines.append("")
                lines.append("🔗 [前往 ToBid 採購預告總覽平台](https://tobid.tw/)")
                return "\n".join(lines)
            # Never fall through to open tenders for a forecast request
            return f"ℹ️ 目前資料庫中查無符合條件【關鍵字：{filter_q or clean_q or '無'}，機關：{clean_unit or '無'}】的未來採購預告案件。"

        title_unit = f"【{clean_unit}】" if clean_unit else ""
        title_q = f"「{clean_q}」" if clean_q else ""

        # 2. Comprehensive 'all' search (includes both active tenders and awards)
        if clean_kind == "all":
            search_t_args: Dict[str, Any] = {"kind": "tender", "page": 1}
            search_a_args: Dict[str, Any] = {"kind": "award", "page": 1}
            if clean_q:
                search_t_args["q"] = clean_q
                search_a_args["q"] = clean_q
            if clean_unit:
                search_t_args["unit_name"] = clean_unit
                search_a_args["unit_name"] = clean_unit

            t_data = _call_tobid_mcp("search_tenders", search_t_args, timeout=10)
            a_data = _call_tobid_mcp("search_tenders", search_a_args, timeout=10)

            t_failed = t_data is None or not isinstance(t_data, dict)
            a_failed = a_data is None or not isinstance(a_data, dict)

            if t_failed and a_failed:
                stale = _tender_cache.get_stale(cache_key)
                if stale:
                    return stale + "\n\n*(⚠️ 目前 ToBid 上游回應延遲，此為快取歷史資料)*"
                return "⚠️ 檢索政府標案時連線逾時或上游暫時無法取得數據，請稍後再試。"

            t_results = t_data.get("results", []) if not t_failed else []
            a_results = a_data.get("results", []) if not a_failed else []
            t_total = t_data.get("total", len(t_results)) if not t_failed else 0
            a_total = a_data.get("total", len(a_results)) if not a_failed else 0

            if not t_results and not a_results:
                if t_failed or a_failed:
                    return f"⚠️ 檢索政府標案時部分上游服務回應異常【關鍵字：{clean_q or '不拘'}，機關：{clean_unit or '不拘'}】，暫無法取得完整標案。"
                return f"ℹ️ 查無符合條件的標案【關鍵字：{clean_q or '不拘'}，機關：{clean_unit or '不拘'}】。"

            partial_note = " *(決標數據暫時無法取得)*" if a_failed else (" *(招標數據暫時無法取得)*" if t_failed else "")
            lines = [
                f"📢 **{title_unit}{title_q}政府採購綜合標案情報（公開招標 {t_total:,} 筆、已決標 {a_total:,} 筆）**{partial_note}",
                "",
            ]

            # Allocate single result budget across categories to respect requested limit
            if t_results and a_results:
                t_limit = max(1, clamped_limit // 2)
                a_limit = max(0, clamped_limit - t_limit)
            elif t_results:
                t_limit = clamped_limit
                a_limit = 0
            else:
                t_limit = 0
                a_limit = clamped_limit

            if t_results and t_limit > 0:
                lines.append("📌 **公開招標公告（正在公告招標中）：**")
                for idx, r in enumerate(t_results[:t_limit], 1):
                    title = r.get("title", "未命名標案")
                    r_unit = r.get("unit_name", clean_unit or "政府機關")
                    unit_id = r.get("unit_id", "")
                    job_number = r.get("job_number", "")
                    budget = _format_currency(r.get("budget", 0))
                    deadline = r.get("deadline", "請洽公告")
                    tender_type = r.get("type", "招標公告")
                    case_url = f"https://tobid.tw/?case={unit_id}|{job_number}" if (unit_id and job_number) else "https://tobid.tw/"
                    lines.append(f"  {idx}. **[{title}]({case_url})**")
                    lines.append(f"     • 機關：`{r_unit}` | 預算：**{budget}** | 截標：`{deadline}` ({tender_type})")
                lines.append("")

            if a_results and a_limit > 0:
                lines.append("🏆 **近期代表性決標標案：**")
                for idx, r in enumerate(a_results[:a_limit], 1):
                    title = r.get("title", "未命名標案")
                    r_unit = r.get("unit_name", clean_unit or "政府機關")
                    unit_id = r.get("unit_id", "")
                    job_number = r.get("job_number", "")
                    award_amt = _format_currency(r.get("award_amount", 0))
                    winners = r.get("winners", [])
                    winner_str = "、".join([w.split(" (")[0] for w in winners[:2]]) if winners else "得標廠商"
                    date_val = str(r.get("date", ""))
                    date_str = f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:]}" if len(date_val) == 8 else (date_val or "近期")
                    case_url = f"https://tobid.tw/?case={unit_id}|{job_number}" if (unit_id and job_number) else "https://tobid.tw/"
                    lines.append(f"  {idx}. **[{title}]({case_url})**")
                    lines.append(f"     • 機關：`{r_unit}` | 決標：**{award_amt}** | 得標廠商：`{winner_str}` ({date_str})")
                lines.append("")

            lines.append("🔗 [前往 ToBid 搜尋平台查看更多標案明細](https://tobid.tw/)")
            lines.append("*(數據來源：行政院公共工程委員會政府電子採購網，由 ToBid 即時分析引擎驅動)*")
            return "\n".join(lines)

        # 3. Specific Tender or Award search
        t_kind = "award" if clean_kind == "award" else "tender"
        search_args: Dict[str, Any] = {"kind": t_kind, "page": 1}
        if clean_q:
            search_args["q"] = clean_q
        if clean_unit:
            search_args["unit_name"] = clean_unit

        data = _call_tobid_mcp("search_tenders", search_args, timeout=12)
        if not data or not isinstance(data, dict):
            stale = _tender_cache.get_stale(cache_key)
            if stale:
                return stale + "\n\n*(⚠️ 目前 ToBid 上游回應延遲，此為快取歷史資料)*"
            return "⚠️ 檢索政府標案時連線逾時或上游暫時無法取得數據，請稍後再試。"

        results = data.get("results", [])
        total = data.get("total", len(results))

        if not results:
            return f"ℹ️ 查無符合條件的標案【關鍵字：{clean_q or '不拘'}，機關：{clean_unit or '不拘'}，類別：{'已決標' if t_kind == 'award' else '招標中'}】。"

        kind_desc = "最新公開決標標案清單" if t_kind == "award" else "最新公開招標（正在公告招標中）標案清單"

        lines = [
            f"📢 **{title_unit}{title_q}政府採購{kind_desc}（符合條件共 {total:,} 筆）**",
            "",
        ]

        for idx, r in enumerate(results[:clamped_limit], 1):
            title = r.get("title", "未命名標案")
            r_unit = r.get("unit_name", clean_unit or "政府機關")
            unit_id = r.get("unit_id", "")
            job_number = r.get("job_number", "")
            budget = _format_currency(r.get("budget", 0))
            date_val = str(r.get("date", ""))
            date_str = f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:]}" if len(date_val) == 8 else (date_val or "近期")
            case_url = f"https://tobid.tw/?case={unit_id}|{job_number}" if (unit_id and job_number) else "https://tobid.tw/"

            if t_kind == "award":
                award_amt = _format_currency(r.get("award_amount", 0))
                winners = r.get("winners", [])
                winner_str = "、".join([w.split(" (")[0] for w in winners[:2]]) if winners else "得標廠商"
                lines.append(f"{idx}. **[{title}]({case_url})**")
                lines.append(f"   • 發包機關：`{r_unit}` | 案號：`{job_number}`")
                lines.append(f"   • 決標金額：**{award_amt}**（招標預算：{budget}）")
                lines.append(f"   • 得標廠商：**{winner_str}** | 決標日期：`{date_str}`")
            else:
                deadline = r.get("deadline", "請洽公告")
                tender_type = r.get("type", "招標公告")
                lines.append(f"{idx}. **[{title}]({case_url})**")
                lines.append(f"   • 發包機關：`{r_unit}` | 案號：`{job_number}`")
                lines.append(f"   • 招標方式：`{tender_type}` | 公告日期：`{date_str}`")
                lines.append(f"   • 招標預算：**{budget}** | 截標期限：`{deadline}`")
            lines.append("")

        lines.append("🔗 [前往 ToBid 搜尋平台查看更多標案明細](https://tobid.tw/)")
        lines.append("*(數據來源：行政院公共工程委員會政府電子採購網，由 ToBid 即時分析引擎驅動)*")
        return "\n".join(lines)

    result_text = _single_flight.run(cache_key, _execute_search)
    if not result_text.startswith("⚠️"):
        _tender_cache.set(cache_key, result_text)
    return result_text
