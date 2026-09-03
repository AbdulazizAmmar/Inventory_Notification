# Part of Odoo. See LICENSE file for full copyright and licensing details.

from markupsafe import Markup

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
        destination location hierarchy, and move line locations.
        Ensures strict deduplication across operation types and locations.
        """
        self.ensure_one()
        recipients = self.env['res.users']

        # 1. Operation Type Managers
        if self.picking_type_id:
            recipients |= self.picking_type_id.notification_user_ids

        # 2. Collect all locations involved in the picking
        locations = self.env['stock.location']
        if self.location_id:
            locations |= self.location_id
        if self.location_dest_id:
            locations |= self.location_dest_id

        if self.move_ids:
            locations |= self.move_ids.mapped('location_id')
            locations |= self.move_ids.mapped('location_dest_id')

        if self.move_line_ids:
            locations |= self.move_line_ids.mapped('location_id')
            locations |= self.move_line_ids.mapped('location_dest_id')

        # 3. Traverse parent hierarchy for all collected locations
        all_locations = self.env['stock.location']
        for loc in locations:
            curr_loc = loc
            while curr_loc:
                all_locations |= curr_loc
                curr_loc = curr_loc.location_id

        # 4. Add Responsible Users from all locations in the hierarchy
        for loc in all_locations:
            if loc.responsible_user_ids:
                recipients |= loc.responsible_user_ids

        return recipients

    def _send_creation_notifications(self):
        """Send notifications (Chatter, Activity, Web Bus) on operation creation.
        Ensures each user receives exactly one activity and notification regardless of overlap.
        """
        for picking in self:
            recipients = picking._get_notification_recipients()
            if not recipients:
                continue

            src_name = picking.location_id.display_name if picking.location_id else _('N/A')
            dest_name = picking.location_dest_id.display_name if picking.location_dest_id else _('N/A')
            op_type_name = picking.picking_type_id.display_name if picking.picking_type_id else _('N/A')

            msg_body = Markup(
                "<strong>New Operation Created: %s</strong><br/>"
                "Operation Type: %s<br/>"
                "Source Location: %s<br/>"
                "Destination Location: %s<br/>"
                "Status: Pending Validation"
            ) % (picking.name, op_type_name, src_name, dest_name)

            todo_activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            picking_model = self.env.ref('stock.model_stock_picking', raise_if_not_found=False)

            users_to_notify = self.env['res.users']
            for user in recipients:
                if picking_model and todo_activity_type:
                    existing_activity = self.env['mail.activity'].sudo().search([
                        ('res_model_id', '=', picking_model.id),
                        ('res_id', '=', picking.id),
                        ('user_id', '=', user.id),
                    ], limit=1)
                    if not existing_activity:
                        users_to_notify |= user
                        self.env['mail.activity'].sudo().create({
                            'activity_type_id': todo_activity_type.id,
                            'note': msg_body,
                            'summary': _('Operation Pending Validation: %s', picking.name),
                            'user_id': user.id,
                            'res_id': picking.id,
                            'res_model_id': picking_model.id,
                        })
                else:
                    users_to_notify |= user

            if users_to_notify:
                notify_partner_ids = list(set(users_to_notify.mapped('partner_id').ids))

                # 1. Post Chatter message
                picking.message_post(
                    body=msg_body,
                    partner_ids=notify_partner_ids,
                    message_type='notification',
                    subtype_xmlid='mail.mt_note'
                )

                # 2. Real-time Web Desktop Bus Notification
                bus = self.env['bus.bus']
                bus_message = {
                    'type': 'warning',
                    'title': _('New Operation: %s', picking.name),
                    'message': _('New transfer %s created (%s -> %s)', picking.name, src_name, dest_name),
                    'sticky': False,
                }
                for partner in users_to_notify.mapped('partner_id'):
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

            partner_ids = list(set(recipients.mapped('partner_id').ids))
            src_name = picking.location_id.display_name if picking.location_id else _('N/A')
            dest_name = picking.location_dest_id.display_name if picking.location_dest_id else _('N/A')

            msg_body = Markup(
                "<strong>Operation Validated: %s</strong><br/>"
                "Source Location: %s<br/>"
                "Destination Location: %s<br/>"
                "Status: Validated / Done"
            ) % (picking.name, src_name, dest_name)

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

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('location_id', 'location_dest_id', 'picking_type_id', 'move_ids', 'move_ids_without_package', 'move_line_ids')):
            for picking in self.filtered(lambda p: p.notification_status == 'pending'):
                picking._send_creation_notifications()
        return res

    def _action_done(self):
        res = super()._action_done()
        for picking in self:
            picking.notification_status = 'validated'
            picking._send_validation_notifications()
        return res

