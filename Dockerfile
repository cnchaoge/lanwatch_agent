FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（SNMP 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    snmp \
    net-tools \
    iputils-ping \
    traceroute \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ .

EXPOSE 8000
# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
