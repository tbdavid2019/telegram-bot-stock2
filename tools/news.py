import yfinance as yf
import requests
import json
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Optional
from bs4 import BeautifulSoup

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

import logging
from config import TWOMD_SEARCH_ENDPOINTS
from tools.cache_util import TTLCache, SingleFlight

logger = logging.getLogger(__name__)

# --- Caches & SingleFlight to Prevent Thundering Herd & Cascading Fallbacks ---
_2md_news_cache = TTLCache(default_ttl=600.0, max_size=500)      # 10-minute cache for 2MD SERP queries
_financial_news_cache = TTLCache(default_ttl=600.0, max_size=500) # 10-minute cache for ticker news
_investing_rss_cache = TTLCache(default_ttl=300.0, max_size=100)   # 5-minute cache for Investing.com RSS
_news_singleflight = SingleFlight()

# --- Investing.com Official RSS Feeds (Zero anti-bot blocking & sub-second response) ---
INVESTING_RSS_FEEDS = {
    "investing_hk": {
        "name": "Investing.com (繁中焦點快訊)",
        "url": "https://hk.investing.com/rss/news_25.rss"
    },
    "investing": {
        "name": "Investing.com (全球股市消息)",
        "url": "https://www.investing.com/rss/news_25.rss"
    },
    "investing_commodities": {
        "name": "Investing.com (大宗商品)",
        "url": "https://www.investing.com/rss/commodities.rss"
    },
    "investing_bonds": {
        "name": "Investing.com (全球債券與利率)",
        "url": "https://www.investing.com/rss/bonds.rss"
    },
    "investing_forex": {
        "name": "Investing.com (外匯市場)",
        "url": "https://www.investing.com/rss/forex.rss"
    }
}


def fetch_investing_rss(feed_key: str = "investing_hk", limit: int = 8) -> List[Dict]:
    """
    Fetch real-time news from Investing.com official RSS feeds without anti-bot blocks.
    Uses a 5-minute in-memory cache and SingleFlight protection.
    """
    if feed_key not in INVESTING_RSS_FEEDS:
        feed_key = "investing_hk"

    cache_key = f"{feed_key}_{limit}"
    cached = _investing_rss_cache.get(cache_key)
    if cached is not None:
        return cached

    def _do_fetch():
        feed_info = INVESTING_RSS_FEEDS[feed_key]
        url = feed_info["url"]
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=6.0)
            if resp.status_code == 200 and resp.content:
                root = ET.fromstring(resp.content)
                items = []
                for idx, item in enumerate(root.findall(".//item")[:limit], 1):
                    title = item.findtext("title", "").strip()
                    link = item.findtext("link", "").strip()
                    pub_date = item.findtext("pubDate", "").strip()
                    author = item.findtext("author", feed_info["name"]).strip()
                    if title and link:
                        items.append({
                            "rank": idx,
                            "title": title,
                            "url": link,
                            "link": link,
                            "source": f"{feed_info['name']} ({author})" if author else feed_info["name"],
                            "publisher": f"Investing.com - {author}" if author else "Investing.com",
                            "published_at": pub_date,
                            "published_date": int(time.time())
                        })
                if items:
                    _investing_rss_cache.set(cache_key, items, ttl=300.0)
                    return items
        except Exception as e:
            logger.warning(f"Investing.com RSS fetch failed for {feed_key}: {e}")

        stale = _investing_rss_cache.get_stale(cache_key)
        return stale if stale is not None else []

    try:
        return _news_singleflight.run(f"rss:{cache_key}", _do_fetch)
    except Exception as e:
        logger.warning(f"SingleFlight RSS execution failed for {feed_key}: {e}")
        return []


