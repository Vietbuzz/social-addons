import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.livestream_sale.tests.common import LivestreamCommon
from odoo.addons.livestream_sepay.models import sepay_api

PAYLOADS = Path(__file__).parent / "payloads"


def payload(name):
    return json.loads((PAYLOADS / name).read_text())


@tagged("post_install", "-at_install", "livestream")
class TestSepay(LivestreamCommon, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.company_data["company"]
        cls.sepay = cls.env["payment.provider"].create({
            "name": "SePay",
            "code": "sepay",
            "company_id": company.id,
            "journal_id": cls.bank_journal.id,
            "sepay_webhook_api_key": "secret-key",
            "sepay_api_token": "api-token",
            "sepay_account_number": "0011223344",
        })
        cls.env["payment.method"].create({
            "name": "SePay transfer", "code": "sepay_test", "provider_id": cls.sepay.id, "active": True,
        })
        cls.ls_account.payment_provider_id = cls.sepay
        comment = cls.env["livestream.comment"]._ingest(
            cls.session, "c1", "u1", "Nguyen Van A", "69", fields.Datetime.now(),
        )
        cls.order = cls.env["sale.order"].browse(comment.action_create_order(
            [{"product_id": cls.product_shirt.id, "quantity": 1, "price_unit": 150000}],
            "0912345678", "Nguyen Van A", "HN", 100000,
        ))
        cls.Tx = cls.env["livestream.bank.transaction"]

    def _post(self, body, key="secret-key"):
        headers = {"Content-Type": "application/json"}
        if key is not None:
            headers["Authorization"] = f"Apikey {key}"
        return self.url_open(
            f"/livestream/sepay/webhook/{self.sepay.id}", data=json.dumps(body), headers=headers,
        )

    def _webhook_body(self, **kw):
        body = payload("webhook_in.json")
        body["content"] = f"{self.order.livestream_payment_ref} chuyen tien"
        body.update(kw)
        return body

    def test_sepay_webhook_idempotent(self):
        body = self._webhook_body()
        for _i in range(2):
            res = self._post(body)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json(), {"success": True})
        self.env["livestream.webhook.event"]._cron_process()
        txs = self.Tx.search([("provider_id", "=", self.sepay.id)])
        self.assertEqual(len(txs), 1)
        self.assertEqual(len(self.order.transaction_ids), 1)

    def test_webhook_bad_key_rejected(self):
        with mute_logger("odoo.addons.livestream_sepay.controllers.main"):
            self.assertEqual(self._post(self._webhook_body(), key="wrong").status_code, 401)
            self.assertEqual(self._post(self._webhook_body(), key=None).status_code, 401)
        self.assertFalse(self.env["livestream.webhook.event"].search([("source", "=", "sepay")]))

    def test_webhook_out_ignored(self):
        self._post(self._webhook_body(transferType="out", id=1))
        self.env["livestream.webhook.event"]._cron_process()
        self.assertFalse(self.Tx.search([("provider_id", "=", self.sepay.id)]))

    def test_webhook_auto_matches_order(self):
        self._post(self._webhook_body())
        self.env["livestream.webhook.event"]._cron_process()
        tx = self.Tx.search([("provider_id", "=", self.sepay.id)])
        self.assertEqual((tx.state, tx.external_id, tx.reference), ("matched", "92704", "FT24012345678"))
        self.assertEqual(self.order.amount_paid, 100000)
        self.assertEqual(self.order.state, "sale")

    def test_cron_pull_dedup_with_webhook(self):
        self._post(self._webhook_body())
        self.env["livestream.webhook.event"]._cron_process()
        listing = payload("transactions_list.json")["transactions"]
        with patch.object(sepay_api, "fetch_transactions", return_value=listing) as fetch:
            self.env["payment.provider"]._sepay_cron_pull()
        fetch.assert_called_once_with("api-token", "0011223344", 1)
        txs = self.Tx.search([("provider_id", "=", self.sepay.id)])
        self.assertEqual(sorted(txs.mapped("external_id")), ["92704", "92705"])  # out tx skipped, no dup
        new = txs.filtered(lambda t: t.external_id == "92705")
        self.assertEqual((new.amount, new.content, new.state), (50000, "ck coc ao do", "unmatched"))
        self.assertEqual(self.sepay.sepay_last_pulled_id, 92705)

    def test_date_timezone(self):
        vals = sepay_api.sepay_webhook_to_vals(self._webhook_body())
        self.assertEqual(vals["date"], datetime(2026, 11, 22, 7, 2, 37))
        self.assertEqual(vals["amount"], 100000)

    def test_cron_pull_bad_row_does_not_block(self):
        listing = payload("transactions_list.json")["transactions"]
        Tx = self.registry["livestream.bank.transaction"]
        real = Tx._register_transfer

        def flaky(model, provider, vals):
            if vals["external_id"] == "92704":
                raise ValueError("boom")
            return real(model, provider, vals)

        with patch.object(sepay_api, "fetch_transactions", return_value=listing), \
                patch.object(Tx, "_register_transfer", autospec=True, side_effect=flaky), \
                mute_logger("odoo.addons.livestream_sepay.models.payment_provider"):
            self.env["payment.provider"]._sepay_cron_pull()
        self.assertTrue(self.Tx.search([("external_id", "=", "92705")]))
        self.assertEqual(self.sepay.sepay_last_pulled_id, 92705)

    def test_webhook_event_company_is_provider_company(self):
        self._post(self._webhook_body())
        event = self.env["livestream.webhook.event"].search([("source", "=", "sepay")])
        self.assertEqual(event.company_id, self.sepay.company_id)
