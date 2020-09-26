
.PHONY: build stop run

build :
	docker build -f Dockerfile.orig -t my_telegram_rss_bot .

stop :
	container_id=`docker ps -aqf "name=my_telegram_rss_bot"`
	docker stop $container_id
	docker rm $container_id

run :
	docker run -d -v `pwd`/config:/app/config --name my_telegram_rss_bot my_telegram_rss_bot
