from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.mail.tools.discuss import Store

WINDOW = timedelta(hours=24)


def is_livestream_channel(channel):
    return channel.channel_type == "livestream"


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    channel_type = fields.Selection(
        selection_add=[("livestream", "Livestream")], ondelete={"livestream": "cascade"},
    )
    livestream_customer_id = fields.Many2one("livestream.customer", index="btree_not_null", ondelete="cascade")
    livestream_origin_comment_id = fields.Many2one("livestream.comment", ondelete="set null")
    livestream_window_expires_at = fields.Datetime("Messaging Window Ends")
    livestream_window_state = fields.Selection(
        [("waiting", "Waiting for customer"), ("open", "Open"), ("closed", "Closed")],
        compute="_compute_livestream_window_state",
    )

    @api.depends("livestream_window_expires_at", "livestream_customer_id.psid")
    def _compute_livestream_window_state(self):
        now = fields.Datetime.now()
        for channel in self:
            if channel.livestream_window_expires_at and channel.livestream_window_expires_at > now:
                channel.livestream_window_state = "open"
            elif not channel.livestream_customer_id.psid:
                channel.livestream_window_state = "waiting"
            else:
                channel.livestream_window_state = "closed"

    def _store_channel_fields(self, res: Store.FieldList):
        super()._store_channel_fields(res)
        if res.is_for_internal_users():
            res.attr("livestream_window_expires_at", predicate=is_livestream_channel)
            res.attr("livestream_window_state", predicate=is_livestream_channel)
            res.attr("livestream_customer_id", lambda c: c.livestream_customer_id.id, predicate=is_livestream_channel)
            res.attr(
                "livestream_origin_comment_id", lambda c: c.livestream_origin_comment_id.id,
                predicate=is_livestream_channel,
            )

    def _message_post_after_hook(self, message):
        res = super()._message_post_after_hook(message)
        if (
            self.channel_type == "livestream"
            and not self.env.context.get("livestream_inbound")
            and message.message_type == "comment"
            and message.subtype_id == self.env.ref("mail.mt_comment")
            and message.author_id != self.livestream_customer_id.partner_id
        ):
            self._livestream_deliver(message)
        return res

    def _livestream_deliver(self, message):
        """Send an operator message out to the customer's platform inbox."""
        self.ensure_one()
        customer = self.livestream_customer_id
        account = customer.account_id.sudo()
        comment = self.livestream_origin_comment_id
        body = html2plaintext(message.body or "").strip()
        attachments = message.attachment_ids
        if self.livestream_window_state == "open":
            account._livestream_send_message(customer, body, attachments)
        elif comment and not comment.private_reply_sent:
            psid = account._livestream_private_reply(comment, body, attachments)
            comment.private_reply_sent = True
            if psid and not customer.psid:
                customer.psid = psid
        elif customer.psid:
            account._livestream_send_message(customer, body, attachments)
        else:
            raise UserError(self.env._(
                "Waiting for the customer to reply on Messenger: only one private reply is allowed per comment.",
            ))
