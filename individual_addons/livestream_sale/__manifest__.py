{
    "name": "Livestream Sale",
    "version": "20.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Sell from social livestreams: comments, chat, orders and verified deposits",
    "depends": ["sale_management", "mail", "bus", "account_payment", "l10n_vn"],
    "data": [
        "security/livestream_security.xml",
        "security/ir.access.csv",
        "data/ir_cron.xml",
        "data/ir_sequence.xml",
        "views/livestream_account_views.xml",
        "views/livestream_session_views.xml",
        "views/livestream_comment_views.xml",
        "views/sale_order_views.xml",
        "wizard/livestream_unmatch_wizard_views.xml",
        "views/livestream_bank_transaction_views.xml",
        "data/client_action.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "livestream_sale/static/src/**/*",
        ],
    },
    "license": "LGPL-3",
    "application": True,
}
