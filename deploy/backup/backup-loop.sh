#!/bin/sh
# Long-running backup scheduler: daily dump at BACKUP_HOUR_UTC, restore check every Sunday.
set -u
HOUR="${BACKUP_HOUR_UTC:-2}"
DIR="$(dirname "$0")"
echo "backup loop started; daily at ${HOUR}:00 UTC"

notify_restore_failed() { # best-effort, same payload shape as backup.sh (slack/discord/generic)
  [ -n "${ALERT_WEBHOOK_URL:-}" ] || return 0
  msg="Weekly restore verification failed; the newest dump may not be restorable. See: docker compose -f docker-compose.prod.yml logs backup"
  wget -q -O /dev/null --timeout=10 --header "Content-Type: application/json" \
    --post-data "{\"key\":\"restore_verification_failed\",\"severity\":\"critical\",\"title\":\"Restore verification failed\",\"message\":\"$msg\",\"text\":\"[GJURMË] $msg\",\"content\":\"[GJURMË] $msg\"}" \
    "$ALERT_WEBHOOK_URL" || true
}
while true; do
  now="$(date -u +%s)"
  target="$(date -u -d "@$now" +%Y-%m-%d)"
  next="$(date -u -d "$target $HOUR:00:00" +%s 2>/dev/null || date -u -D '%Y-%m-%d %H:%M:%S' -d "$target $HOUR:00:00" +%s)"
  [ "$next" -gt "$now" ] || next=$((next + 86400))
  echo "next backup in $(( (next - now) / 60 )) minutes"
  sleep $((next - now))
  if sh "$DIR/backup.sh"; then
    if [ "$(date -u +%u)" = "7" ]; then
      sh "$DIR/verify-restore.sh" || { echo "restore verification FAILED"; notify_restore_failed; }
    fi
  fi
done
