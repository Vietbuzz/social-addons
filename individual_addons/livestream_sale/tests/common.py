from odoo import fields
from odoo.fields import Command

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.account_payment.tests.common import AccountPaymentCommon


class LivestreamCommon(AccountPaymentCommon):
    """Shared fixture: VN company (VND), bank journal + VietQR account,
    a payment provider bound to the bank journal, a simulator account,
    a live session and tag 69 -> "Ao thun do" at 150 000."""

    @classmethod
    @AccountTestInvoicingCommon.setup_country("vn")
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref("livestream_sale.group_livestream_manager")
        company = cls.company_data["company"]
        company.partner_id.write({"country_id": cls.env.ref("base.vn").id, "city": "Ha Noi"})
        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.vn_bank_account = cls.env["res.partner.bank"].create({
            "account_number": "0011223344",
            "bank_name": "Vietcombank",
            "bank_bic": "970436",
            "partner_id": company.partner_id.id,
            "proxy_type": "bank_acc",
            "proxy_value": "0011223344",
            "include_reference": True,
            "allow_out_payment": True,
        })
        cls.bank_journal.bank_account_id = cls.vn_bank_account
        cls.provider.write({"journal_id": cls.bank_journal.id})
        cls.ls_account = cls.env["livestream.account"].create({
            "name": "Shop Test",
            "platform": "simulator",
            "external_id": "page-1",
            "payment_provider_id": cls.provider.id,
        })
        cls.product_shirt = cls.env["product.product"].create({
            "name": "Ao thun do",
            "lst_price": 150000,
            "taxes_id": [Command.clear()],
            "invoice_policy": "order",
        })
        cls.session = cls.env["livestream.session"].create({
            "name": "Live 22/11",
            "account_id": cls.ls_account.id,
            "state": "live",
            "date_start": fields.Datetime.now(),
            "tag_ids": [Command.create({"code": "69", "product_id": cls.product_shirt.id, "price_unit": 150000})],
        })
        cls.tag_69 = cls.session.tag_ids
