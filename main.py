import datetime
import logging
import os
from urllib.parse import unquote, quote

import aiohttp
import jwt
from aiohttp import ClientTimeout
from aiohttp_socks import ProxyConnector
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from jwt import ExpiredSignatureError, DecodeError
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

# 环境
PROFILE = os.getenv("PROFILE", 'production')

# 定义中央仓库
cus_docker_hub_domain = f"docker.{CUSTOM_DOMAIN}" if PROFILE == 'production' else f"chatpy-dev.{CUSTOM_DOMAIN}"

# 代理转发路径前缀匹配规则
routes = {
    f"{cus_docker_hub_domain}/token": "https://auth.docker.io/token",
    f"{cus_docker_hub_domain}": "https://registry-1.docker.io",
    f"quay.{CUSTOM_DOMAIN}": "https://quay.io",
    f"gcr.{CUSTOM_DOMAIN}": "https://gcr.io",
    f"k8s-gcr.{CUSTOM_DOMAIN}": "https://k8s.gcr.io",
    f"k8s.{CUSTOM_DOMAIN}": "https://registry.k8s.io",
    f"ghcr.{CUSTOM_DOMAIN}": "https://ghcr.io",
    f"cloudsmith.{CUSTOM_DOMAIN}": "https://docker.cloudsmith.io",
    f"ecr.{CUSTOM_DOMAIN}": "https://public.ecr.aws",
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
    'date',
]

# 忽略请求的header的key集合
ignore_headers = [
    'host',
    'x-real-ip',
    'x-forwarded-for',
    'x-forwarded-proto',
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


# 从请求头中提取 JWT 令牌
def valid_jwt_and_remove_from_headers(headers):
    auth_header = headers.get('authorization', None)
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        try:
            # 解码并验证令牌
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            # 获取当前时间
            current_time = datetime.datetime.utcnow()
            # 获取令牌中的过期时间
            exp_time = datetime.datetime.utcfromtimestamp(decoded_token['exp'])
            # 检查令牌是否已过期
            if current_time > exp_time:
                print("JWT 令牌已失效")
                del headers["authorization"]
            else:
                print("JWT 令牌有效")
        except ExpiredSignatureError:
            del headers["authorization"]
            print("JWT 令牌已过期")
        except DecodeError:
            del headers["authorization"]
            print("JWT 令牌无效")
    return headers

# 处理所有传入的请求
@app.middleware("http")
async def handle_request(request: Request, call_next):
    try:
        # 获取请求体
        method = request.method.lower()
        url = str(request.url)
        body = await request.body()
        # 原始字典
        headers = dict(request.headers)
        proxy = False

        logging.info(f'接收到请求\n【{method}】: {url} \n【headers】: {headers}')

        # 白名单中的path不进行转发
        if request.url.path in path_whitelist:
            logging.info(f'未代理转发\n【{method}】: {url} \n【headers】: {headers}')
            return await call_next(request)

        for route in routes:
            route_url = f'{request.url.scheme}://{route}'
            if url.startswith(route_url):
                proxy = True
                url = url.replace(route_url, routes[route])
                pass

        if not proxy:
            return await call_next(request)

        # 过滤headers保留reserved_headers中的key
        # headers = {key: headers[key] for key in reserved_headers if key in headers}
        # 过滤headers忽略ignore_headers中的key
        headers = {key: value for key, value in headers.items() if key not in ignore_headers}

        headers = valid_jwt_and_remove_from_headers(headers)

        # 处理获取token的请求参数,如果镜像是基础镜像并且未带library则补全
        # Example: repository:busybox:pull => repository:library/busybox:pull
        if url.startswith('https://auth.docker.io/token'):
            if request.scope['query_string']:
                query_string = request.scope['query_string'].decode('utf-8')
                query_string = unquote(query_string)
                splits = query_string.split(':')
                if len(splits) == 3 and '/' not in splits[1]:
                    splits[1] = f'library/{splits[1]}'
                    new_query_string = ':'.join(splits)
                    new_query_string = quote(new_query_string)
                    url = f'https://auth.docker.io/token?{new_query_string}'

        # 处理获取镜像的地址,如果是基础镜像并且未带library，则补全
        # https://registry-1.docker.io/v2/nginx/manifests/latest
        # Example: /v2/busybox/manifests/latest => /v2/library/busybox/manifests/latest
        docker_registry_prefix_url = 'https://registry-1.docker.io/v2/'
        if url.startswith(docker_registry_prefix_url) and len(url) > len(docker_registry_prefix_url):
            _url = url.replace(docker_registry_prefix_url, '')
            path_parts = _url.split('/')
            # 只有基础镜像切割后分成3块，大于3的都是带了前缀的
            if len(path_parts) == 3:
                path_parts[0] = f'library/{path_parts[0]}'
                url = f'{docker_registry_prefix_url}{"/".join(path_parts)}'
            pass

        logging.info(f'代理转发\n【{method}】: {url} \n【headers】: {headers}')
        connector = ProxyConnector.from_url(PROXY_URL) if PROXY_URL else None
        async with (aiohttp.ClientSession(
                connector=connector,
                timeout=ClientTimeout(total=300, connect=60, sock_read=300, sock_connect=300, ceil_threshold=5),
        ) as session):
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
                    logging.info(f'返回结果 【{resp.status}】\n【{method}】: {url}\n【headers】: {response_headers}')
                    # logging.info(f'返回结果\n【{method}】: {url}\n【headers】: {response_headers}\n【content】: {response_body}')
                    return Response(content=response_body, status_code=resp.status, headers=response_headers)
                except Exception as e:
                    logger.error(f"Error processing response: {e}")
                    return JSONResponse({"error": "Internal Server Error"}, status_code=500)
    except BaseException as e:
        return JSONResponse({"error": repr(e)}, status_code=500)


# 启动应用程序
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
