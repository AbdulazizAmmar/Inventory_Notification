{
    'name': 'Inventory Operation Notifications',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Location and Operation Type based notifications for Inventory transfers',
    'description': """
Inventory Operation Notifications
=================================
Provides operation-type and location-based notifications for stock transfers in Odoo 19:
- Assign Warehouse Managers to Operation Types.
- Assign Responsible Users to Stock Locations.
- Send creation & validation notifications (Chatter, Mail Activity, Web Desktop Bus) to all relevant managers & location users.
- Support Receipts, Deliveries, and Internal Transfers across virtual and physical locations.
- Approval-style activity logging marked done automatically upon operation validation.
    """,
    'author': 'Antigravity / Zack',
    'license': 'LGPL-3',
    'depends': ['stock', 'mail'],
    'data': [
        'views/stock_picking_type_views.xml',
        'views/stock_location_views.xml',
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': False,
}
