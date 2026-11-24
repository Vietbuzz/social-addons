import logging

import requests

from odoo import fields, models

from odoo.addons.livestream_facebook.models import graph_api

_logger = logging.getLogger(__name__)


class LivestreamWebhookEvent(models.Model):
    _inherit = "livestream.webhook.event"

    source = fields.Selection(selection_add=[("instagram", "Instagram")], ondelete={"instagram": "cascade"})

    def _process_instagram(self, entry):
        account = self.account_id or self.env["livestream.account"].sudo().search(
            [("platform", "=", "instagram"), ("external_id", "=", str(entry.get("id")))], limit=1,
        )
        if not account:
            return
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            if change.get("field") == "live_comments":
                self._ig_live_comment(account, value, entry.get("time"))
            elif change.get("field") == "messages":
                self._ig_event(account, value)
        for event in entry.get("messaging", []):
            self._ig_event(account, event)

    def _ig_live_comment(self, account, value, time):
        author = value.get("from") or {}
        if not value.get("comment_id") or author.get("id") == account.external_id:
            return
        media_id = (value.get("media") or {}).get("id")
        if not media_id:
            return
        session = self.env["livestream.session"].sudo()._ig_upsert_live(account, media_id, True)
        if session.state != "live":
            return  # late event for an ended live
        self.env["livestream.comment"].sudo()._ingest(
            session, value["comment_id"], author.get("id") or f"anon:{value['comment_id']}",
            author.get("username") or "Instagram user", value.get("text", ""),
            graph_api.parse_time(time),
        )

    def _ig_event(self, account, event):
        message = event.get("message")
        sender = (event.get("sender") or {}).get("id")
        if not message or not sender or message.get("is_echo") or message.get("is_self") or sender == account.external_id:
            return
        customer = self._ig_customer_for_igsid(account, sender)
        files = []
        for att in message.get("attachments") or []:
            url = (att.get("payload") or {}).get("url")
            if att.get("type") == "image" and url:
                try:
                    files.append((f"{message['mid']}.jpg", requests.get(url, timeout=20).content))
                except requests.RequestException as e:
                    _logger.info("Cannot download Instagram attachment: %s", e)
        customer._receive_message(message.get("text") or "", message["mid"], files)

    def _ig_customer_for_igsid(self, account, igsid):
        Customer = self.env["livestream.customer"].sudo()
        base = [("account_id", "=", account.id)]
        customer = Customer.search(base + [("psid", "=", igsid)], limit=1)
        if customer:
            return customer
        customer = Customer.search(base + [("external_user_id", "=", igsid)], limit=1)
        if customer:
            customer.psid = igsid
            return customer
        try:
            profile = graph_api._request("GET", igsid, account._fb_token(), params={"fields": "username,name"})
        except Exception as e:  # noqa: BLE001 - profile access may be restricted
            _logger.info("Cannot read Instagram profile %s: %s", igsid, e)
            profile = {}
        username = profile.get("username")
        if username:
            pending = Customer.search(base + [
                ("psid", "=", False), ("name", "=", username),
                ("channel_id.livestream_origin_comment_id.private_reply_sent", "=", True),
            ], order="write_date desc", limit=1)
            if pending:
                pending.psid = igsid
                return pending
        return Customer.create({
            "account_id": account.id,
            "external_user_id": f"igsid:{igsid}",
            "psid": igsid,
            "name": username or profile.get("name") or "Instagram user",
        })
