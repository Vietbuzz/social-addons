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
- Update: `./update.sh`.
- Backup: systemd timer `livestream20-backup.timer` (02:30 nightly) runs `backup.sh` → `/root/livestream20/backups` (7 days). The host has no cron.
- Admin login: `cat /root/livestream20/etc/.admin_login` (root only).
- Odoo 20 binds to 127.0.0.1 by default: keep `http_interface = 0.0.0.0` in `etc/odoo.conf`.
- Remove completely: `docker compose down -v`, then `DROP DATABASE livestream20; DROP ROLE livestream;`.
