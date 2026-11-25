import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

MAX_ATTEMPTS = 3

_logger = logging.getLogger(__name__)


class LivestreamWebhookEvent(models.Model):
    """Raw inbound platform/bank events.

    Controllers store the payload and answer immediately; processing happens
    here (cron, triggered on enqueue) so a slow or failing handler never makes
    the sender retry, and stored payloads can be replayed.
    """

    _name = "livestream.webhook.event"
    _description = "Livestream Webhook Event"
    _order = "id desc"

    source = fields.Selection([("simulator", "Simulator")], required=True, index=True)
    payload = fields.Json(required=True)
    state = fields.Selection(
        [("pending", "Pending"), ("done", "Done"), ("error", "Error")],
        default="pending", required=True, index=True,
    )
    error = fields.Text()
    attempts = fields.Integer(default=0)
    account_id = fields.Many2one("livestream.account", ondelete="set null", index=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, index=True)

    @api.model
    def _enqueue(self, source, payload, account=None):
        event = self.sudo().create({
            "source": source,
            "payload": payload,
            "account_id": account.id if account else False,
            "company_id": account.company_id.id if account else self.env.company.id,
        })
        self.env.ref("livestream_sale.ir_cron_process_webhook_events").sudo()._trigger()
        return event

    def _process(self):
        for event in self:
            if event.state == "done":
                continue
            try:
                with self.env.cr.savepoint():
                    handler = getattr(event, f"_process_{event.source}")
                    handler(event.payload)
                event.write({"state": "done", "error": False})
            except (UserError, ValidationError) as e:  # permanent: bad data, no retry
                _logger.warning("Livestream event %s failed: %s", event.id, e)
                event.write({"state": "error", "error": str(e), "attempts": event.attempts + 1})
            except Exception as e:  # noqa: BLE001 - transient (e.g. serialization): retry on next runs
                attempts = event.attempts + 1
                _logger.warning("Livestream event %s failed (attempt %s): %s", event.id, attempts, e)
                event.write({
                    "state": "pending" if attempts < MAX_ATTEMPTS else "error", "error": str(e), "attempts": attempts,
                })

    def action_retry(self):
        self.filtered(lambda e: e.state == "error").write({"state": "pending", "error": False})
        self._process()
        return True

    @api.model
    def _cron_process(self, limit=200):
        self.search([("state", "=", "pending")], order="id", limit=limit)._process()

    def _process_simulator(self, payload):
        kind = payload.get("kind")
        if kind == "comment":
            session = self.env["livestream.session"].browse(payload["session_id"]).exists()
            if not session:
                raise UserError(self.env._("Unknown session %s", payload["session_id"]))
            self.env["livestream.comment"]._ingest(
                session, payload["comment_id"], payload["user_id"], payload["name"],
                payload.get("message", ""), fields.Datetime.to_datetime(payload.get("time")) or fields.Datetime.now(),
                avatar_url=payload.get("avatar_url"),
            )
        else:
            raise UserError(self.env._("Unsupported simulator event kind: %s", kind))
