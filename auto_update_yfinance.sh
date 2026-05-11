#!/bin/bash

# =================================================================
# yfinance 自動更新與重建腳本
# =================================================================

# 配置
PACKAGE_NAME="yfinance"
CONTAINER_NAME="telegram-bot-stock2"
BASE_DIR="/home/bitnami/telegram-bot-stock2"
REBUILD_SCRIPT="$BASE_DIR/david.sh"

cd "$BASE_DIR" || exit 1

echo "[$(date)] 正在檢查 $PACKAGE_NAME 更新..."

# 1. 取得容器內目前的版本
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    CURRENT_VERSION=$(docker exec $CONTAINER_NAME pip show $PACKAGE_NAME 2>/dev/null | grep Version | awk '{print $2}')
    if [ -z "$CURRENT_VERSION" ]; then
        echo "⚠️  在容器內找不到 $PACKAGE_NAME，將執行重建..."
        bash "$REBUILD_SCRIPT"
        exit 0
    fi
else
    echo "⚠️  容器 $CONTAINER_NAME 未運行，將執行重建並啟動..."
    bash "$REBUILD_SCRIPT"
    exit 0
fi

# 2. 取得 PyPI 上最新的版本
LATEST_VERSION=$(curl -s https://pypi.org/pypi/$PACKAGE_NAME/json | python3 -c "import sys, json; print(json.load(sys.stdin)['info']['version'])" 2>/dev/null)

if [ -z "$LATEST_VERSION" ]; then
    echo "❌ 錯誤：無法從 PyPI 取得最新版本資訊。"
    exit 1
fi

echo "當前版本: $CURRENT_VERSION"
echo "最新版本: $LATEST_VERSION"

# 3. 比較版本並決定是否重建
if [ "$CURRENT_VERSION" != "$LATEST_VERSION" ]; then
    echo "🚀 發現新版本！正在執行重建任務 ($REBUILD_SCRIPT)..."
    bash "$REBUILD_SCRIPT"
    echo "✅ 更新完成。"
else
    echo "😴 版本一致，無需更新。"
fi
