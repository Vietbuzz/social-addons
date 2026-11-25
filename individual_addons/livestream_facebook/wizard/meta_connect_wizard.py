from odoo import api, fields, models


class LivestreamMetaConnectWizard(models.TransientModel):
    _name = "livestream.meta.connect.wizard"
    _description = "Connect Facebook Pages"

    source_account_id = fields.Many2one("livestream.account", required=True, ondelete="cascade")
    user_token = fields.Char(groups="livestream_sale.group_livestream_manager")
    line_ids = fields.One2many("livestream.meta.connect.wizard.line", "wizard_id")

    @api.model
    def _create_from_pages(self, account, user_token, pages):
        Account = self.env["livestream.account"]
        connected = set(Account.search([("platform", "=", "facebook")]).mapped("external_id"))
        if account.platform == "instagram" and account.fb_page_id:
            connected.add(account.fb_page_id)
        return self.create({
            "source_account_id": account.id,
            "user_token": user_token,
            "line_ids": [fields.Command.create({
                "page_id": p["page_id"], "name": p["name"], "page_token": p["token"],
                "ig_id": p["ig_id"], "ig_username": p["ig_username"],
                "selected": p["page_id"] in connected,
            }) for p in pages],
        })


class LivestreamMetaConnectWizardLine(models.TransientModel):
    _name = "livestream.meta.connect.wizard.line"
    _description = "Facebook Page to connect"

    wizard_id = fields.Many2one("livestream.meta.connect.wizard", required=True, ondelete="cascade")
    selected = fields.Boolean("Connect")
    page_id = fields.Char("Page ID", readonly=True)
    name = fields.Char("Page", readonly=True)
    page_token = fields.Char(groups="livestream_sale.group_livestream_manager")
    ig_id = fields.Char("Instagram ID", readonly=True)
    ig_username = fields.Char("Instagram", readonly=True)
