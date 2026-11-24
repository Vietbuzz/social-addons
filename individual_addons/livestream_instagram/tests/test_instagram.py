import json
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.livestream_facebook.models import graph_api

from .common import InstagramCommon, raw


@tagged("post_install", "-at_install", "livestream")
class TestInstagramWebhook(InstagramCommon):
    def test_verify_challenge(self):
        ok = self.url_open("/livestream/instagram/webhook?hub.mode=subscribe&hub.verify_token=IGVERIFY&hub.challenge=777")
        self.assertEqual((ok.status_code, ok.text), (200, "777"))
        with mute_logger("odoo.addons.livestream_instagram.controllers.main"):
            bad = self.url_open("/livestream/instagram/webhook?hub.mode=subscribe&hub.verify_token=NO&hub.challenge=1")
        self.assertEqual(bad.status_code, 403)

    def test_signature_required(self):
        body = raw("live_comment.json")
        with mute_logger("odoo.addons.livestream_instagram.controllers.main"):
            self.assertEqual(self._post(body, sig=False).status_code, 403)
            self.assertEqual(self._post(body, sig=self._sig(body, "WRONG")).status_code, 403)
        self.assertFalse(self.Event.search([("source", "=", "instagram")]))

    def test_live_comment_ingested(self):
        self._deliver("live_comment.json")
        self._deliver("live_comment.json")  # Meta retry: no duplicate
        session = self.env["livestream.session"].search([("account_id", "=", self.ig.id)])
        self.assertEqual((session.external_video_id, session.state), ("MEDIA1", "live"))
        comment = self.Comment.search([("session_id", "=", session.id)])
        self.assertEqual(len(comment), 1)
        self.assertEqual((comment.external_id, comment.message), ("IGC1", "69 x2"))
        self.assertEqual(comment.customer_id.external_user_id, "IGSID1")
        self.assertEqual(comment.customer_id.name, "nguyenvana")

    def test_own_comment_ignored(self):
        payload = self._json("live_comment.json")
        payload["entry"][0]["changes"][0]["value"]["from"] = {"id": "IG1", "username": "shop"}
        self._deliver_body(json.dumps(payload).encode())
        self.assertFalse(self.Comment.search([("external_id", "=", "IGC1")]))

    def test_message_both_shapes(self):
        with patch.object(graph_api, "_request", return_value={"username": "khach9", "name": "Khach 9"}):
            self._deliver("message.json")
            changes_shape = {"object": "instagram", "entry": [{"id": "IG1", "time": 1, "changes": [{
                "field": "messages", "value": {"sender": {"id": "IGSID9"}, "recipient": {"id": "IG1"},
                                                "timestamp": 2, "message": {"mid": "igm_2", "text": "alo"}}}]}]}
            self._deliver_body(json.dumps(changes_shape).encode())
            self._deliver("message.json")  # retry of the first message
        customer = self.Customer.search([("psid", "=", "IGSID9")])
        self.assertEqual(len(customer), 1)
        bodies = customer.channel_id.message_ids.mapped("body")
        self.assertEqual(len([b for b in bodies if "0912345678" in b]), 1)
        self.assertTrue(any("alo" in b for b in bodies))
        self.assertEqual(customer.channel_id.livestream_window_state, "open")

    def test_comment_then_dm_same_customer(self):
        self._deliver("live_comment.json")
        payload = self._json("message.json")
        payload["entry"][0]["messaging"][0]["sender"]["id"] = "IGSID1"
        with patch.object(graph_api, "_request", return_value={"username": "nguyenvana"}):
            self._deliver_body(json.dumps(payload).encode())
        customers = self.Customer.search([("account_id", "=", self.ig.id)])
        self.assertEqual(len(customers), 1)
        self.assertEqual(customers.psid, "IGSID1")

    def test_echo_ignored(self):
        payload = self._json("message.json")
        payload["entry"][0]["messaging"][0]["message"]["is_echo"] = True
        with patch.object(graph_api, "_request", return_value={}) as req:
            self._deliver_body(json.dumps(payload).encode())
        req.assert_not_called()
        self.assertFalse(self.Customer.search([("account_id", "=", self.ig.id)]))
