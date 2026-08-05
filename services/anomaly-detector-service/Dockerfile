FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY sentinel_shared/ /app/sentinel_shared/
COPY services/anomaly-detector-service/ /app/

RUN pip install --no-cache-dir -e /app/sentinel_shared && \
    pip install --no-cache-dir \
        fastapi==0.111.0 \
        "uvicorn[standard]==0.29.0" \
        pydantic==2.7.1 \
        sqlalchemy==2.0.30 \
        asyncpg==0.29.0 \
        aiokafka==0.10.0 \
        structlog==24.1.0 \
        apscheduler==3.10.4 \
        prometheus-fastapi-instrumentator==7.0.0 \
        httpx==0.27.0 \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        torch==2.3.0+cpu \
        shap==0.45.0 \
        numpy==1.26.4 \
        scipy==1.13.0

EXPOSE 8005

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
