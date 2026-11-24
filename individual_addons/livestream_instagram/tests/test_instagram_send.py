import json
from datetime import timedelta
from unittest.mock import patch

from markupsafe import Markup

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.livestream_facebook.models import graph_api
from odoo.addons.livestream_instagram.models import ig_api

from .common import InstagramCommon


@tagged("post_install", "-at_install", "livestream")
class TestInstagramSend(InstagramCommon):
    def _comment(self):
        self._deliver("live_comment.json")
        return self.Comment.search([("external_id", "=", "IGC1")])

    def _channel(self, comment):
        return self.env["discuss.channel"].browse(comment.action_open_conversation()["channel_id"])

    def _say(self, channel, body, **kw):
        return channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment", **kw)

    def test_private_reply_sets_igsid(self):
        comment = self._comment()
        channel = self._channel(comment)
        with patch.object(graph_api, "_request", return_value={"recipient_id": "IGSID1", "message_id": "m"}) as req:
            self._say(channel, Markup("<p>Chao ban</p>"))
        method, path, token = req.call_args.args[:3]
        self.assertEqual((method, path, token), ("POST", "PAGE1/messages", "PAGE_TOKEN"))
        self.assertEqual(req.call_args.kwargs["json"], {"recipient": {"comment_id": "IGC1"}, "message": {"text": "Chao ban"}})
        self.assertEqual(comment.customer_id.psid, "IGSID1")

    def test_private_reply_after_live_ended_refused(self):
        comment = self._comment()
        comment.session_id.state = "ended"
        channel = self._channel(comment)
        with patch.object(graph_api, "_request") as req, self.assertRaises(UserError):
            self._say(channel, "Chao ban")
        req.assert_not_called()

    def test_long_message_split_utf8(self):
        text = ("Shop gửi anh/chị thông tin đặt cọc đơn hàng, số tiền cọc là một trăm nghìn đồng. " * 20).strip()
        parts = ig_api.split_utf8(text, 1000)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p.encode()) <= 1000 for p in parts))
        self.assertEqual(" ".join(parts).replace("  ", " "), text)
        self.assertEqual(ig_api.split_utf8("ngắn"), ["ngắn"])
        self.assertTrue(all(len(p.encode()) <= 10 for p in ig_api.split_utf8("đđđđđđđđđđđđ", 10)))

    def test_send_long_text_in_window_sends_parts(self):
        comment = self._comment()
        comment.customer_id.psid = "IGSID1"
        channel = self._channel(comment)
        channel.livestream_window_expires_at = fields.Datetime.now() + timedelta(hours=1)
        with patch.object(graph_api, "_request", return_value={"message_id": "m"}) as req:
            self._say(channel, "đ" * 700)  # 1400 bytes
        self.assertEqual(req.call_count, 2)
        self.assertEqual(req.call_args.kwargs["json"]["recipient"], {"id": "IGSID1"})

    def test_send_message_outside_window_raises(self):
        comment = self._comment()
        customer = comment.customer_id
        customer.psid = "IGSID1"
        with self.assertRaises(UserError):
            self.ig._livestream_send_message(customer, "hi", self.env["ir.attachment"])

    def test_send_image_uploads_then_sends(self):
        calls = []

        def fake(method, path, token, **kw):
            calls.append((path, kw))
            return {"attachment_id": "ATT1"} if path.endswith("message_attachments") else {"message_id": "m"}

        with patch.object(graph_api, "_request", side_effect=fake):
            ig_api.send_image("TOKEN", "PAGE1", "IGSID1", "VietQR-LS000001.png", b"png-bytes", "image/png")
        self.assertEqual([c[0] for c in calls], ["PAGE1/message_attachments", "PAGE1/messages"])
        upload = calls[0][1]
        self.assertEqual(upload["data"]["platform"], "instagram")
        self.assertIn("filedata", upload["files"])
        self.assertEqual(calls[1][1]["json"]["message"]["attachment"],
                         {"type": "image", "payload": {"attachment_id": "ATT1"}})

    def test_dm_links_pending_by_username(self):
        """Commenter id differs from the IGSID: link by username to the customer we private-replied to."""
        self._deliver("live_comment.json")
        comment = self.Comment.search([("external_id", "=", "IGC1")])
        channel = self.env["discuss.channel"].browse(comment.action_open_conversation()["channel_id"])
        with patch.object(graph_api, "_request", return_value={"message_id": "m"}):
            channel.message_post(body="Chao ban", message_type="comment", subtype_xmlid="mail.mt_comment")
        payload = self._json("message.json")
        payload["entry"][0]["messaging"][0]["sender"]["id"] = "IGSID_OTHER"
        with patch.object(graph_api, "_request", return_value={"username": "nguyenvana", "name": "A"}):
            self._deliver_body(json.dumps(payload).encode())
        self.assertEqual(comment.customer_id.psid, "IGSID_OTHER")
        self.assertEqual(self.Customer.search_count([("account_id", "=", self.ig.id)]), 1)

