FROM python:3.12-slim

WORKDIR /app

COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY web/ /app/web/

ENV PORT=8080

CMD ["python", "-m", "backend.app"]
