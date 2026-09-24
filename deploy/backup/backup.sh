#!/bin/sh
# One backup run: pg_dump (custom format) → integrity check → rotate.
# Layout:  $BACKUP_DIR/daily/gjurme-YYYYmmddTHHMMZ.dump   (RETAIN_DAILY newest kept)
#          $BACKUP_DIR/weekly/gjurme-YYYYmmddTHHMMZ.dump  (Sunday copies, RETAIN_WEEKLY kept)
#          $BACKUP_DIR/status.json                        (last result, for humans & monitoring)
set -eu
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETAIN_DAILY="${RETAIN_DAILY:-7}"
RETAIN_WEEKLY="${RETAIN_WEEKLY:-4}"
stamp="$(date -u +%Y%m%dT%H%MZ)"
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly"
tmp="$BACKUP_DIR/daily/.gjurme-$stamp.dump.partial"
final="$BACKUP_DIR/daily/gjurme-$stamp.dump"

notify() { # best-effort failure alert through the same webhook the app uses
  [ -n "${ALERT_WEBHOOK_URL:-}" ] || return 0
  wget -q -O /dev/null --timeout=10 --header "Content-Type: application/json" \
    --post-data "{\"key\":\"backup_failed\",\"severity\":\"critical\",\"title\":\"Backup failed\",\"message\":\"$1\",\"text\":\"[GJURMË] Backup failed: $1\",\"content\":\"[GJURMË] Backup failed: $1\"}" \
    "$ALERT_WEBHOOK_URL" || true
}
fail() { echo "{\"ok\": false, \"at\": \"$stamp\", \"error\": \"$1\"}" > "$BACKUP_DIR/status.json"; notify "$1"; echo "backup FAILED: $1" >&2; exit 1; }

echo "backup started $stamp"
pg_dump --format=custom --compress=6 --no-owner --no-privileges --file="$tmp" || { rm -f "$tmp"; fail "pg_dump error"; }
# Integrity: the archive's table of contents must be readable and contain our core tables.
pg_restore --list "$tmp" > /tmp/toc.txt 2>/dev/null || { rm -f "$tmp"; fail "dump unreadable"; }
grep -q "TABLE DATA core articles" /tmp/toc.txt || { rm -f "$tmp"; fail "dump lacks core.articles"; }
mv "$tmp" "$final"
size="$(wc -c < "$final" | tr -d ' ')"

if [ "$(date -u +%u)" = "7" ]; then cp "$final" "$BACKUP_DIR/weekly/"; fi
# Rotation: keep the newest N files of each tier.
ls -1t "$BACKUP_DIR"/daily/gjurme-*.dump 2>/dev/null | tail -n +"$((RETAIN_DAILY + 1))" | xargs -r rm -f
ls -1t "$BACKUP_DIR"/weekly/gjurme-*.dump 2>/dev/null | tail -n +"$((RETAIN_WEEKLY + 1))" | xargs -r rm -f

echo "{\"ok\": true, \"at\": \"$stamp\", \"file\": \"$final\", \"bytes\": $size}" > "$BACKUP_DIR/status.json"
echo "backup ok $final ($size bytes)"
