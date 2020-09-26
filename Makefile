
.PHONY: build stop run

build :
	docker build -f Dockerfile.orig -t my_telegram_rss_bot .

stop :
	ID := $$(docker ps -aqf "name=my_telegram_rss_bot")
	docker stop "${ID}"
	docker rm "${ID}"

run :
	docker run -d -v `pwd`/config:/app/config --name my_telegram_rss_bot my_telegram_rss_bot