def fetch_2md_news(query: str, limit: int = 5) -> List[Dict]:
    """
    Search news articles using 2MD Search API across primary and backup endpoints.
    Primary: https://2md.aiurl.tw/
    Backup 1: https://2md.glsoft.ai/
    Backup 2: https://create360.ai/

    Protected with:
    - 8.5-second timeout per endpoint (sufficient for SERP/headless rendering)
    - 10-minute In-Memory TTL Cache
    - SingleFlight concurrency coalescing (prevents thundering herd)
    - Stale-While-Revalidate disaster recovery fallback
    """
    cache_key = f"{query.strip().lower()}_{limit}"
    cached = _2md_news_cache.get(cache_key)
    if cached is not None:
        return cached

    def _do_fetch():
        for base_url in TWOMD_SEARCH_ENDPOINTS:
            try:
                search_url = f"{base_url.rstrip('/')}/search"
                headers = {
                    "Accept": "application/json",
                    "User-Agent": "telegram-bot-stock2/2.11"
                }
                params = {"q": query}
                
                # Optimized timeout to 8.5s for resilient SERP response
                response = requests.get(search_url, params=params, headers=headers, timeout=8.5)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("data", data.get("results", []))
                    if items and isinstance(items, list):
                        news_list = []
                        for item in items:
                            title = str(item.get("title") or "").strip()
                            url = str(item.get("url") or item.get("link") or "").strip()
                            description = str(item.get("description") or item.get("snippet") or "").strip()
                            
                            if title and url and len(title) > 3:
                                news_list.append({
                                    "title": title,
                                    "publisher": "2MD Search",
                                    "link": url,
                                    "description": description,
                                    "published_date": int(time.time())
                                })
                            if len(news_list) >= limit:
                                break
                        if news_list:
                            logger.info(f"2MD search succeeded on {base_url} for '{query}' with {len(news_list)} items.")
                            _2md_news_cache.set(cache_key, news_list, ttl=600.0)
                            return news_list
            except Exception as e:
                logger.warning(f"2MD search attempt failed on {base_url}: {e}")
                continue

        # Disaster recovery fallback: Return stale cache if available
        stale = _2md_news_cache.get_stale(cache_key)
        if stale:
            logger.info(f"2MD search endpoints timed out; serving {len(stale)} stale cached items for '{query}'.")
            return stale

        return []

    try:
        return _news_singleflight.run(f"2md:{cache_key}", _do_fetch)
    except Exception as e:
        logger.warning(f"SingleFlight 2MD search failed for '{query}': {e}")
        stale = _2md_news_cache.get_stale(cache_key)
        return stale if stale is not None else []


@tool
def search_financial_web(query: str) -> Dict:
    """Searches the live web via 2MD for company background, IPO status, stock ticker lookup, or recent market events."""
    logger.info(f"=== [Tool] search_financial_web called with query: {query}")
    results = fetch_2md_news(query, limit=5)
    if not results:
        return {
            "query": query,
            "error": "2MD 搜尋模組未檢索到即時相關結果",
            "results": []
        }
    return {
        "query": query,
        "results": results
    }


