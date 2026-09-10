{
    'name': 'Product Company Isolation',
    'version': '19.0.1.0.0',
    'category': 'Hidden',
    'summary': 'Assign the active company to new products automatically',
    'description': (
        'Products created without an explicit company were left as "global" '
        '(company_id empty), so the standard multi-company product rule '
        'showed them in every company. This module defaults company_id to '
        'the active company on creation, so new products stay scoped to the '
        'company that created them.'
    ),
    'depends': ['product'],
    'data': [],
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
