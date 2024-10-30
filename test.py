import asyncio

import aiohttp


async def fetch():
    # 使用 aiohttp 发送请求
    async with aiohttp.ClientSession() as session:
        # 发送请求到目标地址
        async with session.request('get', 'https://yj2025.com/terms.html') as response:
            # 获取响应内容
            content = await response.read()

            # 获取响应头
            response_headers = dict(response.headers)

            with open('terms.html', 'wb') as f:
                f.write(content)

            print(response_headers, content)


if __name__ == '__main__':
    # 运行异步主函数
    asyncio.run(fetch())
