import logging

from markupsafe import escape

from odoo import http
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request

from ..models.meta_oauth import CALLBACK_PATH

_logger = logging.getLogger(__name__)


class MetaOAuthController(http.Controller):
    @http.route(CALLBACK_PATH, type="http", auth="user", methods=["GET"])
    def meta_oauth_callback(self, state=None, code=None, error=None, error_description=None, **kw):
        env = request.env
        if not env.user.has_group("livestream_sale.group_livestream_manager"):
            return request.make_response("Forbidden", status=403)
        OAuth = env["livestream.meta.oauth"]
        try:
            account = OAuth._check_state(state)
        except AccessDenied:
            _logger.warning("Rejected Meta OAuth callback (bad state) for user %s", env.uid)
            return request.make_response("Invalid or expired connection request. Start again from Odoo.", status=403)
        if error or not code:
            _logger.info("Meta OAuth cancelled: %s", error)
            message = error_description or error or "Missing authorization code"
            return request.make_response(f"Facebook connection cancelled: {escape(message)}", status=400)
        try:
            user_token = OAuth._exchange_code(account, code)
            pages = OAuth._list_pages(user_token)
        except UserError as e:
            _logger.warning("Meta OAuth exchange failed: %s", e)
            return request.make_response(f"Facebook connection failed: {escape(str(e))}", status=400)
        except Exception as e:  # noqa: BLE001 - never let a traceback (URL with secrets) reach logs/user
            _logger.warning("Meta OAuth exchange failed unexpectedly: %s", type(e).__name__)
            return request.make_response("Facebook connection failed. Please try again.", status=400)
        wizard = env["livestream.meta.connect.wizard"]._create_from_pages(account, user_token, pages)
        return request.redirect(f"/odoo/action-livestream_facebook.action_meta_connect_wizard/{wizard.id}")
