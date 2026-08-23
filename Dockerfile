FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libglib2.0-0 \
        libgl1 \
        libportaudio2 \
        portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .
RUN chmod +x scripts/start_web_api.sh

EXPOSE 8000
CMD ["./scripts/start_web_api.sh"]
