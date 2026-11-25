import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from odoo.exceptions import AccessDenied, UserError
from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.livestream_facebook.models import graph_api

from .common import FacebookCommon


def fake_meta(fail_exchange=False):
    calls = []

    def _fake(method, path, token, **kw):
        params = kw.get("params") or {}
        calls.append((path, params))
        if path == "oauth/access_token" and "code" in params:
            if fail_exchange:
                raise UserError("Facebook: This authorization code has been used.")
            return {"access_token": "SHORT_USER"}
        if path == "oauth/access_token":
            assert params["fb_exchange_token"] == "SHORT_USER"
            return {"access_token": "LONG_USER", "token_type": "bearer"}
        if path == "me/accounts":
            assert token == "LONG_USER"
            return {"data": [
                {"id": "PAGE1", "name": "Nuoc hoa", "access_token": "PAGE1_LONG",
                 "instagram_business_account": {"id": "IG1", "username": "nuochoa"}},
                {"id": "PAGE2", "name": "Page 2", "access_token": "PAGE2_LONG"},
            ]}
        raise AssertionError(path)
    return _fake, calls


@tagged("post_install", "-at_install", "livestream")
class TestMetaOAuth(FacebookCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fb.fb_app_id = "APPID"
        cls.manager = new_test_user(
            cls.env, login="ls_oauth_mgr", groups="base.group_user,livestream_sale.group_livestream_manager",
            company_id=cls.company_data["company"].id,
        )
        cls.OAuth = cls.env["livestream.meta.oauth"]

    def setUp(self):
        super().setUp()
        # LivestreamCommon.session (a live session record) shadows HttpCase's HTTP session attribute
        self.session = None

    def test_authorize_url_contains_state_and_scopes(self):
        action = self.fb.with_user(self.manager).action_meta_connect()
        url = urlparse(action["url"])
        self.assertEqual((url.netloc, url.path), ("www.facebook.com", f"/{graph_api.GRAPH_VERSION}/dialog/oauth"))
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.assertEqual(q["client_id"], "APPID")
        self.assertTrue(q["redirect_uri"].endswith("/livestream/facebook/oauth/callback"))
        self.assertIn("pages_messaging", q["scope"])
        self.assertIn("instagram_manage_comments", q["scope"])
        self.assertEqual(self.OAuth.with_user(self.manager)._check_state(q["state"]), self.fb)
        self.assertNotIn("APPSECRET", action["url"])

    def test_state_rejected_when_tampered_expired_or_other_user(self):
        state = self.OAuth.with_user(self.manager)._make_state(self.fb)
        with self.assertRaises(AccessDenied):
            self.OAuth.with_user(self.manager)._check_state(state[:-2] + "xx")
        with self.assertRaises(AccessDenied):
            self.OAuth._check_state(state)  # another user
        with patch.object(time, "time", return_value=time.time() + 1000), self.assertRaises(AccessDenied):
            self.OAuth.with_user(self.manager)._check_state(state)

    def test_callback_creates_wizard_with_pages(self):
        self.authenticate("ls_oauth_mgr", "ls_oauth_mgr")
        state = self.OAuth.with_user(self.manager)._make_state(self.fb)
        fake, calls = fake_meta()
        with patch.object(graph_api, "_request", side_effect=fake):
            res = self.url_open(f"/livestream/facebook/oauth/callback?code=CODE1&state={state}", allow_redirects=False)
        self.assertIn(res.status_code, (302, 303))
        wizard = self.env["livestream.meta.connect.wizard"].search([], order="id desc", limit=1)
        self.assertEqual(wizard.source_account_id, self.fb)
        self.assertEqual(sorted(wizard.line_ids.mapped("page_id")), ["PAGE1", "PAGE2"])
        line1 = wizard.line_ids.filtered(lambda l: l.page_id == "PAGE1")
        self.assertTrue(line1.selected)  # already connected page is pre-selected
        self.assertEqual((line1.ig_id, line1.ig_username), ("IG1", "nuochoa"))
        self.assertIn(str(wizard.id), res.headers["Location"])
        self.assertNotIn("LONG", res.headers["Location"])
        code_call = next(p for path, p in calls if "code" in p)
        self.assertEqual((code_call["client_id"], code_call["client_secret"]), ("APPID", "APPSECRET"))

    def test_callback_rejects_bad_state(self):
        self.authenticate("ls_oauth_mgr", "ls_oauth_mgr")
        fake, calls = fake_meta()
        with patch.object(graph_api, "_request", side_effect=fake), \
                mute_logger("odoo.addons.livestream_facebook.controllers.oauth", "odoo.http"):
            res = self.url_open("/livestream/facebook/oauth/callback?code=CODE1&state=forged", allow_redirects=False)
        self.assertEqual(res.status_code, 403)
        self.assertFalse(calls)
        self.assertFalse(self.env["livestream.meta.connect.wizard"].search([]))

    def test_callback_exchange_error(self):
        self.authenticate("ls_oauth_mgr", "ls_oauth_mgr")
        state = self.OAuth.with_user(self.manager)._make_state(self.fb)
        fake, _calls = fake_meta(fail_exchange=True)
        with patch.object(graph_api, "_request", side_effect=fake), \
                mute_logger("odoo.addons.livestream_facebook.controllers.oauth"):
            res = self.url_open(f"/livestream/facebook/oauth/callback?code=OLD&state={state}", allow_redirects=False)
        self.assertEqual(res.status_code, 400)
        self.assertIn("authorization code", res.text)
        self.assertFalse(self.env["livestream.meta.connect.wizard"].search([]))

    def test_callback_user_denied(self):
        self.authenticate("ls_oauth_mgr", "ls_oauth_mgr")
        state = self.OAuth.with_user(self.manager)._make_state(self.fb)
        with mute_logger("odoo.addons.livestream_facebook.controllers.oauth"):
            res = self.url_open(f"/livestream/facebook/oauth/callback?error=access_denied&state={state}", allow_redirects=False)
        self.assertEqual(res.status_code, 400)
