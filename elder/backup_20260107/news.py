import requests
from bs4 import BeautifulSoup

def fetch_yahoo_news(stock_code):
    """
    從 Yahoo News 搜尋特定股票代碼的新聞，並返回標題和連結。
    """
    url = f"https://tw.news.yahoo.com/search?p={stock_code}"
    print(f"📡 正在抓取：{url}")

    try:
        # 發送 HTTP 請求
        response = requests.get(url)
        response.raise_for_status()  # 確保請求成功
        soup = BeautifulSoup(response.text, "html.parser")

        # 抓取所有新聞項目的連結和標題
        news_links = []
        for item in soup.find_all("a", href=True):
            href = item["href"]
            if href.startswith("/"):
                full_url = f"https://tw.news.yahoo.com{href}"
                title = item.get_text(strip=True)
                if title and full_url not in news_links:
                    news_links.append((title, full_url))

        # 篩選出有效的新聞標題和連結（前5則）
        valid_news = [(title, url) for title, url in news_links if "news" in url][:5]

        # 顯示結果
        if not valid_news:
            print(f"⚠️ 找不到 {stock_code} 的新聞。")
            return []

        print(f"✅ {stock_code} 的 Yahoo News：")
        for idx, (title, url) in enumerate(valid_news):
            print(f"{idx+1}. {title}\n   {url}")

        return valid_news

    except Exception as e:
        print(f"❌ 抓取新聞時發生錯誤：{str(e)}")
        return []

if __name__ == "__main__":
    # 測試股票代碼：輸入不同股票代碼來測試
    stock_code = input("請輸入股票代碼（例如：2330.TW）： ").strip()
    fetch_yahoo_news(stock_code)