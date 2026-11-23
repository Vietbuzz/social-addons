import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import patch

from markupsafe import Markup

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.livestream_facebook.models import graph_api
from odoo.addons.livestream_sale.tests.common import LivestreamCommon

PAYLOADS = Path(__file__).parent / "payloads"


def raw(name):
    return (PAYLOADS / name).read_bytes()


@tagged("post_install", "-at_install", "livestream")
class TestFacebook(LivestreamCommon, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fb = cls.env["livestream.account"].create({
            "name": "FB Page",
            "platform": "facebook",
            "external_id": "PAGE1",
            "access_token": "PAGE_TOKEN",
            "fb_app_secret": "APPSECRET",
            "fb_verify_token": "VERIFY",
            "payment_provider_id": cls.provider.id,
        })
        cls.fb_session = cls.env["livestream.session"].create({
            "name": "FB live", "account_id": cls.fb.id, "state": "live",
            "external_video_id": "LIVE1", "external_post_id": "PAGE1_VID1",
            "tag_ids": [fields.Command.create({"code": "69", "product_id": cls.product_shirt.id, "price_unit": 150000})],
        })
        cls.Event = cls.env["livestream.webhook.event"]
        cls.Comment = cls.env["livestream.comment"]

    def _sig(self, body, secret="APPSECRET"):
        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def _post(self, body, sig=None):
        headers = {"Content-Type": "application/json"}
        if sig is not False:
            headers["X-Hub-Signature-256"] = sig or self._sig(body)
        return self.url_open("/livestream/facebook/webhook", data=body, headers=headers)

    def _deliver(self, name):
        self.assertEqual(self._post(raw(name)).status_code, 200)
        self.Event._cron_process()

    def test_verify_challenge(self):
        ok = self.url_open("/livestream/facebook/webhook?hub.mode=subscribe&hub.verify_token=VERIFY&hub.challenge=12345")
        self.assertEqual((ok.status_code, ok.text), (200, "12345"))
        with mute_logger("odoo.addons.livestream_facebook.controllers.main"):
            bad = self.url_open("/livestream/facebook/webhook?hub.mode=subscribe&hub.verify_token=NOPE&hub.challenge=1")
        self.assertEqual(bad.status_code, 403)

    def test_signature_required(self):
        body = raw("feed_comment.json")
        with mute_logger("odoo.addons.livestream_facebook.controllers.main"):
            self.assertEqual(self._post(body, sig=False).status_code, 403)
            self.assertEqual(self._post(body, sig=self._sig(body, "WRONG")).status_code, 403)
        self.assertFalse(self.Event.search([("source", "=", "facebook")]))
        self.assertEqual(self._post(body).status_code, 200)
        self.assertEqual(self.Event.search([("source", "=", "facebook")]).state, "pending")

    def test_feed_comment_ingested(self):
        self._deliver("feed_comment.json")
        self._deliver("feed_comment.json")  # retried delivery: no duplicate
        comment = self.Comment.search([("session_id", "=", self.fb_session.id)])
        self.assertEqual(len(comment), 1)
        self.assertEqual((comment.external_id, comment.tag_code, comment.quantity), ("VID1_C1", "69", 2))
        self.assertEqual(comment.customer_id.external_user_id, "FBUSER1")
        self.assertEqual(comment.customer_id.name, "Nguyen Van A")

    def test_page_own_comment_ignored(self):
        payload = json.loads(raw("feed_comment.json"))
        payload["entry"][0]["changes"][0]["value"]["from"] = {"id": "PAGE1", "name": "Shop"}
        body = json.dumps(payload).encode()
        self._post(body)
        self.Event._cron_process()
        self.assertFalse(self.Comment.search([("session_id", "=", self.fb_session.id)]))

    def test_comment_on_unknown_post_ignored(self):
        payload = json.loads(raw("feed_comment.json"))
        payload["entry"][0]["changes"][0]["value"]["post_id"] = "PAGE1_OTHER"
        self._post(json.dumps(payload).encode())
        self.Event._cron_process()
        self.assertFalse(self.Comment.search([("session_id", "=", self.fb_session.id)]))
        self.assertEqual(self.Event.search([("source", "=", "facebook")]).state, "done")

    def test_private_reply_sets_psid(self):
        self._deliver("feed_comment.json")
        comment = self.Comment.search([("external_id", "=", "VID1_C1")])
        channel = self.env["discuss.channel"].browse(comment.action_open_conversation()["channel_id"])
        with patch.object(graph_api, "_request", return_value={"recipient_id": "PSID1", "message_id": "m_x"}) as req:
            channel.message_post(body=Markup("<p>Chao anh</p>"), message_type="comment", subtype_xmlid="mail.mt_comment")
        method, path, token = req.call_args.args[:3]
        self.assertEqual((method, path, token), ("POST", "PAGE1/messages", "PAGE_TOKEN"))
        self.assertEqual(req.call_args.kwargs["json"], {"recipient": {"comment_id": "VID1_C1"}, "message": {"text": "Chao anh"}})
        self.assertEqual(comment.customer_id.psid, "PSID1")

    def test_inbound_message_links_pending_customer_by_name(self):
        """Private reply response without recipient_id: first inbound message is linked by name."""
        self._deliver("feed_comment.json")
        comment = self.Comment.search([("external_id", "=", "VID1_C1")])
        channel = self.env["discuss.channel"].browse(comment.action_open_conversation()["channel_id"])
        with patch.object(graph_api, "_request", return_value={"message_id": "m_x"}):
            channel.message_post(body="Chao anh", message_type="comment", subtype_xmlid="mail.mt_comment")
        self.assertFalse(comment.customer_id.psid)
        with patch.object(graph_api, "_request", return_value={"name": "Nguyen Van A", "id": "PSID1"}):
            self._deliver("messages_text.json")
        self.assertEqual(comment.customer_id.psid, "PSID1")
        self.assertEqual(channel.livestream_window_state, "open")
        self.assertIn("0912345678", channel.message_ids[:1].body)

    def test_inbound_message_creates_unknown_customer(self):
        with patch.object(graph_api, "_request", return_value={"name": "Le Thi C", "id": "PSID1"}):
            self._deliver("messages_text.json")
        customer = self.env["livestream.customer"].search([("psid", "=", "PSID1")])
        self.assertEqual(customer.name, "Le Thi C")
        self.assertEqual(customer.channel_id.livestream_window_state, "open")

    def test_echo_ignored(self):
        payload = json.loads(raw("messages_text.json"))
        payload["entry"][0]["messaging"][0]["message"]["is_echo"] = True
        with patch.object(graph_api, "_request", return_value={"name": "X"}) as req:
            self._post(json.dumps(payload).encode())
            self.Event._cron_process()
        req.assert_not_called()
        self.assertFalse(self.env["livestream.customer"].search([("psid", "=", "PSID1")]))

    def test_send_message_outside_window_raises(self):
        customer = self.env["livestream.customer"]._get_or_create(self.fb, "FBUSER2", "B")
        customer.psid = "PSID2"
        with self.assertRaises(UserError):
            self.fb._livestream_send_message(customer, "hi", self.env["ir.attachment"])

    def test_live_status_updates_session(self):
        self.fb_session.state = "draft"
        self._deliver("live_videos.json")
        self.assertEqual(self.fb_session.state, "live")
        payload = json.loads(raw("live_videos.json"))
        payload["entry"][0]["changes"][0]["value"]["status"] = "live_stopped"
        self._post(json.dumps(payload).encode())
        self.Event._cron_process()
        self.assertEqual(self.fb_session.state, "ended")

    def test_cron_pull_comments(self):
        data = {"data": [
            {"id": "VID1_C9", "from": {"id": "FBUSER9", "name": "Pham D"}, "message": "69", "created_time": "2026-11-22T07:00:00+0000"},
        ]}
        with patch.object(graph_api, "_request", return_value=data) as req:
            self.env["livestream.session"]._fb_cron_pull_comments()
        self.assertEqual(req.call_args.args[1], "LIVE1/comments")
        comment = self.Comment.search([("external_id", "=", "VID1_C9")])
        self.assertEqual(comment.tag_code, "69")

    def test_scheduled_live_then_live(self):
        Session = self.env["livestream.session"]
        session = Session._fb_upsert_live(self.fb, {"id": "LIVE2", "status": "SCHEDULED_UNPUBLISHED"})
        self.assertEqual(session.state, "draft")
        Session._fb_upsert_live(self.fb, {"id": "LIVE2", "status": "UNPUBLISHED"})
        self.assertEqual(session.state, "draft")
        Session._fb_upsert_live(self.fb, {"id": "LIVE2", "status": "LIVE"})
        self.assertEqual(session.state, "live")
        Session._fb_upsert_live(self.fb, {"id": "LIVE2", "status": "LIVE_STOPPED"})
        self.assertEqual(session.state, "ended")
        Session._fb_upsert_live(self.fb, {"id": "LIVE2", "status": "LIVE"})  # late event: stays ended
        self.assertEqual(session.state, "ended")

    def test_cron_pull_one_bad_row_does_not_lose_batch(self):
        data = {"data": [
            {"id": "VID1_C21", "from": {"id": "U21", "name": "A"}, "message": "69", "created_time": "2026-11-22T07:00:01+0000"},
            {"id": "VID1_C20", "from": {"id": "U20", "name": "B"}, "message": "69", "created_time": "2026-11-22T07:00:00+0000"},
        ]}
        Comment = self.registry["livestream.comment"]
        real = Comment._ingest

        def flaky(model, session, external_id, *args, **kwargs):
            if external_id == "VID1_C20":
                raise ValueError("race")
            return real(model, session, external_id, *args, **kwargs)

        with patch.object(graph_api, "_request", return_value=data), \
                patch.object(Comment, "_ingest", autospec=True, side_effect=flaky), \
                mute_logger("odoo.addons.livestream_facebook.models.livestream_session"):
            self.env["livestream.session"]._fb_cron_pull_comments()
        self.assertTrue(self.Comment.search([("external_id", "=", "VID1_C21")]))

    def test_simulated_reply_refused_on_facebook(self):
        self._deliver("feed_comment.json")
        comment = self.Comment.search([("external_id", "=", "VID1_C1")])
        channel_id = comment.action_open_conversation()["channel_id"]
        with self.assertRaises(UserError):
            self.env["livestream.simulator"].simulate_customer_reply(channel_id, "fake")
        self.assertFalse(comment.customer_id.psid)
