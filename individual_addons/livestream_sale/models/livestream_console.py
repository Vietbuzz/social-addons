from odoo import api, fields, models
from odoo.exceptions import UserError


class LivestreamConsole(models.AbstractModel):
    """Server API of the 3-column operator console (client action)."""

    _name = "livestream.console"
    _description = "Livestream Operator Console"

    COMMENT_PAGE = 200
    BANK_PAGE = 50

    @api.model
    def load(self, session_id):
        Session = self.env["livestream.session"]
        session = Session.browse(session_id).exists() if session_id else Session
        if not session:
            session = Session.search([("state", "=", "live"), ("user_ids", "in", self.env.uid)], limit=1) \
                or Session.search([("state", "=", "live")], limit=1) \
                or Session.search([], limit=1)
        sessions = Session.search([], limit=30)
        result = {
            "sessions": [{"id": s.id, "name": s.name, "state": s.state} for s in sessions | session],
            "session": False,
            "comments": [],
            "bank_transactions": [],
            "can_simulate": self._can_simulate(),
            "default_deposit": self.env["ir.config_parameter"].sudo().get_int("livestream_sale.default_deposit_amount"),
        }
        if not session:
            return result
        result["session"] = {
            "id": session.id,
            "name": session.name,
            "state": session.state,
            "account_id": session.account_id.id,
            "tags": [{
                "code": t.code, "product_id": t.product_id.id,
                "product_name": t.product_id.display_name, "price_unit": t.price_unit,
            } for t in session.tag_ids],
        }
        comments = self.env["livestream.comment"].search(
            [("session_id", "=", session.id)], limit=self.COMMENT_PAGE,
        )
        result["comments"] = [c._console_format() for c in comments]
        provider = session.account_id.sudo().payment_provider_id
        if provider:
            txs = self.env["livestream.bank.transaction"].search(
                [("provider_id", "=", provider.id)], limit=self.BANK_PAGE,
            )
            result["bank_transactions"] = [t._console_format() for t in txs]
        return result

    @api.model
    def _can_simulate(self):
        user = self.env.user
        return user.has_group("livestream_sale.group_livestream_manager") or bool(
            self.env["ir.config_parameter"].sudo().get_bool("livestream_sale.simulator_enabled")
        )

    @api.model
    def load_more_comments(self, session_id, before_id, tag_code=False):
        domain = [("session_id", "=", session_id), ("id", "<", before_id)]
        if tag_code:
            domain.append(("tag_code", "=", tag_code))
        comments = self.env["livestream.comment"].search(domain, order="id desc", limit=self.COMMENT_PAGE)
        return [c._console_format() for c in comments]

    @api.model
    def order_panel(self, comment_id):
        comment = self.env["livestream.comment"].browse(comment_id).exists()
        if not comment:
            raise UserError(self.env._("Comment not found."))
        customer = comment.customer_id
        partner = customer.partner_id
        order = comment.sale_order_id
        lines = []
        if comment.tag_id:
            tag = comment.tag_id
            lines.append({
                "product_id": tag.product_id.id,
                "product_name": tag.product_id.display_name,
                "quantity": comment.quantity,
                "price_unit": tag.price_unit,
            })
        channel = comment.channel_id or customer.channel_id
        return {
            "comment": comment._console_format(),
            "channel": {
                "id": channel.id,
                "window_state": channel.livestream_window_state,
                "window_expires_at": fields.Datetime.to_string(channel.livestream_window_expires_at),
            } if channel else None,
            "customer": {
                "name": partner.name or customer.name,
                "phone": partner.phone or "",
                "street": partner.street or "",
                "partner_id": partner.id or False,
            },
            "lines": lines,
            "order": self._order_format(order) if order else None,
        }

    @api.model
    def order_summary(self, order_id):
        order = self.env["sale.order"].browse(order_id).exists()
        return self._order_format(order) if order else None

    @api.model
    def _order_format(self, order):
        try:
            qr_url = order._generate_vietqr_url() if order.livestream_deposit_due > 0 else False
            qr_error = False
        except UserError as e:
            qr_url, qr_error = False, str(e)
        return {
            "id": order.id,
            "name": order.name,
            "state": order.state,
            "amount_total": order.amount_total,
            "prepayment_amount": order.prepayment_amount,
            "amount_paid": order.amount_paid,
            "deposit_due": order.livestream_deposit_due,
            "payment_ref": order.livestream_payment_ref,
            "qr_url": qr_url,
            "qr_error": qr_error,
            "lines": [{
                "product_name": line.product_id.display_name,
                "quantity": line.product_uom_qty,
                "price_unit": line.price_unit,
            } for line in order.order_line],
            "transactions": [{
                "id": t.id, "amount": t.amount, "content": t.content or "",
                "date": fields.Datetime.to_string(t.date), "match_method": t.match_method,
            } for t in order.sudo().livestream_bank_transaction_ids],
        }
