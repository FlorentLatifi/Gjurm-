#!/bin/sh
# One backup run: pg_dump (custom format) → integrity check → rotate.
# Layout:  $BACKUP_DIR/daily/gjurme-YYYYmmddTHHMMZ.dump   (RETAIN_DAILY newest kept)
#          $BACKUP_DIR/weekly/gjurme-YYYYmmddTHHMMZ.dump  (Sunday copies, RETAIN_WEEKLY kept)
#          $BACKUP_DIR/status.json                        (last result, for humans & monitoring)
# Every way this script can end without a verified dump sends the failure alert (an EXIT trap),
# and BACKUP_HEALTHCHECK_URL, if set, is pinged on success: an external dead-man check
# (healthchecks.io or similar) then alerts when a backup silently stops happening at all.
set -eu
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETAIN_DAILY="${RETAIN_DAILY:-7}"
RETAIN_WEEKLY="${RETAIN_WEEKLY:-4}"
stamp="$(date -u +%Y%m%dT%H%MZ)"
tmp="$BACKUP_DIR/daily/.gjurme-$stamp.dump.partial"
final="$BACKUP_DIR/daily/gjurme-$stamp.dump"
finished=0

notify() { # best-effort failure alert through the same webhook the app uses
  [ -n "${ALERT_WEBHOOK_URL:-}" ] || return 0
  wget -q -O /dev/null --timeout=10 --header "Content-Type: application/json" \
    --post-data "{\"key\":\"backup_failed\",\"severity\":\"critical\",\"title\":\"Backup failed\",\"message\":\"$1\",\"text\":\"[GJURMË] Backup failed: $1\",\"content\":\"[GJURMË] Backup failed: $1\"}" \
    "$ALERT_WEBHOOK_URL" || true
}
ping_check() { # optional dead-man check: "" on success, "/fail" on failure
  [ -n "${BACKUP_HEALTHCHECK_URL:-}" ] || return 0
  wget -q -O /dev/null --timeout=10 "${BACKUP_HEALTHCHECK_URL}$1" || true
}
# Alert first: the status file lives in the backup directory, which may be the very thing that
# is broken (not writable, disk full).
fail() {
  finished=1
  rm -f "$tmp"
  notify "$1"
  ping_check /fail
  (echo "{\"ok\": false, \"at\": \"$stamp\", \"error\": \"$1\"}" > "$BACKUP_DIR/status.json") 2>/dev/null || true
  echo "backup FAILED: $1" >&2
  exit 1
}
on_exit() {
  code=$?
  [ "$finished" = 1 ] && return 0
  rm -f "$tmp"
  notify "backup aborted unexpectedly (exit $code); see: docker compose logs backup"
  ping_check /fail
}
trap on_exit EXIT

echo "backup started $stamp"
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" 2>/dev/null \
  || fail "cannot create $BACKUP_DIR/daily (the directory must be writable by UID 70)"
[ -w "$BACKUP_DIR/daily" ] || fail "$BACKUP_DIR/daily is not writable by UID 70"
pg_dump --format=custom --compress=6 --no-owner --no-privileges --file="$tmp" || fail "pg_dump error"
# Integrity: the archive's table of contents must be readable and contain our core tables.
pg_restore --list "$tmp" > /tmp/toc.txt 2>/dev/null || fail "dump unreadable"
grep -q "TABLE DATA core articles" /tmp/toc.txt || fail "dump lacks core.articles"
mv "$tmp" "$final" || fail "cannot move the dump into place (disk full?)"
size="$(wc -c < "$final" | tr -d ' ')"

if [ "$(date -u +%u)" = "7" ]; then cp "$final" "$BACKUP_DIR/weekly/" || fail "weekly copy failed"; fi
# Rotation: keep the newest N files of each tier.
ls -1t "$BACKUP_DIR"/daily/gjurme-*.dump 2>/dev/null | tail -n +"$((RETAIN_DAILY + 1))" | xargs -r rm -f
ls -1t "$BACKUP_DIR"/weekly/gjurme-*.dump 2>/dev/null | tail -n +"$((RETAIN_WEEKLY + 1))" | xargs -r rm -f

echo "{\"ok\": true, \"at\": \"$stamp\", \"file\": \"$final\", \"bytes\": $size}" > "$BACKUP_DIR/status.json"
finished=1
ping_check ""
echo "backup ok $final ($size bytes)"
