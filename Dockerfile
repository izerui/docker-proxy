FROM python:3.10-slim

WORKDIR /data/www

COPY ./*.py ./
COPY ./requirements.txt ./
COPY ./static ./static
COPY ./templates ./templates

RUN pip config set global.index-url https://mirrors.cloud.tencent.com/pypi/simple/
RUN pip cache purge
RUN pip install --no-cache-dir -r requirements.txt

CMD ["uvicorn", "main:app","--port", "8000",  "--host", "0.0.0.0", "--timeout-keep-alive", "300", "--workers", "8"]