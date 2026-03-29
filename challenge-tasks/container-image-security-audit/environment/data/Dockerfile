FROM python:latest

ENV DATABASE_PASSWORD=supersecret123
ENV API_KEY=sk-1234567890abcdef
ENV JWT_SECRET=my-super-secret-key-12345

RUN apt-get update && apt-get install -y vim curl wget netcat net-tools iputils-ping

COPY requirements.txt /app/requirements.txt
WORKDIR /app

RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/
COPY config.json /app/

RUN chmod 777 /app

EXPOSE 8080 9090

CMD ["python", "app.py"]
