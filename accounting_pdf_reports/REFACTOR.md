# Refactor: Reportes financieros con vista web embebida

**Estado:** ✅ Completado en `version 1.0.6` — los 10 reportes financieros del
módulo migrados al nuevo flujo (4 fases, tabla completa al pie del doc).

Este documento describe el refactor del módulo `accounting_pdf_reports` para
convertir los reportes financieros del flujo tradicional **"menú → wizard popup
→ PDF"** a un flujo moderno **"menú → vista web embebida con filtros inline +
botón PDF opcional"**.

El reporte queda embebido dentro del SPA de Odoo (con navbar y menú lateral
visibles), no abre en pestaña nueva ni reemplaza la UI completa.

---

## Arquitectura

```
Menú (ir.actions.client tag='accounting_pdf_reports.report_iframe')
       │
       ▼
OWL component ReportIframe   ←── static/src/report_iframe/report_iframe.js
       │  renderiza un <iframe>
       ▼
GET /accounting/report/<slug>?date_from=...&date_to=...&...
       │  controllers/main.py
       │  - parsea query params (con defaults: mes actual, posted, todos los journals)
       │  - crea wizard transient para reutilizar _build_contexts
       │  - llama al modelo report.* (el mismo que usa el PDF original)
       │  - renderiza plantilla QWeb del reporte
       ▼
HTML standalone con:
  - Header (título del reporte + compañía + período)
  - Filter bar (date_from / date_to / target_move / journals / filtros propios)
    └── Botones: Apply (GET reload), PDF (POST → pestaña nueva), Print
  - Tabla del reporte (jerárquica, flat, etc. según el reporte)
```

### Piezas reutilizables

- **`report/report_styles_template.xml`** — un solo `<template id="report_styles">`
  que embebe la hoja de estilos completa (clases prefijadas `.afr-*`). Cada
  reporte la incluye con `<t t-call="accounting_pdf_reports.report_styles"/>`
  dentro del `<head>`. **No depende de Bootstrap** ni de assets externos
  (importante: Bootstrap raw no existe como archivo servible en Odoo 19; los
  assets vienen compilados en bundles SCSS, y el iframe no carga bundles
  backend).

- **`report/filter_bar_template.xml`** — dos templates QWeb compartidos por
  todos los reportes:
  - `report_filter_bar_common`: inputs comunes (date_from, date_to,
    target_move, journals) usando clases `.afr-field`, `.afr-input`,
    `.afr-select`, `.afr-multiselect`.
  - `report_filter_bar_buttons`: botones Apply / PDF / Print (`.afr-btn`,
    `.afr-btn-primary`, `.afr-btn-outline`). PDF usa `formtarget="_blank"`
    para no romper el iframe.

- **`static/src/report_iframe/`** — componente OWL genérico que renderiza un
  iframe ocupando el área de contenido. Recibe la URL en `action.params.url`.

- **`controllers/main.py`** — un método `_build_<report>_data(kwargs)` por
  reporte que arma el dict `data['form']` desde query params + crea el
  wizard transient (reutiliza `_build_contexts` / `_build_comparison_context`).

---

## Decisiones tomadas

| Decisión | Elegido | Razón |
|---|---|---|
| Alcance | Todos los reportes financieros (8) | Pedido del usuario |
| Selector de período | From / To (no mes) | Más control para el usuario |
| Refresh de filtros | Recarga GET con query params | Más simple, sin AJAX |
| Botón PDF | Conservar, dentro del filter bar | Mantener compatibilidad con el reporte PDF original |
| Embebido en UI | OWL client action + iframe | El reporte queda dentro del SPA, navbar visible |
| Many2many filters | `<select multiple>` (ctrl+click) | Sin dependencias JS externas |

---

## Patrón de migración cuando cambia el modelo de un xml_id

Odoo rechaza el upgrade cuando un `xml_id` ya existente apunta a un modelo y el
XML nuevo intenta crear el mismo `xml_id` con otro modelo (ej:
`ir.actions.act_window` → `ir.actions.client`). Solución:

