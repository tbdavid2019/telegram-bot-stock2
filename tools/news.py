import yfinance as yf
import requests
import json
import time
from typing import Dict, List, Tuple
from bs4 import BeautifulSoup
try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

import logging
from config import TWOMD_SEARCH_ENDPOINTS

logger = logging.getLogger(__name__)

def fetch_2md_news(query: str, limit: int = 5) -> List[Dict]:
    """
    Search news articles using 2MD Search API across primary and backup endpoints.
    Primary: https://2md.aiurl.tw/
    Backup 1: https://2md.glsoft.ai/
    Backup 2: https://create360.ai/
    """
    for base_url in TWOMD_SEARCH_ENDPOINTS:
        try:
            search_url = f"{base_url.rstrip('/')}/search"
            headers = {
                "Accept": "application/json",
                "User-Agent": "telegram-bot-stock2/2.0"
            }
            params = {"q": query}
            
            response = requests.get(search_url, params=params, headers=headers, timeout=6.0)
            if response.status_code == 200:
                data = response.json()
                items = data.get("data", [])
                if items and isinstance(items, list):
                    news_list = []
                    for item in items:
                        title = item.get("title", "").strip()
                        url = item.get("url", "").strip()
                        description = item.get("description", "").strip()
                        
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
                        return news_list
        except Exception as e:
            logger.warning(f"2MD search attempt failed on {base_url}: {e}")
            continue

    return []

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

@tool
def get_financial_news(ticker: str) -> Dict:
    """Fetches the latest financial news related to a given ticker using 2MD search, yfinance, and fallbacks."""
    logger.info(f"=== [Tool] get_financial_news called with ticker: {ticker}")
    latest_news = []
    
    try:
        # Strategy 1: 2MD Search Engine (Primary + Backups)
        try:
            query = f"{ticker} stock news 財經" if ".TW" in ticker.upper() or ".TWO" in ticker.upper() else f"{ticker} stock news"
            latest_news = fetch_2md_news(query, limit=5)
        except Exception as e:
            logger.warning(f"Strategy 1 (2MD) failed: {e}")

        # Strategy 2: yfinance News API
        if not latest_news:
            try:
                stock = yf.Ticker(ticker)
                news = stock.news
                if news:
                    for idx, article in enumerate(news[:5]):
                        try:
                            title = "Title Unavailable"
                            link = f"https://finance.yahoo.com/quote/{ticker}"
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
                logger.warning(f"Strategy 2 (yfinance) failed: {e}")

        # Strategy 3: Web Scraping (Yahoo Finance)
        if not latest_news:
            logger.info("Using fallback scraping for news (Yahoo)...")
            latest_news = scrape_yahoo_finance_news(ticker)

        # Strategy 4: Google News Scraping (Last Resort)
        if not latest_news:
            logger.info("Using Google News fallback...")
            latest_news = scrape_google_news(ticker)
            
        if not latest_news:
            return {
                "stock": ticker,
                "error": f"新聞模組故障：目前無法獲取 {ticker} 的即時新聞",
                "news": []
            }
            
        return {"stock": ticker, "news": latest_news}

    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        return {
            "stock": ticker, 
            "error": f"新聞模組故障：{str(e)}",
            "news": []
        }

def scrape_yahoo_finance_news(ticker: str) -> List[Dict]:
    news_items = []
    try:
        url = f"https://finance.yahoo.com/quote/{ticker}/news"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
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
        response = requests.get(url, headers=headers, timeout=10)
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

# --- NewsNow High-Frequency Hot News Integration ---
NEWSNOW_BASE_URL = "https://newsnow.busiyi.world"
NEWSNOW_SOURCES = {
    "cls": "財聯社 (CLS 盤中快訊)",
    "wallstreetcn": "華爾街見聞 (全球宏觀)",
    "xueqiu": "雪球 (熱門討論榜)"
}
_newsnow_cache = {}

def get_hot_financial_news(source_id: str = "cls", count: int = 10) -> List[Dict]:
    """
    Fetches real-time hot financial news headlines from NewsNow API (cls, wallstreetcn, xueqiu).
    Uses a 3-minute in-memory cache.
    """
    if source_id not in NEWSNOW_SOURCES:
        source_id = "cls"
        
    cache_key = f"{source_id}_{count}"
    now = time.time()
    if cache_key in _newsnow_cache and (now - _newsnow_cache[cache_key]["time"] < 180):
        return _newsnow_cache[cache_key]["data"]

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
                        "source": source_name,
                        "published_at": item.get("pubDate")
                    })
            if result_list:
                _newsnow_cache[cache_key] = {"time": now, "data": result_list}
                return result_list
    except Exception as e:
        logger.warning(f"NewsNow fetch failed for {source_id}: {e}")

    # Fallback to stale cache if exists
    if cache_key in _newsnow_cache:
        return _newsnow_cache[cache_key]["data"]

    return []

@tool
def get_hot_news_flash(source: str = "cls") -> Dict:
    """
    Fetches the hottest real-time breaking financial news headlines from 財聯社 (cls), 華爾街見聞 (wallstreetcn), or 雪球 (xueqiu).
    Use this tool whenever users ask for:
    - '今日重大財經快訊 / 財聯社快訊'
    - '華爾街見聞熱門話題'
    - '目前市場有哪些重大突發新聞 / 熱門板塊'
    Valid sources: 'cls', 'wallstreetcn', 'xueqiu'. Default is 'cls'.
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

