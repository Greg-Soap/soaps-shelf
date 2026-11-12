FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WTE_HOST=127.0.0.1 \
    WTE_PORT=8791 \
    WTE_URL=http://127.0.0.1:8791 \
    PORT=8000

# Node 20 for the WebToEpub headless runner
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg wget \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY compiler-js/package.json compiler-js/package-lock.json* ./compiler-js/
RUN cd compiler-js && npm install --omit=dev

COPY app ./app
COPY library ./library
COPY scripts ./scripts
COPY vendor ./vendor
COPY compiler-js ./compiler-js
COPY requirements.txt ./

RUN chmod +x /app/scripts/docker-entrypoint.sh \
    && mkdir -p /app/data/epubs /app/data/cache /app/data/raw

EXPOSE 8000

VOLUME ["/app/data"]

CMD ["/app/scripts/docker-entrypoint.sh"]