1. **Bump del manifest version** (ej: `1.0.2` → `1.0.3`) para disparar la
   carpeta `migrations/<version>/`.
2. **`migrations/<version>/pre-migration.py`** que limpia las filas anteriores
   antes de que el XML loader corra:

```python
def migrate(cr, version):
    cr.execute("SELECT model, res_id FROM ir_model_data "
               "WHERE module = 'accounting_pdf_reports' AND name IN %s",
               (XML_IDS,))
    for model, res_id in cr.fetchall():
        # Borrar de la tabla específica del modelo (ir_act_window, ir_act_url, etc.)
        # más ir_actions, más ir_model_data
        ...
```

3. **El nuevo `<record>` con el modelo deseado** se carga sin problemas porque
   el xml_id quedó libre.

Referencia: `migrations/1.0.3/pre-migration.py`.

---

## Sistema de estilos (clases `.afr-*`)

Las páginas se renderizan dentro de un `<iframe>` que **no carga el bundle de
assets del backend** de Odoo. Por eso intentar usar Bootstrap a través de
`/web/static/lib/bootstrap/css/bootstrap.css` no funciona (en Odoo 19 ese
archivo no existe como recurso servible — Bootstrap viene compilado dentro de
bundles SCSS que solo se aplican en la UI principal).

La solución fue escribir una hoja de estilos propia, embebida inline en cada
página vía el template compartido `accounting_pdf_reports.report_styles`. Las
clases usan el prefijo **`.afr-`** (Accounting Financial Reports) para no
colisionar con nada de Odoo.

**Convenciones de clases:**

| Categoría | Clases |
|---|---|
| Layout | `.afr-container`, `.afr-header`, `.afr-title`, `.afr-subtitle`, `.afr-meta` |
| Filter bar | `.afr-filter-bar`, `.afr-filter-row`, `.afr-cmp-row` |
| Campo (label + input) | `.afr-field`, `.afr-label`, `.afr-label-hint` |
| Inputs | `.afr-input`, `.afr-select`, `.afr-multiselect` |
| Checkbox | `.afr-check`, `.afr-check-input`, `.afr-check-label` |
| Acciones | `.afr-actions`, `.afr-btn`, `.afr-btn-primary`, `.afr-btn-outline` |
| Misc | `.afr-hint`, `.afr-view-toolbar`, `.afr-no-print` |
| Tabla | `.afr-table`, `.afr-text-end` |
| Niveles del reporte | `.o-level-1..4`, `.o-toggleable`, `.o-toggle-icon`, `.o-account-row` |

**Paleta:**

- Acento principal: `#875A7B` (Odoo purple) — botón primary, focus rings,
  checkbox marcado.
- Bordes: `#d1d5db` (gris claro) → `#9ca3af` (hover).
- Fondo página: `#f3f4f6`; tarjeta: `#ffffff`; filter bar: `#f9fafb`.
- Texto: `#111827` (principal), `#6b7280` (muted), `#374151` (medio).
- Tabla header: `#4b5563` con texto blanco uppercase.

**Pequeños detalles:**

- Números en la tabla con `font-variant-numeric: tabular-nums` para alineación
  estable.
- Checkbox custom usando `appearance: none` + `::after` con un check blanco.
- Focus en inputs/botones con halo (`box-shadow: 0 0 0 3px rgba(...)`).
- `@media print` oculta filter bar, toolbar y los toggles para que el navegador
  imprima solo la tabla del reporte.

---

## Fases

### Fase 1 — Balance Sheet + Profit and Loss ✅

**Estado:** Implementada en `version 1.0.3`.

Estos dos reportes comparten el wizard `accounting.report` (solo cambia
`account_report_id`), así que se atacan juntos.

**Archivos nuevos:**

| Archivo | Propósito |
|---|---|
| `report/report_styles_template.xml` | Hoja de estilos compartida (`.afr-*`) embebida vía `<t t-call>`. Sin dependencias externas (no Bootstrap). |
| `report/filter_bar_template.xml` | Partials QWeb del filter bar (común + buttons). |
| `static/src/report_iframe/report_iframe.js` | OWL component `ReportIframe` registrado como client action. |
| `static/src/report_iframe/report_iframe.xml` | Template OWL: `<iframe>` que llena el área de contenido. |
| `migrations/1.0.3/pre-migration.py` | Limpia los xml_ids `action_account_report_bs` y `action_account_report_pl` (cualquiera sea el modelo anterior). |

