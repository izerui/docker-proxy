# docker proxy

docker 代理转发服务，解决国内镜像拉取问题。
前提你得有一台海外服务器，配置不要太高，只要有流量即可。
然后将自己的泛域名指向该服务器，并配置好ssl和转发规则(nginx转docker本地监听端口)。
或者将下面指定的域名指向该服务器也行。
```
docker rmi izerui/docker-proxy
docker pull izerui/docker-proxy
docker run -e CUSTOM_DOMAIN="xxx.com" -d -p 9000:8000 izerui/docker-proxy
```

默认代理的仓库有:
```
docker-auth.xxx.com --> auth.docker.io,
docker.xxx.com --> registry-1.docker.io,
quay.xxx.com --> quay.io,
gcr.xxx.com --> gcr.io,
k8s-gcr.xxx.com --> k8s.gcr.io,
k8s.xxx.com --> registry.k8s.io,
ghcr.xxx.com --> ghcr.io,
cloudsmith.xxx.com --> docker.cloudsmith.io,
ecr.xxx.com --> public.ecr.aws,
```



下面是开发相关的:

* `pip install fastapi`
* `pip install uvicorn[standard]`
* `pip install aiohttp`
* `pip install aiohttp-socks`
* `pip install jinja2`
* `pip install pyjwt`
* `pip install prettytable`
* `pip install colorama`


依赖管理:
```
# 安装依赖
pip install -r requirements.txt
# 生成依赖描述文件
pip freeze > requirements.txt
```

# docker 拉取镜像流程
1. 请求 https://registry-1.docker.io/v2/ 验证是否已经授权
2. 如果未授权会返回401，并且响应head头会附带告诉客户端应该去哪里授权，WWW-Authenticate: Bearer realm="https://auth.docker.io/token",service="registry.docker.io"
3. 这个时候代理应该修改上面返回的授权地址，改成自己可代理的地址。比如修改 auth.docker.io 改为 docker-auth.serv999.com，再返回
4. 然后客户端会根据返回的授权地址去请求token，https://auth.docker.io/token?scope=repository%3Abitnami%2Fmysql%3Apull&service=registry.docker.io ,并返回json内容，包含token授权字段
   * 移除请求附带的authorization头
   * docker中央仓库路径/token，其他仓库授权地址为/v2/auth
   * docker中央仓库注意: 这里获取token之前注意将docker中央仓库的基础镜像添加library前缀，其他仓库不用处理
5. 然后客户端会将获取的token字段值作为head头 authorization 授权附带上去去请求镜像，比如： https://registry-1.docker.io/v2/bitnami/mysql/manifests/latest head头: authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsIng1YyI6WyJNSUlFRmpD...

注意： docker仓库返回的授权域名与仓库域名不一致。


这里有一个免费的镜像代理网站可以直接使用
https://dockerpull.org/