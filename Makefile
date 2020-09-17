
.PHONY: build stop run

build :
	docker build -f Dockerfile.orig -t my_telegram_rss_bot .

stop :
	docker stop my_telegram_rss_bot
	sleep 2
	docker rm $(docker ps -aqf "name=my_telegram_rss_bot")

run :
	docker run -d -v `pwd`/config:/app/config --name my_telegram_rss_bot my_telegram_rss_bot
