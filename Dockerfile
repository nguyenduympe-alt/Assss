FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DB_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8080
CMD ["sh", "-c", "gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 120"]