**Archivos modificados:**

| Archivo | Cambio |
|---|---|
| `__manifest__.py` | `version: 1.0.3`; bundle `web.assets_backend` con el JS/XML del componente; agregados `report/report_styles_template.xml` y `report/filter_bar_template.xml` a `data`. |
| `controllers/main.py` | Reescrito. Ahora expone `GET /accounting/report/financial` (vista) y `POST /accounting/report/financial/pdf` (descarga PDF). Antes solo existía la ruta con `<wizard_id>`. |
| `report/report_financial_view.xml` | Reescrito con las clases `.afr-*` del sistema de estilos compartido. El `<head>` solo llama `<t t-call="accounting_pdf_reports.report_styles"/>`. Header, filter-bar, fila de comparación, toolbar y tabla todos rediseñados. |
| `wizard/balance_sheet.xml` | `action_account_report_bs` cambia de `ir.actions.act_window` (abre wizard) a `ir.actions.client` (abre iframe con el reporte). |
| `wizard/profit_and_loss.xml` | Idem para `action_account_report_pl`. |

**Filtros disponibles en la vista:**

- `date_from` / `date_to` (defaults: primer día del mes actual / hoy)
- `target_move` (Posted / All — default: Posted)
- `journal_ids` (multi-select — default: todos los journals de la compañía)
- `debit_credit` (toggle — agrega columnas Debit/Credit)
- `enable_filter` (toggle — agrega columna de comparación; mutuamente exclusivo con Debit/Credit)
- Cuando `enable_filter` está activo aparecen 3 inputs extra en una segunda fila:
  - `label_filter` (string — encabezado de la columna de comparación; default `"Comparison"`)
  - `date_from_cmp` / `date_to_cmp` (defaults: el mismo rango pero un mes antes; el usuario los puede sobreescribir)

**Detalle importante sobre Comparison:**

El wizard original requiere `filter_cmp='filter_date'` + `date_from_cmp`/`date_to_cmp` poblados
para que `_build_comparison_context` use fechas distintas; si no, la columna de comparación
sale con los mismos valores que la principal. El controller del refactor infiere
`filter_cmp` automáticamente: si `enable_filter=True` y hay fechas de comparación
(provistas o auto-defaulteadas a un mes antes), setea `filter_cmp='filter_date'`.

**Lo que NO cambió:**

- El modelo `accounting.report` (wizard) sigue existiendo y se usa
  internamente desde el controller (`create` para reutilizar
  `_build_contexts` y `_build_comparison_context`).
- Los `binding_model_id` (acciones que aparecen como "Print" desde un partner
  o cuenta) siguen abriendo el wizard tradicional — no se tocan.

**Cómo probar:**

1. Actualizar: `-u accounting_pdf_reports` (la pre-migration corre
   automáticamente al detectar el bump de versión).
2. Menú **Accounting → Reporting → Balance Sheet** o **Profit and Loss**
   debe abrir el reporte EMBEBIDO en Odoo (navbar visible arriba), sin
   wizard popup ni pestaña nueva.
3. Cambiar `From` / `To` / `Target` / `Journals` / `Debit-Credit` /
   `Comparison` → click **Apply** → la vista recarga con los nuevos
   filtros en la URL.
4. **PDF** → abre el reporte PDF original en pestaña nueva.
5. **Print** → imprime el contenido del iframe.

---

### Fase 2 — Trial Balance + General Ledger ✅

**Estado:** Implementada en `version 1.0.4`.

A diferencia de la Fase 1, ambos wizards (`account.balance.report` y
`account.report.general.ledger`) tienen `binding_model_id ref="account.model_account_account"`,
es decir, sus acciones aparecen ALSO como botón "Print" desde un record de cuenta.
Para no romper ese binding:
- **Mantenemos** los `ir.actions.act_window` originales con su `binding_model_id` intacto.
- **Creamos NUEVAS** acciones `ir.actions.client` (xml_id distinto) para los menús.
- **Cambiamos** el `<menuitem>` para que apunte a la nueva acción.

