FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y bash tmux asciinema && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pytest==8.2.0

RUN mkdir -p /app/input/pipeline /app/output /usr/local/bin

WORKDIR /app

