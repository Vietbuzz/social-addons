from odoo import fields
from odoo.tests import tagged

from .common import LivestreamCommon


@tagged("post_install", "-at_install", "livestream")
class TestConsole(LivestreamCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Console = cls.env["livestream.console"]
        cls.comment = cls.env["livestream.comment"]._ingest(
            cls.session, "c1", "u1", "Nguyen Van A", "69 x2", fields.Datetime.now(),
        )

    def test_console_load_shapes(self):
        data = self.Console.load(self.session.id)
        self.assertEqual(set(data), {"sessions", "session", "comments", "bank_transactions", "can_simulate", "default_deposit"})
        self.assertEqual(data["session"]["id"], self.session.id)
        self.assertEqual(data["session"]["account_id"], self.ls_account.id)
        self.assertEqual(data["session"]["tags"][0]["code"], "69")
        self.assertEqual(data["comments"][0]["id"], self.comment.id)
        self.assertTrue(data["can_simulate"])

    def test_console_load_defaults_to_live_session(self):
        data = self.Console.load(False)
        self.assertEqual(data["session"]["id"], self.session.id)

    def test_load_more_comments_filters_tag(self):
        other = self.env["livestream.comment"]._ingest(self.session, "c2", "u2", "B", "dep qua", fields.Datetime.now())
        res = self.Console.load_more_comments(self.session.id, other.id + 1, "69")
        self.assertEqual([c["id"] for c in res], [self.comment.id])

    def test_order_panel_prefills_from_tag(self):
        panel = self.Console.order_panel(self.comment.id)
        self.assertEqual(panel["lines"][0], {
            "product_id": self.product_shirt.id, "product_name": "Ao thun do", "quantity": 2, "price_unit": 150000,
        })
        self.assertIsNone(panel["order"])
        self.assertEqual(panel["customer"]["name"], "Nguyen Van A")

    def test_order_panel_existing_order_has_qr(self):
        self.comment.action_create_order(
            [{"product_id": self.product_shirt.id, "quantity": 2, "price_unit": 150000}],
            "0912345678", "Nguyen Van A", "HN", 100000,
        )
        panel = self.Console.order_panel(self.comment.id)
        order = panel["order"]
        self.assertEqual(order["deposit_due"], 100000)
        self.assertTrue(order["qr_url"].startswith("data:image/png;base64,"))
        self.assertRegex(order["payment_ref"], r"^LS\d{6}$")
        self.assertEqual(panel["customer"]["phone"], "0912345678")

    def test_order_panel_channel_window(self):
        self.comment.action_open_conversation()
        panel = self.Console.order_panel(self.comment.id)
        self.assertEqual(panel["channel"]["id"], self.comment.channel_id.id)
        self.assertEqual(panel["channel"]["window_state"], "waiting")

    def test_session_opens_console(self):
        action = self.session.action_open_console()
        self.assertEqual(action["tag"], "livestream_console")
        self.assertEqual(action["params"]["session_id"], self.session.id)

    def test_console_platform_fields(self):
        data = self.Console.load(self.session.id)
        self.assertEqual(data["session"]["platform"], "simulator")
        self.assertTrue(all("platform" in s for s in data["sessions"]))
        self.assertEqual(data["comments"][0]["platform"], "simulator")
