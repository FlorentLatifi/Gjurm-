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
ARG VITE_CONTACT_URL=""
ENV VITE_PUBLIC_URL=${VITE_PUBLIC_URL} VITE_API_BASE=${VITE_API_BASE} \
    VITE_CONTACT_URL=${VITE_CONTACT_URL}
# the build manifest is for CI's bundle budgets only; it is not served
RUN npm run build && rm -rf dist/.vite

# ---------------------------------------------------------------- build Caddy
# The official caddy:2 image (v2.11.4, Go 1.26.3) carries 17 fixable HIGH CVEs in the Go stdlib
# and golang.org/x/{crypto,net,text} / grpc (Trivy, 2026-09-24). Build the same Caddy release
# with a patched toolchain and the fixed dependency versions instead of weakening the scan.
# x/net 0.60.0, go-jose/v4 4.1.6 and klauspost/compress 1.18.7 fix three more HIGH CVEs (Trivy,
# 2026-10-28); Caddy v2.11.7 still ships the vulnerable x/net and go-jose.
# Re-evaluate on each Caddy release: once upstream ships the fixes, the pins can go.
FROM golang:1.27-alpine AS caddy
ARG CADDY_VERSION=v2.11.4
WORKDIR /build
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    printf '%s\n' 'package main' \
      'import (' \
      '  caddycmd "github.com/caddyserver/caddy/v2/cmd"' \
      '  _ "github.com/caddyserver/caddy/v2/modules/standard"' \
      ')' \
      'func main() { caddycmd.Main() }' > main.go \
 && go mod init gjurme/caddy \
 && go get github.com/caddyserver/caddy/v2@${CADDY_VERSION} \
      golang.org/x/crypto@v0.57.0 golang.org/x/net@v0.60.0 golang.org/x/text@v0.42.0 \
      google.golang.org/grpc@v1.83.2 github.com/go-jose/go-jose/v4@v4.1.6 \
      github.com/klauspost/compress@v1.18.7 \
 && go mod tidy \
 && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /usr/bin/caddy . \
 && /usr/bin/caddy version

# ---------------------------------------------------------------- serve
FROM caddy:2-alpine
ARG VERSION=dev
LABEL org.opencontainers.image.title="gjurme-web" \
      org.opencontainers.image.source="https://github.com/FlorentLatifi/Gjurm-" \
      org.opencontainers.image.version="${VERSION}"
# The caddy:2-alpine tag is rebuilt later than Alpine publishes fixes: on 2026-10-28 it still had
# brotli-libs, curl and libcurl with fixable HIGH CVEs. Take the fixed packages at build time.
RUN apk upgrade --no-cache
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy
# Run unprivileged: the binary gets only the capability to bind :80/:443 (the production compose
# drops every other capability and adds NET_BIND_SERVICE back to the bounding set).
RUN setcap cap_net_bind_service=+ep /usr/bin/caddy \
 && adduser -D -H -u 10001 -s /sbin/nologin web \
 && chown -R web:web /data /config
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
USER web
