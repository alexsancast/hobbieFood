from odoo import api, fields, models, _
from odoo.exceptions import UserError

MOVE_TYPES = ("out_invoice", "out_refund")


class ReportMargin(models.AbstractModel):
    _name = "report.accounting_pdf_reports.report_margin"
    _description = "Margin Report"

    def _get_query_get_clause(self, data):
        return self.env["account.move.line"].with_context(
            data["form"].get("used_context", {})
        )._query_get()

    def _get_move_lines(self, data):
        query_get_clause = self._get_query_get_clause(data)
        query = (
            'SELECT "account_move_line".id FROM ' + query_get_clause[0] + ", account_move am "
            'WHERE "account_move_line".move_id = am.id '
            "AND am.move_type IN %s "
            "AND \"account_move_line\".display_type = %s "
            "AND " + query_get_clause[1] + " "
            "ORDER BY am.invoice_date, am.name, \"account_move_line\".id"
        )
        params = [MOVE_TYPES, "product"] + query_get_clause[2]
        self.env.cr.execute(query, tuple(params))
        ids = [row[0] for row in self.env.cr.fetchall()]
        return self.env["account.move.line"].browse(ids)

    def get_margin_lines(self, data):
        move_lines = self._get_move_lines(data)
        result = []
        totals = {"venta": 0.0, "costo": 0.0, "margen": 0.0}
        for line in move_lines:
            move = line.move_id
            company = move.company_id
            sign = -1 if move.move_type == "out_refund" else 1

            costo_unit = 0.0
            if line.product_id:
                costo_unit = line.product_id.with_company(company).standard_price
                if move.currency_id and move.currency_id != company.currency_id:
                    costo_unit = company.currency_id._convert(
                        costo_unit,
                        move.currency_id,
                        company,
                        move.invoice_date or fields.Date.context_today(self),
                    )

            venta = line.price_subtotal * sign
            costo = costo_unit * line.quantity * sign
            margen = venta - costo
            margen_pct = round(margen / venta * 100.0, 2) if venta else 0.0

            totals["venta"] += venta
            totals["costo"] += costo
            totals["margen"] += margen

            result.append({
                "move": move,
                "line": line,
                "fecha": move.invoice_date,
                "documento": move.ref or move.name,
                "cliente": move.partner_id.display_name,
                "producto": line.product_id.display_name,
                "cantidad": line.quantity,
                "venta": venta,
                "costo": costo,
                "margen": margen,
                "margen_pct": margen_pct,
                "currency": move.currency_id,
            })

        totals["margen_pct"] = (
            round(totals["margen"] / totals["venta"] * 100.0, 2) if totals["venta"] else 0.0
        )
        return result, totals

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data.get("form"):
            raise UserError(_("Form content is missing, this report cannot be printed."))

        lines, totals = self.get_margin_lines(data)
        wizard = self.env["account.margin.report"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "account.margin.report",
            "docs": wizard,
            "data": data,
            "company": wizard.company_id or self.env.company,
            "lines": lines,
            "totals": totals,
        }
