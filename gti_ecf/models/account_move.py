from odoo import models, fields, _
from odoo.exceptions import UserError
import json
import io
import base64
import re

# Solo los prefijos electrónicos (E__) van a GTI.
# El tipo e-CF se extrae directamente del prefijo: E31 → "31", E32 → "32", etc.
# Los prefijos B__ son NCF tradicionales y no se envían a GTI.


def _format_telefono(telefono):
    digits = "".join(filter(str.isdigit, telefono or ""))
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    # GTI exige exactamente 12 caracteres (###-###-####); si el número no tiene
    # 10 dígitos, devolvemos un placeholder para que el error sea visible en logs.
    raise ValueError(
        f"TelefonoEmisor inválido: '{telefono}' tiene {len(digits)} dígitos "
        f"(se requieren exactamente 10). Corrija el teléfono en la configuración GTI."
    )


def _prefix_to_ecf(prefix):
    """Devuelve el tipo e-CF si el prefijo es electrónico (E31, E32...), o None."""
    if prefix and prefix.startswith("E") and len(prefix) == 3:
        return prefix[1:]  # E31 → "31", E32 → "32", etc.
    return None


# Mapeo código account.payment.method → FormaPago DGII
# DGII: 1=Efectivo, 2=Cheque/Transferencia/Depósito, 3=Tarjeta, 4=Crédito,
#       5=Bonos (solo tipo 32), 6=Permuta, 7=Nota crédito, 8=Otras
FORMA_PAGO_MAP = {
    "efectivo": 1,
    "cheque": 2,
    "transferencia": 2,
    "deposito": 2,
    "tarjeta_credito": 3,
    "tarjeta_debito": 3,
}


