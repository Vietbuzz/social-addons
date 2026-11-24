import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.livestream_facebook.models import graph_api
from odoo.addons.livestream_instagram.models import ig_api

from .common import InstagramCommon


@tagged("post_install", "-at_install", "livestream")
class TestInstagramReviewFixes(InstagramCommon):
    def _comment(self):
        self._deliver("live_comment.json")
        return self.Comment.search([("external_id", "=", "IGC1")])

    def test_dm_then_comment_same_customer(self):
        payload = self._json("message.json")
        payload["entry"][0]["messaging"][0]["sender"]["id"] = "IGSID1"
        with patch.object(graph_api, "_request", return_value={"username": "nguyenvana"}):
            self._deliver_body(json.dumps(payload).encode())
        self._deliver("live_comment.json")
        customers = self.Customer.search([("account_id", "=", self.ig.id)])
        self.assertEqual(len(customers), 1)
        self.assertEqual(self.Comment.search([("external_id", "=", "IGC1")]).customer_id, customers)

    def test_private_reply_too_long_refused(self):
        comment = self._comment()
        channel = self.env["discuss.channel"].browse(comment.action_open_conversation()["channel_id"])
        with patch.object(graph_api, "_request") as req, self.assertRaises(UserError):
            channel.message_post(body="đ" * 600, message_type="comment", subtype_xmlid="mail.mt_comment")
        req.assert_not_called()

    def test_image_failure_after_text_posts_note(self):
        comment = self._comment()
        comment.customer_id.psid = "IGSID1"
        channel = self.env["discuss.channel"].browse(comment.action_open_conversation()["channel_id"])
        channel.livestream_window_expires_at = fields.Datetime.now() + timedelta(hours=1)
        with patch.object(graph_api, "_request", return_value={"message_id": "m"}), \
                patch.object(ig_api, "send_image", side_effect=UserError("upload rejected")):
            msg = channel.message_post(body="Thong tin coc", message_type="comment", subtype_xmlid="mail.mt_comment",
                                       attachments=[("qr.png", b"png")])
        self.assertTrue(msg.exists())
        notes = channel.message_ids.filtered(lambda m: m.subtype_id == self.env.ref("mail.mt_note"))
        self.assertTrue(any("upload rejected" in (m.body or "") for m in notes))

    def _live(self, ids):
        def fake(method, path, token, **kw):
            if path.endswith("/live_media"):
                return {"data": [{"id": i} for i in ids]}
            return {"data": []}
        return fake

    def test_cron_needs_two_misses_to_end(self):
        Session = self.env["livestream.session"]
        with patch.object(graph_api, "_request", side_effect=self._live(["MEDIA7"])):
            Session._ig_cron_sync()
        session = Session.search([("external_video_id", "=", "MEDIA7")])
        with patch.object(graph_api, "_request", side_effect=self._live([])):
            Session._ig_cron_sync()
        self.assertEqual(session.state, "live")
        with patch.object(graph_api, "_request", side_effect=self._live(["MEDIA7"])):
            Session._ig_cron_sync()  # seen again: miss counter resets
        with patch.object(graph_api, "_request", side_effect=self._live([])):
            Session._ig_cron_sync()
        self.assertEqual(session.state, "live")
        with patch.object(graph_api, "_request", side_effect=self._live([])):
            Session._ig_cron_sync()
        self.assertEqual(session.state, "ended")

    def test_deleted_or_unsupported_message_ignored(self):
        for flag in ("is_deleted", "is_unsupported"):
            payload = self._json("message.json")
            payload["entry"][0]["messaging"][0]["message"][flag] = True
            payload["entry"][0]["messaging"][0]["message"]["mid"] = f"m_{flag}"
            with patch.object(graph_api, "_request", return_value={"username": "x"}):
                self._deliver_body(json.dumps(payload).encode())
        self.assertFalse(self.Customer.search([("account_id", "=", self.ig.id)]))

    def test_cron_bad_account_isolated(self):
        other = self.ig.copy({"name": "IG2", "external_id": "IG2", "access_token": "T2"})
        Session = self.registry["livestream.session"]
        real = Session._ig_upsert_live

        def flaky(model, account, media_id, live):
            if account == self.ig:
                raise ValueError("db error")
            return real(model, account, media_id, live)

        with patch.object(graph_api, "_request", side_effect=self._live(["M9"])), \
                patch.object(Session, "_ig_upsert_live", autospec=True, side_effect=flaky), \
                mute_logger("odoo.addons.livestream_instagram.models.livestream_session"):
            self.env["livestream.session"]._ig_cron_sync()
        self.assertTrue(self.env["livestream.session"].search([("account_id", "=", other.id)]))

    def test_subscribe_instagram_uses_linked_page(self):
        with patch.object(graph_api, "_request", return_value={"success": True}) as req:
            self.ig.action_fb_subscribe()
        self.assertEqual(req.call_args.args[1], "PAGE1/subscribed_apps")
