from unittest.mock import patch

import requests

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.livestream_facebook.models import graph_api

from .common import FacebookCommon


@tagged("post_install", "-at_install", "livestream")
class TestTokenHealth(FacebookCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fb.fb_app_id = "APPID"

    def _check(self, **patch_kw):
        with patch.object(graph_api, "_request", **patch_kw) as req, \
                mute_logger("odoo.addons.livestream_facebook.models.livestream_account"):
            self.env["livestream.account"]._cron_check_tokens()
        return req

    def test_health_marks_invalid(self):
        req = self._check(return_value={"data": {"is_valid": False, "error": {"message": "Session has expired"}}})
        self.assertEqual(req.call_args.args[1], "debug_token")
        self.assertEqual(req.call_args.kwargs["params"]["input_token"], "PAGE_TOKEN")
        self.assertEqual(req.call_args.args[2], "APPID|APPSECRET")
        self.assertEqual(self.fb.token_state, "invalid")
        self.assertIn("expired", self.fb.token_error)

    def test_health_marks_valid(self):
        self.fb.token_state = "invalid"
        self._check(return_value={"data": {"is_valid": True, "expires_at": 0}})
        self.assertEqual(self.fb.token_state, "valid")
        self.assertTrue(self.fb.token_checked_at)
        self.assertFalse(self.fb.token_error)

    def test_health_error_190_invalid(self):
        self._check(side_effect=graph_api.MetaApiError("Facebook: Error validating access token", code=190))
        self.assertEqual(self.fb.token_state, "invalid")

    def test_health_network_error_not_invalid(self):
        self.fb.token_state = "valid"
        self._check(side_effect=requests.ConnectionError("dns"))
        self.assertEqual(self.fb.token_state, "valid")
        self.assertIn("dns", self.fb.token_error)

    def test_health_without_app_credentials_uses_me(self):
        self.fb.sudo().fb_app_secret = False
        req = self._check(return_value={"id": "PAGE1", "name": "Page"})
        self.assertEqual(req.call_args.args[1], "me")
        self.assertEqual(self.fb.token_state, "valid")

    def test_health_skips_simulator(self):
        self.fb.active = False
        req = self._check(return_value={"data": {"is_valid": True}})
        req.assert_not_called()
        self.assertEqual(self.ls_account.token_state, "unknown")

    def test_check_button(self):
        with patch.object(graph_api, "_request", return_value={"data": {"is_valid": True}}):
            self.fb.action_check_token()
        self.assertEqual(self.fb.token_state, "valid")
