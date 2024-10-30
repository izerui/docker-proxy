docker build -f Dockerfile -t docker-proxy .
docker tag docker-proxy izerui/docker-proxy
docker push izerui/docker-proxy