# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class StockLocation(models.Model):
    _inherit = 'stock.location'

    responsible_user_ids = fields.Many2many(
        'res.users',
        'stock_location_responsible_user_rel',
        'location_id',
        'user_id',
        string='Location Responsible Users',
        help='Users responsible for this location who will receive notifications for operations affecting this location.'
    )
