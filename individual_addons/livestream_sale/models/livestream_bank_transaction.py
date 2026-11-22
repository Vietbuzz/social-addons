import re
import unicodedata
from datetime import timedelta

import psycopg2

from odoo import api, fields, models
from odoo.exceptions import UserError

from .res_partner import normalize_vn_phone

REF_RE = re.compile(r"LS(\d{6})(?!\d)")
IMMUTABLE_FIELDS = {
    "provider_id", "external_id", "date", "amount", "content", "reference",
    "account_number", "gateway", "raw_payload",
}


class LivestreamBankTransaction(models.Model):
    """An incoming bank transfer as reported by the bank feed (SePay...).

    The bank data is write-once: only matching fields can change, and every
    match/unmatch is logged in the chatter.
    """

    _name = "livestream.bank.transaction"
    _description = "Incoming Bank Transfer"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _rec_name = "reference"

    provider_id = fields.Many2one("payment.provider", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one(related="provider_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    external_id = fields.Char("Bank Feed ID", required=True)
    date = fields.Datetime(required=True, index=True)
    amount = fields.Monetary(required=True, currency_field="currency_id")
    content = fields.Char("Transfer Content")
    reference = fields.Char("Bank Reference")
    account_number = fields.Char()
    gateway = fields.Char("Bank")
    raw_payload = fields.Json()
    state = fields.Selection(
        [("unmatched", "Unmatched"), ("matched", "Matched"), ("ignored", "Ignored")],
        default="unmatched", required=True, index=True, tracking=True,
    )
    sale_order_id = fields.Many2one("sale.order", index="btree_not_null", tracking=True, copy=False)
    payment_transaction_id = fields.Many2one("payment.transaction", copy=False, readonly=True)
    match_method = fields.Selection([("auto", "Automatic"), ("manual", "Manual")], tracking=True, copy=False)
    matched_by = fields.Many2one("res.users", copy=False, readonly=True)
    matched_at = fields.Datetime(copy=False, readonly=True)

    _provider_external_uniq = models.Constraint(
        "UNIQUE(provider_id, external_id)", "This bank transaction was already recorded.",
    )

    # ------------------------------------------------------------------
    # Immutability
    # ------------------------------------------------------------------
    def write(self, vals):
        if IMMUTABLE_FIELDS & set(vals) and not self.env.context.get("livestream_allow_immutable_write"):
            raise UserError(self.env._("Bank transaction data cannot be modified."))
        return super().write(vals)

    def unlink(self):
        if any(tx.state != "ignored" for tx in self) or not self.env.user.has_group(
            "livestream_sale.group_livestream_manager"
        ):
            raise UserError(self.env._("Only ignored bank transactions can be deleted, by a manager."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Intake
    # ------------------------------------------------------------------
    @api.model
    def _register_transfer(self, provider, vals):
        """Record a bank transfer once per (provider, external_id); try to auto-match new ones."""
        existing = self.sudo().search([
            ("provider_id", "=", provider.id), ("external_id", "=", vals["external_id"]),
        ], limit=1)
        if existing:
            return existing.sudo(False)
        tx = self.sudo().create({**vals, "provider_id": provider.id})
        if not tx._try_auto_match():
            tx._notify()
        return tx.sudo(False)

    @staticmethod
    def _normalize(text):
        text = unicodedata.normalize("NFKD", text or "")
        text = "".join(c for c in text if not unicodedata.combining(c)).replace("đ", "d").replace("Đ", "D")
        return re.sub(r"[^A-Z0-9]", "", text.upper())

    def _find_ref_orders(self):
        self.ensure_one()
        refs = {f"LS{num}" for num in REF_RE.findall(self._normalize(self.content))}
        if not refs:
            return self.env["sale.order"]
        return self.env["sale.order"].sudo().search([
            ("livestream_payment_ref", "in", list(refs)), ("company_id", "=", self.company_id.id),
        ])

    def _try_auto_match(self):
        self.ensure_one()
        orders = self._find_ref_orders()
        if len(orders) != 1 or orders.state == "cancel":
            return False
        self._match_to_order(orders, "auto")
        return True

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------
    def _lock_for_matching(self):
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    "SELECT id FROM livestream_bank_transaction WHERE id = %s FOR UPDATE NOWAIT", [self.id],
                )
        except psycopg2.errors.LockNotAvailable:
            raise UserError(self.env._("This transaction is being processed by someone else, retry in a moment."))
        self.invalidate_recordset(["state"])

    def _match_to_order(self, order, method):
        self.ensure_one()
        order.ensure_one()
        self._lock_for_matching()
        if self.state != "unmatched":
            raise UserError(self.env._("Transaction %s is already matched or ignored.", self.reference or self.external_id))
        if order.state == "cancel":
            raise UserError(self.env._("Order %s is cancelled.", order.name))
        if order.company_id != self.company_id:
            raise UserError(self.env._("Order and bank transaction belong to different companies."))
        provider = self.sudo().provider_id
        method_rec = provider.payment_method_ids[:1]
        if not method_rec:
            raise UserError(self.env._("Provider %s has no payment method.", provider.name))
        order_sudo = order.sudo()
        # payment_safe_write: the bank row is locked above and nothing here calls an external API,
        # so the whole match (tx, payment, order confirmation) rolls back atomically on error.
        pay_tx = self.env["payment.transaction"].sudo().with_context(payment_safe_write=True).create({
            "provider_id": provider.id,
            "payment_method_id": method_rec.id,
            "reference": f"{order_sudo.livestream_payment_ref or order_sudo.name}-{self.external_id}",
            "provider_reference": self.external_id,
            "amount": self.amount,
            "currency_id": self.currency_id.id,
            "partner_id": order_sudo.partner_id.id,
            "sale_order_ids": [fields.Command.set(order.ids)],
        })
        user = self.env.user
        super(LivestreamBankTransaction, self.sudo()).write({
            "state": "matched",
            "sale_order_id": order.id,
            "payment_transaction_id": pay_tx.id,
            "match_method": method,
            "matched_by": user.id,
            "matched_at": fields.Datetime.now(),
        })
        pay_tx._set_done()
        pay_tx._post_process()
        info = self.env._(
            "Bank transfer %(amount)s đ (%(content)s) matched to %(order)s (%(method)s by %(user)s).",
            amount=f"{round(self.amount):,}".replace(",", "."), content=self.content or "",
            order=order_sudo.name, method=dict(self._fields["match_method"].selection)[method], user=user.name,
        )
        self.sudo().message_post(body=info)
        order_sudo.message_post(body=info)
        if order_sudo.livestream_channel_id:
            order_sudo.livestream_channel_id.message_post(
                body=info, message_type="comment", subtype_xmlid="mail.mt_note",
            )
        self._notify()
        return pay_tx

    def action_match_manual(self, order_id):
        self.ensure_one()
        order = self.env["sale.order"].browse(order_id).exists()
        if not order:
            raise UserError(self.env._("Order not found."))
        self._match_to_order(order, "manual")
        return self._console_format()

    def action_ignore(self):
        if not self.env.user.has_group("livestream_sale.group_livestream_manager"):
            raise UserError(self.env._("Only a livestream manager can ignore bank transactions."))
        for tx in self:
            if tx.state != "unmatched":
                raise UserError(self.env._("Only unmatched transactions can be ignored."))
            tx.state = "ignored"
            tx._notify()

    def _unmatch(self, reason):
        """Undo a match (manager only, checked by the wizard)."""
        self.ensure_one()
        if self.state != "matched":
            raise UserError(self.env._("This transaction is not matched."))
        order = self.sale_order_id.sudo()
        if order.invoice_ids.filtered(
            lambda m: m.state == "posted" and any(not l.is_downpayment for l in m.invoice_line_ids.sale_line_ids)
        ):
            raise UserError(self.env._("Order %s already has a final invoice; reverse it first.", order.name))
        if "picking_ids" in order._fields and order.picking_ids.filtered(lambda p: p.state == "done"):
            raise UserError(self.env._("Order %s was already delivered.", order.name))
        pay_tx = self.payment_transaction_id.sudo().with_context(payment_safe_write=True)
        if pay_tx.payment_id and pay_tx.payment_id.state != "canceled":
            pay_tx.payment_id.action_draft()
            pay_tx.payment_id.action_cancel()
        pay_tx._set_canceled(state_message=reason, extra_allowed_states=("done",))
        super(LivestreamBankTransaction, self.sudo()).write({
            "state": "unmatched", "sale_order_id": False, "payment_transaction_id": False,
            "match_method": False, "matched_by": False, "matched_at": False,
        })
        body = self.env._(
            "Unmatched from %(order)s by %(user)s. Reason: %(reason)s",
            order=order.name, user=self.env.user.name, reason=reason,
        )
        self.sudo().message_post(body=body)
        order.message_post(body=body)
        self._notify()

    # ------------------------------------------------------------------
    # Suggestions & console
    # ------------------------------------------------------------------
    def _suggest_orders(self, limit=5):
        self.ensure_one()
        now = fields.Datetime.now()
        orders = self.env["sale.order"].search([
            ("is_livestream", "=", True),
            ("state", "in", ("draft", "sent", "sale")),
            ("company_id", "=", self.company_id.id),
            ("create_date", ">=", now - timedelta(days=7)),
        ], limit=500)
        content = self._normalize(self.content)
        content_words = set(re.findall(r"[A-Z]+", self._normalize_words(self.content)))
        cmp = self.currency_id.compare_amounts
        results = []
        for order in orders:
            due = order.livestream_deposit_due
            if due <= 0:
                continue
            score = 0
            if not cmp(self.amount, due):
                score += 50
            phone = normalize_vn_phone(order.partner_id.phone)
            if phone and (phone in content or phone[1:] in content):
                score += 30
            ref_num = (order.livestream_payment_ref or "")[2:].lstrip("0")
            if ref_num and len(ref_num) >= 2 and ref_num in content:
                score += 20
            name_words = set(re.findall(r"[A-Z]+", self._normalize_words(order.partner_id.name)))
            if len(name_words & content_words) >= 2:
                score += 10
            if order.create_date >= now - timedelta(hours=24):
                score += 10
            if score > 0:
                results.append({
                    "order_id": order.id, "name": order.name, "partner_name": order.partner_id.name,
                    "deposit_due": due, "score": score,
                })
        results.sort(key=lambda r: (-r["score"], -r["order_id"]))
        return results[:limit]

    @classmethod
    def _normalize_words(cls, text):
        text = unicodedata.normalize("NFKD", text or "")
        text = "".join(c for c in text if not unicodedata.combining(c)).replace("đ", "d").replace("Đ", "D")
        return re.sub(r"[^A-Z0-9 ]", " ", text.upper())

    def _console_format(self):
        self.ensure_one()
        return {
            "id": self.id,
            "date": fields.Datetime.to_string(self.date),
            "amount": self.amount,
            "content": self.content or "",
            "gateway": self.gateway or "",
            "state": self.state,
            "match_method": self.match_method or False,
            "sale_order_id": self.sale_order_id.id or False,
            "sale_order_name": self.sale_order_id.sudo().name or False,
            "partner_name": self.sale_order_id.sudo().partner_id.name or False,
            "suggestions": self._suggest_orders() if self.state == "unmatched" else [],
        }

    def _notify(self):
        for tx in self:
            accounts = self.env["livestream.account"].sudo().search([("payment_provider_id", "=", tx.provider_id.id)])
            payload = [tx.sudo()._console_format()]
            for account in accounts:
                account._notify_console("livestream/bank_transaction", payload)
