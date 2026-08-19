# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    notification_status = fields.Selection([
        ('pending', 'Pending Validation'),
        ('validated', 'Validated'),
    ], string='Notification Status', default='pending', copy=False,
        help="Tracks notification lifecycle: pending approval notification on creation, non-intractable validated status once completed.")

    def _get_notification_recipients(self):
        """Collect notification recipients from operation type, source location hierarchy,
        and destination location hierarchy.
        """
        self.ensure_one()
        recipients = self.env['res.users']
        if self.picking_type_id:
            recipients |= self.picking_type_id.notification_user_ids

        # Source location and parent hierarchy
        loc = self.location_id
        while loc:
            recipients |= loc.responsible_user_ids
            loc = loc.location_id

        # Destination location and parent hierarchy
        dest_loc = self.location_dest_id
        while dest_loc:
            recipients |= dest_loc.responsible_user_ids
            dest_loc = dest_loc.location_id

        return recipients

    def _send_creation_notifications(self):
        """Send notifications (Chatter, Activity, Web Bus) on operation creation."""
        for picking in self:
            recipients = picking._get_notification_recipients()
            if not recipients:
                continue

            partner_ids = recipients.mapped('partner_id').ids
            src_name = picking.location_id.display_name if picking.location_id else _('N/A')
            dest_name = picking.location_dest_id.display_name if picking.location_dest_id else _('N/A')
            op_type_name = picking.picking_type_id.display_name if picking.picking_type_id else _('N/A')

            msg_body = _(
                "<strong>New Operation Created: %s</strong><br/>"
                "Operation Type: %s<br/>"
                "Source Location: %s<br/>"
                "Destination Location: %s<br/>"
                "Status: Pending Validation",
                picking.name, op_type_name, src_name, dest_name
            )

            # 1. Post Chatter message
            picking.message_post(
                body=msg_body,
                partner_ids=partner_ids,
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )

            # 2. Schedule Activity for recipients (Approval-style tracking)
            todo_activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            if todo_activity_type:
                picking_model = self.env.ref('stock.model_stock_picking', raise_if_not_found=False)
                if picking_model:
                    for user in recipients:
                        self.env['mail.activity'].sudo().create({
                            'activity_type_id': todo_activity_type.id,
                            'note': msg_body,
                            'summary': _('Operation Pending Validation: %s', picking.name),
                            'user_id': user.id,
                            'res_id': picking.id,
                            'res_model_id': picking_model.id,
                        })

            # 3. Real-time Web Desktop Bus Notification
            bus = self.env['bus.bus']
            bus_message = {
                'type': 'warning',
                'title': _('New Operation: %s', picking.name),
                'message': _('New transfer %s created (%s -> %s)', picking.name, src_name, dest_name),
                'sticky': False,
            }
            for partner in recipients.mapped('partner_id'):
                bus._sendone(partner, 'simple_notification', bus_message)

    def _send_validation_notifications(self):
        """Send notifications and mark pending activities as done when operation is validated."""
        for picking in self:
            recipients = picking._get_notification_recipients()

            # Mark module-generated activities as DONE
            picking_model_id = self.env.ref('stock.model_stock_picking', raise_if_not_found=False)
            if picking_model_id:
                activities = self.env['mail.activity'].sudo().search([
                    ('res_model_id', '=', picking_model_id.id),
                    ('res_id', '=', picking.id),
                ])
                if activities:
                    activities.action_done()

            if not recipients:
                continue

            partner_ids = recipients.mapped('partner_id').ids
            src_name = picking.location_id.display_name if picking.location_id else _('N/A')
            dest_name = picking.location_dest_id.display_name if picking.location_dest_id else _('N/A')

            msg_body = _(
                "<strong>Operation Validated: %s</strong><br/>"
                "Source Location: %s<br/>"
                "Destination Location: %s<br/>"
                "Status: Validated / Done",
                picking.name, src_name, dest_name
            )

            # 1. Chatter post
            picking.message_post(
                body=msg_body,
                partner_ids=partner_ids,
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )

            # 2. Real-time Web Desktop Bus Notification
            bus = self.env['bus.bus']
            bus_message = {
                'type': 'success',
                'title': _('Operation Validated: %s', picking.name),
                'message': _('Transfer %s has been validated (%s -> %s)', picking.name, src_name, dest_name),
                'sticky': False,
            }
            for partner in recipients.mapped('partner_id'):
                bus._sendone(partner, 'simple_notification', bus_message)

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        for picking in pickings:
            picking._send_creation_notifications()
        return pickings

    def _action_done(self):
        res = super()._action_done()
        for picking in self:
            picking.notification_status = 'validated'
            picking._send_validation_notifications()
        return res
