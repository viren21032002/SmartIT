# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = "res.partner"

    # Field Declarations
    birthdate_date = fields.Date(string="Birthdate", copy=False)
