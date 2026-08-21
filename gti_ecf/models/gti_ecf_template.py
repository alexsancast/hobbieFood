from odoo import models, fields, api
import json


class GtiEcfTemplate(models.Model):
    _name = "gti.ecf.template"
    _description = "Plantilla JSON e-CF por Tipo"
    _rec_name = "tipo_ecf"

    tipo_ecf = fields.Selection(
        [
            ("31", "31 - Factura de Crédito Fiscal"),
            ("32", "32 - Factura de Consumo"),
            ("33", "33 - Nota de Débito"),
            ("34", "34 - Nota de Crédito"),
            ("43", "43 - Gastos Menores"),
            ("44", "44 - Régimen Especial"),
            ("45", "45 - Gubernamental"),
        ],
        string="Tipo e-CF",
        required=True,
    )
    descripcion = fields.Char(string="Descripción", required=True)
    notas = fields.Text(
        string="Notas / Requisitos",
        help="Información adicional sobre este tipo de comprobante.",
    )
    template_json = fields.Text(
        string="Plantilla JSON",
        required=True,
        help="Estructura JSON que se enviará a GTI. Modifíquela si la API cambia.",
    )
    json_valido = fields.Boolean(
        string="JSON Válido",
        compute="_compute_json_valido",
    )

    _sql_constraints = [
        ("tipo_ecf_unique", "unique(tipo_ecf)", "Ya existe una plantilla para este tipo de e-CF."),
    ]

    @api.depends("template_json")
    def _compute_json_valido(self):
        for rec in self:
            try:
                json.loads(rec.template_json or "{}")
                rec.json_valido = True
            except Exception:
                rec.json_valido = False

    def action_formatear_json(self):
        """Formatea el JSON con indentación para mejor lectura."""
        self.ensure_one()
        try:
            parsed = json.loads(self.template_json)
            self.template_json = json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "JSON inválido",
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }
