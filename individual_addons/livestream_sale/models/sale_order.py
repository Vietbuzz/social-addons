import base64

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError

DEFAULT_DEPOSIT_TEMPLATE = (
    "Shop gửi anh/chị thông tin đặt cọc đơn {order}:\n"
    "- Số tiền cọc: {amount} đ\n"
    "- Số tài khoản: {account_number} ({bank})\n"
    "- Chủ tài khoản: {holder}\n"
    "- Nội dung chuyển khoản: {ref}\n"
    "Anh/chị quét mã QR bên dưới để chuyển nhanh, vui lòng giữ nguyên nội dung {ref} ạ."
)


def format_vnd(amount):
    return f"{round(amount or 0):,}".replace(",", ".")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    livestream_session_id = fields.Many2one("livestream.session", "Live Session", index="btree_not_null", copy=False)
    livestream_comment_ids = fields.One2many("livestream.comment", "sale_order_id", "Live Comments")
    livestream_channel_id = fields.Many2one("discuss.channel", "Live Conversation", copy=False)
    livestream_payment_ref = fields.Char("Transfer Reference", readonly=True, copy=False, index="btree_not_null")
    livestream_deposit_due = fields.Monetary(
        "Deposit Due", compute="_compute_livestream_deposit_due", currency_field="currency_id",
    )
    is_livestream = fields.Boolean(compute="_compute_is_livestream", store=True)
    livestream_bank_transaction_ids = fields.One2many(
        "livestream.bank.transaction", "sale_order_id", "Bank Transfers",
    )

    _livestream_payment_ref_uniq = models.UniqueIndex(
        "(livestream_payment_ref) WHERE livestream_payment_ref IS NOT NULL",
    )

    @api.depends("livestream_session_id")
    def _compute_is_livestream(self):
        for order in self:
            order.is_livestream = bool(order.livestream_session_id)

    @api.depends("prepayment_percent", "amount_total", "amount_paid")
    def _compute_livestream_deposit_due(self):
        for order in self:
            order.livestream_deposit_due = max(order._get_prepayment_required_amount() - order.amount_paid, 0.0)

    # ------------------------------------------------------------------
    # Deposit guard
    # ------------------------------------------------------------------
    def action_confirm(self):
        short = self.filtered(lambda o: o.is_livestream and not o._is_confirmation_amount_reached())
        if short:
            if not self.env.user.has_group("livestream_sale.group_livestream_manager"):
                raise UserError(self.env._(
                    "Deposit not received for %(orders)s: %(amount)s remaining.",
                    orders=", ".join(short.mapped("name")),
                    amount=", ".join(format_vnd(o.livestream_deposit_due) for o in short),
                ))
            for order in short:
                order.message_post(body=self.env._(
                    "Confirmed without full deposit by %(user)s (%(amount)s đ still due).",
                    user=self.env.user.name, amount=format_vnd(order.livestream_deposit_due),
                ))
        return super().action_confirm()

    # ------------------------------------------------------------------
    # VietQR / deposit request
    # ------------------------------------------------------------------
    def _livestream_bank_account(self):
        self.ensure_one()
        provider = self.livestream_session_id.account_id.sudo().payment_provider_id
        bank = provider.journal_id.bank_account_id
        if not bank:
            raise UserError(self.env._(
                "Configure a deposit provider with a bank journal and bank account on the live account first.",
            ))
        return bank

    def _generate_vietqr_url(self):
        self.ensure_one()
        bank = self._livestream_bank_account()
        qr = bank.build_qr_code_base64(
            amount=self.livestream_deposit_due,
            free_communication=self.livestream_payment_ref,
            structured_communication=self.livestream_payment_ref,
            currency=self.currency_id,
            debtor_partner=self.partner_id,
            qr_method="emv_qr",
            silent_errors=False,
        )
        if not qr:
            raise UserError(self.env._("Could not generate a VietQR code for account %s.", bank.account_number))
        return qr

    def livestream_deposit_message(self):
        self.ensure_one()
        bank = self._livestream_bank_account()
        template = self.env["ir.config_parameter"].sudo().get_str(
            "livestream_sale.deposit_message_template",
        ) or DEFAULT_DEPOSIT_TEMPLATE
        return template.format(
            order=self.name,
            amount=format_vnd(self.livestream_deposit_due),
            account_number=bank.account_number,
            bank=bank.bank_name or "",
            holder=bank.partner_id.name or "",
            ref=self.livestream_payment_ref,
        )

    def action_livestream_send_deposit_request(self):
        self.ensure_one()
        if not self.livestream_channel_id:
            raise UserError(self.env._("This order has no live conversation."))
        qr_url = self._generate_vietqr_url()
        png = base64.b64decode(qr_url.split(",", 1)[1])
        text = self.livestream_deposit_message()
        body = Markup("<br/>").join(escape(line) for line in text.split("\n"))
        self.livestream_channel_id.message_post(
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            attachments=[(f"VietQR-{self.livestream_payment_ref}.png", png)],
        )
