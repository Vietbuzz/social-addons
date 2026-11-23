import re

from odoo import api, fields, models


def normalize_vn_phone(phone):
    """'+84 912.345.678' -> '0912345678'; returns '' when nothing usable."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("84") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


class ResPartner(models.Model):
    _inherit = "res.partner"

    livestream_phone_norm = fields.Char(
        "Normalized Phone", compute="_compute_livestream_phone_norm", store=True, index="btree_not_null",
    )

    @api.depends("phone")
    def _compute_livestream_phone_norm(self):
        for partner in self:
            partner.livestream_phone_norm = normalize_vn_phone(partner.phone) or False

    @api.model
    def _livestream_find_or_create(self, name, phone, street=None):
        phone_norm = normalize_vn_phone(phone)
        if phone_norm and len(phone_norm) >= 9:
            partner = self.search([("livestream_phone_norm", "=", phone_norm)], order="id", limit=1)
            if partner:
                if street and not partner.street:
                    partner.sudo().street = street
                return partner
        # sudo: assistants (salesmen) may not create contacts; values are limited to name/phone/street
        return self.sudo().create({"name": name, "phone": phone_norm or phone, "street": street}).sudo(False)
