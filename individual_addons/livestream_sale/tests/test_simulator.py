from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged

from .common import LivestreamCommon


@tagged("post_install", "-at_install", "livestream")
class TestSimulator(LivestreamCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Sim = cls.env["livestream.simulator"]
        cls.assistant = new_test_user(
            cls.env, login="ls_assistant3", groups="livestream_sale.group_livestream_user",
            company_id=cls.company_data["company"].id,
        )

    def test_simulate_comment_creates_comment(self):
        cid = self.Sim.simulate_comment(self.session.id)
        comment = self.env["livestream.comment"].browse(cid)
        self.assertEqual(comment.session_id, self.session)
        self.assertEqual(comment.tag_code, "69")
        self.assertIn(comment.quantity, (1, 2, 3))
        cid2 = self.Sim.simulate_comment(self.session.id, message="69 x2", author_name="Nguyen Van A")
        self.assertEqual(self.env["livestream.comment"].browse(cid2).customer_id.name, "Nguyen Van A")

    def test_simulate_customer_reply(self):
        comment = self.env["livestream.comment"].browse(self.Sim.simulate_comment(self.session.id))
        channel_id = comment.action_open_conversation()["channel_id"]
        self.Sim.simulate_customer_reply(channel_id, "Sdt em 0912345678")
        channel = self.env["discuss.channel"].browse(channel_id)
        self.assertEqual(channel.livestream_window_state, "open")
        self.assertTrue(comment.customer_id.psid)

    def test_simulate_bank_auto_matches(self):
        comment = self.env["livestream.comment"].browse(self.Sim.simulate_comment(self.session.id, message="69"))
        so = self.env["sale.order"].browse(comment.action_create_order(
            [{"product_id": self.product_shirt.id, "quantity": 1, "price_unit": 150000}],
            "0912345678", "A", "HN", 50000,
        ))
        tid = self.Sim.simulate_bank(self.ls_account.id, 50000, f"CK {so.livestream_payment_ref}")
        tx = self.env["livestream.bank.transaction"].browse(tid)
        self.assertEqual(tx.state, "matched")
        self.assertEqual(so.state, "sale")

    def test_simulator_disabled_for_assistant(self):
        with self.assertRaises(AccessError):
            self.Sim.with_user(self.assistant).simulate_comment(self.session.id)

    def test_simulator_enabled_by_parameter(self):
        self.env["ir.config_parameter"].sudo().set_bool("livestream_sale.simulator_enabled", True)
        cid = self.Sim.with_user(self.assistant).simulate_comment(self.session.id)
        self.assertTrue(cid)
