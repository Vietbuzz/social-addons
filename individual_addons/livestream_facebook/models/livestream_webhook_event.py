import logging

import requests

from odoo import fields, models

from . import graph_api

_logger = logging.getLogger(__name__)


class LivestreamWebhookEvent(models.Model):
    _inherit = "livestream.webhook.event"

    source = fields.Selection(selection_add=[("facebook", "Facebook")], ondelete={"facebook": "cascade"})

    def _process_facebook(self, entry):
        account = self.account_id or self.env["livestream.account"].sudo().search(
            [("platform", "=", "facebook"), ("external_id", "=", entry.get("id"))], limit=1,
        )
        if not account:
            return
        for change in entry.get("changes", []):
            if change.get("field") == "feed":
                self._fb_feed(account, change.get("value") or {})
            elif change.get("field") == "live_videos":
                self.env["livestream.session"].sudo()._fb_upsert_live(account, change.get("value") or {})
        for event in entry.get("messaging", []):
            message = event.get("message")
            if message and not message.get("is_echo"):
                self._fb_message(account, event["sender"]["id"], message)

    def _fb_feed(self, account, value):
        if value.get("item") != "comment" or value.get("verb") != "add":
            return
        author = value.get("from") or {}
        if author.get("id") == account.external_id:
            return  # the Page's own comments
        session = self.env["livestream.session"].sudo()._fb_find_for_post(account, value.get("post_id"))
        if not session:
            return  # comment on a regular post
        self.env["livestream.comment"].sudo()._ingest(
            session, value["comment_id"], author.get("id") or f"anon:{value['comment_id']}",
            author.get("name") or "Facebook user", value.get("message", ""),
            graph_api.parse_time(value.get("created_time")),
        )

    def _fb_customer_for_psid(self, account, psid):
        Customer = self.env["livestream.customer"].sudo()
        customer = Customer.search([("account_id", "=", account.id), ("psid", "=", psid)], limit=1)
        if customer:
            return customer
        try:
            profile = graph_api._request("GET", psid, account._fb_token(), params={"fields": "name,profile_pic"})
        except Exception as e:  # noqa: BLE001 - profile access may be restricted
            _logger.info("Cannot read Messenger profile %s: %s", psid, e)
            profile = {}
        name = profile.get("name") or "Messenger user"
        # A customer we private-replied to (reply response gave no psid) and who now writes back.
        pending = Customer.search([
            ("account_id", "=", account.id), ("psid", "=", False), ("name", "=", name),
            ("channel_id.livestream_origin_comment_id.private_reply_sent", "=", True),
        ], order="write_date desc", limit=1)
        if pending:
            pending.psid = psid
            return pending
        return Customer.create({
            "account_id": account.id,
            "external_user_id": f"psid:{psid}",
            "psid": psid,
            "name": name,
            "avatar_url": profile.get("profile_pic"),
        })

    def _fb_message(self, account, psid, message):
        customer = self._fb_customer_for_psid(account, psid)
        files = []
        for att in message.get("attachments") or []:
            url = (att.get("payload") or {}).get("url")
            if att.get("type") == "image" and url:
                try:
                    files.append((f"{message['mid']}.jpg", requests.get(url, timeout=20).content))
                except requests.RequestException as e:
                    _logger.info("Cannot download Messenger attachment: %s", e)
        customer._receive_message(message.get("text") or "", message["mid"], files)
