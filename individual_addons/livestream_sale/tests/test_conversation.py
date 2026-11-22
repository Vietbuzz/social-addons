from datetime import timedelta
from unittest.mock import patch

from markupsafe import Markup

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import LivestreamCommon


@tagged("post_install", "-at_install", "livestream")
class TestConversation(LivestreamCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Comment = cls.env["livestream.comment"]
        now = fields.Datetime.now()
        cls.comment = cls.Comment._ingest(cls.session, "c1", "u1", "Nguyen Van A", "69 x2", now)
        cls.comment_b = cls.Comment._ingest(cls.session, "c2", "u1", "Nguyen Van A", "69", now)
        cls.customer = cls.comment.customer_id
        cls.Account = cls.registry["livestream.account"]

    def _open(self, comment):
        return self.env["discuss.channel"].browse(comment.action_open_conversation()["channel_id"])

    def test_open_conversation_reuses_channel(self):
        ch1 = self._open(self.comment)
        ch2 = self._open(self.comment_b)
        self.assertEqual(ch1, ch2)
        self.assertEqual(ch1.channel_type, "livestream")
        self.assertEqual(ch1.livestream_customer_id, self.customer)
        self.assertEqual(ch1.livestream_origin_comment_id, self.comment_b)
        self.assertEqual(self.comment.state, "contacted")
        self.assertIn(self.env.user.partner_id, ch1.channel_member_ids.partner_id)
        self.assertIn(self.customer.partner_id, ch1.channel_member_ids.partner_id)
        self.assertEqual(ch1.livestream_window_state, "waiting")

    def test_first_message_uses_private_reply(self):
        ch = self._open(self.comment)
        with patch.object(self.Account, "_livestream_private_reply", autospec=True, return_value="psid-1") as pr, \
                patch.object(self.Account, "_livestream_send_message", autospec=True) as send:
            ch.message_post(body="Chao anh", message_type="comment", subtype_xmlid="mail.mt_comment")
        pr.assert_called_once()
        self.assertEqual(pr.call_args.args[1], self.comment)
        self.assertEqual(pr.call_args.args[2], "Chao anh")
        send.assert_not_called()
        self.assertEqual(self.customer.psid, "psid-1")
        self.assertTrue(self.comment.private_reply_sent)

    def test_second_message_before_reply_blocked(self):
        ch = self._open(self.comment)
        with patch.object(self.Account, "_livestream_private_reply", autospec=True, return_value=None):
            ch.message_post(body="Chao anh", message_type="comment", subtype_xmlid="mail.mt_comment")
            with self.assertRaises(UserError):
                ch.message_post(body="Anh oi", message_type="comment", subtype_xmlid="mail.mt_comment")

    def test_message_with_open_window_uses_send_api(self):
        self.customer.psid = "psid-9"
        ch = self._open(self.comment)
        ch.livestream_window_expires_at = fields.Datetime.now() + timedelta(hours=2)
        with patch.object(self.Account, "_livestream_send_message", autospec=True) as send:
            ch.message_post(body=Markup("<p>Gia 150k</p>"), message_type="comment", subtype_xmlid="mail.mt_comment")
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1], self.customer)
        self.assertEqual(send.call_args.args[2], "Gia 150k")

    def test_internal_note_not_delivered(self):
        ch = self._open(self.comment)
        with patch.object(self.Account, "_livestream_private_reply", autospec=True) as pr, \
                patch.object(self.Account, "_livestream_send_message", autospec=True) as send:
            ch.message_post(body="ghi chu noi bo", message_type="comment", subtype_xmlid="mail.mt_note")
        pr.assert_not_called()
        send.assert_not_called()

    def test_receive_message_opens_window(self):
        self.customer.psid = "psid-2"
        ch = self._open(self.comment)
        msg = self.customer._receive_message("Em lay 2 cai", "mid.1")
        self.assertEqual(msg.author_id, self.customer.partner_id)
        self.assertEqual(ch.livestream_window_state, "open")
        self.assertAlmostEqual(
            ch.livestream_window_expires_at, fields.Datetime.now() + timedelta(hours=24), delta=timedelta(minutes=1),
        )
        again = self.customer._receive_message("Em lay 2 cai", "mid.1")
        self.assertEqual(again, msg)
        self.assertEqual(len(ch.message_ids.filtered(lambda m: m.livestream_external_id == "mid.1")), 1)

    def test_customer_message_not_echoed(self):
        self.customer.psid = "psid-3"
        self._open(self.comment)
        with patch.object(self.Account, "_livestream_send_message", autospec=True) as send:
            self.customer._receive_message("alo", "mid.2")
        send.assert_not_called()

    def test_receive_creates_channel_when_missing(self):
        self.customer.psid = "psid-4"
        msg = self.customer._receive_message("hello shop", "mid.3")
        self.assertEqual(msg.model, "discuss.channel")
        self.assertEqual(self.customer.channel_id.channel_type, "livestream")

    def test_closed_window_new_comment_uses_private_reply(self):
        """Returning customer (psid known, window expired) commenting again: reuse private reply."""
        self.customer.psid = "psid-6"
        ch = self._open(self.comment)
        ch.livestream_window_expires_at = fields.Datetime.now() - timedelta(hours=1)
        with patch.object(self.Account, "_livestream_private_reply", autospec=True, return_value="psid-6") as pr, \
                patch.object(self.Account, "_livestream_send_message", autospec=True) as send:
            ch.message_post(body="Chao anh", message_type="comment", subtype_xmlid="mail.mt_comment")
        pr.assert_called_once()
        send.assert_not_called()

    def test_window_closed_after_expiry(self):
        self.customer.psid = "psid-5"
        ch = self._open(self.comment)
        ch.livestream_window_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self.assertEqual(ch.livestream_window_state, "closed")
