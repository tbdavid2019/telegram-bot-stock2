import yfinance as yf
import requests
import json
import time
from bs4 import BeautifulSoup
from typing import Dict, List, Tuple
from langchain_core.tools import tool
import logging

logger = logging.getLogger(__name__)

@tool
def get_financial_news(ticker: str) -> Dict:
    """Fetches the latest financial news related to a given ticker using multiple strategies."""
    logger.info(f"=== [Tool] get_financial_news called with ticker: {ticker}")
    try:
        # Strategy 1: yfinance
        stock = yf.Ticker(ticker)
        news = stock.news
        latest_news = []
        
        if news:
            for idx, article in enumerate(news[:5]):
                try:
                    title = "Title Unavailable"
                    link = "#"
                    publisher = "Unknown"
                    published_date = int(time.time())

                    if 'content' in article: # New structure
                         content = article['content']
                         if isinstance(content, dict):
                             title = content.get('title', title)
                             if 'clickThroughUrl' in content and 'url' in content['clickThroughUrl']:
                                 link = content['clickThroughUrl']['url']
                             elif 'url' in content:
                                 link = content['url']
                             publisher = article.get('publisher', publisher)
                             published_date = article.get('providerPublishTime', published_date)
                    else: # Old structure or fallback
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
                    logger.debug(f"Error parsing news item {idx}: {e}")
                    continue
        
        # Strategy 2: Web Scraping (Fallback)
        if not latest_news:
            logger.info("Using fallback scraping for news...")
            latest_news = scrape_yahoo_finance_news(ticker)

        # Strategy 3: Google News (Last Resort)
        if not latest_news:
             logger.info("Using Google News fallback...")
             latest_news = scrape_google_news(ticker)
            
        if not latest_news:
            latest_news.append({
                "title": f"No news found for {ticker}",
                "publisher": "System",
                "link": f"https://finance.yahoo.com/quote/{ticker}",
                "published_date": int(time.time())
            })
            
        return {"stock": ticker, "news": latest_news}
    
    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        import traceback
        traceback.print_exc()
        return {
            "stock": ticker, 
            "news": [{
                "title": f"Error fetching news for {ticker}",
                "publisher": "System",
                "link": f"https://finance.yahoo.com/quote/{ticker}",
                "published_date": int(time.time())
            }]
        }

def scrape_yahoo_finance_news(ticker: str) -> List[Dict]:
    news_items = []
    try:
        url = f"https://finance.yahoo.com/quote/{ticker}/news"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Specific scraping logic for Yahoo structure
        # (Simplified from original for brevity and reliability)
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
