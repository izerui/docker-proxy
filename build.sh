docker build -f Dockerfile -t docker-proxy:1.1 .
docker tag docker-proxy:1.1 izerui/docker-proxy:1.1
docker push izerui/docker-proxy:1.1