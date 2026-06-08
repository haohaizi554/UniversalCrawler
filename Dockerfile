FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UCRAWL_USER_DATA_ROOT=/data/user_data \
    UCRAWL_DOWNLOAD_ROOT=/data/downloads

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN mkdir -p /data/user_data /data/downloads

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/ping || exit 1

CMD ["python", "-m", "entry.web_entry", "--host", "0.0.0.0", "--port", "8000", "--no-qt", "--no-browser"]
