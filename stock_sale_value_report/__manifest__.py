{
    'name': 'Stock Report Sale Value',
    'version': '19.0.1.0.0',
    'category': 'Hidden',
    'summary': 'Add "Precio Venta" / "Valor Total" (sale price based) columns to Inventory > Reporting > Stock',
    'depends': ['stock_account'],
    'data': [
        'views/product_stock_tree.xml',
    ],
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
