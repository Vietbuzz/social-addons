"""Facebook Login (manual flow) to obtain long-lived Page tokens for Pages and linked Instagram accounts."""
import time
from urllib.parse import urlencode

from odoo import api, models
from odoo.exceptions import AccessDenied, UserError
from odoo.tools.misc import consteq, hmac

from . import graph_api

CALLBACK_PATH = "/livestream/facebook/oauth/callback"
STATE_TTL = 900  # seconds
SCOPES = [
    "pages_show_list", "pages_read_engagement", "pages_manage_metadata", "pages_messaging",
    "pages_read_user_content", "instagram_basic", "instagram_manage_comments", "instagram_manage_messages",
    "business_management",
]


class LivestreamMetaOAuth(models.AbstractModel):
    _name = "livestream.meta.oauth"
    _description = "Livestream Meta OAuth helper"

    @api.model
    def _sign(self, payload):
        return hmac(self.env(su=True), "livestream-meta-oauth", payload)

    @api.model
    def _make_state(self, account):
        payload = f"{account.id}.{self.env.uid}.{int(time.time())}"
        return f"{payload}.{self._sign(payload)}"

    @api.model
    def _check_state(self, state):
        """Return the account the OAuth flow was started for; AccessDenied if forged/expired/other user."""
        try:
            payload, signature = (state or "").rsplit(".", 1)
            account_id, uid, issued = (int(x) for x in payload.split("."))
        except ValueError:
            raise AccessDenied() from None
        if (
            not consteq(signature, self._sign(payload))
            or uid != self.env.uid
            or time.time() - issued > STATE_TTL
        ):
            raise AccessDenied()
        account = self.env["livestream.account"].browse(account_id).exists()
        if not account:
            raise AccessDenied()
        return account

    @api.model
    def _redirect_uri(self):
        return f"{self.get_base_url()}{CALLBACK_PATH}"

    @api.model
    def _app_credentials(self, account):
        account = account.sudo()
        if not account.fb_app_id or not account.fb_app_secret:
            raise UserError(self.env._("Enter the Meta App ID and App Secret on %s first.", account.name))
        return account.fb_app_id, account.fb_app_secret

    @api.model
    def _authorize_url(self, account):
        app_id, _secret = self._app_credentials(account)
        query = urlencode({
            "client_id": app_id,
            "redirect_uri": self._redirect_uri(),
            "state": self._make_state(account),
            "scope": ",".join(SCOPES),
            "response_type": "code",
        })
        return f"https://www.facebook.com/{graph_api.GRAPH_VERSION}/dialog/oauth?{query}"

    @api.model
    def _exchange_code(self, account, code):
        """code -> short-lived user token -> long-lived user token."""
        app_id, secret = self._app_credentials(account)
        short = graph_api._request("GET", "oauth/access_token", None, params={
            "client_id": app_id, "client_secret": secret, "redirect_uri": self._redirect_uri(), "code": code,
        })["access_token"]
        return graph_api._request("GET", "oauth/access_token", None, params={
            "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": secret,
            "fb_exchange_token": short,
        })["access_token"]

    @api.model
    def _list_pages(self, user_token):
        """Pages the user manages, with long-lived Page tokens and linked Instagram business accounts."""
        res = graph_api._request("GET", "me/accounts", user_token, params={
            "fields": "id,name,access_token,instagram_business_account{id,username}", "limit": 100,
        })
        pages = []
        for page in res.get("data", []):
            ig = page.get("instagram_business_account") or {}
            pages.append({
                "page_id": page["id"], "name": page.get("name") or page["id"], "token": page.get("access_token"),
                "ig_id": ig.get("id"), "ig_username": ig.get("username"),
            })
        return pages
