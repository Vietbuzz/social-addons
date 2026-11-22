from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged

from .common import LivestreamCommon


@tagged("post_install", "-at_install", "livestream")
class TestCommentIngest(LivestreamCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Comment = cls.env["livestream.comment"]
        cls.Event = cls.env["livestream.webhook.event"]
        cls.now = fields.Datetime.now()

    def _sent_types(self, mock):
        return [call.args[2] for call in mock.call_args_list]

    def test_ingest_duplicate_comment(self):
        c1 = self.Comment._ingest(self.session, "c1", "u1", "Nguyen Van A", "69 x2", self.now)
        c2 = self.Comment._ingest(self.session, "c1", "u1", "Nguyen Van A", "69 x2", self.now)
        self.assertEqual(c1, c2)
        self.assertEqual(self.Comment.search_count([("session_id", "=", self.session.id)]), 1)
        self.assertEqual((c1.tag_id.code, c1.quantity), ("69", 2))
        self.assertEqual(c1.tag_id, self.tag_69)
        self.assertEqual(c1.customer_id.external_user_id, "u1")
        self.assertEqual(c1.state, "new")

    def test_ingest_unknown_code_has_no_tag(self):
        comment = self.Comment._ingest(self.session, "c9", "u9", "Le C", "12 dep qua", self.now)
        self.assertFalse(comment.tag_code)
        self.assertFalse(comment.tag_id)

    def test_ingest_sends_bus(self):
        with patch.object(self.registry["bus.bus"], "_sendone", autospec=True) as sendone:
            comment = self.Comment._ingest(self.session, "c2", "u2", "Tran B", "69", self.now)
            self.Comment._ingest(self.session, "c2", "u2", "Tran B", "69", self.now)  # duplicate: no 2nd notify
        self.assertEqual(self._sent_types(sendone), ["livestream/comment"])
        payload = sendone.call_args.args[3]
        self.assertEqual(payload["account_id"], self.ls_account.id)
        item = payload["items"][0]
        self.assertEqual((item["id"], item["tag_code"], item["product_name"]), (comment.id, "69", "Ao thun do"))
        self.assertEqual(
            sendone.call_args.args[1], self.env.ref("livestream_sale.group_livestream_user"),
        )

    def test_event_error_isolated(self):
        bad = self.Event._enqueue("simulator", {"kind": "broken"}, self.ls_account)
        good = self.Event._enqueue("simulator", {
            "kind": "comment", "session_id": self.session.id, "comment_id": "c3",
            "user_id": "u3", "name": "Pham D", "message": "69", "time": fields.Datetime.to_string(self.now),
        }, self.ls_account)
        (bad | good)._process()
        self.assertEqual((bad.state, good.state), ("error", "done"))
        self.assertTrue(bad.error)
        self.assertTrue(self.Comment.search([("external_id", "=", "c3")]))

    def test_cron_processes_pending(self):
        event = self.Event._enqueue("simulator", {
            "kind": "comment", "session_id": self.session.id, "comment_id": "c4",
            "user_id": "u4", "name": "Vo E", "message": "69 sl 3", "time": fields.Datetime.to_string(self.now),
        }, self.ls_account)
        self.Event._cron_process()
        self.assertEqual(event.state, "done")
        self.assertEqual(self.Comment.search([("external_id", "=", "c4")]).quantity, 3)
