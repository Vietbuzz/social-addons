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
        ], order="source_type, id desc", limit=1)  # 'live' sorts before 'post'

    @api.model
    def _fb_live_for_video(self, account, video_id):
        """Find the Page's live video whose underlying video is `video_id` (comments arrive before any sync)."""
        try:
            res = graph_api._request("GET", f"{account.external_id}/live_videos", account._fb_token(), params={
                "fields": "id,status,title,video{id},creation_time", "limit": 10,
            })
        except Exception as e:  # noqa: BLE001
            _logger.info("Cannot list live videos of %s: %s", account.external_id, e)
            return None
        for live in res.get("data", []):
            if (live.get("video") or {}).get("id") == video_id:
                return live
        return None

    @api.model
    def _fb_post_session(self, account, post_id, status_type=None):
        """Regular Page post -> its own session (named after the post text).

        A video post may be a running live that was never synced: resolve it first.
        """
        if status_type in (None, "added_video"):
            live = self._fb_live_for_video(account, (post_id or "").split("_")[-1])
            if live:
                return self._fb_upsert_live(account, live)
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
        if not video_id and not (session and session.external_post_id):
            try:  # live_videos webhooks carry only {id, status}
                info = graph_api._request("GET", live["id"], account._fb_token(), params={"fields": "video{id},title"})
                video_id = (info.get("video") or {}).get("id")
                live = {**live, "title": live.get("title") or info.get("title")}
            except Exception as e:  # noqa: BLE001
                _logger.info("Cannot read live video %s: %s", live.get("id"), e)
        if video_id:
            vals["external_post_id"] = f"{account.external_id}_{video_id}"
        if session:
            # never reopen an ended live (late/out-of-order events); draft -> live is allowed
            if session.state != state and session.state != "ended":
                session.write(vals)
            elif vals.get("external_post_id") and not session.external_post_id:
                session.external_post_id = vals["external_post_id"]
            session._fb_absorb_post_sessions()
            return session
        session = self.create({
            **vals,
            "name": live.get("title") or self.env._("Facebook live %s", live["id"]),
            "account_id": account.id,
            "external_video_id": live["id"],
            "date_start": graph_api.parse_time(live.get("creation_time")) if live.get("creation_time") else fields.Datetime.now(),
        })
        session._fb_absorb_post_sessions()
        return session

    def _fb_absorb_post_sessions(self):
        """Comments that arrived as a 'post' before the live was known move into the live session."""
        self.ensure_one()
        if self.source_type != "live" or not self.external_post_id:
            return
        posts = self.search([
            ("account_id", "=", self.account_id.id), ("source_type", "=", "post"),
            ("external_post_id", "=", self.external_post_id), ("id", "!=", self.id),
        ])
        for post in posts:
            existing = set(self.env["livestream.comment"].search([("session_id", "=", self.id)]).mapped("external_id"))
            for comment in post.env["livestream.comment"].search([("session_id", "=", post.id)]):
                if comment.external_id in existing:
                    comment.unlink()
                else:
                    comment.session_id = self
            self.env["sale.order"].search([("livestream_session_id", "=", post.id)]).livestream_session_id = self
            post.write({"state": "ended", "date_end": fields.Datetime.now()})

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
