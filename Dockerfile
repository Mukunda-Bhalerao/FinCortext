# FinCortext as one container: the interface is built, then served by the API process, so a
# deployment has a single origin, no CORS and one URL.
#
#   docker build -t fincortext .
#   docker run -p 8000:8000 --env-file .env -v fincortext-data:/data fincortext
#
# The database lives in /data. Mount a volume there to keep portfolios across restarts; on a
# platform without persistent storage it is rebuilt empty, and cached market data refills
# itself from the providers.

# --- build the interface -------------------------------------------------------------------
FROM node:20-alpine AS interface
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- run the backend and serve the interface -------------------------------------------------
FROM python:3.11-slim AS app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DUCKDB_PATH=/data/fincortext.duckdb \
    STATIC_DIR=/srv/static \
    LLM_PROVIDER=none

WORKDIR /srv
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir . && mkdir -p /data

# The API serves these; app/api/static.py looks for /srv/static first.
COPY --from=interface /build/dist ./static

# A non-root user owns the database directory.
RUN useradd --system --uid 10001 fincortext && chown -R fincortext /data /srv
USER fincortext

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8000') + '/api/health', timeout=4).status == 200 else 1)"

# Hosts such as Render and Railway choose the port; default to 8000 locally.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
