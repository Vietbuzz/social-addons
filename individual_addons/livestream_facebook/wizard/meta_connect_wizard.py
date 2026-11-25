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


    def _shared_values(self):
        source = self.source_account_id.sudo()
        return {
            "fb_app_id": source.fb_app_id,
            "fb_app_secret": source.fb_app_secret,
            "company_id": source.company_id.id,
            "token_state": "valid",
            "token_checked_at": fields.Datetime.now(),
            "token_error": False,
            "active": True,
        }

    def _upsert_account(self, platform, external_id, values, create_values):
        Account = self.env["livestream.account"].sudo().with_context(active_test=False)
        account = Account.search([("platform", "=", platform), ("external_id", "=", external_id)], limit=1)
        if account:
            account.write(values)
        else:
            account = Account.create({**create_values, **values, "platform": platform, "external_id": external_id})
        return account

    def _apply_page(self, line):
        source = self.source_account_id.sudo()
        return self._upsert_account(
            "facebook", line.page_id,
            {**self._shared_values(), "access_token": line.page_token},
            {"name": line.name, "fb_verify_token": source.fb_verify_token,
             "payment_provider_id": source.payment_provider_id.id},
        )

    def _apply_instagram(self, line):
        """Hook: livestream_instagram connects the linked Instagram account."""
        return self.env["livestream.account"]

    def action_apply(self):
        self.ensure_one()
        accounts = self.env["livestream.account"]
        for line in self.line_ids.filtered("selected"):
            accounts |= self._apply_page(line)
            accounts |= self._apply_instagram(line)
        self.user_token = False
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Connected Accounts"),
            "res_model": "livestream.account",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "domain": [("id", "in", accounts.ids)],
            "target": "current",
        }


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
