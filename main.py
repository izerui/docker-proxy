import logging

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.responses import HTMLResponse

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

TARGET_URL = "https://harbor.yj2025.com/"  # 替换为你要重定向的目标地址

image_mirros = {
    'https://docker.serv999.com/': 'https://registry-1.docker.io/',
    'https://quay.serv999.com/': 'https://quay.io/',
    'https://gcr.serv999.com/': 'https://gcr.io/',
    'https://k8s-gcr.serv999.com/': 'https://k8s.gcr.io/',
    'https://k8s.serv999.com/': 'https://registry.k8s.io/',
    'https://ghcr.serv999.com/': 'https://ghcr.io/',
    'https://cloudsmith.serv999.com/': 'https://docker.cloudsmith.io/',
    'https://ecr.serv999.com/': 'https://public.ecr.aws/',
}


@app.middleware("http")
async def proxy_middleware(request: Request, call_next):
    try:

        logging.info(f'---> {request.method.lower()}: {request.url} headers: {request.headers}')
        # 构建目标 URL，包括查询字符串
        target_url = str(request.url).replace(str(request.base_url), TARGET_URL)

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
