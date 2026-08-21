{
    'name': 'Hide Discuss',
    'version': '19.0.1.0.0',
    'category': 'Hidden',
    'summary': 'Hide the Discuss menu and systray icon',
    'depends': ['mail'],
    'data': [
        'views/mail_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hide_discuss/static/src/js/messaging_menu_patch.js',
            'hide_discuss/static/src/xml/messaging_menu_patch.xml',
        ],
    },
    'license': 'LGPL-3',
}
