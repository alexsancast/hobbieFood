from odoo import models


class AccountMarginReport(models.TransientModel):
    _name = "account.margin.report"
    _inherit = "account.common.report"
    _description = "Margin Report"
