# -*- coding: utf-8 -*-
{
    'name': 'Order Receipt Customization',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Remove the "Powered by Odoo" branding, replace the invoice QR with an Instagram QR, and enlarge/center the printed ticket',
    'description': """Removes the hardcoded "Powered by Odoo" footer and the
    "Need an invoice?" link/QR/code block from the Point of Sale
    printed/customer receipt, replacing it with a QR code linking to the
    Instagram page, and prints the ticket larger and centered on the page.""",
    'author': 'Alex Sancas',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'order_receipt/static/src/app/screens/receipt_screen/receipt/order_receipt.xml',
            'order_receipt/static/src/app/screens/receipt_screen/receipt_screen.scss',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
