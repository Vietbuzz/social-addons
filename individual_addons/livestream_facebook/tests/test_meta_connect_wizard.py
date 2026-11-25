from odoo.tests import tagged

from .common import FacebookCommon

PAGES = [
    {"page_id": "PAGE1", "name": "Nuoc hoa", "token": "PAGE1_LONG", "ig_id": None, "ig_username": None},
    {"page_id": "PAGE2", "name": "Page 2", "token": "PAGE2_LONG", "ig_id": None, "ig_username": None},
    {"page_id": "PAGE3", "name": "Page 3", "token": "PAGE3_LONG", "ig_id": None, "ig_username": None},
]


@tagged("post_install", "-at_install", "livestream")
class TestMetaConnectWizard(FacebookCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fb.fb_app_id = "APPID"
        cls.Account = cls.env["livestream.account"]

    def _wizard(self, select=("PAGE1", "PAGE2")):
        wizard = self.env["livestream.meta.connect.wizard"]._create_from_pages(self.fb, "LONG_USER", PAGES)
        for line in wizard.line_ids:
            line.selected = line.page_id in select
        return wizard

    def test_wizard_updates_existing_and_creates_new_page(self):
        self._wizard().action_apply()
        self.assertEqual(self.fb.access_token, "PAGE1_LONG")
        self.assertEqual(self.fb.token_state, "valid")
        page2 = self.Account.search([("platform", "=", "facebook"), ("external_id", "=", "PAGE2")])
        self.assertEqual((page2.name, page2.access_token, page2.fb_app_id, page2.fb_app_secret),
                         ("Page 2", "PAGE2_LONG", "APPID", "APPSECRET"))
        self.assertEqual(page2.company_id, self.fb.company_id)
        self.assertTrue(page2.fb_verify_token)

    def test_wizard_unselected_page_untouched(self):
        self._wizard(select=("PAGE2",)).action_apply()
        self.assertEqual(self.fb.access_token, "PAGE_TOKEN")
        self.assertFalse(self.Account.search([("external_id", "=", "PAGE3")]))

    def test_wizard_preselects_connected_pages(self):
        wizard = self.env["livestream.meta.connect.wizard"]._create_from_pages(self.fb, "LONG_USER", PAGES)
        self.assertEqual(wizard.line_ids.filtered("selected").mapped("page_id"), ["PAGE1"])
