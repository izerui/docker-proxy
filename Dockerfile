FROM python:3.10-slim

WORKDIR /data/www

COPY ./*.py ./
COPY ./requirements.txt ./

RUN pip cache purge
RUN pip install --no-cache-dir -r requirements.txt

CMD ["uvicorn", "main:app","--port", "8000",  "--host", "0.0.0.0", "--timeout-keep-alive", "60", "--workers", "8"]