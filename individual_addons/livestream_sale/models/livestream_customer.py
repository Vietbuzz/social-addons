from datetime import timedelta

from odoo import api, fields, models

WINDOW = timedelta(hours=24)


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

    def _ensure_partner(self):
        self.ensure_one()
        if not self.partner_id:
            self.partner_id = self.env["res.partner"].sudo().create({
                "name": self.name,
                "company_id": self.company_id.id,
            })
        return self.partner_id

    def _get_or_create_channel(self):
        """One conversation per customer, reused across lives; the current
        user is added as member so the console can post in it."""
        self.ensure_one()
        partner = self._ensure_partner()
        channel = self.channel_id.sudo()
        if not channel:
            channel = self.env["discuss.channel"].sudo().create({
                "name": self.name,
                "channel_type": "livestream",
                "livestream_customer_id": self.id,
            })
            channel._add_members(partners=partner, post_joined_message=False)
            self.channel_id = channel
        if not self.env.user._is_public() and self.env.user.partner_id not in channel.channel_member_ids.partner_id:
            channel._add_members(users=self.env.user, post_joined_message=False)
        return channel.sudo(False)

    def _receive_message(self, text, external_message_id, attachments=None):
        """Store a customer message coming from the platform (idempotent)."""
        self.ensure_one()
        Message = self.env["mail.message"].sudo()
        existing = Message.search([("livestream_external_id", "=", external_message_id)], limit=1)
        if existing:
            return existing
        channel = self._get_or_create_channel().sudo()
        attachment_vals = [(name, content) for name, content in (attachments or [])]
        message = channel.with_context(livestream_inbound=True).message_post(
            body=text,
            author_id=self.partner_id.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            attachments=attachment_vals,
        )
        message.livestream_external_id = external_message_id
        channel.livestream_window_expires_at = fields.Datetime.now() + WINDOW
        return message
