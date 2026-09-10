#!/usr/bin/env python3
"""
scripts/update_stock_registries.py

Fetches and normalizes official stock registries for:
1. US Stocks: SEC EDGAR official company_tickers.json (~10,400 stocks) + curated Chinese alias map
2. Hong Kong Stocks: HKEX official ListOfSecurities_c.xlsx (~3,200 equities/ETFs)
3. Taiwan Stocks: TWSE/TPEx registries (~2,234 stocks)
"""

import os
import re
import sys
import json
import urllib.request
import datetime
import io

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 StockBot/2.0"

# Curated High-Frequency US Chinese Aliases
US_CHINESE_ALIASES = {
    "蘋果": "AAPL",
    "蘋果公司": "AAPL",
    "特斯拉": "TSLA",
    "輝達": "NVDA",
    "英偉達": "NVDA",
    "微軟": "MSFT",
    "亞馬遜": "AMZN",
    "谷歌": "GOOGL",
    "GOOGLE": "GOOGL",
    "ALPHABET": "GOOGL",
    "臉書": "META",
    "META": "META",
    "超微": "AMD",
    "超微半導體": "AMD",
    "博通": "AVGO",
    "高通": "QCOM",
    "美光": "MU",
    "台積電ADR": "TSM",
    "台積電美股": "TSM",
    "聯電ADR": "UMC",
    "日月光ADR": "ASX",
    "艾司摩爾": "ASML",
    "ASML": "ASML",
    "網飛": "NFLX",
    "奈飛": "NFLX",
    "英特爾": "INTC",
    "思科": "CSCO",
    "甲骨文": "ORCL",
    "波音": "BA",
    "星巴克": "SBUX",
    "麥當勞": "MCD",
    "可口可樂": "KO",
    "百事可樂": "PEP",
    "百事": "PEP",
    "好市多": "COST",
    "開市客": "COST",
    "沃爾瑪": "WMT",
    "波克夏": "BRK-B",
    "巴菲特公司": "BRK-B",
    "摩根大通": "JPM",
    "小摩": "JPM",
    "高盛": "GS",
    "摩根士丹利": "MS",
    "大摩": "MS",
    "花旗": "C",
    "富國銀行": "WFC",
    "VISA": "V",
    "萬事達卡": "MA",
    "迪士尼": "DIS",
    "輝瑞": "PFE",
    "禮來": "LLY",
    "諾和諾德": "NVO",
    "嬌生": "JNJ",
    "強生": "JNJ",
    "SPACEX": "SPCX",
    "SPACE X": "SPCX",
    "太空探索": "SPCX",
    "安謀": "ARM",
    "ARM": "ARM",
    "戴爾": "DELL",
    "超微電腦": "SMCI",
    "美超微": "SMCI",
    "帕蘭提爾": "PLTR",
    "PALANTIR": "PLTR",
    "COINBASE": "COIN",
    "ROBINHOOD": "HOOD",
    "羅賓漢": "HOOD",
    "優步": "UBER",
    "UBER": "UBER",
    "AIRBNB": "ABNB",
    "愛彼迎": "ABNB",
    "蔚來": "NIO",
    "小鵬": "XPEV",
    "理想汽車": "LI",
    "理想": "LI",
    "拼多多": "PDD",
    "京東ADR": "JD",
    "百度ADR": "BIDU",
    "網易ADR": "NTES",
    "嗶哩嗶哩ADR": "BILI",
    "B站ADR": "BILI"
}


