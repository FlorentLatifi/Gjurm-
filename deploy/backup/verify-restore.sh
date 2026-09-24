#!/bin/sh
# Restore verification: restore the newest dump into a scratch database, sanity-check it against
# the live database, then drop the scratch copy. A backup that has never been restored is a hope,
# not a backup. Runs weekly from backup-loop.sh; also safe to run by hand.
set -eu
BACKUP_DIR="${BACKUP_DIR:-/backups}"
SCRATCH="${SCRATCH_DB:-gjurme_restore_verify}"
latest="$(ls -1t "$BACKUP_DIR"/daily/gjurme-*.dump 2>/dev/null | head -1)"
[ -n "$latest" ] || { echo "no backups found" >&2; exit 1; }
stamp="$(date -u +%Y%m%dT%H%MZ)"
echo "verifying $latest into $SCRATCH"

psql -v ON_ERROR_STOP=1 -q -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH" -c "CREATE DATABASE $SCRATCH"
cleanup() { psql -q -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true; }
trap cleanup EXIT

if ! pg_restore --no-owner --no-privileges --exit-on-error -d "$SCRATCH" "$latest"; then
  echo "{\"ok\": false, \"at\": \"$stamp\", \"file\": \"$latest\", \"error\": \"pg_restore failed\"}" > "$BACKUP_DIR/verify.json"
  exit 1
fi
q() { psql -tA -d "$1" -c "$2"; }
restored_articles="$(q "$SCRATCH" 'SELECT count(*) FROM core.articles')"
restored_sources="$(q "$SCRATCH" 'SELECT count(*) FROM core.sources')"
restored_version="$(q "$SCRATCH" 'SELECT version_num FROM ops.alembic_version')"
live_articles="$(q "${PGDATABASE:-gjurme}" 'SELECT count(*) FROM core.articles')"
live_version="$(q "${PGDATABASE:-gjurme}" 'SELECT version_num FROM ops.alembic_version')"

ok=true
[ "$restored_sources" -gt 0 ] || ok=false
[ "$restored_articles" -le "$live_articles" ] || ok=false  # a backup cannot hold more than live
[ "$restored_version" = "$live_version" ] || echo "note: schema version differs (restore $restored_version, live $live_version)"
echo "{\"ok\": $ok, \"at\": \"$stamp\", \"file\": \"$latest\", \"restored_articles\": $restored_articles, \"live_articles\": $live_articles, \"restored_sources\": $restored_sources, \"schema\": \"$restored_version\"}" > "$BACKUP_DIR/verify.json"
cat "$BACKUP_DIR/verify.json"
[ "$ok" = true ]