def _fetch_financial_news_impl(ticker: str) -> Dict:
    """Internal implementation for fetching financial news with multi-layer fallbacks."""
    latest_news = []
    clean_ticker = ticker.strip().upper()
    
    try:
        # Strategy 1: 2MD Search Engine (Primary + Backups with SingleFlight + TTL Cache)
        try:
            query = f"{clean_ticker} stock news 財經" if ".TW" in clean_ticker or ".TWO" in clean_ticker else f"{clean_ticker} stock news"
            latest_news = fetch_2md_news(query, limit=5)
        except Exception as e:
            logger.warning(f"Strategy 1 (2MD) failed: {e}")

        # Strategy 2: Investing.com RSS search matching
        if not latest_news:
            try:
                hk_items = fetch_investing_rss("investing_hk", limit=15)
                global_items = fetch_investing_rss("investing", limit=15)
                matched = []
                sym_plain = clean_ticker.split(".")[0]
                for it in (hk_items + global_items):
                    t_upper = it["title"].upper()
                    if sym_plain in t_upper or clean_ticker in t_upper:
                        matched.append(it)
                    if len(matched) >= 5:
                        break
                if matched:
                    latest_news = matched
                    logger.info(f"Strategy 2 (Investing.com RSS) matched {len(matched)} items for {clean_ticker}")
            except Exception as e:
                logger.warning(f"Strategy 2 (Investing.com RSS) failed: {e}")

        # Strategy 3: yfinance News API
        if not latest_news:
            try:
                stock = yf.Ticker(clean_ticker)
                news = stock.news
                if news:
                    for idx, article in enumerate(news[:5]):
                        try:
                            title = "Title Unavailable"
                            link = f"https://finance.yahoo.com/quote/{clean_ticker}"
                            publisher = "Yahoo Finance"
                            published_date = int(time.time())

                            if 'content' in article:
                                content = article['content']
                                if isinstance(content, dict):
                                    title = content.get('title', title)
                                    if 'clickThroughUrl' in content and isinstance(content['clickThroughUrl'], dict) and 'url' in content['clickThroughUrl']:
                                        link = content['clickThroughUrl']['url']
                                    elif 'canonicalUrl' in content and isinstance(content['canonicalUrl'], dict) and 'url' in content['canonicalUrl']:
                                        link = content['canonicalUrl']['url']
                                    elif 'url' in content:
                                        link = content['url']
                                    publisher = article.get('publisher', publisher)
                                    published_date = article.get('providerPublishTime', published_date)
                            else:
                                title = article.get('title', title)
                                link = article.get('link', link)
                                publisher = article.get('publisher', publisher)
                                published_date = article.get('providerPublishTime', published_date)
                            
                            latest_news.append({
                                "title": title,
                                "publisher": publisher,
                                "link": link,
                                "published_date": published_date
                            })
                        except Exception as e:
                            logger.debug(f"Error parsing yfinance news item {idx}: {e}")
                            continue
            except Exception as e:
                logger.warning(f"Strategy 3 (yfinance) failed: {e}")

        # Strategy 4: Web Scraping (Yahoo Finance)
        if not latest_news:
            logger.info("Using fallback scraping for news (Yahoo)...")
            latest_news = scrape_yahoo_finance_news(clean_ticker)

        # Strategy 5: Google News Scraping (Last Resort)
        if not latest_news:
            logger.info("Using Google News fallback...")
            latest_news = scrape_google_news(clean_ticker)
            
        if not latest_news:
            # Check if stale cache exists before declaring error
            stale_data = _financial_news_cache.get_stale(clean_ticker)
            if stale_data and stale_data.get("news"):
                logger.info(f"All real-time strategies failed for {clean_ticker}; serving stale cache.")
                return stale_data

            return {
                "stock": clean_ticker,
                "error": f"新聞模組故障：目前無法獲取 {clean_ticker} 的即時新聞",
                "news": []
            }
            
        res = {"stock": clean_ticker, "news": latest_news}
        _financial_news_cache.set(clean_ticker, res, ttl=600.0)
        return res

    except Exception as e:
        logger.error(f"Error fetching news for {clean_ticker}: {e}")
        stale_data = _financial_news_cache.get_stale(clean_ticker)
        if stale_data and stale_data.get("news"):
            return stale_data

        return {
            "stock": clean_ticker, 
            "error": f"新聞模組故障：{str(e)}",
            "news": []
        }


@tool
def get_financial_news(ticker: str) -> Dict:
    """Fetches the latest financial news related to a given ticker using 2MD search, Investing.com, yfinance, and fallbacks."""
    logger.info(f"=== [Tool] get_financial_news called with ticker: {ticker}")
    clean_ticker = ticker.strip().upper()
    cached = _financial_news_cache.get(clean_ticker)
    if cached is not None:
        return cached

    try:
        return _news_singleflight.run(f"news:{clean_ticker}", _fetch_financial_news_impl, clean_ticker)
    except Exception as e:
        logger.warning(f"SingleFlight financial news failed for {clean_ticker}: {e}")
        stale = _financial_news_cache.get_stale(clean_ticker)
        if stale is not None:
            return stale
        return {
            "stock": clean_ticker,
            "error": f"新聞獲取超時或中斷：{str(e)}",
            "news": []
        }


def scrape_yahoo_finance_news(ticker: str) -> List[Dict]:
    news_items = []
    try:
        url = f"https://finance.yahoo.com/quote/{ticker}/news"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=8.0)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link in soup.find_all('a', href=True):
            if '/news/' in link.get('href', '') and link.text:
                title = link.text.strip()
                href = link['href']
                full_url = f"https://finance.yahoo.com{href}" if href.startswith('/') else href
                if title and len(title) > 15:
                    news_items.append({
                        "title": title,
                        "publisher": "Yahoo Finance",
                        "link": full_url,
                        "published_date": int(time.time())
                    })
                    if len(news_items) >= 5: break
    except Exception as e:
        logger.error(f"Scraping Yahoo failed: {e}")
    return news_items


def scrape_google_news(ticker: str) -> List[Dict]:
    news_items = []
    try:
        url = f"https://www.google.com/search?q={ticker}+stock+news&tbm=nws"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=8.0)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for result in soup.select('div.SoaBEf'):
            title_elem = result.select_one('div.mCBkyc')
            link_elem = result.select_one('a')
            if title_elem and link_elem:
                title = title_elem.text.strip()
                link = link_elem.get('href', '')
                if 'url=' in link:
                    link = link.split('url=')[1].split('&')[0]
                news_items.append({
                    "title": title,
                    "publisher": "Google News",
                    "link": link,
                    "published_date": int(time.time())
                })
                if len(news_items) >= 5: break
    except Exception as e:
        logger.error(f"Scraping Google failed: {e}")
    return news_items


