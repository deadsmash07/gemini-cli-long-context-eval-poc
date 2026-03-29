FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    procps \
    && pip install --no-cache-dir pytest==8.2.2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app/ /app/
ENV PYTHONPATH=/app:$PYTHONPATH
