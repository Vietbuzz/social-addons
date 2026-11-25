import logging

from odoo import api, fields, models

from . import graph_api

_logger = logging.getLogger(__name__)


class LivestreamSession(models.Model):
    _inherit = "livestream.session"

    @api.model
    def _fb_find_for_post(self, account, post_id):
        """Feed comments reference the video post as '<page>_<video>' (or just the id)."""
        short = (post_id or "").split("_")[-1]
        return self.search([
            ("account_id", "=", account.id),
            "|", "|",
            ("external_post_id", "=", post_id),
            ("external_post_id", "=", short),
            ("external_video_id", "=", short),
        ], limit=1)

    @api.model
    def _fb_post_session(self, account, post_id):
        """Regular Page post -> its own session (named after the post text)."""
        try:
            info = graph_api._request("GET", post_id, account._fb_token(), params={"fields": "message,permalink_url"})
        except Exception as e:  # noqa: BLE001 - never lose the comment because the post can't be read
            _logger.info("Cannot read Facebook post %s: %s", post_id, e)
            info = {}
        return self._get_or_create_post(account, post_id, info.get("message"), info.get("permalink_url"))

    @api.model
    def _fb_upsert_live(self, account, live):
        session = self.search([("account_id", "=", account.id), ("external_video_id", "=", live["id"])], limit=1)
        status = (live.get("status") or "").upper()
        if status == "LIVE":
            state = "live"
        elif "SCHEDULED" in status or "UNPUBLISHED" in status or status == "PREVIEW":
            state = "draft"
        else:
            state = "ended"
        vals = {"state": state}
        video_id = (live.get("video") or {}).get("id")
        if video_id:
            vals["external_post_id"] = f"{account.external_id}_{video_id}"
        if session:
            # never reopen an ended live (late/out-of-order events); draft -> live is allowed
            if session.state != state and session.state != "ended":
                session.write(vals)
            return session
        return self.create({
            **vals,
            "name": live.get("title") or self.env._("Facebook live %s", live["id"]),
            "account_id": account.id,
            "external_video_id": live["id"],
            "date_start": graph_api.parse_time(live.get("creation_time")) if live.get("creation_time") else fields.Datetime.now(),
        })

    @api.model
    def _fb_cron_pull_comments(self):
        """Poll comments of running lives: backup for webhooks that cannot reach a local server."""
        Comment = self.env["livestream.comment"]
        for session in self.sudo().search([("state", "=", "live"), ("platform", "=", "facebook")]):
            account = session.account_id
            if not session.external_video_id or not account.sudo().access_token:
                continue
            try:
                res = graph_api._request("GET", f"{session.external_video_id}/comments", account._fb_token(), params={
                    "filter": "stream", "live_filter": "no_filter", "order": "reverse_chronological",
                    "fields": "id,from,message,created_time", "limit": 100,
                })
            except Exception as e:  # noqa: BLE001
                _logger.warning("Facebook comment pull failed for session %s: %s", session.id, e)
                continue
            for row in reversed(res.get("data", [])):
                author = row.get("from") or {}
                if author.get("id") == account.external_id:
                    continue
                try:
                    with self.env.cr.savepoint():
                        Comment._ingest(
                            session, row["id"], author.get("id") or f"anon:{row['id']}",
                            author.get("name") or "Facebook user",
                            row.get("message", ""), graph_api.parse_time(row.get("created_time")),
                        )
                except Exception as e:  # noqa: BLE001 - e.g. webhook committed the same comment meanwhile
                    _logger.info("Skipped pulled comment %s: %s", row.get("id"), e)
