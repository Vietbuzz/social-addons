import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SepayController(http.Controller):
    @http.route("/livestream/sepay/webhook/<int:provider_id>", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    def sepay_webhook(self, provider_id, **form):
        provider = request.env["payment.provider"].sudo().browse(provider_id).exists()
        expected = provider.sepay_webhook_api_key if provider and provider.code == "sepay" else None
        received = request.httprequest.headers.get("Authorization", "")
        if not expected or not hmac.compare_digest(received.encode(), f"Apikey {expected}".encode()):
            _logger.warning("Rejected SePay webhook for provider %s (bad API key)", provider_id)
            return request.make_json_response({"success": False}, status=401)
        try:
            payload = json.loads(request.httprequest.get_data(as_text=True) or "{}")
        except ValueError:
            payload = dict(form)  # SePay can also post form-encoded data
        payload["_provider_id"] = provider.id
        request.env["livestream.webhook.event"].sudo()._enqueue("sepay", payload)
        return request.make_json_response({"success": True}, status=200)
