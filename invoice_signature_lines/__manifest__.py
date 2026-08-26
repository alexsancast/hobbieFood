{
    'name': 'Invoice Signature Lines',
    'version': '19.0.1.0.0',
    'category': 'Hidden',
    'summary': 'Add "Entregado por" / "Recibido por" signature lines to the invoice report',
    'depends': ['account'],
    'data': [
        'views/report_invoice_signature.xml',
    ],
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
