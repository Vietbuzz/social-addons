from odoo import fields, models
from odoo.exceptions import UserError

from . import ig_api


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

    def _livestream_private_reply(self, comment, body, attachments):
        if self.platform != "instagram":
            return super()._livestream_private_reply(comment, body, attachments)
        if comment.session_id.state != "live":
            raise UserError(self.env._(
                "Instagram only allows private replies during the live broadcast; this live has ended.",
            ))
        parts = ig_api.split_utf8(body) or [""]
        res = ig_api.send_text(self._fb_token(), self.fb_page_id, {"comment_id": comment.external_id}, parts[0])
        return res.get("recipient_id")

    def _livestream_send_message(self, customer, body, attachments):
        if self.platform != "instagram":
            return super()._livestream_send_message(customer, body, attachments)
        if not customer.psid or customer.channel_id.livestream_window_state != "open":
            raise UserError(self.env._(
                "The 24h Instagram window is closed: wait for %s to write to the shop.", customer.name,
            ))
        token = self._fb_token()
        for part in ig_api.split_utf8(body):
            ig_api.send_text(token, self.fb_page_id, {"id": customer.psid}, part, "RESPONSE")
        for att in attachments:
            if (att.mimetype or "").startswith("image/"):
                ig_api.send_image(token, self.fb_page_id, customer.psid, att.name, att.raw, att.mimetype)
