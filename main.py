import datetime
import logging
import os
from urllib.parse import unquote, urlparse, quote

import aiohttp
import jwt
from aiohttp import ClientTimeout
from aiohttp_socks import ProxyConnector
from colorama import Style, Fore
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from jwt import ExpiredSignatureError, DecodeError
from prettytable import PrettyTable
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

# 设置日志记录
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# 从环境变量中获取自定义域名、模式和目标上游服务器
CUSTOM_DOMAIN = os.getenv("CUSTOM_DOMAIN", "serv999.com")

# 从环境变量中获取代理 URL，本地开发调试需要设置代理，否则无法正常访问docker、gcr等外网仓库
PROXY_URL = os.getenv("PROXY_URL", None)

# 环境
PROFILE = os.getenv("PROFILE", 'production')

# 代理转发路径前缀匹配规则
routes = {
    f"docker-auth.{CUSTOM_DOMAIN}": "auth.docker.io",
    f"docker.{CUSTOM_DOMAIN}": "registry-1.docker.io",
    f"quay.{CUSTOM_DOMAIN}": "quay.io",
    f"gcr.{CUSTOM_DOMAIN}": "gcr.io",
    f"k8s-gcr.{CUSTOM_DOMAIN}": "k8s.gcr.io",
    f"k8s.{CUSTOM_DOMAIN}": "registry.k8s.io",
    f"ghcr.{CUSTOM_DOMAIN}": "ghcr.io",
    f"cloudsmith.{CUSTOM_DOMAIN}": "docker.cloudsmith.io",
    f"ecr.{CUSTOM_DOMAIN}": "public.ecr.aws",
}

# 白名单路径不进行转发
path_whitelist = [
    '/'
]

# 保留请求的header的key集合
reserved_headers = [
    'authorization',
    'accept',
    'accept-encoding',
]

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


def pretty_headers(headers, title_name, title_value):
    pretty_headers_table = PrettyTable([title_name, title_value])
    for k, v in headers.items():
        pretty_headers_table.add_row([k, f'{v[:150]}...' if len(v) > 150 else v])
    return pretty_headers_table


# 碰到的问题: https://github.com/docker/hub-feedback/issues/1636 , 实际解决是因为url地址编码不对，应该只针对参数值进行编码
# 处理所有传入的请求
@app.middleware("http")
async def handle_request(request: Request, call_next):
    try:
        # 获取请求体
        method = request.method.lower()
        origin_url = str(request.url)
        body = await request.body()
        # 原始字典
        origin_headers = dict(request.headers)
        proxy = False

        # logging.info(f'接收请求\n【{method}】: {url} \n【headers】: {headers}')

        # 白名单中的path不进行转发
        if request.url.path in path_whitelist:
            return await call_next(request)

        # 根据路由进行匹配转发
        url = origin_url
        for route in routes:
            route_url = f'{request.url.scheme}://{route}'
            if url.startswith(route_url):
                proxy = True
                url = url.replace(route_url, f'https://{routes[route]}')
                pass

        # 未匹配转发
        if not proxy:
            logging.info(
                f'\n【请求地址】{method}: {str(request.url)}\n{Fore.CYAN}{pretty_headers(origin_headers, "请求头", "请求值")}{Style.RESET_ALL}')
            return await call_next(request)

        # 过滤headers保留reserved_headers中的key
        headers = {key: value for key, value in origin_headers.items() if key.lower() in reserved_headers}
        # headers = valid_jwt_and_remove_from_headers(headers)

        url_parse = urlparse(url)

        # docker中央仓库获取token需要将基础镜像增加前缀 library
        # 处理获取token的请求参数,如果镜像是基础镜像并且未带library则补全,并且移除headers中的 Authenticate
        # Example: repository:busybox:pull => repository:library/busybox:pull
        if url_parse.netloc == 'auth.docker.io' and url_parse.path == '/token':
            if 'authorization' in headers:
                del headers['authorization']
            if url_parse.query:
                query_string = url_parse.query
                params = query_string.split('&')
                for index, param in enumerate(params):
                    kv = param.split('=')
                    if kv[0] == 'scope':
                        v = kv[1]
                        v = unquote(v)
                        if '/' not in v:
                            vsplit = v.split(':')
                            vsplit[1] = f'library/{vsplit[1]}'
                            new_scope = f'{kv[0]}={quote(":".join(vsplit))}'
                            params[index] = new_scope
                            query_string = '&'.join(params)
                            url = f'{url_parse.scheme}://{url_parse.netloc}{url_parse.path}?{query_string}'

        # 兼容其他仓库的token验证, 其他仓库不需要增加library前缀
        if url_parse.path == '/v2/auth':
            if 'authorization' in headers:
                del headers['authorization']

        # docker中央仓库需要 处理获取镜像的地址,如果是基础镜像并且未带library，则补全
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

        connector = ProxyConnector.from_url(PROXY_URL) if PROXY_URL else None
        async with (aiohttp.ClientSession(
                connector=connector,
                timeout=ClientTimeout(total=300, connect=60, sock_read=300, sock_connect=300, ceil_threshold=300),
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
                            if value in www_auth:
                                # 将返回的realm的域名替换为代理域名,让docker或者contanerd访问自定义域名进行授权
                                www_auth = www_auth.replace(value, key, 1)
                                response_headers['WWW-Authenticate-pre-modify'] = response_headers['WWW-Authenticate']
                                response_headers['WWW-Authenticate'] = www_auth
                                break

                    # 删除分段传输的头, 这里应该有nginx转发来自动判断是否添加，原始服务器返回的该头针对当前nginx代理不一定匹配
                    if 'Transfer-Encoding' in response_headers:
                        del response_headers['Transfer-Encoding']

                    logging.info(
                        f'\n【请求地址】{method}: {str(request.url)} {"200 OK" if resp.status == 200 else resp.status}\n【转发地址】{method}: {url} {"200 OK" if resp.status == 200 else resp.status}\n【返回内容】: {f"{response_body[:150]}..." if len(response_body) > 150 else response_body}\n{Fore.CYAN}{pretty_headers(origin_headers, "原始请求头", "原始请求值")}\n{pretty_headers(headers, "代理请求头", "代理请求值")}\n{pretty_headers(response_headers, "响应头", "响应值")}{Style.RESET_ALL}')
                    return Response(content=response_body, status_code=resp.status, headers=response_headers)
                except Exception as e:
                    logger.error(f"Error processing response: {e}")
                    return JSONResponse({"error": "Internal Server Error"}, status_code=500)
    except BaseException as e:
        logger.exception(e)
        return JSONResponse({"error": repr(e)}, status_code=500)


# 启动应用程序
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
