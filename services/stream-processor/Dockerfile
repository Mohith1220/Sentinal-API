FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY sentinel_shared/ /app/sentinel_shared/
COPY services/stream-processor/ /app/

RUN pip install --no-cache-dir -e /app/sentinel_shared && \
    pip install --no-cache-dir \
        fastapi==0.111.0 \
        "uvicorn[standard]==0.29.0" \
        pydantic==2.7.1 \
        aiokafka==0.10.0 \
        structlog==24.1.0 \
        prometheus-fastapi-instrumentator==7.0.0 \
        httpx==0.27.0

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