Resultado: el binding desde la vista de cuenta sigue abriendo el wizard tradicional;
el menú de Reporting abre la nueva vista web embebida. Sin migration necesaria —
los xml_ids viejos no cambian de modelo.

**Archivos nuevos:**

| Archivo | Propósito |
|---|---|
| `report/report_trial_balance_view.xml` | Template QWeb del Trial Balance (tabla flat con totales en `<tfoot>`). |
| `report/report_general_ledger_view.xml` | Template QWeb del General Ledger (sección colapsable por cuenta con sub-tabla de move lines). |

**Archivos modificados:**

| Archivo | Cambio |
|---|---|
| `__manifest__.py` | `version: 1.0.4`; agregados los dos nuevos templates a `data`. |
| `controllers/main.py` | Refactorizado: extraídos helpers compartidos (`_default_dates`, `_all_company_journals`, `_money_formatter`, `_render_pdf_response`). Agregadas rutas `GET /accounting/report/trial_balance` + `POST /pdf` y `GET /accounting/report/general_ledger` + `POST /pdf`. Cada una construye su wizard transient, llama a `pre_print_report` para reutilizar la lógica del wizard, y luego invoca `_get_report_values` del report model correspondiente. |
| `report/report_styles_template.xml` | Agregadas clases `.afr-account-section`, `.afr-account-header`, `.afr-account-code`, `.afr-account-name`, `.afr-account-totals`, `.afr-stat`, `.afr-ledger-table`, `.afr-ledger-empty`. Estilos para totales en `<tfoot>` del trial balance. |
| `wizard/trial_balance.xml` | Agregada `action_account_balance_web` (`ir.actions.client`); menú `menu_general_balance_report` ahora apunta a la nueva acción. La `action_account_balance_menu` original queda para el binding desde cuentas. |
| `wizard/general_ledger.xml` | Idem para `action_account_general_ledger_web` y `menu_general_ledger`. |

**Filtros disponibles en cada vista:**

*Trial Balance:*
- `date_from`, `date_to`, `target_move`, `journal_ids` (common)
- `display_account`: All / With movements / Balance ≠ 0 (default: With movements)
- (Aceptados también por URL: `account_ids`, `partner_ids`, `analytic_account_ids` como CSV de IDs)

*General Ledger:*
- `date_from`, `date_to`, `target_move`, `journal_ids` (common)
- `display_account`: All / With movements / Balance ≠ 0 (default: With movements)
- `sortby`: Date / Journal & Partner (default: Date)
- `initial_balance` (checkbox — default: off)
- (Aceptados también por URL: `account_ids`, `partner_ids`, `analytic_account_ids`)

**UI:**

- *Trial Balance*: tabla flat con columnas Code / Account / Debit / Credit / Balance,
  y un `<tfoot>` con totales (suma de debit/credit/balance).
- *General Ledger*: una "card" por cuenta. El header de la card muestra Code,
  Name, y stats Debit/Credit/Balance alineados a la derecha. Click en el header
  colapsa/expande la sub-tabla de move lines (Date / Journal / Move / Partner /
  Label / Debit / Credit / Balance). Botones globales **Expand All** / **Collapse All**.

**Decisión sobre many2many (accounts/partners)**: no se exponen en el filter bar
para mantenerlo limpio. Pueden pasarse manualmente por URL
(`?partner_ids=1,2,3&account_ids=10,20`). Si en el futuro se necesita UI, se
puede agregar un typeahead con un endpoint JSON.

**Cómo probar:**

1. Actualizar: `-u accounting_pdf_reports`.
2. Menú **Accounting → Reporting → Trial Balance** debe abrir la nueva vista
   embebida con la tabla flat y totales.
3. Menú **Accounting → Reporting → General Ledger** debe abrir la vista con
   secciones colapsables por cuenta.
