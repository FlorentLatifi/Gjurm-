# syntax=docker/dockerfile:1.7
# One image, three roles (selected by command):
#   api        uvicorn gjurme.api.app:create_app --factory ...   (default CMD)
#   scheduler  gjurme scheduler
#   migrate    gjurme db upgrade
ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- build: resolve & install deps
FROM python:${PYTHON_VERSION}-slim AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
# Optional extra CA bundle for builds behind a TLS-intercepting proxy (corporate networks):
#   docker build --secret id=ca_bundle,src=/path/to/ca.pem .
# A BuildKit secret is never written into an image layer; without it this is a no-op.
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install uv==0.8.17
WORKDIR /app
# Dependencies first (cached layer; only invalidated when the lockfile changes)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle UV_NATIVE_TLS=1; fi; \
    uv sync --frozen --no-dev --no-install-project
# Then the application itself, installed non-editable (source tree not needed at runtime)
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle UV_NATIVE_TLS=1; fi; \
    uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------- runtime: minimal, non-root
FROM python:${PYTHON_VERSION}-slim AS runtime
ARG VERSION=dev
LABEL org.opencontainers.image.title="gjurme" \
      org.opencontainers.image.description="GJURMË pipeline + API" \
      org.opencontainers.image.source="https://github.com/FlorentLatifi/Gjurm-" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    GJURME_VERSION="${VERSION}"
RUN groupadd --system --gid 10001 gjurme \
 && useradd --system --uid 10001 --gid gjurme --no-create-home --shell /usr/sbin/nologin gjurme
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
USER gjurme
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
# --proxy-headers: the client IP comes from Caddy's X-Forwarded-For (Caddy discards any
# client-supplied value), so rate limiting sees real client addresses.
CMD ["uvicorn", "gjurme.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
