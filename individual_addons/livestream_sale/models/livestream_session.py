from odoo import api, fields, models


class LivestreamSession(models.Model):
    _name = "livestream.session"
    _description = "Livestream Session"
    _inherit = ["mail.thread"]
    _order = "date_start desc, id desc"

    name = fields.Char(required=True, tracking=True)
    account_id = fields.Many2one("livestream.account", required=True, ondelete="cascade", index=True)
    platform = fields.Selection(related="account_id.platform")
    company_id = fields.Many2one(related="account_id.company_id", store=True, index=True)
    external_video_id = fields.Char("Video ID", index=True)
    external_post_id = fields.Char("Post ID", index=True)
    state = fields.Selection(
        [("draft", "Scheduled"), ("live", "Live"), ("ended", "Ended")],
        default="draft", required=True, tracking=True,
    )
    date_start = fields.Datetime("Start")
    date_end = fields.Datetime("End")
    tag_ids = fields.One2many("livestream.session.tag", "session_id", "Product Tags", copy=True)
    source_type = fields.Selection(
        [("live", "Live"), ("post", "Post")], string="Source", required=True, default="live", index=True,
    )
    permalink_url = fields.Char("Post Link")
    last_comment_at = fields.Datetime("Last Comment", index=True, copy=False)
    user_ids = fields.Many2many("res.users", string="Assistants")

    def action_start(self):
        self.write({"state": "live", "date_start": fields.Datetime.now()})

    def action_end(self):
        self.write({"state": "ended", "date_end": fields.Datetime.now()})

    @api.model
    def _get_or_create_post(self, account, external_post_id, name, permalink=None):
        """A regular post is handled like a live: one session per post (ended posts are kept, not recreated)."""
        session = self.search([
            ("account_id", "=", account.id), ("source_type", "=", "post"), ("external_post_id", "=", external_post_id),
        ], limit=1)
        if session:
            return session
        name = (name or "").strip().replace("\n", " ")
        if len(name) > 60:
            name = name[:57].rstrip() + "..."
        return self.create({
            "name": name or self.env._("Post %s", fields.Datetime.now().strftime("%d/%m")),
            "account_id": account.id,
            "source_type": "post",
            "external_post_id": external_post_id,
            "permalink_url": permalink,
            "state": "live",
            "date_start": fields.Datetime.now(),
        })

    def action_open_console(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "livestream_console",
            "name": self.env._("Operator Console"),
            "params": {"session_id": self.id},
        }


class LivestreamSessionTag(models.Model):
    _name = "livestream.session.tag"
    _description = "Livestream Product Tag"
    _order = "session_id, code"

    session_id = fields.Many2one("livestream.session", required=True, ondelete="cascade", index=True)
    code = fields.Char(required=True)
    product_id = fields.Many2one("product.product", required=True)
    price_unit = fields.Float("Price", digits="Product Price")
    note = fields.Char()

    _session_code_uniq = models.Constraint(
        "UNIQUE(session_id, code)", "A tag code must be unique within a session.",
    )

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id and not self.price_unit:
            self.price_unit = self.product_id.lst_price
