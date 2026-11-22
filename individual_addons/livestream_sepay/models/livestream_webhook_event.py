from odoo import fields, models
from odoo.exceptions import UserError

from . import sepay_api


class LivestreamWebhookEvent(models.Model):
    _inherit = "livestream.webhook.event"

    source = fields.Selection(selection_add=[("sepay", "SePay")], ondelete={"sepay": "cascade"})

    def _process_sepay(self, payload):
        if payload.get("transferType") != "in":
            return
        provider = self.env["payment.provider"].sudo().browse(payload.get("_provider_id")).exists()
        if not provider or provider.code != "sepay":
            raise UserError(self.env._("Unknown SePay provider %s", payload.get("_provider_id")))
        body = {k: v for k, v in payload.items() if not k.startswith("_")}
        self.env["livestream.bank.transaction"]._register_transfer(provider, sepay_api.sepay_webhook_to_vals(body))
