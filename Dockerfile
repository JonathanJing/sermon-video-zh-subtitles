FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY data/scripture/ /app/data/scripture/
COPY web/ /app/web/

ENV PORT=8080

CMD ["python", "-m", "backend.app"]
