import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def verify_meta_signature(body, header, secret):
    """Meta webhooks: X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(app secret, raw body)."""
    if not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest((header or "").encode(), expected.encode())


class FacebookWebhookController(http.Controller):
    @http.route("/livestream/facebook/webhook", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    def facebook_verify(self, **kw):
        token = kw.get("hub.verify_token")
        if kw.get("hub.mode") == "subscribe" and token and request.env["livestream.account"].sudo().search_count(
            [("platform", "=", "facebook"), ("fb_verify_token", "=", token)], limit=1,
        ):
            return request.make_response(kw.get("hub.challenge", ""), headers=[("Content-Type", "text/plain")])
        _logger.warning("Rejected Facebook webhook verification")
        return request.make_response("Forbidden", status=403)

    @http.route("/livestream/facebook/webhook", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    def facebook_event(self):
        body = request.httprequest.get_data()
        signature = request.httprequest.headers.get("X-Hub-Signature-256", "")
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            return request.make_response("Bad Request", status=400)
        Account = request.env["livestream.account"].sudo()
        accepted = []
        for entry in payload.get("entry", []):
            account = Account.search([("platform", "=", "facebook"), ("external_id", "=", str(entry.get("id")))], limit=1)
            if not verify_meta_signature(body, signature, account.fb_app_secret if account else None):
                _logger.warning("Rejected Facebook webhook for page %s (bad signature)", entry.get("id"))
                return request.make_response("Forbidden", status=403)
            accepted.append((account, entry))
        Event = request.env["livestream.webhook.event"].sudo()
        for account, entry in accepted:
            Event._enqueue("facebook", entry, account)
        return request.make_response("EVENT_RECEIVED", headers=[("Content-Type", "text/plain")])
