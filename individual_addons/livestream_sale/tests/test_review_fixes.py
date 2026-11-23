from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user, tagged

from odoo.addons.livestream_sale.models.tag_parser import parse_tag

from .common import LivestreamCommon


@tagged("post_install", "-at_install", "livestream")
class TestReviewFixes(LivestreamCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tx = cls.env["livestream.bank.transaction"]
        company = cls.company_data["company"]
        cls.assistant = new_test_user(
            cls.env, login="ls_rf_assistant", groups="livestream_sale.group_livestream_user", company_id=company.id,
        )
        cls.other_company = cls.env["res.company"].create({"name": "Other Shop"})
        cls.other_assistant = new_test_user(
            cls.env, login="ls_rf_other", groups="livestream_sale.group_livestream_user",
            company_id=cls.other_company.id, company_ids=[cls.other_company.id],
        )
        cls._n = 0

    def _order(self, deposit=100000, phone="0912345678", user="u1"):
        type(self)._n += 1
        comment = self.env["livestream.comment"]._ingest(
            self.session, f"rf-{self._n}", user, "Nguyen Van A", "69", fields.Datetime.now(),
        )
        return self.env["sale.order"].browse(comment.action_create_order(
            [{"product_id": self.product_shirt.id, "quantity": 2, "price_unit": 150000}],
            phone, "Nguyen Van A", "HN", deposit,
        ))

    def _bank(self, amount, content):
        type(self)._n += 1
        return self.Tx._register_transfer(self.provider, {
            "external_id": f"RF{self._n}", "date": fields.Datetime.now(), "amount": amount,
            "content": content, "reference": "R", "account_number": "1", "gateway": "VCB", "raw_payload": {},
        })

    # 1. failure after matching must not lose the transfer
    def test_auto_match_failure_keeps_transfer(self):
        so = self._order()
        with patch.object(self.registry["payment.transaction"], "_post_process", side_effect=UserError("boom")):
            tx = self._bank(100000, so.livestream_payment_ref)
        self.assertTrue(tx.exists())
        self.assertEqual(tx.state, "unmatched")
        self.assertEqual(so.amount_paid, 0)

    def test_retry_error_event(self):
        Event = self.env["livestream.webhook.event"]
        ev = Event._enqueue("simulator", {"kind": "comment", "session_id": 999999, "comment_id": "x",
                                          "user_id": "u", "name": "n", "message": "69"}, self.ls_account)
        ev._process()
        self.assertEqual(ev.state, "error")
        ev.payload = dict(ev.payload, session_id=self.session.id)
        ev.action_retry()
        self.assertEqual(ev.state, "done")

    # 2. re-match same order after unmatch
    def test_rematch_same_order_after_unmatch(self):
        so = self._order()
        tx = self._bank(100000, so.livestream_payment_ref)
        self.env["livestream.unmatch.wizard"].create({"transaction_id": tx.id, "reason": "test"}).action_confirm()
        tx._match_to_order(so, "manual")
        self.assertEqual(tx.state, "matched")
        self.assertEqual(so.amount_paid, 100000)

    # 3. assistants cannot bypass the deposit
    def test_assistant_zero_deposit_refused(self):
        comment = self.env["livestream.comment"]._ingest(self.session, "rf-z", "uz", "Z", "69", fields.Datetime.now())
        with self.assertRaises(UserError):
            comment.with_user(self.assistant).action_create_order(
                [{"product_id": self.product_shirt.id, "quantity": 1, "price_unit": 150000}], "0900000001", "Z", "HN", 0,
            )

    def test_assistant_cannot_lower_deposit(self):
        so = self._order()
        with self.assertRaises(UserError):
            so.with_user(self.assistant).write({"prepayment_amount": 0})
        with self.assertRaises(UserError):
            so.with_user(self.assistant).write({"prepayment_percent": 0})
        so.write({"prepayment_amount": 50000})  # manager may
        self.assertEqual(so.prepayment_amount, 50000)

    def test_assistant_can_create_order_with_deposit(self):
        comment = self.env["livestream.comment"]._ingest(self.session, "rf-a", "ua", "A", "69", fields.Datetime.now())
        oid = comment.with_user(self.assistant).action_create_order(
            [{"product_id": self.product_shirt.id, "quantity": 1, "price_unit": 150000}], "0900000002", "A", "HN", 50000,
        )
        self.assertEqual(self.env["sale.order"].browse(oid).prepayment_amount, 50000)

    def test_comment_cannot_create_second_order(self):
        so = self._order()
        comment = so.livestream_comment_ids
        with self.assertRaises(UserError):
            comment.action_create_order(
                [{"product_id": self.product_shirt.id, "quantity": 1, "price_unit": 150000}], "0900000003", "A", "HN", 50000,
            )

    # 4. bus pushes stay within the company
    def test_bus_only_to_company_users(self):
        with patch.object(self.registry["bus.bus"], "_sendone", autospec=True) as sendone:
            self.env["livestream.comment"]._ingest(self.session, "rf-bus", "ub", "B", "69", fields.Datetime.now())
        targets = [c.args[1] for c in sendone.call_args_list if c.args[2] == "livestream/comment"]
        self.assertTrue({self.assistant, self.assistant.partner_id} & set(targets))
        self.assertFalse({self.other_assistant, self.other_assistant.partner_id} & set(targets))
        self.assertNotIn(self.env.ref("livestream_sale.group_livestream_user"), targets)

    # 5. transfer content variants
    def test_ref_followed_by_digits_matches(self):
        for content in ["{ref} 0912345678", "DON {ref} 2 AO", "{ref} 1", "ck {ref}.0912345678"]:
            so = self._order(deposit=50000)
            tx = self._bank(10000, content.format(ref=so.livestream_payment_ref))
            self.assertEqual((tx.state, tx.sale_order_id), ("matched", so), content)

    def test_two_refs_one_unknown_not_matched(self):
        so = self._order()
        tx = self._bank(100000, f"{so.livestream_payment_ref} LS999998")
        self.assertEqual(tx.state, "unmatched")

    # 6. tag parser
    def test_parser_phone_and_quantity_words(self):
        self.assertEqual(parse_tag("0912 345 678"), (None, 1))
        self.assertEqual(parse_tag("0912.345.678"), (None, 1))
        self.assertEqual(parse_tag("sđt 0912-345-678 lấy 69"), ("69", 1))
        self.assertEqual(parse_tag("+84 912 345 678 69"), ("69", 1))
        self.assertEqual(parse_tag("lấy 2 cái mã 69", codes={"2", "69"}), ("69", 2))
        self.assertEqual(parse_tag("1 cái 69", codes={"1", "69"}), ("69", 1))
        self.assertEqual(parse_tag("sz 69-70"), ("69", 1))
        self.assertEqual(parse_tag("69 - 2c"), ("69", 2))
        self.assertEqual(parse_tag("#12 nha", codes={"12", "69"}), ("12", 1))

    # 8. partner dedup at scale
    def test_partner_dedup_many_similar_phones(self):
        self.env["res.partner"].create([{"name": f"P{i}", "phone": f"0987{i:06d}"} for i in range(250)])
        target = self.env["res.partner"].create({"name": "Target", "phone": "+84 987.654.912"})
        self.assertEqual(self.env["res.partner"]._livestream_find_or_create("X", "0987654912"), target)

    # 9. simulator cannot fake deposits on live providers / other companies
    def test_simulator_refuses_live_provider(self):
        self.provider.is_live = True
        with self.assertRaises(UserError):
            self.env["livestream.simulator"].simulate_bank(self.ls_account.id, 1000, "x")

    def test_simulator_respects_company(self):
        self.env["ir.config_parameter"].sudo().set_bool("livestream_sale.simulator_enabled", True)
        with self.assertRaises((AccessError, UserError)):
            self.env["livestream.simulator"].with_user(self.other_assistant).simulate_bank(self.ls_account.id, 1000, "x")

    # 10. tags are company-scoped
    def test_tag_not_visible_to_other_company(self):
        tags = self.env["livestream.session.tag"].with_user(self.other_assistant).search([("id", "=", self.tag_69.id)])
        self.assertFalse(tags)

    # 11. QR on private reply is not silently lost
    def test_qr_on_private_reply_logged(self):
        so = self._order()
        so.livestream_comment_ids.action_open_conversation()
        so.action_livestream_send_deposit_request()
        notes = so.livestream_channel_id.message_ids.filtered(lambda m: m.subtype_id == self.env.ref("mail.mt_note"))
        self.assertTrue(any("QR" in (m.body or "") for m in notes))
