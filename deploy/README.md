# Deploy on tino2

Layout on the server (`/root/livestream20`, never committed: `etc/odoo.conf`, `.env`, `backups/`):

```
/root/livestream20/
  docker-compose.yml   -> copied from deploy/docker-compose.yml
  .env                 -> DOMAIN=fit2hand.io.vn
  etc/odoo.conf        -> from deploy/odoo.conf.example with real secrets (chmod 644, /root is 700)
  social-addons/       -> git clone git@github.com:Vietbuzz/social-addons.git (branch main)
  update.sh, backup.sh -> copied from deploy/
```

- Database: shared container `db-pg16` (project `/root/docker-compose.yml`), own role `livestream` and DB `livestream20`.
- HTTPS: the host Traefik (resolver `mytlschallenge`) routes `fit2hand.io.vn` → 8069 and `/websocket` → 8072.
- Update: `./update.sh`. Backup: cron `30 2 * * * /root/livestream20/backup.sh`.
- Remove completely: `docker compose down -v`, then `DROP DATABASE livestream20; DROP ROLE livestream;`.
