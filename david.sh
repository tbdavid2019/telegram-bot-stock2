cd /home/bitnami/telegram-bot-stock2
source myenv/bin/activate
nohup python main.py > /tmp/stockapp.log 2>&1 &



docker build -t telegram-bot-stock2 .
docker run -d --name telegram-bot -e TELEGRAM_BOT_TOKEN=金鑰匙 telegram-bot-stock2

docker tag telegram-bot-stock2 tbdavid2019/telegram-bot-stock2:latest
docker push tbdavid2019/telegram-bot-stock2:latest