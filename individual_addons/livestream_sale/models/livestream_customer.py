from odoo import api, fields, models


class LivestreamCustomer(models.Model):
    _name = "livestream.customer"
    _description = "Livestream Customer Identity"
    _order = "name"

    account_id = fields.Many2one("livestream.account", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="account_id.company_id", store=True, index=True)
    external_user_id = fields.Char("Platform User ID", required=True)
    psid = fields.Char("Messenger ID", index=True, copy=False)
    name = fields.Char(required=True)
    avatar_url = fields.Char()
    partner_id = fields.Many2one("res.partner", index=True)
    channel_id = fields.Many2one("discuss.channel", copy=False)

    _account_user_uniq = models.Constraint(
        "UNIQUE(account_id, external_user_id)", "Customer identity already exists.",
    )

    @api.model
    def _get_or_create(self, account, external_user_id, name, avatar_url=None):
        customer = self.search([
            ("account_id", "=", account.id), ("external_user_id", "=", external_user_id),
        ], limit=1)
        if customer:
            updates = {}
            if name and customer.name != name:
                updates["name"] = name
            if avatar_url and customer.avatar_url != avatar_url:
                updates["avatar_url"] = avatar_url
            if updates:
                customer.write(updates)
            return customer
        return self.create({
            "account_id": account.id,
            "external_user_id": external_user_id,
            "name": name or external_user_id,
            "avatar_url": avatar_url,
        })
