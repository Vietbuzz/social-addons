import logging

from odoo import api, fields, models

from . import sepay_api

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(selection_add=[("sepay", "SePay")], ondelete={"sepay": "set default"})
    sepay_webhook_api_key = fields.Char(
        "Webhook API Key", groups="base.group_system", copy=False,
        help="Key SePay sends as 'Authorization: Apikey <key>' on each webhook.",
    )
    sepay_api_token = fields.Char("API Token", groups="base.group_system", copy=False)
    sepay_account_number = fields.Char("Bank Account Number", help="Limit pulled transactions to this account.")
    sepay_last_pulled_id = fields.Integer("Last Pulled SePay ID", copy=False, readonly=True)
    sepay_webhook_url = fields.Char(compute="_compute_sepay_webhook_url")

    def _compute_sepay_webhook_url(self):
        base = self.get_base_url()
        for provider in self:
            provider.sepay_webhook_url = f"{base}/livestream/sepay/webhook/{provider.id}" if provider.id else False

    def _get_default_payment_method_codes(self):
        if self.code != "sepay":
            return super()._get_default_payment_method_codes()
        return {"sepay"}

    @api.model
    def _sepay_cron_pull(self):
        """Pull recent transfers to catch webhooks that never arrived (e.g. no tunnel locally)."""
        for provider in self.sudo().search([("code", "=", "sepay"), ("active", "=", True)]):
            if not provider.sepay_api_token:
                continue
            try:
                rows = sepay_api.fetch_transactions(
                    provider.sepay_api_token, provider.sepay_account_number, provider.sepay_last_pulled_id + 1,
                )
            except Exception as e:  # noqa: BLE001 - network errors must not break the cron for other providers
                _logger.warning("SePay pull failed for provider %s: %s", provider.id, e)
                continue
            Tx = self.env["livestream.bank.transaction"]
            max_id = provider.sepay_last_pulled_id
            for row in sorted(rows, key=lambda r: int(r["id"])):
                max_id = max(max_id, int(row["id"]))
                vals = sepay_api.sepay_api_to_vals(row)
                if not vals:
                    continue
                try:
                    with self.env.cr.savepoint():
                        Tx._register_transfer(provider, vals)
                except Exception as e:  # noqa: BLE001 - e.g. webhook committed the same transfer meanwhile
                    _logger.warning("SePay transaction %s skipped by pull: %s", row.get("id"), e)
            provider.sepay_last_pulled_id = max_id
