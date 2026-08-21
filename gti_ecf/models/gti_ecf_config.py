from odoo import models, fields, api


class GtiEcfConfig(models.Model):
    _name = "gti.ecf.config"
    _description = "Configuración de Conexión GTI e-CF"
    _rec_name = "name"

    name = fields.Char(
        string="Nombre",
        required=True,
        help="Nombre descriptivo para esta configuración (ej: Producción, Pruebas)",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
    )
    environment = fields.Selection(
        [("test", "Pruebas (Sandbox)"), ("production", "Producción")],
        string="Ambiente",
        required=True,
        default="test",
    )
    url_base = fields.Char(
        string="URL Base",
        compute="_compute_url_base",
        store=True,
        readonly=False,
        help="URL base de la API GTI. Se completa automáticamente según el ambiente.",
    )
    rnc_emisor = fields.Char(
        string="RNC Emisor",
        required=True,
        help="RNC de la empresa emisora. Se usa como Usuario en la autenticación.",
    )
    api_key = fields.Char(
        string="API Key (Clave)",
        required=True,
        help="API Key proporcionada por GTI. Se usa como Clave en la autenticación.",
    )
    medio_emision = fields.Char(
        string="Medio Emisión",
        required=True,
        default="xy1fcYHxWxjJ10t3ZD5HIg==",
        help="Valor fijo de MedioEmision proporcionado por GTI.",
    )
    provincia_code = fields.Char(
        string="Código Provincia",
        required=True,
        help="Código numérico de provincia según catálogo DGII. Ej: 120000",
    )
    municipio_code = fields.Char(
        string="Código Municipio",
        required=True,
        help="Código numérico de municipio según catálogo DGII. Ej: 120100",
    )
    telefono_emisor = fields.Char(
        string="Teléfono Emisor",
        required=True,
        help="Teléfono en formato GTI. Ej: 809-707-1591",
    )

    # Token activo (se llena al autenticar)
    token = fields.Char(
        string="Token Activo",
        readonly=True,
        copy=False,
        help="Token JWT vigente. Válido por 60 minutos.",
    )
    token_expiry = fields.Datetime(
        string="Expiración del Token",
        readonly=True,
        copy=False,
    )
    active = fields.Boolean(default=True)

    @api.depends("environment")
    def _compute_url_base(self):
        urls = {
            "test": "https://pruebas.facturadominicana.do/apicargafactura/api",
            "production": "https://www.facturadominicana.do/apicargafactura/api",
        }
        for rec in self:
            if rec.environment:
                rec.url_base = urls[rec.environment]

    def action_test_connection(self):
        """Botón de prueba: intenta obtener un token y muestra el resultado."""
        self.ensure_one()
        import requests
        from datetime import datetime

        url = f"{self.url_base.rstrip('/')}/Authz/Token"
        headers = {
            "Usuario": self.rnc_emisor,
            "Clave": self.api_key,
        }
        try:
            response = requests.post(url, headers=headers, timeout=15)
            data = response.json()
            if data.get("estado") and data.get("datos", {}).get("token"):
                token_data = data["datos"]
                self.write({
                    "token": token_data["token"],
                    "token_expiry": datetime.strptime(
                        token_data["fechaExpiracion"][:19], "%Y-%m-%dT%H:%M:%S"
                    ),
                })
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Conexión exitosa",
                        "message": "Token obtenido correctamente. Expira: %s"
                        % token_data["fechaExpiracion"],
                        "type": "success",
                        "sticky": False,
                    },
                }
            else:
                msg = str(data.get("respuesta", data))
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Error de autenticación",
                        "message": msg,
                        "type": "danger",
                        "sticky": True,
                    },
                }
        except Exception as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Error de conexión",
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }
