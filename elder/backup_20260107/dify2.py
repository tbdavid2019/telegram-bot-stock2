import requests
import json  # 正確導入標準 json 庫

# API 設定
LLM_ENDPOINT = "http://llm.glsoft.ai/v1/chat-messages"
API_KEY = "app-Nei865AcKu"
USER_ID = "test_user_123"

# 測試問題
query = "AVGO 的股價前景如何？"

# 請求 headers 和 payload
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

payload = {
    "inputs": {},
    "query": query,
    "response_mode": "streaming",  # 使用 streaming 模式
    "conversation_id": "",
    "user": USER_ID
}

# 發送請求並逐步解析資料
try:
    print("🚀 正在發送請求 (Streaming 模式)...\n")
    response = requests.post(LLM_ENDPOINT, headers=headers, json=payload, stream=True)
    response.raise_for_status()

    # 逐行處理 SSE 回應
    print("🤖 **AI 回應**：", end="", flush=True)
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode("utf-8")
            if decoded_line.startswith("data:"):
                # 解析 JSON 格式的資料
                data = decoded_line[5:].strip()  # 去掉 "data:"
                if data:  # 確保資料有效
                    chunk = json.loads(data)  # 使用標準 json 庫
                    if "answer" in chunk:
                        print(chunk["answer"], end="", flush=True)
            elif "event: message_end" in decoded_line:
                # 結束標誌
                print("\n✅ 回應完成！")
                break

except requests.exceptions.RequestException as e:
    print(f"❌ 發送請求時發生錯誤：{str(e)}")