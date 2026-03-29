# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from dateutil.relativedelta import relativedelta
from markupsafe import Markup


class RentalMaintenance(models.Model):
    _name = 'rental.maintenance'
    _description = "Vehicle Maintenance Record"
    _order = "scheduled_date desc"
    _rec_name = "scheduled_date"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # Vehicle Info
    vehicle_id = fields.Many2one(
        "rental.vehicle", string="Vehicle", required=True
    )
    # Maintenance Details
    maintenance_type = fields.Selection(
        selection=[
            ("routine", "Routine"),
            ("repair", "Repair"),
            ("inspection", "Inspection"),
            ("cleaning", "Cleaning")
        ],
        string="Maintenance Type",
        required=True
    )
    description = fields.Text(string="Description", required=True)
    notes = fields.Text(string="Notes")
    # Dates & Scheduling
    scheduled_date = fields.Date(string="Scheduled Date", required=True)
    completed_date = fields.Date(string="Completed Date")
    next_service_date = fields.Date(string="Next Service Date")
    # Personnel & Costs
    mechanic_id = fields.Many2one(comodel_name="res.users", string="Mechanic")
    cost = fields.Float(string="Cost")
    # Vehicle Metrics
    mileage_at_service = fields.Float(string="Mileage at Service")
    next_service_mileage = fields.Float(string="Next Service Mileage")
    # State Tracking
    state = fields.Selection(
        selection=[
            ("scheduled", "Scheduled"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled")
        ],
        string="Status",
        default="scheduled"
    )
    active = fields.Boolean(default=True)

    def unlink(self):
        """
        Prevent deletion of maintenance records that are not completed.
        """
        if any(rental_maintenance.state != "completed" for rental_maintenance in self):
            raise UserError(_("You cannot delete a maintenance record if it is not completed."))
        return super().unlink()

    @api.constrains("next_service_date", "scheduled_date")
    def _check_service_date(self):
        """
        Ensure that the next service date is after the scheduled service date.
        """
        if self.env.context.get("install_mode"):
            return
        if self.filtered(
                lambda rm: rm.next_service_date and rm.scheduled_date and rm.next_service_date <= rm.scheduled_date):
            raise ValidationError(
                _("Please set the next service date after the scheduled service date.")
            )

    @api.constrains("completed_date", "scheduled_date")
    def _check_dates(self):
        """
        Ensure the completed date is not earlier than the scheduled service date.
        """
        if self.env.context.get("install_mode"):
            return
        if self.filtered(lambda rm: rm.completed_date and rm.scheduled_date and rm.completed_date < rm.scheduled_date):
            raise ValidationError(_("Please ensure the completed date is not earlier than the scheduled date."))

    @api.constrains("cost")
    def _check_cost(self):
        """
        Ensure the maintenance cost is non-negative.
        """
        if self.env.context.get("install_mode"):
            return
        if self.filtered(lambda rm: rm.cost and rm.cost < 0):
            raise ValidationError(
                _("Maintenance cost should not be negative. Please correct the value.")
            )

    @api.constrains("vehicle_id", "scheduled_date")
    def _check_maintenance_date(self):
        """
        Ensure scheduled maintenance does not overlap with any confirmed or active rental booking.
        """
        if self.env.context.get("install_mode"):
            return
        rental_booking_env = self.env["rental.booking"]
        for rental_maintenance in self.filtered(lambda rm: rm.vehicle_id and rm.scheduled_date):
            booking = rental_booking_env.search_count([
                ("vehicle_id", "=", rental_maintenance.vehicle_id.id),
                ("state", "in", ["confirmed", "active"]),
                ("pickup_date", "<=", rental_maintenance.scheduled_date),
                ("return_date", ">=", rental_maintenance.scheduled_date),
            ], limit=1)
            if booking > 0:
                raise ValidationError(
                    _("The scheduled maintenance date overlaps with an active or confirmed rental booking. Please select a different date.")
                )

    def action_initiate_maintenance(self):
        """
        Set the maintenance state to "in_progress" and mark the vehicle as under maintenance.
        """
        self.state = "in_progress"
        self.vehicle_id.status = "maintenance"

    def action_scheduled(self):
        """
        Set the maintenance state to "scheduled".
        """
        self.state = "scheduled"

    def action_complete(self):
        """
        Mark the maintenance as completed:
        - Update completed_date to today
        - Change state to "completed"
        - Set the vehicle status to "available"
        """
        self.update({"completed_date": fields.Date.today(), "state": "completed"})
        self.vehicle_id.status = "available"

    def action_cancel(self):
        """
        Cancel the maintenance by setting the state to "cancelled".
        """
        self.state = "cancelled"

    def _cron_proceed_routine_maintenance(self):
        """
        Cron job to schedule routine maintenance for vehicles.

        - Checks all available vehicles with mileage > 0 and not out of service.
        - Determines if routine maintenance is due based on:
            - Mileage since last service (>= 5000 km)
            - Time since last service or vehicle creation (>= 180 days)
        - If maintenance is due:
            - Schedules maintenance on next available date (after active bookings if any)
            - Sets next service date and next service mileage
            - Creates maintenance records in "routine" type
        """
        available_vehicles = self.env["rental.vehicle"].search([
            ("status", "!=", "out_of_service"),
            ("mileage", ">", 0)
        ])
        VehicleMaintenance = self.env["rental.maintenance"]
        RentalBooking = self.env["rental.booking"]
        vehicle_maintenance = VehicleMaintenance.search([
            ("vehicle_id", "in", available_vehicles.ids),
            ("completed_date", "!=", False),
            ("maintenance_type", "=", "routine"),
            ("state", "=", "completed")
        ])
        today = fields.Date.today()
        maintenance_vals = []

        for vehicle in available_vehicles:
            most_recent_maintenance = vehicle_maintenance.filtered_domain([
                ("vehicle_id", "=", vehicle.id),
            ]).sorted(key=lambda m: m.completed_date, reverse=True)

            if most_recent_maintenance:
                vehicle_mileage = (vehicle.mileage - most_recent_maintenance.mileage_at_service) >= 5000
                due_date = (today - most_recent_maintenance.completed_date).days >= 180
            else:
                vehicle_mileage = vehicle.mileage >= 5000
                due_date = (today - vehicle.create_date.date()).days >= 180

            if vehicle_mileage or due_date:
                active_bookings = RentalBooking.search([
                    ("vehicle_id", "=", vehicle.id),
                    ("pickup_date", "<=", today),
                    ("return_date", ">=", today),
                    ("state", "in", ["confirmed", "active"]),
                ], limit=1)
                scheduled_date = today
                if active_bookings:
                    scheduled_date = active_bookings.return_date + relativedelta(days=1)

                maintenance_vals.append({
                    "vehicle_id": vehicle.id,
                    "scheduled_date": scheduled_date,
                    "mileage_at_service": vehicle.mileage,
                    "next_service_date": scheduled_date + relativedelta(months=6),
                    "next_service_mileage": vehicle.mileage + 5000,
                    "maintenance_type": "routine",
                    "description": "Routine maintenance scheduled",
                })

        if maintenance_vals:
            VehicleMaintenance.create(maintenance_vals)

    def _cron_mileage_reminders(self):
        """
        Cron job to send mileage-based maintenance reminders.

        - Checks all vehicles with mileage > 0.
        - Finds scheduled maintenance where next_service_mileage is within
          0–500 miles from the current mileage.
        - Sends a notification on the maintenance record if no reminder notes exist.
        """
        vehicles = self.env["rental.vehicle"].search([("mileage", ">", 0)])
        rental_maintenance = self.env["rental.maintenance"].search([
            ("vehicle_id", "in", vehicles.ids),
            ("state", "=", "scheduled"),
            ("next_service_mileage", "!=", 0),
        ], limit=1)

        for vehicle in vehicles:
            next_maintenance = rental_maintenance.filtered_domain([
                ("vehicle_id", "=", vehicle.id),
                ("next_service_mileage", ">=", vehicle.mileage),
                ("next_service_mileage", "<=", vehicle.mileage + 500),
            ])
            if not next_maintenance:
                continue

            next_maintenance = next_maintenance[0]
            if next_maintenance and not next_maintenance.notes:
                message = _(
                    "<b>Maintenance Reminder</b><br/><br/>"
                    "The vehicle <b>%(vehicle)s</b> (current mileage: <b>%(current)d</b> miles) "
                    "is approaching its next scheduled maintenance at <b>%(due)d</b> miles."
                    "%(date_line)s<br/><br/>"
                    "Please ensure that the necessary service is scheduled and completed on time."
                ) % {
                      "vehicle": vehicle.name,
                      "current": vehicle.mileage,
                      "due": next_maintenance.next_service_mileage,
                      "date_line": (
                          "<br/>Scheduled maintenance date: <b>%s</b>" % next_maintenance.scheduled_date.strftime(
                              "%d-%m-%Y")
                          if next_maintenance.scheduled_date else ""
                      ),
                }

                next_maintenance.message_post(
                    subject=_("Upcoming Maintenance Reminder"),
                    body=Markup(message),
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                )

    def _cron_update_maintenance_status(self):
        """
        Cron job to synchronize maintenance state with vehicle status.

        - Marks vehicles as "maintenance" and maintenance records as "in_progress"
          if the scheduled date is due and the vehicle is not already under maintenance.
        - Marks vehicles as "available" and maintenance records as "completed"
          if the completed date is reached and the vehicle was under maintenance.
        """
        today = fields.Date.today()

        # Update scheduled/in-progress maintenance
        scheduled_maintenances = self.search([
            ("scheduled_date", "<=", today),
            ("state", "in", ["scheduled", "in_progress"]),
            ("vehicle_id.status", "!=", "maintenance"),
        ])
        scheduled_maintenances.vehicle_id.status = "maintenance"
        scheduled_maintenances.state = "in_progress"

        # Update completed/cancelled maintenance
        completed_maintenances = self.search([
            ("completed_date", "<=", today),
            ("state", "in", ["completed", "cancelled"]),
            ("vehicle_id.status", "=", "maintenance"),
        ])
        completed_maintenances.vehicle_id.status = "available"
        completed_maintenances.state = "completed"
