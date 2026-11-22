from odoo import fields, models
from odoo.exceptions import AccessError


class LivestreamUnmatchWizard(models.TransientModel):
    _name = "livestream.unmatch.wizard"
    _description = "Unmatch Bank Transfer"

    transaction_id = fields.Many2one("livestream.bank.transaction", required=True, ondelete="cascade")
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group("livestream_sale.group_livestream_manager"):
            raise AccessError(self.env._("Only a livestream manager can unmatch a bank transfer."))
        self.transaction_id._unmatch(self.reason)
        return {"type": "ir.actions.act_window_close"}
