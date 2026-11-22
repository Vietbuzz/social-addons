{
    "name": "Livestream Sale - SePay",
    "version": "20.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Receive bank transfers from SePay and match them to livestream orders",
    "depends": ["livestream_sale", "payment"],
    "data": [
        "data/payment_provider_data.xml",
        "data/payment_method_data.xml",
        "data/ir_cron.xml",
        "views/payment_provider_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "license": "LGPL-3",
}
