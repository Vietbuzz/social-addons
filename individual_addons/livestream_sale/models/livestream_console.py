from odoo import api, fields, models
from odoo.exceptions import UserError


class LivestreamConsole(models.AbstractModel):
    """Server API of the 3-column operator console (client action)."""

    _name = "livestream.console"
    _description = "Livestream Operator Console"

    COMMENT_PAGE = 200
    BANK_PAGE = 50

    MAX_OPEN_SESSIONS = 50

    @api.model
    def _session_info(self, session):
        return {
            "id": session.id,
            "name": session.name,
            "state": session.state,
            "platform": session.platform,
            "source_type": session.source_type,
            "last_comment_at": fields.Datetime.to_string(session.last_comment_at),
        }

    @api.model
    def _open_sessions(self):
        return self.env["livestream.session"].search(
            [("state", "=", "live")], order="last_comment_at desc nulls last, id desc", limit=self.MAX_OPEN_SESSIONS,
        )

    @api.model
    def load(self, session_id):
        """session_id: a session id, or "all"/False for every open source (live + posts)."""
        Session = self.env["livestream.session"]
        open_sessions = self._open_sessions()
        recent = Session.search([("state", "!=", "live")], limit=30)
        result = {
            "sessions": [self._session_info(s) for s in open_sessions | recent],
            "session": False,
            "comments": [],
            "bank_transactions": [],
            "can_simulate": self._can_simulate(),
            "default_deposit": self.env["ir.config_parameter"].sudo().get_int("livestream_sale.default_deposit_amount"),
            "token_alerts": [
                {"account_id": a.id, "name": a.name, "platform": a.platform, "error": a.token_error or ""}
                for a in self.env["livestream.account"].search([("token_state", "=", "invalid")])
            ],
        }
        if not session_id or session_id == "all":
            sessions = open_sessions
            result["session"] = {
                "id": "all",
                "name": self.env._("All open sources"),
                "state": "live",
                "platform": False,
                "source_type": False,
                "account_ids": sessions.account_id.ids,
                "account_id": False,
                "tags": [],
            }
        else:
            sessions = Session.browse(int(session_id)).exists()
            if not sessions:
                return result
            result["session"] = {
                **self._session_info(sessions),
                "account_id": sessions.account_id.id,
                "account_ids": sessions.account_id.ids,
                "permalink_url": sessions.permalink_url or False,
                "tags": self._tags(sessions),
            }
            if sessions not in open_sessions | recent:
                result["sessions"].append(self._session_info(sessions))
        comments = self.env["livestream.comment"].search(
            [("session_id", "in", sessions.ids)], order="id desc", limit=self.COMMENT_PAGE,
        )
        result["comments"] = [c._console_format() for c in comments]
        providers = sessions.account_id.sudo().payment_provider_id
        if providers:
            txs = self.env["livestream.bank.transaction"].search(
                [("provider_id", "in", providers.ids)], limit=self.BANK_PAGE,
            )
            result["bank_transactions"] = [t._console_format() for t in txs]
        return result

    @api.model
    def _tags(self, session):
        return [{
            "code": t.code, "product_id": t.product_id.id,
            "product_name": t.product_id.display_name, "price_unit": t.price_unit,
        } for t in session.tag_ids]

    @api.model
    def search_products(self, query, limit=20, company_id=None):
        query = (query or "").strip()
        if len(query) < 2:
            return []
        products = self.env["product.product"].search([
            ("sale_ok", "=", True),
            ("company_id", "in", [False, company_id or self.env.company.id]),
            "|", "|", ("name", "ilike", query), ("default_code", "ilike", query), ("barcode", "=", query),
        ], limit=limit)
        return [{
            "product_id": p.id, "product_name": p.display_name, "price_unit": p.lst_price,
        } for p in products]

    @api.model
    def _can_simulate(self):
        user = self.env.user
        return user.has_group("livestream_sale.group_livestream_manager") or bool(
            self.env["ir.config_parameter"].sudo().get_bool("livestream_sale.simulator_enabled")
        )

    @api.model
    def load_more_comments(self, session_id, before_id, tag_code=False):
        session_ids = self._open_sessions().ids if session_id == "all" else [int(session_id)]
        domain = [("session_id", "in", session_ids), ("id", "<", before_id)]
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
            "tags": self._tags(comment.session_id),
            "permalink_url": comment.session_id.permalink_url or False,
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