4. Cambiar filtros + Apply → recarga con los nuevos params en la URL.
5. PDF → abre el reporte PDF original en pestaña nueva.
6. Print → imprime el contenido (con todas las cuentas expandidas).
7. Desde la vista de una cuenta contable (Accounting → Configuration → Accounts),
   botón **Print → Trial Balance / General Ledger** debe seguir abriendo el
   wizard popup tradicional (el binding no se rompió).

### Fase 3 — Partner Ledger + Aged Partner (Receivable / Payable) ✅

**Estado:** Implementada en `version 1.0.5`.

Mismo patrón que la Fase 2 — los wizards existentes tienen bindings y se
mantienen intactos. Se crean acciones `*_web` nuevas y se repuntean los menús.

Aged Partner tiene la particularidad de **3 variantes de menú** (Aged Balance,
Aged Receivable, Aged Payable) sobre el mismo wizard, distinguidas por context
(`default_result_selection` + `hide_result_selection`). En la versión web el
equivalente es **una única ruta con query params**, y 3 acciones client cada
una con su URL preconfigurada (incluyendo el título a mostrar).

**Archivos nuevos:**

| Archivo | Propósito |
|---|---|
| `report/report_partner_ledger_view.xml` | Template QWeb del Partner Ledger (card colapsable por partner con sub-tabla de move lines + Expand/Collapse All). |
| `report/report_aged_partner_view.xml` | Template QWeb del Aged Partner Balance (matriz partner × buckets de edad + totals en `<tfoot>`). Filter bar custom (sin journals — el reporte no los usa). Title configurable por query param. |

**Archivos modificados:**

| Archivo | Cambio |
|---|---|
| `__manifest__.py` | `version: 1.0.5`; agregados los 2 nuevos templates a `data`. |
| `controllers/main.py` | Agregadas rutas `GET /accounting/report/partner_ledger` + `POST /pdf` y `GET /accounting/report/aged_partner` + `POST /pdf`. El controller de partner ledger itera `result['docs']` y llama a los callables `result['lines']`/`result['sum_partner']` para materializar la data por partner (saltea los que quedan sin lines). El de aged llama a `wizard._get_report_data(data)` que popula los buckets de período `0..4` en `data['form']`. |
| `report/report_styles_template.xml` | (sin cambios — las clases ya existían: `.afr-account-section`, `.afr-table`, `.afr-ledger-table`, etc.) |
| `wizard/partner_ledger.xml` | Agregada `action_account_partner_ledger_web` (`ir.actions.client`); menú `menu_partner_ledger` ahora apunta a ella. Los act_window `action_account_partner_ledger_menu` (binding desde cuentas) y `action_partner_report_partnerledger` (binding desde partners) quedan intactos. |
| `wizard/aged_partner.xml` | Agregadas `action_account_aged_balance_web`, `action_account_aged_receivable_web`, `action_account_aged_payable_web`; los 3 menús apuntan a sus respectivas acciones nuevas. Las URLs de Receivable/Payable incluyen `?result_selection=customer&hide_result_selection=1&title=Aged+Receivable` (o supplier/Payable). |

**Filtros disponibles en cada vista:**

*Partner Ledger:*
- `date_from`, `date_to`, `target_move`, `journal_ids` (common)
- `result_selection`: Receivable / Payable / Receivable & Payable (default: Receivable)
- `reconciled` (checkbox — incluye entries reconciliados; default: off)
- (Aceptados por URL: `amount_currency`, `partner_ids`)

*Aged Partner:*
- `date_from` (rebautizado "Date" — el reporte usa una sola fecha de corte; default: hoy)
- `target_move`: Posted / All (default: Posted)
- `period_length` (entero — bucket size en días; default: 30)
- `result_selection`: Receivable / Payable / Receivable & Payable (oculto si `hide_result_selection=1`)
- (Aceptados por URL: `partner_ids`)
- **NO** se exponen Journals (el reporte los ignora) ni From/To (usa fecha única).

**UI:**