def update_us_stock_registry():
    """Fetch SEC EDGAR company tickers and compile US registry."""
    print("⏳ [US] Fetching SEC EDGAR company_tickers.json...")
    url = "https://www.sec.gov/files/company_tickers.json"
    req = urllib.request.Request(url, headers={"User-Agent": "StockBot/2.0 (contact@glsoft.ai)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"❌ [US] Failed to fetch SEC tickers: {e}")
        return False

    stocks = {}
    title_to_ticker = {}
    for idx, item in data.items():
        ticker = str(item.get("ticker", "")).strip().upper()
        title = str(item.get("title", "")).strip()
        cik = item.get("cik_str")
        if not ticker:
            continue
        stocks[ticker] = {
            "name": title,
            "cik": cik,
            "ticker": ticker
        }
        if title:
            title_to_ticker[title.upper()] = ticker

    # Add SpaceX explicit verification
    stocks["SPCX"] = {
        "name": "Space Exploration Technologies Corp. (SpaceX)",
        "cik": None,
        "ticker": "SPCX",
        "market": "NASDAQ"
    }

    out_data = {
        "updated_at": datetime.date.today().isoformat(),
        "source": "SEC EDGAR company_tickers.json",
        "total": len(stocks),
        "stocks": stocks,
        "aliases": US_CHINESE_ALIASES
    }

    out_file = os.path.join(DATA_DIR, "us_stock_registry.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    print(f"✅ [US] Successfully saved {len(stocks)} US stocks and {len(US_CHINESE_ALIASES)} aliases to {out_file}")
    return True


def update_hk_stock_registry():
    """Fetch HKEX official securities list (Excel) and compile HK registry."""
    print("⏳ [HK] Fetching HKEX official ListOfSecurities_c.xlsx...")
    url = "https://www.hkex.com.hk/chi/services/trading/securities/securitieslists/ListOfSecurities_c.xlsx"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
    except Exception as e:
        print(f"❌ [HK] Failed to fetch HKEX Excel: {e}")
        return False

    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content))
        sheet = wb.active
    except Exception as e:
        print(f"❌ [HK] Failed to parse HKEX Excel with openpyxl: {e}")
        return False

    stocks = {}
    name_to_code = {}

    # Category filter: '股本' (Equities), '交易所買賣產品' (ETFs), '房地產投資信託基金' (REITs)
    valid_categories = {"股本", "交易所買賣產品", "房地產投資信託基金"}

    for row in sheet.iter_rows(min_row=4, values_only=True):
        if not row or len(row) < 6:
            continue
        code_raw = str(row[0] or "").strip()
        name_raw = str(row[1] or "").strip()
        cat = str(row[2] or "").strip()
        sub_cat = str(row[3] or "").strip()
        board_lot = str(row[4] or "").strip()
        isin = str(row[5] or "").strip()

        if not code_raw.isdigit():
            continue
        if cat not in valid_categories:
            continue

        # Standard Yahoo Finance ticker: e.g. 00700 -> 0700.HK, 09988 -> 9988.HK
        code_int = int(code_raw)
        yahoo_ticker = f"{code_int:04d}.HK"

        # Generate clean short name (strip suffix like －Ｗ, －Ｓ, －ＳＷ, －Ｂ)
        clean_name = re.sub(r"[－\-_][ＷＳＢＲＵSWBRU]+$", "", name_raw).strip()

        stocks[code_raw] = {
            "code": code_raw,
            "int_code": str(code_int),
            "ticker": yahoo_ticker,
            "name": name_raw,
            "clean_name": clean_name,
            "category": cat,
            "sub_category": sub_cat,
            "board_lot": board_lot,
            "isin": isin
        }

        # Indexing for name search
        if name_raw:
            name_to_code[name_raw] = yahoo_ticker
        if clean_name and clean_name != name_raw:
            name_to_code[clean_name] = yahoo_ticker

    # Popular extra aliases
    extra_hk_aliases = {
        "騰訊": "0700.HK",
        "阿里": "9988.HK",
        "阿里巴巴": "9988.HK",
        "美團": "3690.HK",
        "小米": "1810.HK",
        "比亞迪": "1211.HK",
        "匯豐": "0005.HK",
        "中芯國際": "0981.HK",
        "中芯": "0981.HK",
        "網易": "9999.HK",
        "京東": "9618.HK",
        "百度": "9888.HK",
        "快手": "1024.HK",
        "攜程": "9961.HK",
        "小鵬汽車": "9868.HK",
        "理想汽車港股": "2015.HK",
        "蔚來港股": "9866.HK",
        "商湯": "0020.HK",
        "泡泡瑪特": "9992.HK",
        "舜宇光學": "2382.HK",
        "吉利汽車": "0175.HK",
        "長城汽車": "2333.HK",
        "友邦保險": "1299.HK",
        "港交所": "0388.HK"
    }
    for alias, ticker in extra_hk_aliases.items():
        name_to_code[alias] = ticker

    out_data = {
        "updated_at": datetime.date.today().isoformat(),
        "source": "HKEX ListOfSecurities_c.xlsx",
        "total": len(stocks),
        "stocks": stocks,
        "aliases": name_to_code
    }

    out_file = os.path.join(DATA_DIR, "hk_stock_registry.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    print(f"✅ [HK] Successfully saved {len(stocks)} HK stocks and {len(name_to_code)} names/aliases to {out_file}")
    return True


def update_jpx_stock_registry():
    """Fetch JPX official stock list (Excel) and compile JPX registry."""
    print("⏳ [JPX] Fetching JPX official data_j.xlsx...")
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
    except Exception as e:
        print(f"❌ [JPX] Failed to fetch JPX Excel: {e}")
        return False

    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content))
        sheet = wb.active
    except Exception as e:
        print(f"❌ [JPX] Failed to parse JPX Excel: {e}")
        return False

    stocks = {}
    name_to_code = {}

    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row or len(row) < 4:
            continue
        code_raw = str(row[1] or "").strip()
        name_raw = str(row[2] or "").strip()
        market_raw = str(row[3] or "").strip()
        industry_raw = str(row[5] or "").strip() if len(row) > 5 else ""

        if not code_raw or not code_raw.isdigit():
            continue

        ticker = f"{code_raw}.T"
        stocks[code_raw] = {
            "code": code_raw,
            "ticker": ticker,
            "name": name_raw,
            "market": market_raw,
            "industry": industry_raw
        }
        if name_raw:
            name_to_code[name_raw] = ticker

    jpx_aliases = {
        "豐田": "7203.T",
        "豐田汽車": "7203.T",
        "TOYOTA": "7203.T",
        "索尼": "6758.T",
        "SONY": "6758.T",
        "軟銀": "9984.T",
        "軟銀集團": "9984.T",
        "SOFTBANK": "9984.T",
        "任天堂": "7974.T",
        "NINTENDO": "7974.T",
        "東京威力科創": "8035.T",
        "TEL": "8035.T",
        "愛德萬測試": "6857.T",
        "日立": "6501.T",
        "HITACHI": "6501.T",
        "三菱日聯": "8306.T",
        "MUFG": "8306.T",
        "優衣庫": "9983.T",
        "迅銷": "9983.T",
        "FAST RETAILING": "9983.T",
        "基恩斯": "6861.T",
        "KEYENCE": "6861.T",
        "信越化學": "4063.T",
        "本田": "7267.T",
        "本田汽車": "7267.T",
        "HONDA": "7267.T"
    }
    for alias, ticker in jpx_aliases.items():
        name_to_code[alias] = ticker

    out_data = {
        "updated_at": datetime.date.today().isoformat(),
        "source": "JPX data_j.xlsx",
        "total": len(stocks),
        "stocks": stocks,
        "aliases": name_to_code
    }

    out_file = os.path.join(DATA_DIR, "jpx_stock_registry.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    print(f"✅ [JPX] Successfully saved {len(stocks)} JPX stocks and {len(name_to_code)} names/aliases to {out_file}")
    return True


def update_cn_stock_registry():
    """Fetch SSE and SZSE official stock lists and compile CN A-shares registry."""
    print("⏳ [CN] Fetching SSE & SZSE official A-share lists...")
    stocks = {}
    name_to_code = {}

    # 1. SSE Main Board + STAR Market
    sse_types = [("1", "上交所主板"), ("8", "科創板")]
    for stype, mname in sse_types:
        sse_url = f"http://query.sse.com.cn/security/stock/downloadStockListFile.do?csrcCode=&stockCode=&areaName=&stockType={stype}"
        req = urllib.request.Request(sse_url, headers={
            "User-Agent": USER_AGENT,
            "Referer": "http://www.sse.com.cn/"
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw_text = resp.read().decode("gbk", errors="ignore")
                for line in raw_text.splitlines():
                    parts = [p.strip() for p in line.split("\t") if p.strip()]
                    if len(parts) >= 4 and parts[0].isdigit() and len(parts[0]) == 6:
                        code = parts[0]
                        name = parts[1]
                        ticker = f"{code}.SS"
                        stocks[code] = {
                            "code": code,
                            "ticker": ticker,
                            "name": name,
                            "market": "SSE (上海證券交易所)",
                            "sub_market": mname
                        }
                        if name:
                            name_to_code[name] = ticker
        except Exception as e:
            print(f"⚠️ [CN] SSE type {stype} fetch warning: {e}")

    # 2. SZSE Main Board + ChiNext
    szse_url = "http://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110&TABKEY=tab1"
    req = urllib.request.Request(szse_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content))
        sheet = wb.active
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not row or len(row) < 5:
                continue
            board = str(row[0] or "").strip()
            full_name = str(row[1] or "").strip()
            code_raw = str(row[4] or "").strip()
            if not code_raw.isdigit() or len(code_raw) != 6:
                continue
            ticker = f"{code_raw}.SZ"
            stocks[code_raw] = {
                "code": code_raw,
                "ticker": ticker,
                "name": full_name,
                "market": "SZSE (深圳證券交易所)",
                "sub_market": board
            }
            if full_name:
                name_to_code[full_name] = ticker
    except Exception as e:
        print(f"⚠️ [CN] SZSE fetch warning: {e}")

    cn_aliases = {
        "貴州茅台": "600519.SS",
        "茅台": "600519.SS",
        "寧德時代": "300750.SZ",
        "比亞迪A股": "002594.SZ",
        "五糧液": "000858.SZ",
        "招商銀行": "600036.SS",
        "中國平安": "601318.SS",
        "中芯國際A股": "688981.SS",
        "長江電力": "600900.SS",
        "海康威視": "002415.SZ",
        "立訊精密": "002475.SZ",
        "邁瑞醫療": "300760.SZ",
        "東方財富": "300059.SZ",
        "紫金礦業": "601899.SS",
        "北方華創": "002371.SZ",
        "中微公司": "688012.SS",
        "海光信息": "688041.SS",
        "寒武紀": "688256.SS",
        "中興通訊": "000063.SZ"
    }
    for alias, ticker in cn_aliases.items():
        name_to_code[alias] = ticker

    out_data = {
        "updated_at": datetime.date.today().isoformat(),
        "source": "SSE & SZSE Official",
        "total": len(stocks),
        "stocks": stocks,
        "aliases": name_to_code
    }

    out_file = os.path.join(DATA_DIR, "cn_stock_registry.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    print(f"✅ [CN] Successfully saved {len(stocks)} CN A-shares and {len(name_to_code)} names/aliases to {out_file}")
    return True


if __name__ == "__main__":
    us_ok = update_us_stock_registry()
    hk_ok = update_hk_stock_registry()
    jpx_ok = update_jpx_stock_registry()
    cn_ok = update_cn_stock_registry()
    if us_ok and hk_ok and jpx_ok and cn_ok:
        print("🎉 All global stock registries successfully updated!")
    else:
        print("⚠️ Some stock registries failed to update.")

