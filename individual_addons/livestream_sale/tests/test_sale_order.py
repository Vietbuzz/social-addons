from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged

from .common import LivestreamCommon


@tagged("post_install", "-at_install", "livestream")
class TestLivestreamOrder(LivestreamCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.comment = cls.env["livestream.comment"]._ingest(
            cls.session, "c1", "u1", "Nguyen Van A", "69 x2", fields.Datetime.now(),
        )
        cls.assistant = new_test_user(
            cls.env, login="ls_assistant", groups="livestream_sale.group_livestream_user",
            company_id=cls.company_data["company"].id,
        )
        cls.Account = cls.registry["livestream.account"]

    def _create_order(self, comment=None, phone="0912 345 678", deposit=100000):
        comment = comment or self.comment
        oid = comment.action_create_order(
            [{"product_id": self.product_shirt.id, "quantity": 2, "price_unit": 150000}],
            phone, "Nguyen Van A", "1 Le Loi", deposit,
        )
        return self.env["sale.order"].browse(oid)

    def test_create_order_from_comment(self):
        so = self._create_order()
        self.assertEqual(so.amount_untaxed, 300000)
        self.assertEqual(so.prepayment_amount, 100000)
        self.assertAlmostEqual(so._get_prepayment_required_amount(), 100000)
        self.assertRegex(so.livestream_payment_ref, r"^LS\d{6}$")
        self.assertEqual(so.livestream_session_id, self.session)
        self.assertTrue(so.is_livestream)
        self.assertFalse(so.require_signature)
        self.assertEqual(so.livestream_deposit_due, 100000)
        self.assertEqual(self.comment.state, "ordered")
        self.assertEqual(self.comment.sale_order_id, so)
        self.assertEqual(so.partner_id.phone, "0912345678")
        self.assertEqual(so.partner_id.street, "1 Le Loi")
        self.assertEqual(self.comment.customer_id.partner_id, so.partner_id)

    def test_payment_refs_unique(self):
        so1 = self._create_order()
        so2 = self._create_order()
        self.assertNotEqual(so1.livestream_payment_ref, so2.livestream_payment_ref)

    def test_partner_merge_by_phone(self):
        existing = self.env["res.partner"].create({"name": "Anh A cu", "phone": "+84 912.345.678"})
        so = self._create_order()
        self.assertEqual(so.partner_id, existing)

    def test_confirm_blocked_without_deposit(self):
        so = self._create_order()
        with self.assertRaises(UserError):
            so.with_user(self.assistant).action_confirm()
        self.assertIn(so.state, ("draft", "sent"))

    def test_manager_confirm_without_deposit_logged(self):
        so = self._create_order()
        so.action_confirm()
        self.assertEqual(so.state, "sale")
        self.assertTrue(so.message_ids.filtered(lambda m: "without full deposit" in (m.body or "")))

    def test_non_livestream_order_unaffected(self):
        so = self.env["sale.order"].create({
            "partner_id": self.partner_a.id,
            "order_line": [fields.Command.create({"product_id": self.product_shirt.id})],
        })
        so.with_user(self.assistant).action_confirm()
        self.assertEqual(so.state, "sale")

    def test_vietqr_generated(self):
        so = self._create_order()
        self.assertTrue(so._generate_vietqr_url().startswith("data:image/png;base64,"))

    def test_vietqr_without_bank_account_raises(self):
        so = self._create_order()
        self.bank_journal.bank_account_id = False
        with self.assertRaises(UserError):
            so._generate_vietqr_url()

    def test_deposit_message_mentions_ref_and_amount(self):
        so = self._create_order()
        msg = so.livestream_deposit_message()
        self.assertIn(so.livestream_payment_ref, msg)
        self.assertIn("100.000", msg)
        self.assertIn("0011223344", msg)

    def test_send_deposit_request_posts_to_channel(self):
        self.comment.action_open_conversation()
        so = self._create_order()
        with patch.object(self.Account, "_livestream_private_reply", autospec=True, return_value="psid") as pr:
            so.action_livestream_send_deposit_request()
        pr.assert_called_once()
        attachments = pr.call_args.args[3]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments.mimetype, "image/png")
        last = so.livestream_channel_id.message_ids[:1]
        self.assertIn(so.livestream_payment_ref, last.body)
