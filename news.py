import requests
from bs4 import BeautifulSoup
from tools.news import fetch_2md_news

def fetch_yahoo_news(stock_code):
    """
    從 Yahoo News 搜尋特定股票代碼的新聞，並返回標題和連結。
    """
    url = f"https://tw.news.yahoo.com/search?p={stock_code}"
    print(f"📡 正在抓取 Yahoo News：{url}")

    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        news_links = []
        for item in soup.find_all("a", href=True):
            href = item["href"]
            if href.startswith("/"):
                full_url = f"https://tw.news.yahoo.com{href}"
                title = item.get_text(strip=True)
                if title and full_url not in news_links:
                    news_links.append((title, full_url))

        valid_news = [(title, url) for title, url in news_links if "news" in url][:5]
        return valid_news
    except Exception as e:
        print(f"❌ 抓取 Yahoo 新聞時發生錯誤：{str(e)}")
        return []

def get_stock_news_combined(stock_code: str):
    """
    綜合抓取股票新聞：優先使用 2MD 搜尋引擎 (主力: 2md.aiurl.tw, 備援: 2md.glsoft.ai, create360.ai)，
    若無結果則回退至 Yahoo News 爬蟲。
    """
    print(f"🔍 正在透過 2MD 搜尋引擎檢索 {stock_code} 最新財經新聞...")
    query = f"{stock_code} 台灣 股票 新聞" if ".TW" in stock_code.upper() else f"{stock_code} stock news"
    two_md_results = fetch_2md_news(query, limit=5)
    
    if two_md_results:
        print(f"✅ 成功從 2MD 獲取 {len(two_md_results)} 則新聞：")
        for idx, item in enumerate(two_md_results):
            print(f"{idx+1}. {item['title']}\n   {item['link']}")
            if item.get('description'):
                print(f"   摘要: {item['description'][:80]}...")
        return [(it['title'], it['link']) for it in two_md_results]
        
    print("⚠️ 2MD 未能檢索到新聞，正在切換至 Yahoo News 爬蟲...")
    return fetch_yahoo_news(stock_code)

if __name__ == "__main__":
    stock_code = input("請輸入股票代碼（例如：2330.TW 或 TSLA）： ").strip()
    get_stock_news_combined(stock_code)