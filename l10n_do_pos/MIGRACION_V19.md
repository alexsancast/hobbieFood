# Migración `l10n_do_pos` a Odoo 19

El módulo estaba escrito para Odoo 16 y no instalaba en Odoo 19. Se corrigieron
5 incompatibilidades. Verificado con instalación headless completa (`Registry
loaded`, sin errores) y `state = installed`.

## Arreglos

### 1. `data/data.xml` — xmlid inexistente (error original)
Referenciaba `point_of_sale.pos_config_main`, un registro que en v19 **ya no
existe como xmlid estático** (la config POS "main" ahora se crea por código,
no como dato del core). Provocaba:

```
Cannot update missing record 'point_of_sale.pos_config_main'
```

Se eliminaron los 2 `<record model="pos.config">`:
- El de `pos_partner_id` era redundante — el campo ya trae ese mismo `default`
  en `models/pos_config.py`.
- El de `credit_note` se asigna a la config POS desde Ajustes (flujo normal).

### 2. `views/*.xml` — `attrs=` eliminado en Odoo 17+
`attrs="{...}"` ya no se soporta; se usan atributos directos con expresión
Python. 6 usos convertidos:

| Antes | Después |
|-------|---------|
| `attrs="{'required': [('l10n_do_fiscal_journal','=',True)]}"` | `required="l10n_do_fiscal_journal"` |
| `attrs="{'invisible': [('l10n_do_type_limit_order_history','!=','days')]}"` | `invisible="l10n_do_type_limit_order_history != 'days'"` |
| `attrs="{'invisible': ['|',('journal_id','!=',False),('split_transactions','=',False)]}"` | `invisible="journal_id or not split_transactions"` |
| `attrs="{'invisible': [('is_credit_note','=',True)]}"` | `invisible="is_credit_note"` |
| `attrs="{'invisible': ['|',('ncf','!=',False),'|',('state','=','draft'),('has_refundable_lines','=',False)]}"` | `invisible="ncf or state == 'draft' or not has_refundable_lines"` |
| `attrs="{'invisible':[('ncf','=',False)]}"` (page) | `invisible="not ncf"` |
| `attrs="{'invisible':[('ncf_origin_out','=','')]}"` | `invisible="not ncf_origin_out"` |

### 3. `views/pos_order_views.xml` — `<tree>` renombrado a `<list>`
- `<tree>...</tree>` → `<list>...</list>`
- `<field name="view_mode">tree,form</field>` → `list,form`

### 4. `views/res_config_settings_views.xml` — estructura de ajustes v19
Los xpath apuntaban a `//div[@id='pos_accounting_section']` y
`//div[@id='pos_technical_section']`:
- `pos_accounting_section` ahora es un `<block>`, no un `<div>`.
- `pos_technical_section` ya no existe en v19.

Reescrito con la estructura `<block>` / `<setting>` de v19; ambos ajustes
(cliente por defecto y límite de historial) se insertan en el block
`pos_accounting_section`.

### 5. `models/pos_payment_method.py` — excepción inexistente
`raise models.ValidationError(...)` no existe (habría fallado en runtime al
disparar la constraint). Se importa desde el lugar correcto:

```python
from odoo.exceptions import ValidationError
...
raise ValidationError(...)
```

### Extra
Se quitó la clave `version` duplicada en `__manifest__.py` (quedó
`19.0.2.3.5`).

## Pendiente (opcional)
Auto-adjuntar el método de pago `credit_note` a los POS existentes al instalar
dependía de la config "main" inexistente, así que se omitió. Si se quiere
automático en todas las configs POS, se implementa con un `post_init_hook`.
