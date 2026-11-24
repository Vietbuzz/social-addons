import logging

from odoo import api, fields, models

from odoo.addons.livestream_facebook.models import graph_api

_logger = logging.getLogger(__name__)


class LivestreamSession(models.Model):
    _inherit = "livestream.session"

    @api.model
    def _ig_upsert_live(self, account, media_id, live):
        """Instagram live media <-> session. draft -> live allowed; an ended live never reopens."""
        session = self.search([("account_id", "=", account.id), ("external_video_id", "=", media_id)], limit=1)
        state = "live" if live else "ended"
        if session:
            if session.state != state and session.state != "ended":
                session.write({"state": state, **({"date_end": fields.Datetime.now()} if state == "ended" else {})})
            return session
        return self.create({
            "name": self.env._("Instagram live %s", fields.Datetime.now().strftime("%d/%m %H:%M")),
            "account_id": account.id,
            "external_video_id": media_id,
            "state": state,
            "date_start": fields.Datetime.now(),
        })

    @api.model
    def _ig_cron_sync(self):
        """Discover running Instagram lives and pull their comments (backup for live_comments webhooks)."""
        Comment = self.env["livestream.comment"]
        accounts = self.env["livestream.account"].sudo().search([("platform", "=", "instagram")])
        for account in accounts.filtered(lambda a: a.access_token and a.external_id):
            token = account._fb_token()
            try:
                res = graph_api._request("GET", f"{account.external_id}/live_media", token, params={
                    "fields": "id,media_product_type,timestamp",
                })
            except Exception as e:  # noqa: BLE001
                _logger.warning("Instagram live_media failed for account %s: %s", account.id, e)
                continue
            live_ids = [m["id"] for m in res.get("data", [])]
            running = self.sudo().search([
                ("account_id", "=", account.id), ("state", "=", "live"), ("external_video_id", "not in", live_ids),
            ])
            for session in running:
                self._ig_upsert_live(account, session.external_video_id, False)
            for media_id in live_ids:
                session = self.sudo()._ig_upsert_live(account, media_id, True)
                if session.state != "live":
                    continue
                try:
                    rows = graph_api._request("GET", f"{media_id}/ordered_comments", token, params={
                        "fields": "id,text,timestamp,from{id,username}", "limit": 50,
                    }).get("data", [])
                except Exception as e:  # noqa: BLE001
                    _logger.warning("Instagram comments pull failed for media %s: %s", media_id, e)
                    continue
                for row in reversed(rows):
                    author = row.get("from") or {}
                    if author.get("id") == account.external_id:
                        continue
                    try:
                        with self.env.cr.savepoint():
                            Comment.sudo()._ingest(
                                session, row["id"], author.get("id") or f"anon:{row['id']}",
                                author.get("username") or "Instagram user", row.get("text", ""),
                                graph_api.parse_time(row.get("timestamp")),
                            )
                    except Exception as e:  # noqa: BLE001 - e.g. the webhook stored it meanwhile
                        _logger.info("Skipped pulled Instagram comment %s: %s", row.get("id"), e)
