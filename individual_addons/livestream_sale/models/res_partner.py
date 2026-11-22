import re

from odoo import api, models


def normalize_vn_phone(phone):
    """'+84 912.345.678' -> '0912345678'; returns '' when nothing usable."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("84") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _livestream_find_or_create(self, name, phone, street=None):
        phone_norm = normalize_vn_phone(phone)
        if phone_norm and len(phone_norm) >= 9:
            candidates = self.search([("phone", "ilike", phone_norm[-9:][:3])], limit=200)
            # ilike on a short chunk then exact compare: phones are stored in many shapes
            for partner in candidates:
                if normalize_vn_phone(partner.phone) == phone_norm:
                    if street and not partner.street:
                        partner.street = street
                    return partner
        return self.create({"name": name, "phone": phone_norm or phone, "street": street})
