from odoo import api, fields, models
from odoo.exceptions import UserError

SERVER_CTX = "livestream_meta_connect"  # only server code (OAuth callback) may create wizards / set tokens


class LivestreamMetaConnectWizard(models.TransientModel):
    _name = "livestream.meta.connect.wizard"
    _description = "Connect Facebook Pages"

    source_account_id = fields.Many2one("livestream.account", required=True, ondelete="cascade")
    user_token = fields.Char(groups="livestream_sale.group_livestream_manager")
    line_ids = fields.One2many("livestream.meta.connect.wizard.line", "wizard_id")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get(SERVER_CTX):
            raise UserError(self.env._("Start the connection with the 'Connect with Facebook' button."))
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) - {"line_ids"} and not self.env.context.get(SERVER_CTX):
            raise UserError(self.env._("This connection cannot be modified."))
        return super().write(vals)

    @api.model
    def _create_from_pages(self, account, user_token, pages):
        Account = self.env["livestream.account"]
        connected = set(Account.search([("platform", "=", "facebook")]).mapped("external_id"))
        if account.platform == "instagram" and account.fb_page_id:
            connected.add(account.fb_page_id)
        return self.with_context(**{SERVER_CTX: True}).create({
            "source_account_id": account.id,
            "user_token": user_token,
            "line_ids": [fields.Command.create({
                "page_id": p["page_id"], "name": p["name"], "page_token": p["token"],
                "ig_id": p["ig_id"], "ig_username": p["ig_username"],
                "selected": bool(p["token"]) and p["page_id"] in connected,
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
            if account.company_id not in self.env.companies:
                raise UserError(self.env._(
                    "%(name)s is already connected in another company (%(company)s).",
                    name=account.name, company=account.company_id.name,
                ))
            account.write({k: v for k, v in values.items() if k != "company_id"})
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
        lines = self.sudo().line_ids.filtered(lambda l: l.selected and l.page_token)
        for line in lines:
            accounts |= self._apply_page(line)
            accounts |= self._apply_instagram(line)
        # tokens are not kept in the transient wizard once applied
        self.sudo().with_context(**{SERVER_CTX: True}).write({"user_token": False})
        self.sudo().line_ids.with_context(**{SERVER_CTX: True}).write({"page_token": False})
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
    connectable = fields.Boolean(compute="_compute_connectable")

    def _compute_connectable(self):
        for line in self:
            line.connectable = bool(line.sudo().page_token)

    def write(self, vals):
        if set(vals) - {"selected"} and not self.env.context.get(SERVER_CTX):
            raise UserError(self.env._("Only the selection of a Page can be changed."))
        return super().write(vals)
