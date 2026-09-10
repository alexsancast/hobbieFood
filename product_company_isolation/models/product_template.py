from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Core Odoo leaves company_id empty by default, which the standard
    # multi-company rule (product_comp_rule) treats as "shared with every
    # company". Defaulting it to the active company keeps new products
    # scoped to whoever created them instead of leaking across companies.
    company_id = fields.Many2one(default=lambda self: self.env.company)
