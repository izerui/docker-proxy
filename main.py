import logging

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

app = FastAPI(
    title='docker代理',
    summary='docker代理',
    description='docker代理仓库',
    version='1.0',
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    }
)

app.mount("/rag/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

my_domain = 'serv999.com'


@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(
        request=request, name="help.html", context={"my_domain": my_domain}
    )


image_mirros = {
    f'https://hub.{my_domain}/': 'https://hub.docker.com/',
    f'https://docker.{my_domain}/': 'https://registry-1.docker.io/',
    f'https://quay.{my_domain}/': 'https://quay.io/',
    f'https://gcr.{my_domain}/': 'https://gcr.io/',
    f'https://k8s-gcr.{my_domain}/': 'https://k8s.gcr.io/',
    f'https://k8s.{my_domain}/': 'https://registry.k8s.io/',
    f'https://ghcr.{my_domain}/': 'https://ghcr.io/',
    f'https://cloudsmith.{my_domain}/': 'https://docker.cloudsmith.io/',
    f'https://ecr.{my_domain}/': 'https://public.ecr.aws/',
}


@app.middleware("http")
async def proxy_middleware(request: Request, call_next):
    try:

        logging.info(f'---> {request.method.lower()}: {request.url} headers: {request.headers}')
        target_url = str(request.url)
        # 构建目标 URL，包括查询字符串
        replace_base_url = image_mirros.get(str(request.base_url), None)
        if not replace_base_url:
            return await call_next(request)

        target_url = target_url.replace(str(request.base_url), replace_base_url)

        # 使用 aiohttp 发送请求
        async with aiohttp.ClientSession() as session:
            # 获取请求方法
            method = request.method.lower()

            # 获取请求体
            body = await request.body()

            # 获取请求头
            headers = {k: v for k, v in request.headers.items() if
                       k in ["Authorization", "WWW-Authenticate"]}

            logging.info(f'<--- {method}: {target_url} headers: {headers}')
            # 发送请求到目标地址
            async with session.request(method, target_url, headers=headers, data=body) as response:
                # 获取响应内容
                content = await response.read()

                # 获取响应头
                response_headers = dict(response.headers)

                # 返回目标地址的响应
                return Response(content=content, status_code=response.status, headers=response_headers)
    except BaseException as e:
        logging.exception(e)
        return HTMLResponse(content=f'出错了: {repr(e)}', status_code=500)


@app.get("/test")
async def test():
    return {"message": "This is a test endpoint"}


# 运行应用
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
