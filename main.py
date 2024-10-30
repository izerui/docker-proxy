import aiohttp
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

app = FastAPI()

dockerHub = "https://registry-1.docker.io"

CUSTOM_DOMAIN = 'serv999.com'

app.mount("/rag/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/help", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(
        request=request, name="help.html", context={"my_domain": my_domain}
    )


routes = {
    # production
    f"docker.{CUSTOM_DOMAIN}": dockerHub,
    f"quay.{CUSTOM_DOMAIN}": "https://quay.io",
    f"gcr.{CUSTOM_DOMAIN}": "https://gcr.io",
    f"k8s-gcr.{CUSTOM_DOMAIN}": "https://k8s.gcr.io",
    f"k8s.{CUSTOM_DOMAIN}": "https://registry.k8s.io",
    f"ghcr.{CUSTOM_DOMAIN}": "https://ghcr.io",
    f"cloudsmith.{CUSTOM_DOMAIN}": "https://docker.cloudsmith.io",
    f"ecr.{CUSTOM_DOMAIN}": "https://public.ecr.aws",

    # staging
    f"docker-staging.{CUSTOM_DOMAIN}": dockerHub,
}


def route_by_hosts(host):
    if host in routes:
        return routes[host]
    return ""


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


def parse_authenticate(authenticate_str):
    parts = authenticate_str.split(',')
    realm = parts[0].split('=')[1].strip('"')
    service = parts[1].split('=')[1].strip('"')
    return {
        "realm": realm,
        "service": service
    }


async def response_unauthorized(url):
    headers = {
        'WWW-Authenticate': f'Bearer realm="https://{url.netloc}/v2/auth",service="cloudflare-docker-proxy"'
    }
    return JSONResponse({"message": "UNAUTHORIZED"}, status_code=401, headers=headers)


@app.middleware("http")
async def handle_request(request: Request, call_next):
    url = request.url
    upstream = route_by_hosts(url.hostname)
    if not upstream:
        return JSONResponse({"routes": routes}, status_code=404)

    is_docker_hub = upstream == dockerHub
    authorization = request.headers.get("Authorization")

    if url.path == "/v2/":
        new_url = f"{upstream}/v2/"
        headers = {"Authorization": authorization} if authorization else {}
        async with aiohttp.ClientSession() as session:
            async with session.get(new_url, headers=headers) as resp:
                if resp.status == 401:
                    return await response_unauthorized(url)
                return Response(content=await resp.read(), status_code=resp.status, headers=dict(resp.headers))

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

    if is_docker_hub:
        path_parts = url.path.split("/")
        if len(path_parts) == 5:
            path_parts.insert(2, "library")
            redirect_url = url.replace(path="/".join(path_parts))
            return RedirectResponse(url=str(redirect_url), status_code=301)

    new_url = f"{upstream}{url.path}"
    headers = dict(request.headers)
    async with aiohttp.ClientSession() as session:
        async with session.request(method=request.method, url=new_url, headers=headers, allow_redirects=True) as resp:
            if resp.status == 401:
                return await response_unauthorized(url)
            return Response(content=await resp.read(), status_code=resp.status, headers=dict(resp.headers))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
