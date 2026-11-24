import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LivestreamSession(models.Model):
    _inherit = "livestream.session"

    @api.model
    def _ig_upsert_live(self, account, media_id, live):
        """Instagram live media <-> session. draft -> live allowed; an ended live never reopens."""
        session = self.search([("account_id", "=", account.id), ("external_video_id", "=", media_id)], limit=1)
        state = "live" if live else "ended"
        if session:
            if session.state != state and session.state != "ended":
                session.write({"state": state, **({"date_end": fields.Datetime.now()} if state == "ended" else {})})
            return session
        return self.create({
            "name": self.env._("Instagram live %s", fields.Datetime.now().strftime("%d/%m %H:%M")),
            "account_id": account.id,
            "external_video_id": media_id,
            "state": state,
            "date_start": fields.Datetime.now(),
        })
