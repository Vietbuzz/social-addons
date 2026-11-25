import logging
from unittest.mock import patch

import requests

from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.livestream_facebook.models import graph_api

from .common import FacebookCommon

LEAKY = ("HTTPSConnectionPool(host='graph.facebook.com', port=443): Max retries exceeded with url: "
         "/v27.0/debug_token?input_token=PAGESECRETTOKEN&access_token=APPID%7CAPPSECRET")


@tagged("post_install", "-at_install", "livestream")
class TestMetaReviewFixes(FacebookCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fb.fb_app_id = "APPID"
        cls.Wizard = cls.env["livestream.meta.connect.wizard"]

    def setUp(self):
        super().setUp()
        self.session = None  # LivestreamCommon.session shadows HttpCase's http session

    # --- secrets never leak from network errors ---
    def test_request_network_error_sanitized(self):
        with patch.object(requests, "request", side_effect=requests.ConnectionError(LEAKY)):
            with self.assertRaises(graph_api.MetaApiError) as ctx:
                graph_api._request("GET", "debug_token", "APPID|APPSECRET", params={"input_token": "PAGESECRETTOKEN"})
        self.assertIsNone(ctx.exception.code)
        self.assertNotIn("SECRET", str(ctx.exception))
        self.assertIn("graph.facebook.com", str(ctx.exception))

    def test_health_network_error_does_not_store_or_log_secrets(self):
        self.fb.token_state = "valid"
        with patch.object(requests, "request", side_effect=requests.ConnectionError(LEAKY)), \
                self.assertLogs("odoo.addons.livestream_facebook", level="INFO") as logs:
            self.fb._check_token_health()
            # keep assertLogs satisfied even if nothing is logged
            logging.getLogger("odoo.addons.livestream_facebook").info("probe")
        self.assertEqual(self.fb.token_state, "valid")
        self.assertNotIn("SECRET", self.fb.token_error or "")
        self.assertFalse([line for line in logs.output if "SECRET" in line])

    def test_callback_unexpected_error_generic_400(self):
        manager = new_test_user(self.env, login="ls_rf_mgr", groups="base.group_user,livestream_sale.group_livestream_manager",
                                company_id=self.company_data["company"].id)
        self.authenticate("ls_rf_mgr", "ls_rf_mgr")
        state = self.env["livestream.meta.oauth"].with_user(manager)._make_state(self.fb)
        with patch.object(type(self.env["livestream.meta.oauth"]), "_exchange_code", side_effect=KeyError("access_token")), \
                mute_logger("odoo.addons.livestream_facebook.controllers.oauth"):
            res = self.url_open(f"/livestream/facebook/oauth/callback?code=C&state={state}", allow_redirects=False)
        self.assertEqual(res.status_code, 400)
        self.assertFalse(self.Wizard.search([]))

    # --- cross-company / client tampering ---
    def _wizard(self, pages):
        return self.Wizard.with_context(livestream_meta_connect=True)._create_from_pages(self.fb, "LONG", pages)

    def test_wizard_refuses_account_of_other_company(self):
        other_company = self.env["res.company"].create({"name": "Other Co"})
        other = self.env["livestream.account"].create({
            "name": "B page", "platform": "facebook", "external_id": "PAGEB", "company_id": other_company.id,
            "access_token": "B_TOKEN",
        })
        wizard = self._wizard([{"page_id": "PAGEB", "name": "B", "token": "NEW", "ig_id": None, "ig_username": None}])
        wizard.line_ids.selected = True
        with self.assertRaises(UserError):
            wizard.with_context(allowed_company_ids=[self.company_data["company"].id]).action_apply()
        self.assertEqual((other.sudo().access_token, other.company_id), ("B_TOKEN", other_company))

    def test_wizard_line_fields_not_writable_by_client(self):
        wizard = self._wizard([{"page_id": "PAGE1", "name": "P", "token": "T", "ig_id": None, "ig_username": None}])
        lines = self.env["livestream.meta.connect.wizard.line"].browse(wizard.line_ids.ids)  # client context
        with self.assertRaises((UserError, AccessError)):
            lines.write({"page_token": "EVIL", "page_id": "PAGEB"})
        lines.write({"selected": False})  # allowed

    def test_wizard_cannot_be_created_by_client(self):
        with self.assertRaises((UserError, AccessError)):
            self.Wizard.create({"source_account_id": self.fb.id, "line_ids": [
                (0, 0, {"page_id": "PAGEB", "name": "x", "page_token": "EVIL", "selected": True})]})

    # --- missing page token ---
    def test_missing_page_token_never_wipes_existing(self):
        wizard = self._wizard([{"page_id": "PAGE1", "name": "P", "token": None, "ig_id": None, "ig_username": None}])
        self.assertFalse(wizard.line_ids.selected)
        wizard.line_ids.with_context(livestream_meta_connect=True).write({"selected": True})
        wizard.action_apply()
        self.assertEqual(self.fb.access_token, "PAGE_TOKEN")

    def test_apply_clears_all_tokens(self):
        wizard = self._wizard([
            {"page_id": "PAGE1", "name": "P", "token": "T1", "ig_id": None, "ig_username": None},
            {"page_id": "PAGE7", "name": "Q", "token": "T7", "ig_id": None, "ig_username": None},
        ])
        wizard.action_apply()
        self.assertFalse(wizard.sudo().user_token)
        self.assertFalse(any(wizard.sudo().line_ids.mapped("page_token")))

    # --- health robustness ---
    def test_health_one_account_error_others_checked(self):
        other = self.env["livestream.account"].create({
            "name": "Page 2", "platform": "facebook", "external_id": "PAGE2", "access_token": "T2",
            "fb_app_id": "APPID", "fb_app_secret": "APPSECRET",
        })

        def fake(method, path, token, **kw):
            if kw["params"]["input_token"] == "PAGE_TOKEN":
                raise RuntimeError("boom")
            return {"data": {"is_valid": True}}

        with patch.object(graph_api, "_request", side_effect=fake), \
                mute_logger("odoo.addons.livestream_facebook.models.livestream_account"):
            self.env["livestream.account"]._cron_check_tokens()
        self.assertEqual(other.token_state, "valid")

    def test_health_other_meta_error_keeps_state(self):
        self.fb.token_state = "valid"
        with patch.object(graph_api, "_request", side_effect=graph_api.MetaApiError("Facebook: rate limit", code=4)):
            self.fb._check_token_health()
        self.assertEqual(self.fb.token_state, "valid")

    def test_new_token_resets_alert(self):
        self.fb.write({"token_state": "invalid", "token_error": "expired"})
        self.fb.access_token = "PASTED"
        self.assertEqual(self.fb.token_state, "unknown")
        self.assertFalse(self.fb.token_error)

    def test_check_token_ignores_other_platforms(self):
        self.ls_account.sudo().access_token = "X"
        with patch.object(graph_api, "_request") as req:
            self.ls_account.action_check_token()
        req.assert_not_called()