- *Partner Ledger*: idéntico patrón al General Ledger — una card por partner con
  Code (`ref`), Name y stats Debit/Credit/Balance. Click expande/colapsa la
  sub-tabla de move lines (Date / Journal / Account / Ref-Label /
  Debit / Credit / Balance running).
- *Aged Partner Balance*: matriz horizontal. Columnas: Partner | Not Due |
  1-30 | 31-60 | 61-90 | 91-120 | +120 | Total. Los labels de los buckets se
  recalculan según `period_length`. Footer con totales por columna y grand
  total. Los amounts en cero se muestran en gris claro para destacar valores
  significativos.

**Detalle importante sobre orden de buckets en el matriz:**

El reporte interno indexa períodos 0..4 donde **0 = oldest (+120)** y
**4 = newest (1-30)**. En el template los rendero en orden visual natural
(newest → oldest), o sea: `periods[4]`, `periods[3]`, `periods[2]`,
`periods[1]`, `periods[0]`. Lo mismo para los totales: `totals[6]` = Not Due,
`totals[4]` = 1-30, ..., `totals[0]` = +120, `totals[5]` = Grand Total.

**Cómo probar:**

1. Actualizar: `-u accounting_pdf_reports`.
2. Menú **Accounting → Reporting → Partner Ledger** → vista web embebida con
   cards colapsables por partner.
3. Menú **Accounting → Reporting → Aged Partner Balance** → matriz con buckets.
4. Menús **Aged Receivable** y **Aged Payable** → misma matriz pero filtrada y
   sin el dropdown de Receivable/Payable.
5. Cambiar `Period Length` (ej: 60) → los headers de columna se actualizan
   automáticamente (1-60, 61-120, 121-180, etc.).
6. PDF → abre el PDF original en pestaña nueva.
7. Desde Partner record (cualquier partner contacto), botón **Print → Balance
   Statement (Partner Ledger)** debe seguir abriendo el wizard tradicional
   (el binding `binding_model_id=res_partner` no se rompió).
8. Desde Account record, botón **Print → Partner Ledger** idem (binding sobre
   `account.account` intacto).

### Fase 4 — Tax Report + Journals Audit ✅

**Estado:** Implementada en `version 1.0.6`. **Plan original cerrado.**

Mismo patrón que las fases anteriores (nuevas acciones `*_web`, repuntear menú,
wizards intactos). Ninguno de los dos wizards tiene `binding_model_id`, así que
en este caso la diferencia con Fase 1 es solo estilística — se mantiene el
act_window legacy aunque ya no se referencia desde el menú.

**Archivos nuevos:**

| Archivo | Propósito |
|---|---|
| `report/report_tax_view.xml` | Template QWeb del Tax Report. Dos secciones (Sales / Purchases), cada una con tabla Tax Name / Net / Tax + totales en `<tfoot>`. Filter bar custom (solo From/To/Target — el reporte no usa journals visiblemente). |
| `report/report_journal_audit_view.xml` | Template QWeb del Journals Audit. Card colapsable por journal con header (code + name + Debit/Credit/Lines) y sub-tabla de move lines (Date / Move / Account / Partner / Label / Debit / Credit) + bloque de Taxes (Base / Amount) abajo de cada card si aplica. |

**Archivos modificados:**

| Archivo | Cambio |
|---|---|
| `__manifest__.py` | `version: 1.0.6`; agregados los 2 nuevos templates a `data`. |
| `controllers/main.py` | Agregadas rutas `GET /accounting/report/tax` + `POST /pdf` y `GET /accounting/report/journal_audit` + `POST /pdf`. El controller de tax llama `report_model._get_report_values(...)` y extrae `lines['sale']` / `lines['purchase']` directo; calcula totales en el controller. El de journal audit itera `result['docs']` y por cada journal arma un dict con move_lines + sumas (callables `sum_debit`/`sum_credit`) + taxes (callable `get_taxes`, normalizado a lista). |
| `wizard/tax_report.xml` | Agregada `action_account_tax_report_web` (`ir.actions.client`); menú `menu_account_report` ahora apunta a ella. El `action_account_tax_report` legacy queda sin uso (ningún binding lo necesita). |
| `wizard/journal_audit.xml` | Idem para `action_account_print_journal_web` y `menu_print_journal`. |

