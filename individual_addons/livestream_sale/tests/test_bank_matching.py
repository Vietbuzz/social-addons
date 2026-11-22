from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user, tagged

from .common import LivestreamCommon


@tagged("post_install", "-at_install", "livestream")
class TestBankMatching(LivestreamCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tx = cls.env["livestream.bank.transaction"]
        cls.assistant = new_test_user(
            cls.env, login="ls_assistant2", groups="livestream_sale.group_livestream_user",
            company_id=cls.company_data["company"].id,
        )
        cls._seq = 0

    def _order(self, name="Nguyen Van A", phone="0912345678", deposit=100000, user="u1"):
        comment = self.env["livestream.comment"]._ingest(
            self.session, f"c-{user}-{phone}", user, name, "69 x2", fields.Datetime.now(),
        )
        oid = comment.action_create_order(
            [{"product_id": self.product_shirt.id, "quantity": 2, "price_unit": 150000}],
            phone, name, "1 Le Loi", deposit,
        )
        return self.env["sale.order"].browse(oid)

    def _bank(self, amount, content, external_id=None):
        type(self)._seq += 1
        return self.Tx._register_transfer(self.provider, {
            "external_id": external_id or f"T{self._seq}",
            "date": fields.Datetime.now(),
            "amount": amount,
            "content": content,
            "reference": f"FT{self._seq}",
            "account_number": "0011223344",
            "gateway": "Vietcombank",
            "raw_payload": {"id": self._seq},
        })

    def test_auto_match_exact_ref(self):
        so = self._order()
        tx = self._bank(100000, f"CK {so.livestream_payment_ref}")
        self.assertEqual(tx.state, "matched")
        self.assertEqual(tx.match_method, "auto")
        self.assertEqual(tx.sale_order_id, so)
        self.assertEqual(so.amount_paid, 100000)
        self.assertEqual(so.state, "sale")
        self.assertEqual(tx.payment_transaction_id.state, "done")

    def test_auto_match_normalizes_content(self):
        so = self._order(deposit=300000)
        n = so.livestream_payment_ref[2:]
        for content in [f"ls {n}", f"L S{n}", f"Ls.{n} chuyen tien", f"thanh toán LS{n}", f"MBVCB.123.ls-{n}.CT tu"]:
            tx = self._bank(1000, content)
            self.assertEqual(tx.state, "matched", content)
            self.assertEqual(tx.sale_order_id, so, content)

    def test_auto_match_ambiguous_skipped(self):
        so1, so2 = self._order(), self._order(phone="0987654321", user="u2")
        tx = self._bank(100000, f"{so1.livestream_payment_ref} {so2.livestream_payment_ref}")
        self.assertEqual(tx.state, "unmatched")

    def test_no_ref_stays_unmatched(self):
        tx = self._bank(100000, "chuyen tien coc ao do")
        self.assertEqual(tx.state, "unmatched")
        self.assertFalse(tx.sale_order_id)

    def test_cancelled_order_not_auto_matched(self):
        so = self._order()
        so._action_cancel()
        tx = self._bank(100000, so.livestream_payment_ref)
        self.assertEqual(tx.state, "unmatched")

    def test_partial_deposit_keeps_quotation(self):
        so = self._order()
        self._bank(50000, so.livestream_payment_ref)
        self.assertIn(so.state, ("draft", "sent"))
        self.assertEqual(so.livestream_deposit_due, 50000)

    def test_two_transfers_confirm_order(self):
        so = self._order()
        self._bank(50000, so.livestream_payment_ref)
        self._bank(50000, f"lan 2 {so.livestream_payment_ref}")
        self.assertEqual(so.state, "sale")
        self.assertEqual(so.amount_paid, 100000)
        self.assertEqual(len(so.livestream_bank_transaction_ids), 2)

    def test_manual_match(self):
        so = self._order()
        tx = self._bank(100000, "ck ao do")
        res = tx.with_user(self.assistant).action_match_manual(so.id)
        self.assertEqual(res["state"], "matched")
        self.assertEqual((tx.state, tx.match_method, tx.matched_by), ("matched", "manual", self.assistant))
        self.assertEqual(so.state, "sale")

    def test_match_twice_raises(self):
        so1, so2 = self._order(), self._order(phone="0987654321", user="u2")
        tx = self._bank(100000, "ck")
        tx._match_to_order(so1, "manual")
        with self.assertRaises(UserError):
            tx._match_to_order(so2, "manual")
        self.assertEqual(so2.amount_paid, 0)

    def test_immutable_fields(self):
        tx = self._bank(100000, "ck")
        for vals in ({"amount": 1}, {"content": "LS000001"}, {"external_id": "X"}, {"date": fields.Datetime.now()}):
            with self.assertRaises(UserError):
                tx.write(vals)
            with self.assertRaises(UserError):
                tx.sudo().write(vals)

    def test_register_idempotent(self):
        so = self._order()
        tx1 = self._bank(100000, so.livestream_payment_ref, external_id="SAME")
        tx2 = self._bank(100000, so.livestream_payment_ref, external_id="SAME")
        self.assertEqual(tx1, tx2)
        self.assertEqual(len(so.transaction_ids), 1)

    def test_payment_created_in_bank_journal(self):
        so = self._order()
        tx = self._bank(100000, so.livestream_payment_ref)
        payment = tx.payment_transaction_id.payment_id
        self.assertTrue(payment)
        self.assertEqual(payment.journal_id, self.bank_journal)
        self.assertEqual(payment.partner_id, so.partner_id.commercial_partner_id)
        self.assertEqual(payment.amount, 100000)

    def test_suggestions_rank_amount_and_phone(self):
        so_amount = self._order(name="Tran Thi B", phone="0987000001", user="u2", deposit=120000)
        so_phone = self._order(name="Le Van C", phone="0987000002", user="u3", deposit=90000)
        self._order(name="Pham D", phone="0987000003", user="u4", deposit=50000)
        tx = self._bank(120000, "chuyen tien 0987000002")
        ranked = [s["order_id"] for s in tx._suggest_orders()]
        self.assertEqual(ranked[:2], [so_amount.id, so_phone.id])
        self.assertTrue(all(s["score"] > 0 for s in tx._suggest_orders()))

    def test_unmatch_by_manager(self):
        so = self._order()
        tx = self._bank(100000, so.livestream_payment_ref)
        payment = tx.payment_transaction_id.payment_id
        pay_tx = tx.payment_transaction_id
        wizard = self.env["livestream.unmatch.wizard"].create({"transaction_id": tx.id, "reason": "nham don"})
        wizard.action_confirm()
        self.assertEqual(tx.state, "unmatched")
        self.assertFalse(tx.sale_order_id)
        self.assertEqual(payment.state, "canceled")
        self.assertEqual(pay_tx.state, "cancel")
        self.assertEqual(so.amount_paid, 0)
        self.assertTrue(tx.message_ids.filtered(lambda m: "nham don" in (m.body or "")))
        # the freed transaction can now be matched to the right order
        so2 = self._order(phone="0987654321", user="u2")
        tx._match_to_order(so2, "manual")
        self.assertEqual(tx.sale_order_id, so2)

    def test_unmatch_forbidden_for_assistant(self):
        so = self._order()
        tx = self._bank(100000, so.livestream_payment_ref)
        with self.assertRaises((AccessError, UserError)):
            self.env["livestream.unmatch.wizard"].with_user(self.assistant).create(
                {"transaction_id": tx.id, "reason": "x"},
            ).action_confirm()
        self.assertEqual(tx.state, "matched")

    def test_ignore_by_manager(self):
        tx = self._bank(5000, "tien an trua")
        tx.action_ignore()
        self.assertEqual(tx.state, "ignored")
        with self.assertRaises(UserError):
            tx._match_to_order(self._order(), "manual")

    def test_setup_provider_journal_posts_to_bank_account(self):
        self.ls_account.action_setup_provider_journal()
        line = self.bank_journal.inbound_payment_method_line_ids.filtered(
            lambda l: l.payment_provider_id == self.provider
        )
        self.assertEqual(line.payment_account_id, self.bank_journal.default_account_id)
        so = self._order()
        tx = self._bank(100000, so.livestream_payment_ref)
        payment = tx.payment_transaction_id.payment_id
        self.assertIn(self.bank_journal.default_account_id, payment.move_id.line_ids.account_id)
