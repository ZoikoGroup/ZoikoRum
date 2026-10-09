# Zoikorum backend image: one image, three roles (see docs/DEPLOYMENT.md)
#   API      (default)        uvicorn on :8000
#   worker                     python -m zoikorum.worker
#   migrate  (one-off job)     alembic upgrade head
# Configuration comes only from environment variables (ZK_*); no .env file is copied into the image.

FROM python:3.13-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Pinned versions first (cached layer).
COPY requirements.txt ./
RUN pip install -r requirements.txt
# Optional integrations: cloud = S3 storage, monitoring = error reporting, ai = Claude assistance.
# Only their dependencies are installed here: the application runs from /app/src (next to /app/alembic, which the
# startup schema check reads), so the package itself is removed again.
ARG EXTRAS="cloud,monitoring,ai"
COPY pyproject.toml ./
COPY src ./src
RUN if [ -n "$EXTRAS" ]; then pip install ".[${EXTRAS}]" && pip uninstall -y zoikorum; fi

FROM python:3.13-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ZK_ENV=production
RUN useradd --system --uid 10001 --home-dir /app zoikorum
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
# Local blob storage is for development only; production uses S3 (ZK_STORAGE_PROVIDER=s3).
RUN mkdir -p /app/var && chown zoikorum /app/var
USER zoikorum
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
# Settings are validated once before the web workers start, so a bad configuration exits with a clear message
# instead of workers restarting in a loop. The load balancer terminates TLS; trust its X-Forwarded-* headers.
CMD ["sh", "-c", "python -c 'from zoikorum.config import get_settings; get_settings()' && exec uvicorn zoikorum.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers ${WEB_CONCURRENCY:-2}"]
