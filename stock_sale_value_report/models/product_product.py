from odoo import api, fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    sale_value_total = fields.Monetary(
        string="Valor Total (Venta)",
        compute='_compute_sale_value_total',
        currency_field='company_currency_id',
    )

    @api.depends('qty_available', 'lst_price')
    def _compute_sale_value_total(self):
        for product in self:
            product.sale_value_total = product.qty_available * product.lst_price
