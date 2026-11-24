from odoo import fields, models


class LivestreamAccount(models.Model):
    _inherit = "livestream.account"

    platform = fields.Selection(selection_add=[("instagram", "Instagram")], ondelete={"instagram": "cascade"})
    fb_page_id = fields.Char(
        "Linked Facebook Page ID",
        help="Instagram via Facebook Login: messages and private replies go through the linked Page.",
    )
    ig_webhook_url = fields.Char(compute="_compute_ig_webhook_url")

    def _compute_ig_webhook_url(self):
        url = f"{self.get_base_url()}/livestream/instagram/webhook"
        for account in self:
            account.ig_webhook_url = url if account.platform == "instagram" else False
