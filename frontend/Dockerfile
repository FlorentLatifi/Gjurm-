# syntax=docker/dockerfile:1.7
# Web edge image: the built SPA served by Caddy, which also terminates TLS and proxies /api.

# ---------------------------------------------------------------- build the SPA
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# Optional extra CA bundle for builds behind a TLS-intercepting proxy (see backend/Dockerfile).
RUN --mount=type=cache,target=/root/.npm --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_bundle; fi; \
    npm ci --no-audit --no-fund
COPY . .
ARG VITE_PUBLIC_URL=""
ARG VITE_API_BASE=""
ENV VITE_PUBLIC_URL=${VITE_PUBLIC_URL} VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

# ---------------------------------------------------------------- serve
FROM caddy:2-alpine
ARG VERSION=dev
LABEL org.opencontainers.image.title="gjurme-web" \
      org.opencontainers.image.source="https://github.com/FlorentLatifi/Gjurm-" \
      org.opencontainers.image.version="${VERSION}"
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
