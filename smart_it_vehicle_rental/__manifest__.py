# -*- coding: utf-8 -*-
{
    'name': "SmartIT: Vehicle Rental Management",
    'summary': "Manage vehicle rentals, bookings, maintenance, and automated notifications.",
    'description': """
Vehicle Rental Management
=========================

Core Features:
- Manage vehicle bookings with pickup and return details, rental duration, and pricing.
- Track vehicle mileage and schedule routine or corrective maintenance.
- Maintain vehicle details including brand, model, category, fuel type, and VIN.
- Apply late return fees and manage deposits automatically.
- Send automated reminders for upcoming maintenance based on mileage or date.
- Support for posting messages and notifications for bookings and maintenance.
- Compute and update vehicle availability and status in real-time.

Designed for rental businesses to efficiently handle fleet operations and customer management.
    """,
    'category': 'Services/Vehicle Rental',
    'author': "Viren Patel",
    'website': "https://www.odoo.com",
    'version': '18.0.1.0.0',
    'depends': ['base', 'mail'],
    'license': 'LGPL-3',
    'data': [
        'data/ir_sequence_data.xml',
        'data/ir_cron.xml',
        'security/ir.model.access.csv',
        'views/rental_booking_views.xml',
        'views/rental_maintenance_views.xml',
        'views/rental_vehicle_views.xml',
        'views/res_partner_views.xml',
        'views/menuitems.xml',
    ],
    'demo': [
        'data/demo_data.xml',
    ],
    'icon': '/smart_it_vehicle_rental/static/description/icon.jpg',
    'installable': True,
    'application': True,
    'auto_install': False,
}
