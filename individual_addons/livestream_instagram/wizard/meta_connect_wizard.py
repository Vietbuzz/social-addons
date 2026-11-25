from odoo import models


class LivestreamMetaConnectWizard(models.TransientModel):
    _inherit = "livestream.meta.connect.wizard"

    def _apply_instagram(self, line):
        accounts = super()._apply_instagram(line)
        if not line.ig_id:
            return accounts
        source = self.source_account_id.sudo()
        return accounts | self._upsert_account(
            "instagram", line.ig_id,
            {**self._shared_values(), "access_token": line.page_token, "fb_page_id": line.page_id},
            {"name": line.ig_username or line.ig_id, "fb_verify_token": source.fb_verify_token,
             "payment_provider_id": source.payment_provider_id.id},
        )
