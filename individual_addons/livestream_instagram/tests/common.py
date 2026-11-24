import hashlib
import hmac
import json
from pathlib import Path

from odoo.tests import HttpCase

from odoo.addons.livestream_sale.tests.common import LivestreamCommon

PAYLOADS = Path(__file__).parent / "payloads"


def raw(name):
    return (PAYLOADS / name).read_bytes()


class InstagramCommon(LivestreamCommon, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ig = cls.env["livestream.account"].create({
            "name": "IG Shop",
            "platform": "instagram",
            "external_id": "IG1",
            "fb_page_id": "PAGE1",
            "access_token": "PAGE_TOKEN",
            "fb_app_secret": "APPSECRET",
            "fb_verify_token": "IGVERIFY",
            "payment_provider_id": cls.provider.id,
        })
        cls.Event = cls.env["livestream.webhook.event"]
        cls.Comment = cls.env["livestream.comment"]
        cls.Customer = cls.env["livestream.customer"]

    def _sig(self, body, secret="APPSECRET"):
        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def _post(self, body, sig=None):
        headers = {"Content-Type": "application/json"}
        if sig is not False:
            headers["X-Hub-Signature-256"] = sig or self._sig(body)
        return self.url_open("/livestream/instagram/webhook", data=body, headers=headers)

    def _deliver_body(self, body):
        self.assertEqual(self._post(body).status_code, 200)
        self.Event._cron_process()

    def _deliver(self, name):
        self._deliver_body(raw(name))

    def _json(self, name):
        return json.loads(raw(name))
