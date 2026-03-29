FROM python:3.12-slim

WORKDIR /app


RUN apt-get update && apt-get install -y \
    tmux \
    asciinema \
    && pip install --no-cache-dir pytest==8.2.2 PyYAML==6.0.1 \
    && rm -rf /var/lib/apt/lists/*

COPY task-deps/ /app/input/

ENV PYTHONPATH=/app
