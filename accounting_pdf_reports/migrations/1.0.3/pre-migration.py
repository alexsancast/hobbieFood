"""Drop the legacy menu actions so the XML loader can recreate them with a
different model (ir.actions.client). Without this, Odoo refuses to overwrite
an existing xml_id when the target model changes.

Handles both possible previous states:
  - ir.actions.act_window (original module)
  - ir.actions.act_url    (intermediate version)
"""

XML_IDS = (
    'action_account_report_bs',
    'action_account_report_pl',
)


def migrate(cr, version):
    cr.execute(
        """
        SELECT model, res_id
          FROM ir_model_data
         WHERE module = 'accounting_pdf_reports'
           AND name IN %s
        """,
        (XML_IDS,),
    )
    rows = cr.fetchall()
    if not rows:
        return

    by_table = {
        'ir.actions.act_window': 'ir_act_window',
        'ir.actions.act_url': 'ir_act_url',
        'ir.actions.client': 'ir_act_client',
        'ir.actions.server': 'ir_act_server',
    }
    for model, res_id in rows:
        table = by_table.get(model)
        if table:
            cr.execute(f"DELETE FROM {table} WHERE id = %s", (res_id,))
        cr.execute("DELETE FROM ir_actions WHERE id = %s", (res_id,))

    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'accounting_pdf_reports'
           AND name IN %s
        """,
        (XML_IDS,),
    )
