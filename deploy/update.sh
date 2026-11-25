#!/bin/sh
# Pull the latest main, upgrade the modules, restart. Run on tino2 in /root/livestream20.
set -eu
cd "$(dirname "$0")"
git -C social-addons pull --ff-only
docker compose run --rm odoo odoo -c /etc/odoo/odoo.conf -d livestream20 \
  -u livestream_sale,livestream_sepay,livestream_facebook,livestream_instagram --stop-after-init --no-http
docker compose up -d
docker compose restart odoo
