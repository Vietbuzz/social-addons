import random
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

SAMPLE_NAMES = [
    "Nguyễn Văn An", "Trần Thị Bích", "Lê Hoàng Long", "Phạm Thu Trang", "Hoàng Minh Đức",
    "Vũ Ngọc Ánh", "Đặng Quốc Huy", "Bùi Thị Mai", "Đỗ Thanh Tùng", "Ngô Phương Linh",
]


class LivestreamSimulator(models.AbstractModel):
    """Fake platform/bank events for development, demos and training."""

    _name = "livestream.simulator"
    _description = "Livestream Simulator"

    @api.model
    def _check_simulator_access(self):
        if self.env.user.has_group("livestream_sale.group_livestream_manager"):
            return
        if self.env.user.has_group("livestream_sale.group_livestream_user") and self.env[
            "ir.config_parameter"
        ].sudo().get_bool("livestream_sale.simulator_enabled"):
            return
        raise AccessError(self.env._("The livestream simulator is disabled."))

    @api.model
    def simulate_comment(self, session_id, message=None, author_name=None):
        self._check_simulator_access()
        session = self.env["livestream.session"].browse(session_id).exists()
        if not session:
            raise UserError(self.env._("Session not found."))
        if not message:
            codes = session.tag_ids.mapped("code") or ["69"]
            message = random.choice([f"{random.choice(codes)}", f"{random.choice(codes)} x{random.randint(2, 3)}"])
        name = author_name or random.choice(SAMPLE_NAMES)
        comment_id = f"sim-{uuid.uuid4().hex[:12]}"
        event = self.env["livestream.webhook.event"]._enqueue("simulator", {
            "kind": "comment",
            "session_id": session.id,
            "comment_id": comment_id,
            "user_id": f"simuser-{name}",
            "name": name,
            "message": message,
            "time": fields.Datetime.to_string(fields.Datetime.now()),
        }, session.account_id)
        event.sudo()._process()
        if event.state != "done":
            raise UserError(event.error)
        return self.env["livestream.comment"].search(
            [("session_id", "=", session.id), ("external_id", "=", comment_id)], limit=1,
        ).id

    @api.model
    def simulate_customer_reply(self, channel_id, text):
        self._check_simulator_access()
        channel = self.env["discuss.channel"].sudo().browse(channel_id).exists()
        customer = channel.livestream_customer_id
        if not customer:
            raise UserError(self.env._("Not a livestream conversation."))
        if not customer.psid:
            customer.psid = f"sim-{customer.external_user_id}"
        customer._receive_message(text, f"sim-mid-{uuid.uuid4().hex[:12]}")

    @api.model
    def simulate_bank(self, account_id, amount, content):
        self._check_simulator_access()
        account = self.env["livestream.account"].sudo().browse(account_id).exists()
        if not account.payment_provider_id:
            raise UserError(self.env._("Set a deposit provider on the account first."))
        tx = self.env["livestream.bank.transaction"]._register_transfer(account.payment_provider_id, {
            "external_id": f"SIM-{uuid.uuid4().hex[:12]}",
            "date": fields.Datetime.now(),
            "amount": amount,
            "content": content,
            "reference": f"SIM{random.randint(100000, 999999)}",
            "account_number": account.payment_provider_id.journal_id.bank_account_id.account_number or "",
            "gateway": "Simulator",
            "raw_payload": {"simulated": True},
        })
        return tx.id
