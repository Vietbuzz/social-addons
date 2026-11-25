import logging
import secrets

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import graph_api

_logger = logging.getLogger(__name__)


class LivestreamAccount(models.Model):
    _inherit = "livestream.account"

    platform = fields.Selection(selection_add=[("facebook", "Facebook Page")], ondelete={"facebook": "cascade"})
    fb_app_id = fields.Char("Meta App ID")
    fb_app_secret = fields.Char("Meta App Secret", groups="livestream_sale.group_livestream_manager", copy=False)
    fb_verify_token = fields.Char(
        "Webhook Verify Token", groups="livestream_sale.group_livestream_manager", copy=False,
        default=lambda self: secrets.token_urlsafe(24),
    )
    fb_webhook_url = fields.Char(compute="_compute_fb_webhook_url")

    def _compute_fb_webhook_url(self):
        url = f"{self.get_base_url()}/livestream/facebook/webhook"
        for account in self:
            account.fb_webhook_url = url if account.platform == "facebook" else False

    def _fb_token(self):
        self.ensure_one()
        token = self.sudo().access_token
        if not token:
            raise UserError(self.env._("Set the Page access token on %s.", self.name))
        return token

    # ------------------------------------------------------------------
    # Setup actions
    # ------------------------------------------------------------------
    def action_meta_connect(self):
        """Start Facebook Login to get long-lived Page tokens (Pages + linked Instagram accounts)."""
        self.ensure_one()
        if not self.env.user.has_group("livestream_sale.group_livestream_manager"):
            raise UserError(self.env._("Only a livestream manager can connect Facebook."))
        return {
            "type": "ir.actions.act_url",
            "url": self.env["livestream.meta.oauth"]._authorize_url(self),
            "target": "self",
        }

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def action_fb_subscribe(self):
        for account in self.filtered(lambda a: a.platform == "facebook"):
            graph_api._request("POST", f"{account.external_id}/subscribed_apps", account._fb_token(), params={
                "subscribed_fields": "feed,live_videos,messages,messaging_postbacks",
            })
        return True

    # ------------------------------------------------------------------
    # Token health
    # ------------------------------------------------------------------
    def _check_token_health(self):
        for account in self.sudo():
            token = account.access_token
            if not token:
                continue
            vals = {"token_checked_at": fields.Datetime.now()}
            try:
                if account.fb_app_id and account.fb_app_secret:
                    data = graph_api._request(
                        "GET", "debug_token", f"{account.fb_app_id}|{account.fb_app_secret}",
                        params={"input_token": token},
                    ).get("data", {})
                    if data.get("is_valid"):
                        vals.update(token_state="valid", token_error=False)
                    else:
                        message = (data.get("error") or {}).get("message") or "Token is no longer valid"
                        vals.update(token_state="invalid", token_error=message[:250])
                else:
                    graph_api._request("GET", "me", token, params={"fields": "id"})
                    vals.update(token_state="valid", token_error=False)
            except graph_api.MetaApiError as e:
                if e.code in (190, 102):
                    vals.update(token_state="invalid", token_error=str(e)[:250])
                else:
                    vals["token_error"] = str(e)[:250]
            except Exception as e:  # noqa: BLE001 - network trouble is not a broken token
                _logger.warning("Token check failed for account %s: %s", account.id, e)
                vals["token_error"] = str(e)[:250]
            account.write(vals)

    @api.model
    def _cron_check_tokens(self):
        self.search([
            ("platform", "in", ("facebook", "instagram")), ("access_token", "!=", False),
        ])._check_token_health()

    def action_check_token(self):
        if not self.env.user.has_group("livestream_sale.group_livestream_manager"):
            raise UserError(self.env._("Only a livestream manager can check tokens."))
        self._check_token_health()
        return True

    def action_fb_sync_live_videos(self):
        Session = self.env["livestream.session"]
        for account in self.filtered(lambda a: a.platform == "facebook"):
            res = graph_api._request("GET", f"{account.external_id}/live_videos", account._fb_token(), params={
                "fields": "id,status,title,video{id},creation_time", "limit": 25,
            })
            for live in res.get("data", []):
                Session._fb_upsert_live(account, live)
        return True

    # ------------------------------------------------------------------
    # Platform hooks
    # ------------------------------------------------------------------
    def _livestream_private_reply(self, comment, body, attachments):
        if self.platform != "facebook":
            return super()._livestream_private_reply(comment, body, attachments)
        res = graph_api.send_text(self._fb_token(), self.external_id, {"comment_id": comment.external_id}, body)
        return res.get("recipient_id")

    def _livestream_send_message(self, customer, body, attachments):
        if self.platform != "facebook":
            return super()._livestream_send_message(customer, body, attachments)
        channel = customer.channel_id
        if not customer.psid or channel.livestream_window_state != "open":
            raise UserError(self.env._(
                "The 24h Messenger window is closed: wait for %s to write to the Page.", customer.name,
            ))
        token = self._fb_token()
        if body:
            graph_api.send_text(token, self.external_id, {"id": customer.psid}, body, "RESPONSE")
        for att in attachments:
            if (att.mimetype or "").startswith("image/"):
                graph_api.send_image(token, self.external_id, customer.psid, att.name, att.raw, att.mimetype)
