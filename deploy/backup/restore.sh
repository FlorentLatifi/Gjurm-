#!/bin/sh
# Disaster recovery: restore a dump over the live database. DESTRUCTIVE.
# Run from the server:  docker compose -f docker-compose.prod.yml stop api scheduler
#                       docker compose -f docker-compose.prod.yml run --rm -e CONFIRM=yes \
#                         backup sh /scripts/restore.sh /backups/daily/gjurme-<stamp>.dump
#                       docker compose -f docker-compose.prod.yml up -d
set -eu
dump="${1:?usage: restore.sh <dump-file>}"
[ -f "$dump" ] || { echo "no such file: $dump" >&2; exit 2; }
if [ "${CONFIRM:-}" != "yes" ]; then
  echo "This will REPLACE database '${PGDATABASE:-gjurme}' with $dump."
  echo "Stop api and scheduler first, then re-run with CONFIRM=yes." >&2
  exit 3
fi
pg_restore --list "$dump" > /dev/null  # fail fast on an unreadable archive
echo "restoring $dump into ${PGDATABASE:-gjurme} …"
pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error -d "${PGDATABASE:-gjurme}" "$dump"
psql -tA -c "SELECT 'articles: ' || count(*) FROM core.articles"
echo "restore complete — start the stack and check /health/ready"
