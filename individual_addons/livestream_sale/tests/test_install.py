from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "livestream")
class TestInstall(TransactionCase):
    def test_groups_exist(self):
        mgr = self.env.ref("livestream_sale.group_livestream_manager")
        user = self.env.ref("livestream_sale.group_livestream_user")
        self.assertIn(user, mgr.implied_ids)