class AccountMove(models.Model):
    _inherit = "account.move"

    gti_ecf_state = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("sent", "Enviado"),
            ("accepted", "Aceptado"),
            ("conditional", "Aceptado Condicional"),
            ("rejected", "Rechazado"),
            ("error", "Error"),
        ],
        string="Estado e-CF",
        default="pending",
        copy=False,
        tracking=True,
    )
    gti_ecf_numero = fields.Char(
        string="e-NCF",
        copy=False,
        readonly=True,
        help="Número de comprobante electrónico asignado por GTI.",
    )
    gti_ecf_response = fields.Text(
        string="Respuesta GTI",
        copy=False,
        readonly=True,
        help="Respuesta raw de la API GTI.",
    )
    gti_url_qr = fields.Char(
        string="URL QR DGII",
        copy=False,
        readonly=True,
    )
    gti_codigo_seguridad = fields.Char(
        string="Código Seguridad",
        copy=False,
        readonly=True,
    )
    gti_fecha_firma = fields.Char(
        string="Fecha Firma",
        copy=False,
        readonly=True,
    )

    def _gti_qr_image(self):
        self.ensure_one()
        if not self.gti_url_qr:
            return False
        import qrcode
        buf = io.BytesIO()
        img = qrcode.make(self.gti_url_qr)
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def _gti_get_tipo_ecf(self):
        """Devuelve el tipo e-CF (31, 32, etc.) si el prefijo es electrónico, o None."""
        self.ensure_one()
        prefix = self.fiscal_type_id.prefix if self.fiscal_type_id else ""
        return _prefix_to_ecf(prefix)

    def _gti_purchase_is_selfbilling(self):
        """Para in_invoice: True solo si el tipo e-CF es 43 (Gastos Menores) o
        44 (Régimen Especial), los únicos casos donde la propia empresa es el
        emisor legítimo. Cualquier otro tipo (p.ej. E31) representa un
        comprobante ya emitido por el proveedor y no debe transmitirse."""
        self.ensure_one()
        return self._gti_get_tipo_ecf() in ("43", "44")

    def _compute_fiscal_sequence(self):
        # El compute padre (l10n_do_accounting), ante is_debit_note=True, busca el
        # primer account.fiscal.type con type=out_debit/in_debit y suele tomar el
        # B03 tradicional. Para NDs originadas en facturas electrónicas (E__),
        # forzamos el tipo electrónico (E33) y reasignamos su fiscal_sequence_id.
        super()._compute_fiscal_sequence()
        debit_map = {"in_invoice": "in_debit", "out_invoice": "out_debit"}
        for inv in self.filtered(
            lambda i: i.state == "draft" and i.is_debit_note and i.debit_origin_id
        ):
            origin_prefix = (
                inv.debit_origin_id.fiscal_type_id.prefix
                if inv.debit_origin_id.fiscal_type_id else ""
            )
            if not _prefix_to_ecf(origin_prefix):
                continue
            current_prefix = inv.fiscal_type_id.prefix if inv.fiscal_type_id else ""
            if _prefix_to_ecf(current_prefix):
                continue  # ya es electrónico
            target = debit_map.get(inv.move_type)
            if not target:
                continue
            electronic = self.env["account.fiscal.type"].search(
                [("type", "=", target), ("prefix", "=like", "E%")], limit=1
            )
            if not electronic:
                continue
            inv.fiscal_type_id = electronic
            if not (inv.is_l10n_do_fiscal_invoice and electronic.assigned_sequence):
                inv.fiscal_sequence_id = False
                continue
            seq_domain = [
                ("company_id", "=", inv.company_id.id),
                ("fiscal_type_id", "=", electronic.id),
                ("state", "=", "active"),
                ("expiration_date", ">=", inv.invoice_date or fields.Date.context_today(inv)),
            ]
            seq = self.env["account.fiscal.sequence"].search(
                seq_domain, order="expiration_date, id desc", limit=1
            )
            inv.fiscal_sequence_id = seq if seq and seq.state == "active" else False

    def _gti_build_payload(self):
        """
        Construye el payload JSON para enviar a GTI.
        Toma el template del tipo correspondiente y sustituye
        los valores reales de la factura.
        """
        self.ensure_one()

        tipo_ecf = self._gti_get_tipo_ecf()
        if not tipo_ecf:
            return None, f"Tipo de comprobante '{self.fiscal_type_id.prefix}' no tiene mapeo e-CF."

        # Buscar template del tipo
        template = self.env["gti.ecf.template"].sudo().search(
            [("tipo_ecf", "=", tipo_ecf)], limit=1
        )
        if not template:
            return None, f"No existe plantilla JSON para el tipo e-CF {tipo_ecf}."

        # Buscar configuración GTI activa de la empresa
        config = self.env["gti.ecf.config"].sudo().search(
            [("company_id", "=", self.company_id.id), ("active", "=", True)], limit=1
        )
        if not config:
            return None, "No hay configuración GTI activa para esta empresa."

        company = self.company_id
        partner = self.partner_id

        # Fecha de emisión en formato DD-MM-YYYY
        fecha_emision = self.invoice_date.strftime("%d-%m-%Y") if self.invoice_date else ""

        # Calcular líneas según fórmula GTI:
        #   MontoItem = PrecioUnitarioItem * CantidadItem - DescuentoMonto + RecargoMonto
        # GTI valida esta fórmula con los valores tal como vienen en el JSON,
        # DescuentoMonto ya redondeados (4 y 2 decimales respectivamente).
        lineas_gti = []
        for line in self.invoice_line_ids:
            cantidad = line.quantity
            precio_unit = round(line.price_unit, 4)
            descuento_monto = (
                round(precio_unit * cantidad * (line.discount or 0.0) / 100.0, 2)
                if line.discount
                else 0.0
            )
            monto_item = round(precio_unit * cantidad - descuento_monto, 2)
            lineas_gti.append({
                "line": line,
                "cantidad": cantidad,
                "precio_unit": precio_unit,
                "descuento_monto": descuento_monto,
                "monto_item": monto_item,
            })

        # Totales derivados de los MontoItem efectivamente enviados,
        # para garantizar consistencia con la validación de GTI.
        monto_gravado = sum(l["monto_item"] for l in lineas_gti if l["line"].tax_ids)
        monto_exento = sum(l["monto_item"] for l in lineas_gti if not l["line"].tax_ids)
        total_itbis = round(monto_gravado * 0.18, 2)
        monto_total = round(monto_gravado + monto_exento + total_itbis, 2)

        es_gasto_menor = tipo_ecf == "43"
        es_regimen_especial = tipo_ecf == "44"
        es_emisor_simple = tipo_ecf in ("43", "44")

        # Construir bloque Emisor
        if es_emisor_simple:
            # Para 43/44 solo se requiere fecha y EmisorPorDefecto
            emisor = {
                "FechaEmision": fecha_emision,
                "EmisorPorDefecto": True,
            }
        else:
            emisor = {
                "RNCEmisor": config.rnc_emisor,
                "RazonSocialEmisor": company.name,
                "DireccionEmisor": company.street or "",
                "Provincia": config.provincia_code,
                "Municipio": config.municipio_code,
                "TablaTelefonoEmisor": [
                    {"TelefonoEmisor": _format_telefono(config.telefono_emisor or "")}
                ],
                "FechaEmision": fecha_emision,
                "EmisorPorDefecto": False,
            }

        # Construir bloque Comprador (no aplica para 43/44)
        # Tipo 31/33/45: obligatorio RNCComprador
        # Tipo 32 (Consumo) y 34 (NC, p.ej. contra e-32): GTI exige el nodo
        #   Comprador presente con al menos RazonSocial; RNC solo si el cliente
        #   lo tiene (obligatorio en 32 si MontoTotal > 250K).
        direccion_comprador = ", ".join(
            filter(None, [partner.street, partner.street2, partner.city])
        )
        rnc_comprador = re.sub(r"\D", "", partner.vat or "")
        comprador = {}
        if tipo_ecf in ("31", "33", "45") and rnc_comprador:
            comprador = {
                "RNCComprador": rnc_comprador,
                "RazonSocialComprador": partner.name,
            }
            if direccion_comprador:
                comprador["DireccionComprador"] = direccion_comprador
        elif tipo_ecf in ("32", "34"):
            if rnc_comprador:
                comprador["RNCComprador"] = rnc_comprador
            comprador["RazonSocialComprador"] = partner.name or "CONSUMIDOR FINAL"
            if direccion_comprador:
                comprador["DireccionComprador"] = direccion_comprador
        elif es_regimen_especial:
            # e-44: Comprador obligatorio, debe tener RNC del beneficiario del régimen
            if not rnc_comprador:
                raise UserError(
                    "Para Régimen Especial (e-44) el cliente debe tener RNC."
                )
            comprador = {
                "RNCComprador": rnc_comprador,
                "RazonSocialComprador": partner.name,
            }

        # TipoPago desde campo invoice_type (quotation_met): credito=2, contado=1
        tipo_pago = 2 if getattr(self, "invoice_type", None) == "credito" else 1

        # Construir IdDoc en ORDEN ESTRICTO según schema DGII:
        # TipoeCF → eNCF → IndicadorNotaCredito → IndicadorMontoGravado →
        # TipoIngresos → TipoPago → FechaLimitePago → TerminoPago → TablaFormasPago
        id_doc = {"TipoeCF": int(tipo_ecf), "eNCF": self.ref}

        if tipo_ecf == "34":
            id_doc["IndicadorNotaCredito"] = 0

        if not es_emisor_simple:
            id_doc["IndicadorMontoGravado"] = 0

        # TipoIngresos: requerido para todos excepto e-43 (Gastos Menores)
        if not es_gasto_menor:
            id_doc["TipoIngresos"] = (
                self.income_type if hasattr(self, "income_type") and self.income_type else "01"
            )

        id_doc["TipoPago"] = tipo_pago

        # e-43 (Gastos Menores): no aplican campos de crédito ni TablaFormasPago
        if es_gasto_menor:
            pass
        elif tipo_pago == 2:
            # Venta a crédito: FechaLimitePago/TerminoPago siempre requeridos
            if self.invoice_date_due:
                id_doc["FechaLimitePago"] = self.invoice_date_due.strftime("%d-%m-%Y")
            if self.invoice_payment_term_id:
                id_doc["TerminoPago"] = self.invoice_payment_term_id.name
            # TablaFormasPago prohibida en tipo 34 (NC) — Código Obligatoriedad 0
            if tipo_ecf != "34":
                id_doc["TablaFormasPago"] = [
                    {"FormaPago": 4, "MontoPago": round(monto_total, 2)}
                ]
        elif tipo_ecf != "34":
            # Contado: FormaPago fijo 1 (Efectivo) — se envía al confirmar
            id_doc["TablaFormasPago"] = [
                {"FormaPago": 1, "MontoPago": round(monto_total, 2)}
            ]
            # --- Lógica anterior (esperaba pago real reconciliado para detectar la forma):
            # tabla = self._gti_build_tabla_formas_pago(monto_total)
            # if tabla:
            #     id_doc["TablaFormasPago"] = tabla

        # Construir Totales
        totales = {"MontoTotal": round(monto_total, 2)}
        if es_emisor_simple:
            totales["MontoExento"] = round(monto_exento or monto_total, 2)
        else:
            totales.update({
                "MontoGravadoTotal": round(monto_gravado, 2),
                "MontoGravadoI1": round(monto_gravado, 2),
                "ITBIS1": 18,
                "TotalITBIS": round(total_itbis, 2),
                "TotalITBIS1": round(total_itbis, 2),
            })
            if monto_exento:
                totales["MontoExento"] = round(monto_exento, 2)

        # Construir líneas de detalle
        detalles = []
        for idx, datos in enumerate(lineas_gti, start=1):
            line = datos["line"]
            if es_emisor_simple:
                indicador = 4  # siempre Exento para 43/44
            else:
                indicador = 1 if line.tax_ids else 4
            item = {
                "NumeroLinea": idx,
                "IndicadorFacturacion": indicador,
                "NombreItem": line.name or line.product_id.name or "",
                "IndicadorBienoServicio": 1 if line.product_id.type == "consu" else 2,
                "CantidadItem": datos["cantidad"],
                "PrecioUnitarioItem": datos["precio_unit"],
            }
            if datos["descuento_monto"]:
                item["DescuentoMonto"] = datos["descuento_monto"]
                item["TablaSubDescuento"] = [{
                    "TipoSubDescuento": "%",
                    "SubDescuentoPorcentaje": round(line.discount, 2),
                    "MontoSubDescuento": datos["descuento_monto"],
                }]
            item["MontoItem"] = datos["monto_item"]
            detalles.append(item)

        # Orden DGII: IdDoc → Emisor → Comprador → Totales
        encabezado = {"IdDoc": id_doc, "Emisor": emisor}
        if comprador:
            encabezado["Comprador"] = comprador
        encabezado["Totales"] = totales

        payload = {
            "Encabezado": encabezado,
            "DetallesItems": detalles,
        }

        # InformacionReferencia para NC/ND
        # FechaNCFModificado debe ser la fecha de la factura original, no de la NC/ND
        # NC: reversed_entry_id (refund). ND: debit_origin_id (account_debit_note).
        factura_original = self.reversed_entry_id or self.debit_origin_id
        ncf_modificado = (factura_original.gti_ecf_numero if factura_original else None) or self.origin_out
        fecha_ncf_modificado = (
            factura_original.invoice_date.strftime("%d-%m-%Y")
            if factura_original and factura_original.invoice_date
            else fecha_emision
        )

        if tipo_ecf == "33" and ncf_modificado:
            # CodigoModificacion 3 = Corrige montos del NCF modificado.
            # Para tipo 33 NO es válido el código 1 (anular), solo aplica a NC (34).
            payload["InformacionReferencia"] = {
                "NCFModificado": ncf_modificado,
                "FechaNCFModificado": fecha_ncf_modificado,
                "CodigoModificacion": 3,
                "RazonModificacion": self.ref or "",
            }
        elif tipo_ecf == "34" and ncf_modificado:
            # Code 1 = full cancellation (amounts must match); code 3 = partial correction.
            es_anulacion_total = (
                factura_original
                and round(self.amount_total, 2) == round(factura_original.amount_total, 2)
            )
            payload["InformacionReferencia"] = {
                "NCFModificado": ncf_modificado,
                "FechaNCFModificado": fecha_ncf_modificado,
                "CodigoModificacion": 1 if es_anulacion_total else 3,
                "RazonModificacion": self.ref or "",
            }

        return payload, config

    def _gti_get_token(self, config):
        """Obtiene token vigente o solicita uno nuevo."""
        import requests
        from datetime import datetime

        now = datetime.now()
        if config.token and config.token_expiry:
            diff = (config.token_expiry - now).total_seconds()
            if diff > 120:
                return config.token

        url = f"{config.url_base.rstrip('/')}/Authz/Token"
        headers = {"Usuario": config.rnc_emisor, "Clave": config.api_key}
        response = requests.post(url, headers=headers, timeout=15)
        data = response.json()
        if not (data.get("estado") and data.get("datos", {}).get("token")):
            raise Exception(f"Error al obtener token GTI: {data.get('respuesta', data)}")
        token_data = data["datos"]
        config.write({
            "token": token_data["token"],
            "token_expiry": datetime.strptime(
                token_data["fechaExpiracion"][:19], "%Y-%m-%dT%H:%M:%S"
            ),
        })
        return token_data["token"]

    def _gti_send(self):
        """Envía la factura a GTI. No lanza excepción — registra el error en la factura."""
        import requests

        self.ensure_one()
        payload, config = self._gti_build_payload()
        import logging, json
        logging.getLogger(__name__).info("GTI PAYLOAD tipo=%s: %s", self._gti_get_tipo_ecf(), json.dumps(payload, ensure_ascii=False))

        if payload is None:
            # config aquí es el mensaje de error
            self.write({"gti_ecf_state": "error", "gti_ecf_response": config})
            return

        try:
            token = self._gti_get_token(config)
            url = f"{config.url_base.rstrip('/')}/eCF/Recepcion"
            headers = {
                "Authorization": f"Bearer {token}",
                "MedioEmision": config.medio_emision,
                "RetornarXml": "0",
                "Content-Type": "application/json",
            }
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            data = response.json()
            raw = json.dumps(data, indent=2, ensure_ascii=False)

            if data.get("estado") and data.get("datos"):
                datos = data["datos"]
                numero_factura = datos.get("numeroFactura")
                self.write({
                    "gti_ecf_state": "sent",
                    "gti_ecf_numero": numero_factura,
                    "gti_url_qr": (datos.get("urlqr") or "").strip(),
                    "gti_codigo_seguridad": datos.get("codigoSeguridad"),
                    "gti_fecha_firma": datos.get("fechaHoraFirma"),
                    "gti_ecf_response": "--- Envío ---\n" + raw,
                })
                # No consultamos estado inmediatamente — GTI tarda unos minutos en procesar
            else:
                self.write({
                    "gti_ecf_state": "error",
                    "gti_ecf_response": raw,
                })
        except Exception as e:
            self.write({
                "gti_ecf_state": "error",
                "gti_ecf_response": str(e),
            })

    def _gti_check_status(self, token, config, numero_factura=None):
        """Consulta el estado del e-CF ante la DGII y actualiza el state."""
        import requests

        ESTADOS = {"1": "accepted", "4": "conditional", "3": "rejected"}
        ecf = numero_factura or self.gti_ecf_numero

        url = f"{config.url_base.rstrip('/')}/ConsultaEcf/EstadoDgii"
        headers = {
            "Authorization": f"Bearer {token}",
            "e-NCF": ecf,
        }
        response = requests.post(url, headers=headers, timeout=15)
        data = response.json()
        raw_status = json.dumps(data, indent=2, ensure_ascii=False)

        codigo = str((data.get("datos") or {}).get("codigo", ""))
        respuesta_actual = self.gti_ecf_response or ""
        vals = {"gti_ecf_response": respuesta_actual + "\n\n--- Estado DGII ---\n" + raw_status}

        # Solo actualizamos el state si GTI devuelve un estado conocido
        if codigo in ESTADOS:
            vals["gti_ecf_state"] = ESTADOS[codigo]

        self.write(vals)

    def _cron_gti_actualizar_estados(self):
        """Cron: consulta el estado DGII de todas las facturas en sent/pending."""
        facturas = self.search([
            ("gti_ecf_state", "in", ["sent", "pending"]),
            ("gti_ecf_numero", "!=", False),
            ("move_type", "in", ["out_invoice", "out_refund", "in_invoice"]),
        ])
        for factura in facturas:
            try:
                config = self.env["gti.ecf.config"].search(
                    [("company_id", "=", factura.company_id.id), ("active", "=", True)], limit=1
                )
                if not config:
                    continue
                token = factura._gti_get_token(config)
                factura._gti_check_status(token, config)
            except Exception:
                continue

    def action_gti_consultar_estado(self):
        """Botón manual para consultar el estado DGII del e-CF."""
        self.ensure_one()
        config = self.env["gti.ecf.config"].search(
            [("company_id", "=", self.company_id.id), ("active", "=", True)], limit=1
        )
        if not config:
            raise Exception("No hay configuración GTI activa para esta empresa.")
        token = self._gti_get_token(config)
        self._gti_check_status(token, config)

    def _gti_build_tabla_formas_pago(self, monto_total):
        """Itera pagos reconciliados y agrupa montos por FormaPago DGII.
        Devuelve lista [{FormaPago, MontoPago}] o [] si no hay pagos."""
        self.ensure_one()
        montos = {}
        rec_lines = self.line_ids.filtered(
            lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable")
        )
        for line in rec_lines:
            for partial in line.matched_debit_ids | line.matched_credit_ids:
                counterpart = (
                    partial.credit_move_id
                    if partial.debit_move_id == line
                    else partial.debit_move_id
                )
                payment = counterpart.move_id.payment_id
                if not payment or not payment.payment_method_id:
                    continue
                code = (payment.payment_method_id.code or "").lower()
                forma = FORMA_PAGO_MAP.get(code, 8)  # 8 = Otras formas
                montos[forma] = montos.get(forma, 0.0) + partial.amount
        return [
            {"FormaPago": f, "MontoPago": round(m, 2)}
            for f, m in sorted(montos.items())
        ]

    def action_gti_reenviar(self):
        """Botón manual para reenviar a GTI cuando hubo un error."""
        self.ensure_one()
        if self.move_type == "in_invoice" and not self._gti_purchase_is_selfbilling():
            raise UserError(_(
                "Esta factura de proveedor no se envía a la DGII: "
                "el proveedor es quien transmite su propio comprobante. "
                "Solo Gastos Menores (E43) y Régimen Especial (E44) se autofacturan."
            ))
        self._gti_send()

    def action_post(self):
        """Override: después de confirmar, envía a GTI si es e-CF electrónico.
        Tanto crédito como contado se envían en este momento.
        Las facturas de proveedor (in_invoice) solo se envían cuando la propia
        empresa es el emisor legítimo (Gastos Menores E43 / Régimen Especial
        E44); en cualquier otro caso (p.ej. E31) el proveedor ya tiene su
        propio comprobante y la transmisión es responsabilidad suya."""
        res = super().action_post()
        for move in self:
            if move.move_type not in ("out_invoice", "out_refund", "in_invoice"):
                continue
            if move.move_type == "in_invoice" and not move._gti_purchase_is_selfbilling():
                continue
            if not move._gti_get_tipo_ecf():
                continue
            move._gti_send()
            # --- Lógica anterior (contado esperaba al pago):
            # if getattr(move, "invoice_type", None) == "credito":
            #     move._gti_send()
        return res

    # --- Override anterior: enviaba la factura a contado a GTI cuando el
    # payment_state pasaba a paid/in_payment. Se desactivó porque ahora el
    # envío de contado ocurre directamente en action_post.
    # def _compute_payment_state(self):
    #     """Override: tras recomputar payment_state, si una factura a contado quedó
    #     pagada y estaba pendiente de enviar a GTI, la enviamos ahora.
    #     Los campos stored-computed se escriben vía _write() interno bypassando el
    #     write() público, por eso hay que engancharse aquí y no en write()."""
    #     res = super()._compute_payment_state()
    #     for move in self:
    #         if (
    #             move.gti_ecf_state == "pending"
    #             and getattr(move, "invoice_type", None) == "contado"
    #             and move.payment_state in ("paid", "in_payment")
    #             and move.move_type in ("out_invoice", "out_refund", "in_invoice")
    #             and move._gti_get_tipo_ecf()
    #         ):
    #             move._gti_send()
    #     return res
