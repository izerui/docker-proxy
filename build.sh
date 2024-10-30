docker build -f Dockerfile -t docker-proxy:1.3 .
docker tag docker-proxy:1.3 izerui/docker-proxy:1.3
docker push izerui/docker-proxy:1.3