# 使用 Debian slim 基底映像檔 (更好的套件兼容性)
FROM python:3.13-slim

# 安裝系統依賴 (prophet 需要的編譯工具)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 複製 requirements.txt 並安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案文件
COPY . .

# 設定環境變數 (PYTHONUNBUFFERED=1 讓 Python 輸出不緩衝)
ENV PYTHONUNBUFFERED=1

# Watchtower 自動化更新標籤
LABEL com.centurylinklabs.watchtower.enable="true"

# 直接啟動 Python 程式
CMD ["python", "main.py"]