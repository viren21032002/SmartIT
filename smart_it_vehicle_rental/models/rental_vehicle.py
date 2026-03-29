# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class RentalVehicle(models.Model):
    _name = 'rental.vehicle'
    _description = "Vehicle Inventory Management"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # Fields Definition
    name = fields.Char(string="License plate/Vehicle Number", required=True)
    brand = fields.Char(string="Vehicle Brand", required=True)
    model = fields.Char(string="Vehicle Model", required=True)
    year = fields.Integer(string="Manufacturing Year", required=True)
    category = fields.Selection(selection=[
        ("economy", "Economy"),
        ("compact", "Compact"),
        ("midsize", "Mid-size"),
        ("luxury", "Luxury"),
        ("suv", "SUV"),
        ("truck", "Truck")
    ], string="Vehicle Category", required=True)
    color = fields.Char(string="Color", required=True)
    seats = fields.Integer(string="No of seats", required=True)
    fuel_type = fields.Selection(selection=[
        ("gasoline", "Gasoline"),
        ("diesel", "Diesel"),
        ("hybrid", "Hybrid"),
        ("electric", "Electric")
    ], string="Fuel Type", required=True)
    transmission = fields.Selection(selection=[
        ("manual", "Manual"),
        ("automatic", "Automatic"),
    ], string="Transmission", required=True)
    daily_rate = fields.Float(string="Daily Rate", required=True)
    mileage = fields.Float(string="Mileage", required=True)
    status = fields.Selection(selection=[
        ("available", "Available"),
        ("rented", "Rented"),
        ("maintenance", "Maintenance"),
        ("out_of_service", "Out of Service"),
    ], string="Status", default="available")
    vin_number = fields.Char(string="VIN Number", required=True)
    rental_ids = fields.One2many(
        comodel_name="rental.booking",
        inverse_name="vehicle_id",
        string="Rental Bookings"
    )
    maintenance_ids = fields.One2many(
        comodel_name="rental.maintenance",
        inverse_name="vehicle_id",
        string="Maintenance Records"
    )
    total_rentals = fields.Integer(
        string="Total Rentals(Completed)", compute="_compute_total_rentals", store=True
    )
    total_revenue = fields.Float(
        string="Total Revenue", compute="_compute_total_revenue", store=True
    )
    active = fields.Boolean(default=True)

    def unlink(self):
        if any(rental_vehicle.maintenance_ids or rental_vehicle.rental_ids for rental_vehicle in self):
            raise UserError(_("You cannot delete vehicle which has a rental bookings and maintenance records."
                              "You can archive it instead."))
        return super().unlink()

    @api.constrains("vin_number")
    def _check_vin_number(self):
        """
        Ensure that each vehicle has a unique VIN number.
        Raises a ValidationError if a duplicate VIN is found.
        """
        if self.env.context.get("install_mode"):
            return

        for rental_vehicle in self.filtered(lambda v: v.vin_number):
            exists = self.search_count([
                ("vin_number", "=", rental_vehicle.vin_number),
                ("id", "!=", rental_vehicle.id)
            ], limit=1)
            if exists > 0:
                raise ValidationError(
                    _("A vehicle with VIN '%s' already exists.") % rental_vehicle.vin_number
                )

    @api.depends("name", "brand", "model", "color")
    def _compute_display_name(self):
        """
        Compute a readable display name for the vehicle combining:
        - Name
        - Brand
        - Model
        - Color (in brackets)
        Example: "Vehicle1 - Toyota - Camry[Red]"
        """
        for rental_vehicle in self:
            display_name = rental_vehicle.name
            if (brand := rental_vehicle.brand) and (model := rental_vehicle.model) and (color := rental_vehicle.color):
                display_name = "%s - %s - %s" % (display_name, brand, model + f"[{color}]")
            rental_vehicle.display_name = display_name

    @api.depends("rental_ids.state")
    def _compute_total_rentals(self):
        RentalENV = self.env["rental.booking"]
        for rental_vehicle in self:
            # Used search_count.... why?
            # Only record counts needed that's why....
            rental_vehicle.total_rentals = RentalENV.search_count([
                ("vehicle_id", "=", rental_vehicle.id),
                ("state", "=", "completed")
            ])

    @api.depends("rental_ids.state", "rental_ids.total_amount")
    def _compute_total_revenue(self):
        RentalBooking = self.env["rental.booking"]
        # Used read_group.... why?
        # We need the sum of the field total_amount that's why...
        rental_booking_data = RentalBooking.read_group([
            ("vehicle_id", "in", self.ids),
            ("state", "=", "completed")
        ], groupby=["vehicle_id"], fields=["total_amount"], lazy=False)
        mapped_data_dict = {data["vehicle_id"][0]: data["total_amount"] for data in rental_booking_data}
        for rental_vehicle in self:
            rental_vehicle.total_revenue = mapped_data_dict.get(rental_vehicle.id, 0.0)
