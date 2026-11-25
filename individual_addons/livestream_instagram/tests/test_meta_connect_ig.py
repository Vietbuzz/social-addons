from odoo.tests import tagged

from .common import InstagramCommon

PAGES = [{"page_id": "PAGE1", "name": "Nuoc hoa", "token": "PAGE1_LONG", "ig_id": "IG1", "ig_username": "nuochoa"},
         {"page_id": "PAGE9", "name": "Page 9", "token": "PAGE9_LONG", "ig_id": "IG9", "ig_username": "shop9"}]


@tagged("post_install", "-at_install", "livestream")
class TestMetaConnectInstagram(InstagramCommon):
    def test_wizard_updates_existing_ig(self):
        self.ig.fb_app_id = "APPID"
        wizard = self.env["livestream.meta.connect.wizard"]._create_from_pages(self.ig, "LONG_USER", PAGES)
        wizard.line_ids.selected = True
        wizard.action_apply()
        igs = self.env["livestream.account"].search([("platform", "=", "instagram")])
        self.assertEqual(sorted(igs.mapped("external_id")), ["IG1", "IG9"])  # IG1 updated, not duplicated
        self.assertEqual((self.ig.access_token, self.ig.fb_page_id, self.ig.token_state), ("PAGE1_LONG", "PAGE1", "valid"))
        ig9 = igs.filtered(lambda a: a.external_id == "IG9")
        self.assertEqual((ig9.name, ig9.fb_page_id, ig9.access_token), ("shop9", "PAGE9", "PAGE9_LONG"))
        self.assertTrue(self.env["livestream.account"].search([("platform", "=", "facebook"), ("external_id", "=", "PAGE9")]))

    def test_wizard_preselects_page_of_ig_account(self):
        wizard = self.env["livestream.meta.connect.wizard"]._create_from_pages(self.ig, "LONG_USER", PAGES)
        self.assertEqual(wizard.line_ids.filtered("selected").mapped("page_id"), ["PAGE1"])
