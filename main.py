import logging
import os

import aiohttp
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

# 设置日志记录
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Docker Hub 的 URL
dockerHub = "https://registry-1.docker.io"

# 从环境变量中获取自定义域名、模式和目标上游服务器
CUSTOM_DOMAIN = os.getenv("CUSTOM_DOMAIN", "serv999.com")
MODE = os.getenv("MODE", "production")
TARGET_UPSTREAM = os.getenv("TARGET_UPSTREAM", "http://localhost:8000")

# 定义主机名到上游服务器的路由映射
routes = {
    # 生产环境
    f"docker.{CUSTOM_DOMAIN}": dockerHub,
    f"quay.{CUSTOM_DOMAIN}": "https://quay.io",
    f"gcr.{CUSTOM_DOMAIN}": "https://gcr.io",
    f"k8s-gcr.{CUSTOM_DOMAIN}": "https://k8s.gcr.io",
    f"k8s.{CUSTOM_DOMAIN}": "https://registry.k8s.io",
    f"ghcr.{CUSTOM_DOMAIN}": "https://ghcr.io",
    f"cloudsmith.{CUSTOM_DOMAIN}": "https://docker.cloudsmith.io",
    f"ecr.{CUSTOM_DOMAIN}": "https://public.ecr.aws",

    # 测试环境
    f"docker-staging.{CUSTOM_DOMAIN}": dockerHub,
}


# 根据主机名获取上游服务器 URL
def route_by_hosts(host):
    if host in routes:
        return routes[host]
    if MODE == "debug":
        return TARGET_UPSTREAM
    return ""


# 获取认证令牌
async def fetch_token(www_authenticate, scope, authorization):
    url = www_authenticate['realm']
    params = {
        "service": www_authenticate['service']
    }
    if scope:
        params["scope"] = scope
    headers = {}
    if authorization:
        headers["Authorization"] = authorization
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as resp:
            return await resp.json()


# 解析 WWW-Authenticate 头
def parse_authenticate(authenticate_str):
    parts = authenticate_str.split(',')
    realm = parts[0].split('=')[1].strip('"')
    service = parts[1].split('=')[1].strip('"')
    return {
        "realm": realm,
        "service": service
    }


# 返回未授权响应
async def response_unauthorized(url):
    headers = {}
    if MODE == "debug":
        headers["WWW-Authenticate"] = f'Bearer realm="http://{url.netloc}/v2/auth",service="cloudflare-docker-proxy"'
    else:
        headers["WWW-Authenticate"] = f'Bearer realm="https://{url.netloc}/v2/auth",service="cloudflare-docker-proxy"'
    return JSONResponse({"message": "UNAUTHORIZED"}, status_code=401, headers=headers)


# 处理所有传入的请求
@app.middleware("http")
async def handle_request(request: Request, call_next):
    url = request.url
    upstream = route_by_hosts(url.hostname)
    if not upstream:
        return JSONResponse({"routes": routes}, status_code=404)

    is_docker_hub = upstream == dockerHub
    authorization = request.headers.get("Authorization")

    # 处理 /v2/ 路径
    if url.path == "/v2/":
        new_url = f"{upstream}/v2/"
        headers = {"Authorization": authorization} if authorization else {}
        async with aiohttp.ClientSession() as session:
            async with session.get(new_url, headers=headers) as resp:
                if resp.status == 401:
                    return await response_unauthorized(url)
                return Response(content=await resp.read(), status_code=resp.status, headers=dict(resp.headers))

    # 处理 /v2/auth 路径
    if url.path == "/v2/auth":
        new_url = f"{upstream}/v2/"
        async with aiohttp.ClientSession() as session:
            async with session.get(new_url) as resp:
                if resp.status != 401:
                    return Response(content=await resp.read(), status_code=resp.status, headers=dict(resp.headers))
                authenticate_str = resp.headers.get("WWW-Authenticate")
                if not authenticate_str:
                    return Response(content=await resp.read(), status_code=resp.status, headers=dict(resp.headers))
                www_authenticate = parse_authenticate(authenticate_str)
                scope = request.query_params.get("scope")
                if scope and is_docker_hub:
                    scope_parts = scope.split(":")
                    if len(scope_parts) == 3 and "/" not in scope_parts[1]:
                        scope_parts[1] = f"library/{scope_parts[1]}"
                        scope = ":".join(scope_parts)
                token_response = await fetch_token(www_authenticate, scope, authorization)
                return JSONResponse(token_response)

    # 对 Docker Hub 的库镜像路径进行重定向
    if is_docker_hub:
        path_parts = url.path.split("/")
        if len(path_parts) == 5:
            path_parts.insert(2, "library")
            redirect_url = url.replace(path="/".join(path_parts))
            return RedirectResponse(url=str(redirect_url), status_code=301)

    # 转发其他请求
    new_url = f"{upstream}{url.path}"
    headers = dict(request.headers)
    async with aiohttp.ClientSession() as session:
        async with session.request(method=request.method, url=new_url, headers=headers, allow_redirects=True) as resp:
            if resp.status == 401:
                return await response_unauthorized(url)
            try:
                content = await resp.read()
                return Response(content=content, status_code=resp.status, headers=dict(resp.headers))
            except Exception as e:
                logger.error(f"Error processing response: {e}")
                return JSONResponse({"error": "Internal Server Error"}, status_code=500)


# 启动应用程序
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
