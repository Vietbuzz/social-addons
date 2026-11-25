import hashlib
import hmac
from pathlib import Path

from odoo import fields
from odoo.tests import HttpCase

from odoo.addons.livestream_sale.tests.common import LivestreamCommon

PAYLOADS = Path(__file__).parent / "payloads"


def raw(name):
    return (PAYLOADS / name).read_bytes()


class FacebookCommon(LivestreamCommon, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fb = cls.env["livestream.account"].create({
            "name": "FB Page",
            "platform": "facebook",
            "external_id": "PAGE1",
            "access_token": "PAGE_TOKEN",
            "fb_app_secret": "APPSECRET",
            "fb_verify_token": "VERIFY",
            "payment_provider_id": cls.provider.id,
        })
        cls.fb_session = cls.env["livestream.session"].create({
            "name": "FB live", "account_id": cls.fb.id, "state": "live",
            "external_video_id": "LIVE1", "external_post_id": "PAGE1_VID1",
            "tag_ids": [fields.Command.create({"code": "69", "product_id": cls.product_shirt.id, "price_unit": 150000})],
        })
        cls.Event = cls.env["livestream.webhook.event"]
        cls.Comment = cls.env["livestream.comment"]

    def _sig(self, body, secret="APPSECRET"):
        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def _post(self, body, sig=None):
        headers = {"Content-Type": "application/json"}
        if sig is not False:
            headers["X-Hub-Signature-256"] = sig or self._sig(body)
        return self.url_open("/livestream/facebook/webhook", data=body, headers=headers)

    def _deliver(self, name):
        self.assertEqual(self._post(raw(name)).status_code, 200)
        self.Event._cron_process()

