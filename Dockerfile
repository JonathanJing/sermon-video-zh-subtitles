FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk nodejs poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
COPY packages/ /app/packages/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY schemas/ /app/schemas/
COPY data/scripture/ /app/data/scripture/
COPY apps/operator-web/ /app/apps/operator-web/

ENV PORT=8080

CMD ["python", "-m", "backend.app"]
