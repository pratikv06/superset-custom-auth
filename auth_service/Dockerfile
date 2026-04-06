FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

RUN mkdir -p /app/data

ENV DB_PATH=/app/data/auth.db \
    SECRET_KEY=change-me-in-production \
    ACCESS_TOKEN_EXPIRE_MINUTES=30 \
    REFRESH_TOKEN_EXPIRE_DAYS=7

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
