import json
import logging

from odoo import http
from odoo.http import request

from odoo.addons.livestream_facebook.controllers.main import verify_meta_signature

_logger = logging.getLogger(__name__)


class InstagramWebhookController(http.Controller):
    @http.route("/livestream/instagram/webhook", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    def instagram_verify(self, **kw):
        token = kw.get("hub.verify_token")
        if kw.get("hub.mode") == "subscribe" and token and request.env["livestream.account"].sudo().search_count(
            [("platform", "=", "instagram"), ("fb_verify_token", "=", token)], limit=1,
        ):
            return request.make_response(kw.get("hub.challenge", ""), headers=[("Content-Type", "text/plain")])
        _logger.warning("Rejected Instagram webhook verification")
        return request.make_response("Forbidden", status=403)

    @http.route("/livestream/instagram/webhook", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    def instagram_event(self):
        body = request.httprequest.get_data()
        signature = request.httprequest.headers.get("X-Hub-Signature-256", "")
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            return request.make_response("Bad Request", status=400)
        Account = request.env["livestream.account"].sudo()
        accepted = []
        for entry in payload.get("entry", []):
            account = Account.search([("platform", "=", "instagram"), ("external_id", "=", str(entry.get("id")))], limit=1)
            if not verify_meta_signature(body, signature, account.fb_app_secret if account else None):
                _logger.warning("Rejected Instagram webhook for account %s (bad signature)", entry.get("id"))
                return request.make_response("Forbidden", status=403)
            accepted.append((account, entry))
        Event = request.env["livestream.webhook.event"].sudo()
        for account, entry in accepted:
            Event.with_company(account.company_id)._enqueue("instagram", entry, account)
        return request.make_response("EVENT_RECEIVED", headers=[("Content-Type", "text/plain")])
