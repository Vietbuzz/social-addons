#!/bin/sh
# Nightly: DB dump + filestore of livestream20, keep 7 days. Run on tino2 in /root/livestream20.
set -eu
cd "$(dirname "$0")"
mkdir -p backups
stamp=$(date +%Y%m%d-%H%M)
docker exec root-db-pg16-1 pg_dump -U odoo -Fc livestream20 > "backups/livestream20-$stamp.dump"
docker run --rm -v livestream20_data:/data:ro -v "$PWD/backups:/out" alpine \
  tar czf "/out/filestore-$stamp.tgz" -C /data filestore/livestream20
find backups -type f -mtime +7 -delete
