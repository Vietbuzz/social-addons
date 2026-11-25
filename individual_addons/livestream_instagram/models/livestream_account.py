from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.livestream_facebook.models import graph_api

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
        if comment.session_id.source_type == "live" and comment.session_id.state != "live":
            raise UserError(self.env._(
                "Instagram only allows private replies during the live broadcast; this live has ended.",
            ))
        parts = ig_api.split_utf8(body)
        if len(parts) > 1:
            raise UserError(self.env._(
                "An Instagram private reply is limited to %s bytes: shorten this first message.", ig_api.TEXT_LIMIT,
            ))
        if not parts:
            raise UserError(self.env._("An Instagram private reply can only carry text."))
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
            if not (att.mimetype or "").startswith("image/"):
                continue
            try:
                ig_api.send_image(token, self.fb_page_id, customer.psid, att.name, att.raw, att.mimetype)
            except Exception as e:  # noqa: BLE001 - the text already reached the customer: never roll it back
                customer.channel_id.sudo().message_post(
                    body=self.env._("Image %(name)s was not delivered to Instagram: %(error)s", name=att.name, error=e),
                    message_type="comment", subtype_xmlid="mail.mt_note",
                )

    def action_fb_subscribe(self):
        instagram = self.filtered(lambda a: a.platform == "instagram")
        for account in instagram:
            graph_api._request("POST", f"{account.fb_page_id}/subscribed_apps", account._fb_token(), params={
                "subscribed_fields": "messages",
            })
        return super(LivestreamAccount, self - instagram).action_fb_subscribe()
