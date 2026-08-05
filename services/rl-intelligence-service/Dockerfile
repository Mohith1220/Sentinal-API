FROM python:3.11-slim

WORKDIR /app

# System deps: curl for healthcheck, gcc for some Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Install shared library first (cached layer)
COPY sentinel_shared/ /app/sentinel_shared/
RUN pip install --no-cache-dir -e /app/sentinel_shared

# Copy service code
COPY services/rl-intelligence-service/ /app/

# Install service dependencies (heavy packages: torch, sb3, xgboost, shap)
RUN pip install --no-cache-dir --timeout=300 \
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
    torch==2.3.0 \
    "stable-baselines3[extra]==2.3.2" \
    "gymnasium==0.29.1" \
    numpy==1.26.4 \
    scikit-learn==1.4.2 \
    xgboost==2.0.3 \
    shap==0.45.0 \
    "neo4j==5.19.0" \
    networkx==3.3

# Create model artifact directory
RUN mkdir -p /models/rl_policies

EXPOSE 8008

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=60s \
    CMD curl -sf http://localhost:8008/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8008"]
