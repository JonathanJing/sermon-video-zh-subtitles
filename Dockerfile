FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk nodejs poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
COPY packages/ /app/packages/
COPY services/api/ /app/services/api/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY tools/ops/sermon_unified_preflight.py /app/tools/ops/sermon_unified_preflight.py
COPY tools/ops/run.py /app/tools/ops/run.py
COPY tools/ops/run_openai_model_access_preflight.py /app/tools/ops/run_openai_model_access_preflight.py
COPY tools/ops/upload_file_to_gcs.py /app/tools/ops/upload_file_to_gcs.py
COPY tools/ops/export_playback_captions.py /app/tools/ops/export_playback_captions.py
COPY tools/ops/offline_live_sermon_subtitles.py /app/tools/ops/offline_live_sermon_subtitles.py
COPY tools/ops/prepare_live_link_playback.py /app/tools/ops/prepare_live_link_playback.py
COPY tools/ops/promote_sunday_manifest.py /app/tools/ops/promote_sunday_manifest.py
COPY tools/ops/translate_playback_with_openai.py /app/tools/ops/translate_playback_with_openai.py
COPY schemas/ /app/schemas/
COPY docs/series-terminology.zh.md /app/docs/series-terminology.zh.md
COPY data/scripture/ /app/data/scripture/
COPY apps/operator-web/ /app/apps/operator-web/

ENV PORT=8080

CMD ["python", "-m", "backend.app"]