**Filtros disponibles en cada vista:**

*Tax Report:*
- `date_from`, `date_to` (defaults: mes actual)
- `target_move`: Posted / All (default: Posted)
- **NO** se exponen Journals (el reporte usa todos los journals de la compañía por defecto).

*Journals Audit:*
- `date_from`, `date_to`, `target_move`, `journal_ids` (common — pero el default es solo journals tipo `sale` + `purchase`, no todos)
- `sort_selection`: Entry Number / Date (default: Entry Number)
- `amount_currency` (checkbox — Show Currency; default: off)

**Detalle sobre Journals Audit default:**

El wizard tiene `journal_ids` con default `[('type', 'in', ['sale', 'purchase'])]`.
El controller respeta ese default cuando el usuario no pasa journals por URL.
El dropdown del filter bar muestra TODOS los journals de la compañía (el usuario
puede agregar otros tipos manualmente).

**Detalle sobre Tax Report PDF:**

El wizard usa `accounting_pdf_reports.action_report_account_tax` (custom de este
módulo). Para el Journals Audit, el wizard original llama
`account.action_report_journal` (Odoo core), pero existe también un
`accounting_pdf_reports.action_report_journal` con el template custom
`accounting_pdf_reports.report_journal`. El controller del refactor usa el
custom (consistente con el resto del módulo).

**Cómo probar:**

1. Actualizar: `-u accounting_pdf_reports`.
2. Menú **Accounting → Reporting → Tax Report** → vista web embebida con 2
   secciones (Sales / Purchases) y sus totales.
3. Menú **Accounting → Reporting → Journals Audit** → cards colapsables por
   journal con move lines + bloque de taxes si aplica.
4. Cambiar `Sort by` (Entry Number ↔ Date) → las move lines se reordenan.
5. PDF → abre el reporte PDF original en pestaña nueva.

---

## Estado final

Los **10 reportes** del módulo (8 wizards × variantes de menú) están convertidos
a vista web embebida con filter bar inline + PDF opcional:

| # | Reporte | Versión | Ruta | Wizard model |
|---|---|---|---|---|
| 1 | Balance Sheet | 1.0.3 | `/accounting/report/financial?account_report_id=<bs>` | `accounting.report` |
| 2 | Profit and Loss | 1.0.3 | `/accounting/report/financial?account_report_id=<pl>` | `accounting.report` |
| 3 | Trial Balance | 1.0.4 | `/accounting/report/trial_balance` | `account.balance.report` |
| 4 | General Ledger | 1.0.4 | `/accounting/report/general_ledger` | `account.report.general.ledger` |
| 5 | Partner Ledger | 1.0.5 | `/accounting/report/partner_ledger` | `account.report.partner.ledger` |
| 6 | Aged Partner Balance | 1.0.5 | `/accounting/report/aged_partner` | `account.aged.trial.balance` |
| 7 | Aged Receivable | 1.0.5 | `/accounting/report/aged_partner?result_selection=customer&hide_result_selection=1` | `account.aged.trial.balance` |
| 8 | Aged Payable | 1.0.5 | `/accounting/report/aged_partner?result_selection=supplier&hide_result_selection=1` | `account.aged.trial.balance` |
| 9 | Tax Report | 1.0.6 | `/accounting/report/tax` | `account.tax.report.wizard` |
| 10 | Journals Audit | 1.0.6 | `/accounting/report/journal_audit` | `account.print.journal` |

**Bindings preservados** (siguen abriendo el wizard popup tradicional cuando se
invocan desde un record, no desde el menú):

- Trial Balance / General Ledger / Partner Ledger desde un `account.account`.
- "Balance Statement (Partner Ledger)" desde un `res.partner`.

**Asuntos opcionales no incluidos en el plan original:**

- Internacionalización al español (todos los labels están en inglés).
- Typeahead/autocompletado para los filtros m2m (hoy se pasan por URL CSV).
- Tests automáticos por ruta.
- Paginación en reportes con grandes volúmenes (General Ledger, Journals Audit).
