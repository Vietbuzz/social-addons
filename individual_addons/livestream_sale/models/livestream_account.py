import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
        message = {"account_id": self.id, "company_id": self.company_id.id, "items": payload}
        users = self.env.ref("livestream_sale.group_livestream_user").sudo().all_user_ids.filtered(
            lambda u: self.company_id in u.company_ids
        )
        for partner in users.partner_id:
            partner._bus_send(notification_type, message)

    # Platform hooks: connector modules override these for their platform.
    def _livestream_private_reply(self, comment, body, attachments):
        """Send the one-off private reply to a comment; return the inbox id if known."""
        self.ensure_one()
        if self.platform == "simulator":
            _logger.info("Simulator private reply to %s: %s", comment.external_id, body)
            return f"sim-{comment.customer_id.external_user_id}"
        raise UserError(self.env._("Private replies are not supported for %s.", self.platform))

    def _livestream_send_message(self, customer, body, attachments):
        self.ensure_one()
        if self.platform == "simulator":
            _logger.info("Simulator message to %s: %s", customer.name, body)
            return
        raise UserError(self.env._("Messaging is not supported for %s.", self.platform))

    def action_setup_provider_journal(self):
        """Post deposits straight to the bank account (Community has no bank
        statement reconciliation widget, so no outstanding receipts step)."""
        if not self.env.user.has_group("livestream_sale.group_livestream_manager"):
            raise UserError(self.env._("Only a livestream manager can configure deposits."))
        for account in self:
            provider = account.payment_provider_id.sudo()
            journal = provider.journal_id
            if not journal or journal.type != "bank":
                raise UserError(self.env._("Set a bank journal on the deposit provider first."))
            lines = journal.inbound_payment_method_line_ids.filtered(lambda l: l.payment_provider_id == provider)
            if not lines:
                raise UserError(self.env._("The bank journal has no payment method line for %s.", provider.name))
            lines.payment_account_id = journal.default_account_id
        return True
