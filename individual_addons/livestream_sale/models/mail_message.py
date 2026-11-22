from odoo import fields, models


class MailMessage(models.Model):
    _inherit = "mail.message"

    livestream_external_id = fields.Char("Platform Message ID", index="btree_not_null", copy=False)

    _livestream_external_id_uniq = models.UniqueIndex(
        "(livestream_external_id) WHERE livestream_external_id IS NOT NULL",
    )
