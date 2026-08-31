{
    'name': 'L10N DO Tax Totals Fix',
    'version': '19.0.1.0.0',
    'category': 'Hidden',
    'summary': 'Fix KeyError crash on Sale/Purchase order PDF printing caused by l10n_do_accounting assuming an invoice record',
    'depends': ['l10n_do_accounting', 'sale', 'purchase'],
    'data': [
        'views/document_tax_totals_fix.xml',
    ],
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
