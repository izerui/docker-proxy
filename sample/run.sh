#!/bin/bash

# 列出所有正在运行的使用 "izerui/docker-proxy" 镜像的容器
running_containers=$(docker ps --filter "ancestor=izerui/docker-proxy" --format "{{.ID}}")

# 检查是否有运行中的容器
if [ -z "$running_containers" ]; then
        echo "No running containers found for the image 'izerui/docker-proxy'."
else
        echo "Stopping running containers for the image 'izerui/docker-proxy':"
        # 循环遍历每个容器ID并停止它们
        for container_id in $running_containers;
        do
                echo "Stopping container ID: $container_id"
                docker stop $container_id
        done
        echo "All containers for the image 'izerui/docker-proxy' have been stopped."
fi
docker rmi izerui/docker-proxy
docker pull izerui/docker-proxy
docker run -e CUSTOM_DOMAIN="serv999.com" -d -p 9000:8000 izerui/docker-proxy