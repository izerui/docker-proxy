docker build -f Dockerfile -t docker-proxy:1.0 .
docker tag docker-proxy:1.0 izerui/docker-proxy:1.0
docker push izerui/docker-proxy:1.0