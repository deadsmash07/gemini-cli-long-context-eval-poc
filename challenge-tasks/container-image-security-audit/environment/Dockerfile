FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    tmux asciinema git curl build-essential procps \
    && pip3 install --no-cache-dir pytest==8.4.1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY data /app/data
