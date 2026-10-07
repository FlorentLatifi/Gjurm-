#!/usr/bin/env bash
# Zero-touch deploy of one image tag, with health verification and automatic rollback.
#
#   ./deploy.sh <image-tag>          # normally called by CI over SSH with the git SHA
#   ./deploy.sh --rollback           # redeploy the previously deployed tag
#
# Migrations run before the new containers start. Schema changes must be backward compatible
# with the previous release (expand → migrate → contract across two releases), so rolling the
# application back never requires rolling the database back. See docs/OPERATIONS.md.
set -euo pipefail
cd "$(dirname "$0")"
COMPOSE=(docker compose -f docker-compose.prod.yml)
STATE=.deploy-state
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-120}
# Rehearsal-only knobs (never set in production): skip the registry pull when images were built
# locally, and extra curl flags (e.g. -k for Caddy's internal CA when DOMAIN=localhost).
DEPLOY_SKIP_PULL=${DEPLOY_SKIP_PULL:-0}
read -r -a CURL_EXTRA <<< "${DEPLOY_CURL_OPTS:-}"

set -a; source .env; set +a
current="$(cat "$STATE/current" 2>/dev/null || true)"
previous="$(cat "$STATE/previous" 2>/dev/null || true)"
mkdir -p "$STATE"

if [[ "${1:-}" == "--rollback" ]]; then
  [[ -n "$previous" ]] || { echo "no previous release recorded" >&2; exit 1; }
  target="$previous"
else
  target="${1:?usage: deploy.sh <image-tag> | --rollback}"
fi
[[ "$target" =~ ^[A-Za-z0-9._-]{1,128}$ ]] || { echo "invalid tag: $target" >&2; exit 2; }

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT))
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 5 "${CURL_EXTRA[@]}" "https://${DOMAIN}/health/ready" >/dev/null 2>&1 &&
       curl -fsS --max-time 5 "${CURL_EXTRA[@]}" "https://${DOMAIN}/api/v1/status" >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

switch_to() {
  local tag="$1"
  export IMAGE_TAG="$tag"
  if [[ "$DEPLOY_SKIP_PULL" != "1" ]]; then
    log "pulling images $tag"
    "${COMPOSE[@]}" pull --quiet migrate api scheduler web || return 1
  fi
  log "running migrations"
  "${COMPOSE[@]}" up -d db || return 1
  "${COMPOSE[@]}" run --rm migrate || return 1
  log "starting containers"
  local services=(db api scheduler web backup)
  # Optional local model (COMPOSE_PROFILES=local-llm in .env): named services ignore profiles.
  [[ ",${COMPOSE_PROFILES:-}," == *",local-llm,"* ]] && services+=(ollama)
  "${COMPOSE[@]}" up -d --remove-orphans "${services[@]}"
}

log "deploying $target (current: ${current:-none})"
if ! switch_to "$target"; then
  # Pull or migration failed before any container was replaced: the running release is intact.
  log "deploy ABORTED before switching containers; ${current:-previous} release still running"
  exit 1
fi
if healthy; then
  if [[ "$target" != "$current" ]]; then
    [[ -n "$current" ]] && echo "$current" > "$STATE/previous"
    echo "$target" > "$STATE/current"
  fi
  "${COMPOSE[@]}" ps
  docker image prune -f --filter "until=168h" >/dev/null || true
  log "deploy OK: $target"
  exit 0
fi

log "health check FAILED for $target"
if [[ -n "$current" && "$current" != "$target" ]]; then
  log "rolling back to $current"
  switch_to "$current"
  healthy && log "rollback OK: $current" || log "ROLLBACK ALSO UNHEALTHY — manual intervention needed"
fi
exit 1
