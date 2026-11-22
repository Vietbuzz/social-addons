from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.livestream_sale.models.tag_parser import parse_tag

from .common import LivestreamCommon


@tagged("post_install", "-at_install", "livestream")
class TestTagParser(TransactionCase):
    def test_parse_tag_variants(self):
        cases = {
            "69": ("69", 1), "#69": ("69", 1), "mã 69": ("69", 1), "ma69": ("69", 1),
            "69 x2": ("69", 2), "69x2": ("69", 2), "69 sl 3": ("69", 3), "69 sl2": ("69", 2),
            "69*2": ("69", 2), "69 - 2c": ("69", 2), "chốt 69 nha": ("69", 1),
            "ok": (None, 1), "0912345678": (None, 1), "😍😍": (None, 1),
            "0912345678 lấy 69": ("69", 1), "": (None, 1),
        }
        for msg, expected in cases.items():
            self.assertEqual(parse_tag(msg), expected, msg)

    def test_parse_tag_restricted_codes(self):
        self.assertEqual(parse_tag("12 69", codes={"69"}), ("69", 1))
        self.assertEqual(parse_tag("12", codes={"69"}), (None, 1))


@tagged("post_install", "-at_install", "livestream")
class TestCustomerAndTags(LivestreamCommon):
    def test_customer_get_or_create_dedup(self):
        Customer = self.env["livestream.customer"]
        c1 = Customer._get_or_create(self.ls_account, "u1", "Nguyen Van A")
        c2 = Customer._get_or_create(self.ls_account, "u1", "Nguyen Van A")
        self.assertEqual(c1, c2)
        self.assertEqual(c1.company_id, self.ls_account.company_id)

    def test_tag_code_unique_per_session(self):
        with self.assertRaises((IntegrityError, ValidationError)), mute_logger("odoo.sql_db"), self.cr.savepoint():
            self.session.write({"tag_ids": [Command.create({"code": "69", "product_id": self.product_shirt.id})]})
            self.env.flush_all()
