from odoo import api, fields, models


class LivestreamAccount(models.Model):
    _name = "livestream.account"
    _description = "Livestream Connected Account"
    _order = "name"

    name = fields.Char(required=True)
    platform = fields.Selection([("simulator", "Simulator")], required=True, default="simulator")
    external_id = fields.Char("External ID", help="Page / account id on the platform")
    access_token = fields.Char(groups="livestream_sale.group_livestream_manager", copy=False)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    active = fields.Boolean(default=True)
    payment_provider_id = fields.Many2one(
        "payment.provider", "Deposit Provider",
        help="Provider receiving bank transfers for deposits; its journal's bank account is used for VietQR.",
    )
    session_ids = fields.One2many("livestream.session", "account_id")

    _platform_external_uniq = models.Constraint(
        "UNIQUE(platform, external_id)", "This account is already connected.",
    )

    def _notify_console(self, notification_type, payload):
        """Push items to every open operator console (clients filter on account_id)."""
        self.ensure_one()
        self.env.ref("livestream_sale.group_livestream_user")._bus_send(notification_type, {
            "account_id": self.id,
            "company_id": self.company_id.id,
            "items": payload,
        })