# --- NewsNow & Investing.com High-Frequency Hot News Integration ---
NEWSNOW_BASE_URL = "https://newsnow.busiyi.world"
NEWSNOW_SOURCES = {
    "cls": "財聯社 (CLS 盤中快訊)",
    "wallstreetcn": "華爾街見聞 (全球宏觀)",
    "xueqiu": "雪球 (熱門討論榜)",
    "investing_hk": "Investing.com (繁中焦點快訊)",
    "investing": "Investing.com (全球股市消息)",
    "investing_commodities": "Investing.com (大宗商品)",
    "investing_bonds": "Investing.com (全球債券與利率)"
}
_newsnow_cache = TTLCache(default_ttl=180.0, max_size=100)


def get_hot_financial_news(source_id: str = "cls", count: int = 10) -> List[Dict]:
    """
    Fetches real-time hot financial news headlines from NewsNow API (cls, wallstreetcn, xueqiu)
    or Investing.com official RSS (investing_hk, investing, investing_commodities, investing_bonds).
    Uses a 3-minute in-memory cache and SingleFlight protection.
    """
    if source_id not in NEWSNOW_SOURCES:
        source_id = "cls"

    # Branch 1: Investing.com RSS Sources
    if source_id in INVESTING_RSS_FEEDS:
        return fetch_investing_rss(source_id, limit=count)

    # Branch 2: NewsNow API Sources
    cache_key = f"{source_id}_{count}"
    cached = _newsnow_cache.get(cache_key)
    if cached is not None:
        return cached

    def _do_fetch():
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }
        try:
            url = f"{NEWSNOW_BASE_URL}/api/s?id={source_id}"
            resp = requests.get(url, headers=headers, timeout=8.0)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])[:count]
                result_list = []
                source_name = NEWSNOW_SOURCES.get(source_id, source_id)
                for idx, item in enumerate(items, 1):
                    title = item.get("title", "").strip()
                    item_url = item.get("url") or item.get("mobileUrl") or ""
                    if title:
                        result_list.append({
                            "rank": idx,
                            "title": title,
                            "url": item_url,
                            "link": item_url,
                            "source": source_name,
                            "published_at": item.get("pubDate")
                        })
                if result_list:
                    _newsnow_cache.set(cache_key, result_list, ttl=180.0)
                    return result_list
        except Exception as e:
            logger.warning(f"NewsNow fetch failed for {source_id}: {e}")

        # Fallback to stale cache if exists
        stale = _newsnow_cache.get_stale(cache_key)
        return stale if stale is not None else []

    try:
        return _news_singleflight.run(f"newsnow:{cache_key}", _do_fetch)
    except Exception as e:
        logger.warning(f"SingleFlight NewsNow failed for {source_id}: {e}")
        stale = _newsnow_cache.get_stale(cache_key)
        return stale if stale is not None else []


@tool
def get_hot_news_flash(source: str = "cls") -> Dict:
    """
    Fetches the hottest real-time breaking financial news headlines from:
    - 財聯社 (cls)
    - 華爾街見聞 (wallstreetcn)
    - 雪球 (xueqiu)
    - Investing.com 繁中焦點 (investing_hk)
    - Investing.com 全球股市 (investing)
    - Investing.com 大宗商品 (investing_commodities)
    - Investing.com 全球債券與利率 (investing_bonds)

    Use this tool whenever users ask for:
    - '今日重大財經快訊 / 財聯社快訊'
    - '華爾街見聞熱門話題'
    - 'Investing.com 焦點新聞'
    - '目前市場有哪些重大突發新聞 / 熱門板塊'
    Valid sources: 'cls', 'wallstreetcn', 'xueqiu', 'investing_hk', 'investing', 'investing_commodities', 'investing_bonds'. Default is 'cls'.
    """
    logger.info(f"=== [Tool] get_hot_news_flash called for source: {source}")
    news_items = get_hot_financial_news(source_id=source, count=8)
    source_name = NEWSNOW_SOURCES.get(source, source)
    
    if not news_items:
        return {
            "source": source_name,
            "error": "目前無法獲取即時快訊，請嘗試使用 2MD 全網搜尋。",
            "headlines": []
        }
        
    return {
        "source": source_name,
        "count": len(news_items),
        "headlines": news_items
    }
