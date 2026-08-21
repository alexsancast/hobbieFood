from odoo import models


def _is_electronic_prefix(prefix):
    return bool(prefix) and prefix.startswith("E") and len(prefix) == 3


class AccountDebitNote(models.TransientModel):
    _inherit = "account.debit.note"

    def _prepare_default_values(self, move):
        defaults = super()._prepare_default_values(move)

        prefix = move.fiscal_type_id.prefix if move.fiscal_type_id else ""
        if not _is_electronic_prefix(prefix):
            return defaults

        debit_type_map = {"in_invoice": "in_debit", "out_invoice": "out_debit"}
        target_type = debit_type_map.get(move.move_type)
        if not target_type:
            return defaults

        electronic_debit_type = self.env["account.fiscal.type"].search(
            [("type", "=", target_type), ("prefix", "=like", "E%")], limit=1
        )
        if not electronic_debit_type:
            return defaults

        defaults.update({
            "ref": False,
            "is_debit_note": True,
            "fiscal_type_id": electronic_debit_type.id,
            "origin_out": move.ref,
        })
        return defaults
