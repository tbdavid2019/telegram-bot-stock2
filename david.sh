docker stop telegram-bot-stock2
docker rm telegram-bot-stock2
docker build -t telegram-bot-stock2 .
docker run -d \
  --name telegram-bot-stock2 \
  --env-file .env \
  telegram-bot-stock2
docker tag telegram-bot-stock2 tbdavid2019/telegram-bot-stock2:latest
docker push tbdavid2019/telegram-bot-stock2:latest  