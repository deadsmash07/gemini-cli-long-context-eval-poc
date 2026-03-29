FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    tmux \
    vim \
    sudo \
    asciinema \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest==8.2.0

WORKDIR /app
RUN mkdir -p /app/output/hooks /app/project /app/input /app/tests

CMD ["/bin/bash"]

