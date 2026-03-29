FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y bash tmux asciinema grep \
    && pip install --no-cache-dir pytest==8.2.2 PyYAML==6.0.1 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/input /app/input/crontab.d /app/output /usr/local/bin

COPY task-deps/ /app/input/
