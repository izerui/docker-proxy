import logging
import os

import aiohttp
from aiohttp_socks import ProxyConnector
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

# 设置日志记录
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# 从环境变量中获取自定义域名、模式和目标上游服务器
CUSTOM_DOMAIN = os.getenv("CUSTOM_DOMAIN", "serv999.com")

# 从环境变量中获取代理 URL
PROXY_URL = os.getenv("PROXY_URL", None)

# 代理转发路径前缀匹配规则
routes = {
    # 生产环境
    f"docker.{CUSTOM_DOMAIN}": "https://registry-1.docker.io",
    f"quay.{CUSTOM_DOMAIN}": "https://quay.io",
    f"gcr.{CUSTOM_DOMAIN}": "https://gcr.io",
    f"k8s-gcr.{CUSTOM_DOMAIN}": "https://k8s.gcr.io",
    f"k8s.{CUSTOM_DOMAIN}": "https://registry.k8s.io",
    f"ghcr.{CUSTOM_DOMAIN}": "https://ghcr.io",
    f"cloudsmith.{CUSTOM_DOMAIN}": "https://docker.cloudsmith.io",
    f"ecr.{CUSTOM_DOMAIN}": "https://public.ecr.aws",
    f"chatpy-dev.{CUSTOM_DOMAIN}/token": "https://auth.docker.io/token",
    f"chatpy-dev.{CUSTOM_DOMAIN}": "https://registry-1.docker.io",
}

# 白名单路径不进行转发
path_whitelist = [
    '/'
]

# 保留请求的header的key集合
reserved_headers = [
    'user-agent',
    'authorization',
    'accept',
]

def is_docker_hub_pull(method, url):
    return method == 'get' and url.startswith("https://registry-1.docker.io/")


app.mount("/rag/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(
        request=request, name="help.html", context={"my_domain": CUSTOM_DOMAIN}
    )


# 处理所有传入的请求
@app.middleware("http")
async def handle_request(request: Request, call_next):
    # 获取请求体
    method = request.method.lower()
    url = str(request.url)
    body = await request.body()
    # 原始字典
    headers = dict(request.headers)
    proxy = False

    logging.info(f'接收到请求\n【{method}】: {url} \n【headers】: {headers}\n【content】:{body}')

    # 白名单中的path不进行转发
    # if request.url.path in path_whitelist:
    #     return await call_next(request)

    for route in routes:
        route_url = f'{request.url.scheme}://{route}'
        if url.startswith(route_url):
            proxy = True
            url = url.replace(route_url, routes[route])
            pass

    if not proxy:
        return await call_next(request)

    # 过滤headers保留reserved_headers中的key
    headers = {key: headers[key] for key in reserved_headers if key in headers}

    logging.info(f'代理转发\n【{method}】: {url} \n【headers】: {headers}\n【content】:{body}')
    connector = ProxyConnector.from_url(PROXY_URL) if PROXY_URL else None
    async with (aiohttp.ClientSession(connector=connector) as session):
        async with session.request(method=request.method, url=url, headers=headers, data=body,
                                   allow_redirects=True) as resp:
            try:
                response_headers = dict(resp.headers)
                response_body = await resp.read()
                # 返回:
                # HTTP/1.1 401 Unauthorized
                # Content-Type: application/json
                # WWW-Authenticate: Bearer realm="https://auth.docker.io/token",service="registry.docker.io",scope="repository:library/nginx:pull"
                if 'WWW-Authenticate' in response_headers:
                    www_auth = response_headers['WWW-Authenticate']
                    for key, value in routes.items():
                        if value == "https://auth.docker.io/token":
                            # 将返回的realm的域名替换为代理域名
                            www_auth = www_auth.replace(value, f'https://{key}')
                            response_headers['WWW-Authenticate'] = www_auth
                            break
                # 删除分段传输的头, 这里应该有nginx转发来自动判断是否添加，原始服务器返回的该头针对当前nginx代理不一定匹配
                if 'Transfer-Encoding' in response_headers:
                    del response_headers['Transfer-Encoding']
                logging.info(
                    f'返回结果\n【{method}】: {url}\n【headers】: {response_headers}\n【content】:{response_body}')
                return Response(content=response_body, status_code=resp.status, headers=response_headers)
            except Exception as e:
                logger.error(f"Error processing response: {e}")
                return JSONResponse({"error": "Internal Server Error"}, status_code=500)


# 启动应用程序
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
