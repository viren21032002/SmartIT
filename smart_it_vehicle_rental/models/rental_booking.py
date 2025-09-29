# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError, UserError
from datetime import timedelta
from markupsafe import Markup

LICENSE_NO_LN = 8
LATE_FEE_PER_DAY = 50


class RentalBooking(models.Model):
    _name = 'rental.booking'
    _description = "Customer Rental Booking"
    _order = "pickup_date desc"
    _rec_name = "booking_number"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # Identifiers
    booking_number = fields.Char(
        string="Booking Number",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New")
    )
    # Customer & Vehicle Info
    customer_id = fields.Many2one(comodel_name="res.partner", string="Customer", required=True)
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Booking Person",
        default=lambda self: self.env.user.id,
        required=True,
    )
    vehicle_id = fields.Many2one(
        comodel_name="rental.vehicle",
        string="Vehicle", required=True
    )
    # This is the optional field
    insurance_required = fields.Boolean(string="Insurance Required")
    # Rental Period
    pickup_date = fields.Datetime(string="Pickup Date", required=True)
    return_date = fields.Datetime(string="Expected Return Date", required=True)
    actual_return_date = fields.Datetime(string="Actual Return Date")
    rental_days = fields.Integer(string="Rental Days", compute="_compute_rental_days", store=True)
    # Locations
    pickup_location = fields.Char(string="Pickup Location", required=True)
    return_location = fields.Char(string="Return Location")
    # Financials
    daily_rate = fields.Float(
        string="Daily Rate",
        compute="_compute_daily_rate",
        inverse="_inverse_daily_rate",
        store=True, readonly=False
    )
    base_amount = fields.Float(string="Base Amount", compute="_compute_base_amount", store=True)
    extra_fees = fields.Float(string="Extra Fees", compute="_compute_total_amount", store=True)
    total_amount = fields.Float(string="Total Amount", compute="_compute_total_amount", store=True)
    deposit_amount = fields.Float(string="Deposit Amount", required=True)
    # Documents
    driver_license = fields.Char(string="Driver License", required=True)
    additional_drivers = fields.Text(string="Additional Drivers")
    special_requests = fields.Text(string="Special Requests")
    # Vehicle Condition
    pickup_mileage = fields.Float(string="Pickup Mileage")
    return_mileage = fields.Float(string="Return Mileage")
    fuel_level_pickup = fields.Selection(selection=[
        ("empty", "Empty"),
        ("quarter", "Quarter"),
        ("half", "Half"),
        ("three_quarter", "Three Quarter"),
        ("full", "Full"),
    ], string="Fuel level at pick-up")
    fuel_level_return = fields.Selection(selection=[
        ("empty", "Empty"),
        ("quarter", "Quarter"),
        ("half", "Half"),
        ("three_quarter", "Three Quarter"),
        ("full", "Full"),
    ], string="Fuel level at return")
    # Tracking
    state = fields.Selection(selection=[
        ("draft", "Draft"),
        ("confirmed", "Confirmed"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ], string="Status", default="draft")
    is_apply_delayed_fair = fields.Boolean(default=False, copy=False, string="Late Fee Applied",
                                         help="Indicates if a late fee has been applied to this booking.")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("booking_number_unique", "unique(booking_number)", "Booking number must be unique."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """
        Assign a sequence number to each new rental booking
        if "booking_number" is set to "New".
        """
        IrSequence = self.env.ref("smart_it_vehicle_rental.ir_seq_rental_booking")
        for vals in vals_list:
            if vals.get("booking_number", "New") == "New":
                vals["booking_number"] = IrSequence.next_by_code("rental.booking") or "New"
        return super().create(vals_list)

    def unlink(self):
        """
        Prevent deletion of rental bookings unless they are in draft state.
        """
        if any(rental_booking.state != "draft" for rental_booking in self):
            raise UserError(_("You cannot delete a booking record if the state is not draft."))
        return super().unlink()

    def write(self, vals):
        """
        Update booking state and vehicle status based on mileage and return data.
        - Confirmed → Active when pickup mileage is recorded.
        - Active → Completed when return mileage and return date are set.
        """

        # Todo : This logic can be adjusted from the wizard and make this flow better
        # As currently the requirement is about to record the change that's why used write.

        for rental_booking in self:
            mileage_at_pickup = vals.get("pickup_mileage") or rental_booking.pickup_mileage or 0

            # Confirmed → Active
            if rental_booking.state == "confirmed" and mileage_at_pickup > 0 and "state" not in vals:
                vals["state"] = "active"
                rental_booking.vehicle_id.update({"status": "rented"})
                rental_booking.message_post(
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                    body=Markup(_(
                        "The booking for vehicle <b>%(vehicle)s</b> has started.<br/>"
                        "Customer: %(customer)s<br/>"
                        "Pickup mileage: %(mileage)d"
                    )) % {
                             "vehicle": rental_booking.vehicle_id.name,
                             "customer": rental_booking.customer_id.name,
                             "mileage": mileage_at_pickup,
                         })

            # Active → Completed
            actual_return_date = vals.get("actual_return_date") or (
                        rental_booking.actual_return_date and rental_booking.actual_return_date.strftime(
                    "%d-%m-%Y")) or False
            mileage_at_return = vals.get("return_mileage") or rental_booking.return_mileage or 0

            if "state" not in vals and actual_return_date and rental_booking.state == "active" and mileage_at_return > 0:
                vals["state"] = "completed"
                rental_booking.vehicle_id.update({
                    "status": "available",
                    "mileage": mileage_at_return,
                })
                rental_booking.message_post(
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                    body=Markup(_(
                        "The booking for vehicle <b>%(vehicle)s</b> is now completed.<br/>"
                        "Customer: %(customer)s<br/>"
                        "Return mileage: %(mileage)d<br/>"
                        "Return date: %(date)s"
                    )) % {
                             "vehicle": rental_booking.vehicle_id.name,
                             "customer": rental_booking.customer_id.name,
                             "mileage": mileage_at_return,
                             "date": actual_return_date,
                         })

        return super().write(vals)

    @api.constrains("return_mileage", "pickup_mileage", "state")
    def _check_vehicle_mileage_details(self):
        """
        1 > Ensure mileage values are non-negative
        2 > Ensure return mileage is not less than pickup mileage when rental is completed
        """
        if self.env.context.get("install_mode"):
            return

        for rental_booking in self:
            if rental_booking.return_mileage < 0 or rental_booking.pickup_mileage < 0:
                raise ValidationError(_("Mileage must be a positive number."))
            if rental_booking.state == "completed" and not (rental_booking.return_mileage >= rental_booking.pickup_mileage):
                raise ValidationError(
                    _("Return mileage must be greater than or equal to pickup mileage when the rental is completed.")
                )

    @api.constrains("pickup_date", "return_date")
    def _check_rental_period(self):
        """
        Note : Skip validation during module installation or updates
        1 > Return date must be after pickup date.
        2 > Minimum rental period: 1 day.
        3 > Maximum rental period: 30 days.
        """
        if self.env.context.get("install_mode"):
            return

        for rental_booking in self.filtered(lambda booking: booking.pickup_date and booking.return_date):
            pickup_date = rental_booking.pickup_date
            return_date = rental_booking.return_date
            duration = return_date - pickup_date
            if return_date <= pickup_date:
                raise ValidationError(_("Return date must be after pickup date."))
            if pickup_date < fields.Datetime.now() + timedelta(hours=1):
                raise ValidationError(_("Please choose a pickup date that is at least one hour in the future."))
            if duration < timedelta(days=1):
                raise ValidationError(_("Minimum rental period: 1 day"))
            if duration > timedelta(days=30):
                raise ValidationError(_("Maximum rental period: 30 days."))

    @api.constrains("driver_license")
    def _check_driver_license_length(self):
        """
        Ensure driver license number has at least LICENSE_NO_LN characters.
        """
        if self.env.context.get("install_mode"):
            return
        if self.filtered(lambda rb: not rb.driver_license or len(rb.driver_license.strip()) < LICENSE_NO_LN):
            raise ValidationError(
                _("Driver license must be at least %s characters.") % LICENSE_NO_LN
            )

    @api.depends("booking_number", "vehicle_id.name")
    def _compute_display_name(self):
        """
        Compute display name as "booking_number - vehicle_name".
        """
        for rental_booking in self:
            display_name = "/"
            if (booking_number := rental_booking.booking_number) and (vehicle_name := rental_booking.vehicle_id.name):
                display_name = "%s - %s" % (booking_number, vehicle_name)
            rental_booking.display_name = display_name

    @api.depends("pickup_date", "return_date")
    def _compute_rental_days(self):
        """
        Compute the number of planned rental days for each booking.
        Adds 1 day to include both pickup and return dates.
        Bookings missing either date have rental_days set to 0.
        """
        rental_booking_records = self.filtered_domain([
            ("pickup_date", "!=", False),
            ("return_date", "!=", False),
        ])
        for rental_booking in rental_booking_records:
            rental_booking.rental_days = max(
                (rental_booking.return_date.date() - rental_booking.pickup_date.date()).days, 0) + 1
        (self - rental_booking_records).rental_days = 0

    @api.depends(
        "base_amount", "extra_fees", "rental_days", "fuel_level_pickup", "fuel_level_return",
        "additional_drivers", "customer_id.birthdate_date", "insurance_required", "actual_return_date"
    )
    def _compute_total_amount(self):
        """
        Compute the total rental amount including:
        - Base amount
        - Late return fees
        - Fuel refill fees
        - Extra driver charges
        - Young driver surcharge (age < 25)
        - Insurance fees
        """
        fuel_maps = ["empty", "quarter", "half", "three_quarter", "full"]
        for rental_booking in self:
            extra_fees = 0
            rental_days = rental_booking.rental_days

            if (
                not rental_booking.is_apply_delayed_fair
                and rental_booking.actual_return_date
                and rental_booking.return_date
                and rental_booking.actual_return_date > rental_booking.return_date
            ):
                difference = rental_booking.actual_return_date - rental_booking.return_date
                late_days = difference.days
                if difference.seconds > 0 or difference.microseconds > 0:
                    late_days += 1
                if late_days <= 0:
                    continue
                extra_fees += late_days * LATE_FEE_PER_DAY

            if fuel_maps.index(rental_booking.fuel_level_pickup or "empty") > fuel_maps.index(
                    rental_booking.fuel_level_return or "empty"
            ):
                extra_fees += 30

            if additional_drivers := rental_booking.additional_drivers:
                extra_fees += rental_booking.get_extra_driver_rate(additional_drivers, rental_days)

            if birthdate_date := rental_booking.customer_id.birthdate_date:
                age = relativedelta(fields.Date.today(), birthdate_date).years
                extra_fees += (age < 25 and rental_days * 15) or 0

            if rental_booking.insurance_required:
                extra_fees += rental_days * 25

            rental_booking.extra_fees = extra_fees
            rental_booking.total_amount = rental_booking.base_amount + extra_fees

    @api.depends("vehicle_id.daily_rate")
    def _compute_daily_rate(self):
        """
        Compute or update the daily rental rate for the booking.
        - In draft state, use vehicle's daily rate if not set or default to 1.
        """
        for rental_booking in self:
            daily_rate = rental_booking.daily_rate
            if rental_booking.state == "draft":
                daily_rate = (not daily_rate and 1) or (daily_rate == 1 and rental_booking.vehicle_id.daily_rate) or 1
            rental_booking.daily_rate = daily_rate

    def _inverse_daily_rate(self):
        """
        Ensure daily_rate is at least 1 for bookings where it is not set.
        """
        if invalid_records := self.filtered(lambda rb: not rb.daily_rate):
            invalid_records.daily_rate = 1

    @api.depends("rental_days", "daily_rate", "extra_fees")
    def _compute_base_amount(self):
        """
        Compute the base amount for each booking as rental_days × daily_rate.
        Bookings missing rental_days or daily_rate will have total_amount set to 0.
        """
        rental_bookings = self.filtered_domain([
            ("rental_days", "!=", False),
            ("daily_rate", "!=", False)
        ])
        for rental_booking in rental_bookings:
            rental_booking.base_amount = rental_booking.rental_days * rental_booking.daily_rate
        (self - rental_bookings).total_amount = 0

    def get_extra_driver_rate(self, additional_drivers, rental_days):
        self.ensure_one()
        # Todo : It can be improved as we can use m2m field instead of using text field.
        additional_drivers_list = additional_drivers.split(",")
        return len(additional_drivers_list) * rental_days * 10

    def action_confirm(self):
        """
        Confirm the rental booking after validating all required information:
        - Pickup mileage, fuel level, pickup date, and location must be set.
        - Vehicle must be available for the selected period.
        - Deposit must be at least 20% of the base amount.

        Upon confirmation:
        - Booking state is set to 'confirmed'.
        - Vehicle status is updated to 'rented'.
        - A message is posted on the chatter summarizing the booking.
        """
        for rental_booking in self:
            if not rental_booking.fuel_level_pickup or not rental_booking.pickup_date or not rental_booking.pickup_location:
                raise UserError(
                    _("Please complete all required pick-up information: fuel level, pick-up date, and location.")
                )

            if not rental_booking._check_availability(rental_booking.vehicle_id,
                                                      rental_booking.pickup_date,
                                                      rental_booking.return_date):
                raise UserError(_("Vehicle is not available for the selected period."))

            if (rental_booking.deposit_amount <= 0 or
                    (rental_booking.base_amount and rental_booking.deposit_amount < 0.2 * rental_booking.base_amount)):
                raise UserError(
                    _(f"Deposit must be at least 20% of base amount '{rental_booking.base_amount}' to confirm the booking.")
                )

            rental_booking.state = "confirmed"
            rental_booking.vehicle_id.update({"status": "rented"})
            rental_booking.message_post(
                message_type="comment",
                subtype_xmlid="mail.mt_note",
                body=Markup(_(
                    "Booking for vehicle <b>%(vehicle)s</b> has been confirmed.<br/>"
                    "Customer: %(customer)s<br/>"
                    "Pickup Date: %(pickup)s<br/>"
                    "Return Date: %(return)s<br/>"
                    "Deposit: %(deposit).2f"
                ) % {
                    "vehicle": rental_booking.vehicle_id.name,
                    "customer": rental_booking.customer_id.name,
                    "pickup": rental_booking.pickup_date.strftime("%d-%m-%Y"),
                    "return": rental_booking.return_date.strftime("%d-%m-%Y"),
                    "deposit": rental_booking.deposit_amount,
                })
            )

    def action_draft(self):
        """
        Reset the booking to draft state and set the vehicle status to "available".
        A message is posted in the chatter indicating the reset.
        """
        self.state = "draft"
        self.vehicle_id.status = "available"
        for rental_booking in self:
            rental_booking.message_post(
                message_type="comment",
                subtype_xmlid="mail.mt_note",
                body=_("The booking for vehicle %(vehicle)s has been reset to draft.") % {
                    "vehicle": rental_booking.vehicle_id.name
                }
            )

    def action_cancel(self):
        """
        Cancel the booking and set the vehicle status to "available".
        A message is posted in the chatter indicating the cancellation.
        """
        self.state = "cancelled"
        self.vehicle_id.status = "available"
        for rental_booking in self:
            rental_booking.message_post(
                message_type="comment",
                subtype_xmlid="mail.mt_note",
                body=_("The booking for vehicle %(vehicle)s has been cancelled.") % {
                    "vehicle": rental_booking.vehicle_id.name
                }
            )

    def _check_availability(self, vehicle, pickup_date, return_date):
        """
        Check if the vehicle is available for the given period.

        Considers:
        - Vehicle status (must not be in maintenance or out_of_service)
        - Conflicting bookings in "confirmed" or "active" state
        - Overlapping maintenance schedules

        Returns:
            bool: True if vehicle is available, False otherwise.
        """
        self.ensure_one()
        vehicle.ensure_one()

        if not vehicle or not pickup_date or not return_date or vehicle.status in ["maintenance", "out_of_service"]:
            return False

        # Check for conflicting bookings
        conflicting_booking = self.env["rental.booking"].search_count([
            ("vehicle_id", "=", vehicle.id),
            ("pickup_date", "<=", return_date),
            ("return_date", ">=", pickup_date),
            ("state", "in", ["confirmed", "active"]),
            ("id", "!=", self.id)
        ], limit=1)
        if conflicting_booking > 0:
            return False

        # Check active maintenance schedules
        conflicting_maintenance = self.env["rental.maintenance"].search_count([
            ("vehicle_id", "=", vehicle.id),
            ("scheduled_date", "<=", return_date.date()),
            ("next_service_date", ">=", pickup_date.date()),
            ("state", "in", ["scheduled", "in_progress"]),
        ], limit=1)
        if conflicting_maintenance > 0:
            return False

        return True

    def _cron_late_return_process(self):
        """
        Cron job to process late vehicle returns.

        For active or completed bookings where the actual return date exceeds
        the planned return date and late fees have not yet been applied:
        - Calculates late days and late fee (LATE_FEE_PER_DAY per day)
        - Updates `total_amount` and `deposit_amount`
        - Marks `is_apply_delayed_fair` as True
        - Posts a notification message to the chatter and relevant partners
        """
        active_rental_bookings = self.search([
            ("actual_return_date", "!=", False),
            ("return_date", "!=", False),
            ("state", "in", ["active", "completed"]),
            ("is_apply_delayed_fair", "=", False),
        ])

        for rental_booking in active_rental_bookings:
            if rental_booking.actual_return_date <= rental_booking.return_date:
                continue

            difference = rental_booking.actual_return_date - rental_booking.return_date
            late_days = difference.days
            if late_days <= 0:
                continue

            late_fee = late_days * LATE_FEE_PER_DAY
            rental_booking.update({
                "is_apply_delayed_fair": True,
                "total_amount": rental_booking.total_amount + late_fee,
                "deposit_amount": rental_booking.deposit_amount + late_fee,
            })

            message = _(
                "<b>Late Return Detected</b><br/>"
                "Vehicle: <b>%(vehicle)s</b><br/>"
                "Customer: %(customer)s<br/>"
                "Expected return date: <b>%(due)s</b><br/>"
                "Actual return date: <b>%(actual)s</b><br/>"
                "Days late: <b>%(days)d</b><br/>"
                "Hypothetical late fee: <b>$%(fee).2f</b>"
            ) % {
                  "vehicle": rental_booking.vehicle_id.name,
                  "customer": rental_booking.customer_id.name,
                  "due": rental_booking.return_date.strftime("%d-%m-%Y"),
                  "actual": rental_booking.actual_return_date.strftime("%d-%m-%Y"),
                  "days": late_days,
                  "fee": late_fee,
            }

            rental_booking.message_post(
                subject=_("Late Return Notification"),
                body=Markup(message),
                partner_ids=[
                    rental_booking.customer_id.id,
                    rental_booking.user_id.partner_id.id
                ],
                message_type="notification",
                subtype_xmlid="mail.mt_note",
                email_layout_xmlid="mail.mail_notification_light",
            )
