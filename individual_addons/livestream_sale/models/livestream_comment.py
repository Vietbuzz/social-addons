from odoo import api, fields, models
from odoo.exceptions import UserError

from .tag_parser import parse_tag


class LivestreamComment(models.Model):
    _name = "livestream.comment"
    _description = "Livestream Comment"
    _order = "comment_time desc, id desc"

    session_id = fields.Many2one("livestream.session", required=True, ondelete="cascade", index=True)
    account_id = fields.Many2one(related="session_id.account_id", store=True, index=True)
    company_id = fields.Many2one(related="session_id.company_id", store=True, index=True)
    external_id = fields.Char(required=True, index=True)
    customer_id = fields.Many2one("livestream.customer", required=True, ondelete="cascade", index=True)
    message = fields.Text()
    tag_code = fields.Char(index=True)
    quantity = fields.Integer(default=1)
    tag_id = fields.Many2one("livestream.session.tag", compute="_compute_tag_id", store=True)
    comment_time = fields.Datetime(default=fields.Datetime.now, index=True)
    state = fields.Selection(
        [("new", "New"), ("contacted", "Contacted"), ("ordered", "Ordered"), ("ignored", "Ignored")],
        default="new", required=True, index=True,
    )
    channel_id = fields.Many2one("discuss.channel", copy=False)
    sale_order_id = fields.Many2one("sale.order", copy=False, index=True)
    private_reply_sent = fields.Boolean(copy=False)

    _session_external_uniq = models.Constraint(
        "UNIQUE(session_id, external_id)", "This comment was already received.",
    )

    @api.depends("tag_code", "session_id.tag_ids.code")
    def _compute_tag_id(self):
        for comment in self:
            comment.tag_id = comment.tag_code and comment.session_id.tag_ids.filtered(
                lambda t: t.code == comment.tag_code
            )[:1]

    @api.model
    def _ingest(self, session, external_id, external_user_id, author_name, message, comment_time, avatar_url=None):
        existing = self.search([("session_id", "=", session.id), ("external_id", "=", external_id)], limit=1)
        if existing:
            return existing
        customer = self.env["livestream.customer"]._get_or_create(
            session.account_id, external_user_id, author_name, avatar_url,
        )
        codes = set(session.tag_ids.mapped("code")) or None
        code, qty = parse_tag(message, codes)
        comment = self.create({
            "session_id": session.id,
            "external_id": external_id,
            "customer_id": customer.id,
            "message": message,
            "tag_code": code,
            "quantity": qty,
            "comment_time": comment_time,
        })
        session.account_id._notify_console("livestream/comment", [comment._console_format()])
        return comment

    def _console_format(self):
        self.ensure_one()
        return {
            "id": self.id,
            "session_id": self.session_id.id,
            "customer_id": self.customer_id.id,
            "customer_name": self.customer_id.name,
            "avatar_url": self.customer_id.avatar_url or False,
            "message": self.message or "",
            "tag_code": self.tag_code or False,
            "quantity": self.quantity,
            "product_name": self.tag_id.product_id.display_name or False,
            "state": self.state,
            "comment_time": fields.Datetime.to_string(self.comment_time),
            "channel_id": self.channel_id.id or False,
            "sale_order_id": self.sale_order_id.id or False,
        }

    def action_open_conversation(self):
        self.ensure_one()
        channel = self.customer_id._get_or_create_channel()
        channel.sudo().livestream_origin_comment_id = self
        if not self.channel_id:
            self.channel_id = channel
        if self.state == "new":
            self.state = "contacted"
        return {"channel_id": channel.id, "comment": self._console_format()}

    def action_create_order(self, lines, phone, name, street, deposit_amount):
        """Create the quotation for this comment's customer (console "Create order")."""
        self.ensure_one()
        if not lines:
            raise UserError(self.env._("Add at least one product."))
        customer = self.customer_id
        partner = self.env["res.partner"]._livestream_find_or_create(name or customer.name, phone, street)
        if customer.partner_id != partner:
            old_partner = customer.partner_id
            customer.partner_id = partner
            channel = customer.channel_id.sudo()
            if channel:
                channel._add_members(partners=partner, post_joined_message=False)
                if old_partner and old_partner != partner:
                    channel.channel_member_ids.filtered(lambda m: m.partner_id == old_partner).sudo().unlink()
        order = self.env["sale.order"].create({
            "partner_id": partner.id,
            "livestream_session_id": self.session_id.id,
            "livestream_channel_id": (self.channel_id or customer.channel_id).id,
            "livestream_payment_ref": self.env["ir.sequence"].sudo().next_by_code("livestream.payment.ref"),
            "require_signature": False,
            "company_id": self.company_id.id,
            "order_line": [
                fields.Command.create({
                    "product_id": line["product_id"],
                    "product_uom_qty": line.get("quantity", 1),
                    "price_unit": line["price_unit"],
                }) for line in lines
            ],
        })
        # prepayment_amount inverts into prepayment_percent: set it once lines exist
        order.prepayment_amount = deposit_amount or 0.0
        self.write({"state": "ordered", "sale_order_id": order.id})
        return order.id
