from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import http
from odoo.http import request, content_disposition
from odoo.tools.misc import formatLang, get_lang


def _parse_int_list(raw):
    if not raw:
        return []
    items = raw if isinstance(raw, list) else str(raw).split(',')
    out = []
    for x in items:
        x = (x or '').strip()
        if not x:
            continue
        try:
            out.append(int(x))
        except ValueError:
            pass
    return out


def _truthy(v):
    return str(v or '').lower() in ('1', 'true', 'on', 'yes')


def _default_dates(kwargs):
    """Return (date_from, date_to) ISO strings, defaulting to current-month-start / today."""
    today = date.today()
    return (
        kwargs.get('date_from') or today.replace(day=1).isoformat(),
        kwargs.get('date_to') or today.isoformat(),
    )


def _all_company_journals():
    company = request.env.company
    return request.env['account.journal'].search([('company_id', '=', company.id)])


def _money_formatter():
    currency = request.env.company.currency_id
    def fmt(amount):
        return formatLang(request.env, float(amount or 0.0), currency_obj=currency)
    return fmt


def _render_pdf_response(action_xmlid, wizard, data, filename):
    """Render an Odoo ir.actions.report (PDF) and return as HTTP download."""
    report = request.env.ref(action_xmlid)
    pdf_content, _ctype = request.env['ir.actions.report'].with_context(
        active_model=wizard._name,
        active_id=wizard.id,
        active_ids=[wizard.id],
    )._render_qweb_pdf(report.report_name, [wizard.id], data=data)
    return request.make_response(
        pdf_content,
        headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', content_disposition(filename)),
        ],
    )


class FinancialReportController(http.Controller):

    # ---------------------------------------------------------------------
    # Balance Sheet / Profit & Loss
    # ---------------------------------------------------------------------

    def _build_financial_data(self, kwargs):
        account_report_id = int(kwargs.get('account_report_id') or 0)
        if not account_report_id:
            raise ValueError("account_report_id is required")

        date_from, date_to = _default_dates(kwargs)
        target_move = kwargs.get('target_move') or 'posted'
        journal_ids = _parse_int_list(request.httprequest.values.getlist('journal_ids'))
        enable_filter = _truthy(kwargs.get('enable_filter'))
        debit_credit = _truthy(kwargs.get('debit_credit')) and not enable_filter
        label_filter = kwargs.get('label_filter') or ''
        date_from_cmp = kwargs.get('date_from_cmp') or ''
        date_to_cmp = kwargs.get('date_to_cmp') or ''

        if enable_filter:
            if not date_from_cmp:
                try:
                    date_from_cmp = (
                        date.fromisoformat(date_from) - relativedelta(months=1)
                    ).isoformat()
                except (TypeError, ValueError):
                    date_from_cmp = ''
            if not date_to_cmp:
                try:
                    date_to_cmp = (
                        date.fromisoformat(date_to) - relativedelta(months=1)
                    ).isoformat()
                except (TypeError, ValueError):
                    date_to_cmp = ''
            filter_cmp = 'filter_date' if (date_from_cmp and date_to_cmp) else 'filter_no'
            if not label_filter:
                label_filter = 'Comparison'
        else:
            filter_cmp = 'filter_no'

        company = request.env.company
        if not journal_ids:
            journal_ids = _all_company_journals().ids

        wizard = request.env['accounting.report'].create({
            'date_from': date_from,
            'date_to': date_to,
            'target_move': target_move,
            'journal_ids': [(6, 0, journal_ids)],
            'account_report_id': account_report_id,
            'enable_filter': enable_filter,
            'debit_credit': debit_credit,
            'label_filter': label_filter,
            'filter_cmp': filter_cmp,
            'date_from_cmp': date_from_cmp or False,
            'date_to_cmp': date_to_cmp or False,
            'company_id': company.id,
        })

        data = {'ids': [], 'model': 'accounting.report', 'form': {}}
        data['form'] = wizard.read([
            'date_from', 'date_to', 'journal_ids', 'target_move', 'company_id',
            'account_report_id', 'enable_filter', 'debit_credit',
            'label_filter', 'filter_cmp', 'date_from_cmp', 'date_to_cmp',
        ])[0]
        used_context = wizard._build_contexts(data)
        data['form']['used_context'] = dict(used_context, lang=get_lang(request.env).code)
        data['form']['comparison_context'] = wizard._build_comparison_context(data)
        return wizard, data

    @http.route('/accounting/report/financial', type='http', auth='user', methods=['GET'])
    def view_financial(self, **kwargs):
        try:
            wizard, data = self._build_financial_data(kwargs)
        except ValueError:
            return request.not_found()

        report_model = request.env['report.accounting_pdf_reports.report_financial']
        flat_lines = report_model.with_context(
            data['form']['used_context']
        ).get_account_lines(data['form'])

        groups = []
        for line in flat_lines:
            if line['type'] == 'report' and line.get('level', 0) != 0:
                groups.append({'report': line, 'accounts': []})
            elif line['type'] == 'account' and groups:
                groups[-1]['accounts'].append(line)

        return request.render('accounting_pdf_reports.financial_report_view', {
            'groups': groups,
            'data': data['form'],
            'company': request.env.company,
            'fmt': _money_formatter(),
            'all_journals': _all_company_journals(),
            'selected_journal_ids': set(data['form'].get('journal_ids') or []),
            'account_report_id': wizard.account_report_id.id,
            'apply_url': '/accounting/report/financial',
            'pdf_url': '/accounting/report/financial/pdf',
        })

    @http.route('/accounting/report/financial/pdf', type='http', auth='user',
                methods=['POST', 'GET'], csrf=False)
    def pdf_financial(self, **kwargs):
        try:
            wizard, data = self._build_financial_data(kwargs)
        except ValueError:
            return request.not_found()
        filename = (wizard.account_report_id.name or 'Financial_Report').replace(' ', '_') + '.pdf'
        return _render_pdf_response(
            'accounting_pdf_reports.action_report_financial', wizard, data, filename,
        )

    # ---------------------------------------------------------------------
    # Trial Balance
    # ---------------------------------------------------------------------

    def _build_trial_balance_data(self, kwargs):
        date_from, date_to = _default_dates(kwargs)
        target_move = kwargs.get('target_move') or 'posted'
        journal_ids = _parse_int_list(request.httprequest.values.getlist('journal_ids'))
        display_account = kwargs.get('display_account') or 'movement'
        analytic_account_ids = _parse_int_list(kwargs.get('analytic_account_ids'))
        account_ids = _parse_int_list(kwargs.get('account_ids'))
        partner_ids = _parse_int_list(kwargs.get('partner_ids'))

        company = request.env.company
        if not journal_ids:
            journal_ids = _all_company_journals().ids

        wizard = request.env['account.balance.report'].create({
            'date_from': date_from,
            'date_to': date_to,
            'target_move': target_move,
            'journal_ids': [(6, 0, journal_ids)],
            'display_account': display_account,
            'analytic_account_ids': [(6, 0, analytic_account_ids)],
            'account_ids': [(6, 0, account_ids)],
            'partner_ids': [(6, 0, partner_ids)],
            'company_id': company.id,
        })

        data = {'ids': wizard.ids, 'model': 'account.balance.report', 'form': {}}
        data['form'] = wizard.read([
            'date_from', 'date_to', 'journal_ids', 'target_move', 'company_id',
        ])[0]
        # pre_print_report mutates data['form'] to add display_account + m2m ids
        wizard.pre_print_report(data)
        used_context = wizard._build_contexts(data)
        data['form']['used_context'] = dict(used_context, lang=get_lang(request.env).code)
        return wizard, data

    @http.route('/accounting/report/trial_balance', type='http', auth='user', methods=['GET'])
    def view_trial_balance(self, **kwargs):
        wizard, data = self._build_trial_balance_data(kwargs)

        report_model = request.env['report.accounting_pdf_reports.report_trialbalance']
        result = report_model.with_context(
            active_model='account.balance.report',
            active_ids=wizard.ids,
            active_id=wizard.id,
        )._get_report_values(wizard.ids, data=data)
        accounts = result['Accounts']

        totals = {
            'debit': sum(a.get('debit') or 0.0 for a in accounts),
            'credit': sum(a.get('credit') or 0.0 for a in accounts),
            'balance': sum(a.get('balance') or 0.0 for a in accounts),
        }

        return request.render('accounting_pdf_reports.trial_balance_view', {
            'accounts': accounts,
            'totals': totals,
            'data': data['form'],
            'company': request.env.company,
            'fmt': _money_formatter(),
            'all_journals': _all_company_journals(),
            'selected_journal_ids': set(data['form'].get('journal_ids') or []),
            'apply_url': '/accounting/report/trial_balance',
            'pdf_url': '/accounting/report/trial_balance/pdf',
        })

    @http.route('/accounting/report/trial_balance/pdf', type='http', auth='user',
                methods=['POST', 'GET'], csrf=False)
    def pdf_trial_balance(self, **kwargs):
        wizard, data = self._build_trial_balance_data(kwargs)
        return _render_pdf_response(
            'accounting_pdf_reports.action_report_trial_balance',
            wizard, data, 'Trial_Balance.pdf',
        )

    # ---------------------------------------------------------------------
    # General Ledger
    # ---------------------------------------------------------------------

    def _build_general_ledger_data(self, kwargs):
        date_from, date_to = _default_dates(kwargs)
        target_move = kwargs.get('target_move') or 'posted'
        journal_ids = _parse_int_list(request.httprequest.values.getlist('journal_ids'))
        display_account = kwargs.get('display_account') or 'movement'
        sortby = kwargs.get('sortby') or 'sort_date'
        initial_balance = _truthy(kwargs.get('initial_balance'))
        analytic_account_ids = _parse_int_list(kwargs.get('analytic_account_ids'))
        account_ids = _parse_int_list(kwargs.get('account_ids'))
        partner_ids = _parse_int_list(kwargs.get('partner_ids'))

        company = request.env.company
        if not journal_ids:
            journal_ids = _all_company_journals().ids

        wizard = request.env['account.report.general.ledger'].create({
            'date_from': date_from,
            'date_to': date_to,
            'target_move': target_move,
            'journal_ids': [(6, 0, journal_ids)],
            'display_account': display_account,
            'sortby': sortby,
            'initial_balance': initial_balance,
            'analytic_account_ids': [(6, 0, analytic_account_ids)],
            'account_ids': [(6, 0, account_ids)],
            'partner_ids': [(6, 0, partner_ids)],
            'company_id': company.id,
        })

        data = {'ids': wizard.ids, 'model': 'account.report.general.ledger', 'form': {}}
        data['form'] = wizard.read([
            'date_from', 'date_to', 'journal_ids', 'target_move', 'company_id',
        ])[0]
        wizard.pre_print_report(data)
        data['form'].update(wizard.read(['initial_balance', 'sortby'])[0])
        used_context = wizard._build_contexts(data)
        data['form']['used_context'] = dict(used_context, lang=get_lang(request.env).code)
        return wizard, data

    @http.route('/accounting/report/general_ledger', type='http', auth='user', methods=['GET'])
    def view_general_ledger(self, **kwargs):
        wizard, data = self._build_general_ledger_data(kwargs)

        report_model = request.env['report.accounting_pdf_reports.report_general_ledger']
        result = report_model.with_context(
            active_model='account.report.general.ledger',
            active_ids=wizard.ids,
            active_id=wizard.id,
        )._get_report_values(wizard.ids, data=data)
        accounts = result['Accounts']

        return request.render('accounting_pdf_reports.general_ledger_view', {
            'accounts': accounts,
            'data': data['form'],
            'company': request.env.company,
            'fmt': _money_formatter(),
            'all_journals': _all_company_journals(),
            'selected_journal_ids': set(data['form'].get('journal_ids') or []),
            'apply_url': '/accounting/report/general_ledger',
            'pdf_url': '/accounting/report/general_ledger/pdf',
        })

    @http.route('/accounting/report/general_ledger/pdf', type='http', auth='user',
                methods=['POST', 'GET'], csrf=False)
    def pdf_general_ledger(self, **kwargs):
        wizard, data = self._build_general_ledger_data(kwargs)
        return _render_pdf_response(
            'accounting_pdf_reports.action_report_general_ledger',
            wizard, data, 'General_Ledger.pdf',
        )

    # ---------------------------------------------------------------------
    # Partner Ledger
    # ---------------------------------------------------------------------

    def _build_partner_ledger_data(self, kwargs):
        date_from, date_to = _default_dates(kwargs)
        target_move = kwargs.get('target_move') or 'posted'
        journal_ids = _parse_int_list(request.httprequest.values.getlist('journal_ids'))
        result_selection = kwargs.get('result_selection') or 'customer'
        reconciled = _truthy(kwargs.get('reconciled'))
        amount_currency = _truthy(kwargs.get('amount_currency'))
        partner_ids = _parse_int_list(kwargs.get('partner_ids'))

        company = request.env.company
        if not journal_ids:
            journal_ids = _all_company_journals().ids

        wizard = request.env['account.report.partner.ledger'].create({
            'date_from': date_from,
            'date_to': date_to,
            'target_move': target_move,
            'journal_ids': [(6, 0, journal_ids)],
            'result_selection': result_selection,
            'reconciled': reconciled,
            'amount_currency': amount_currency,
            'partner_ids': [(6, 0, partner_ids)],
            'company_id': company.id,
        })

        data = {'ids': wizard.ids, 'model': 'account.report.partner.ledger', 'form': {}}
        data['form'] = wizard.read([
            'date_from', 'date_to', 'journal_ids', 'target_move', 'company_id',
        ])[0]
        # _get_report_data calls pre_print_report + adds reconciled/amount_currency
        wizard._get_report_data(data)
        used_context = wizard._build_contexts(data)
        data['form']['used_context'] = dict(used_context, lang=get_lang(request.env).code)
        return wizard, data

    @http.route('/accounting/report/partner_ledger', type='http', auth='user', methods=['GET'])
    def view_partner_ledger(self, **kwargs):
        wizard, data = self._build_partner_ledger_data(kwargs)

        report_model = request.env['report.accounting_pdf_reports.report_partnerledger']
        result = report_model.with_context(
            active_model='account.report.partner.ledger',
            active_id=wizard.id,
            active_ids=wizard.ids,
        )._get_report_values(wizard.ids, data=data)

        partners_data = []
        for partner in result['docs']:
            lines = result['lines'](data, partner)
            if not lines:
                continue
            partners_data.append({
                'partner': partner,
                'lines': lines,
                'debit': result['sum_partner'](data, partner, 'debit'),
                'credit': result['sum_partner'](data, partner, 'credit'),
                'balance': result['sum_partner'](data, partner, 'debit - credit'),
            })

        return request.render('accounting_pdf_reports.partner_ledger_view', {
            'partners_data': partners_data,
            'data': data['form'],
            'company': request.env.company,
            'fmt': _money_formatter(),
            'all_journals': _all_company_journals(),
            'selected_journal_ids': set(data['form'].get('journal_ids') or []),
            'apply_url': '/accounting/report/partner_ledger',
            'pdf_url': '/accounting/report/partner_ledger/pdf',
        })

    @http.route('/accounting/report/partner_ledger/pdf', type='http', auth='user',
                methods=['POST', 'GET'], csrf=False)
    def pdf_partner_ledger(self, **kwargs):
        wizard, data = self._build_partner_ledger_data(kwargs)
        return _render_pdf_response(
            'accounting_pdf_reports.action_report_partnerledger',
            wizard, data, 'Partner_Ledger.pdf',
        )

    # ---------------------------------------------------------------------
    # Aged Partner Balance (also: Aged Receivable, Aged Payable)
    # ---------------------------------------------------------------------

    def _build_aged_partner_data(self, kwargs):
        today = date.today()
        # Aged uses a single point-in-time date: the wizard's date_from.
        date_from = kwargs.get('date_from') or today.isoformat()
        target_move = kwargs.get('target_move') or 'posted'
        result_selection = kwargs.get('result_selection') or 'customer'
        try:
            period_length = int(kwargs.get('period_length') or 30)
        except (TypeError, ValueError):
            period_length = 30
        if period_length <= 0:
            period_length = 30
        partner_ids = _parse_int_list(kwargs.get('partner_ids'))

        company = request.env.company
        # journal_ids is required on the wizard but the report itself ignores it.
        journal_ids = _all_company_journals().ids

        wizard = request.env['account.aged.trial.balance'].create({
            'date_from': date_from,
            'date_to': date_from,
            'target_move': target_move,
            'journal_ids': [(6, 0, journal_ids)],
            'result_selection': result_selection,
            'period_length': period_length,
            'partner_ids': [(6, 0, partner_ids)],
            'company_id': company.id,
        })

        data = {'ids': wizard.ids, 'model': 'account.aged.trial.balance', 'form': {}}
        data['form'] = wizard.read([
            'date_from', 'date_to', 'journal_ids', 'target_move', 'company_id',
        ])[0]
        # _get_report_data populates result_selection, period_length and the
        # period bucket dicts under keys '0'..'4'.
        wizard._get_report_data(data)
        used_context = wizard._build_contexts(data)
        data['form']['used_context'] = dict(used_context, lang=get_lang(request.env).code)
        return wizard, data

    @http.route('/accounting/report/aged_partner', type='http', auth='user', methods=['GET'])
    def view_aged_partner(self, **kwargs):
        wizard, data = self._build_aged_partner_data(kwargs)

        report_model = request.env['report.accounting_pdf_reports.report_agedpartnerbalance']
        result = report_model.with_context(
            active_model='account.aged.trial.balance',
            active_id=wizard.id,
            active_ids=wizard.ids,
        )._get_report_values(wizard.ids, data=data)

        # Period bucket labels — index 4 = newest (e.g. "1-30"), index 0 = oldest ("+120").
        periods = [data['form'].get(str(i), {}) for i in range(5)]

        title = kwargs.get('title') or 'Aged Partner Balance'
        hide_result_selection = _truthy(kwargs.get('hide_result_selection'))

        return request.render('accounting_pdf_reports.aged_partner_view', {
            'movelines': result.get('get_partner_lines') or [],
            'totals': result.get('get_direction') or [0] * 7,
            'periods': periods,
            'data': data['form'],
            'company': request.env.company,
            'fmt': _money_formatter(),
            'title': title,
            'hide_result_selection': hide_result_selection,
            'apply_url': '/accounting/report/aged_partner',
            'pdf_url': '/accounting/report/aged_partner/pdf',
        })

    @http.route('/accounting/report/aged_partner/pdf', type='http', auth='user',
                methods=['POST', 'GET'], csrf=False)
    def pdf_aged_partner(self, **kwargs):
        wizard, data = self._build_aged_partner_data(kwargs)
        return _render_pdf_response(
            'accounting_pdf_reports.action_report_aged_partner_balance',
            wizard, data, 'Aged_Partner_Balance.pdf',
        )

    # ---------------------------------------------------------------------
    # Tax Report
    # ---------------------------------------------------------------------

    def _build_tax_report_data(self, kwargs):
        date_from, date_to = _default_dates(kwargs)
        target_move = kwargs.get('target_move') or 'posted'

        company = request.env.company
        journal_ids = _all_company_journals().ids

        wizard = request.env['account.tax.report.wizard'].create({
            'date_from': date_from,
            'date_to': date_to,
            'target_move': target_move,
            'journal_ids': [(6, 0, journal_ids)],
            'company_id': company.id,
        })

        data = {'ids': wizard.ids, 'model': 'account.tax.report.wizard', 'form': {}}
        data['form'] = wizard.read([
            'date_from', 'date_to', 'journal_ids', 'target_move', 'company_id',
        ])[0]
        used_context = wizard._build_contexts(data)
        data['form']['used_context'] = dict(used_context, lang=get_lang(request.env).code)
        return wizard, data

    @http.route('/accounting/report/tax', type='http', auth='user', methods=['GET'])
    def view_tax_report(self, **kwargs):
        wizard, data = self._build_tax_report_data(kwargs)

        report_model = request.env['report.accounting_pdf_reports.report_tax']
        result = report_model._get_report_values(wizard.ids, data=data)
        groups = result.get('lines') or {'sale': [], 'purchase': []}

        sales_total = {
            'net': sum(t.get('net') or 0.0 for t in groups.get('sale', [])),
            'tax': sum(t.get('tax') or 0.0 for t in groups.get('sale', [])),
        }
        purchase_total = {
            'net': sum(t.get('net') or 0.0 for t in groups.get('purchase', [])),
            'tax': sum(t.get('tax') or 0.0 for t in groups.get('purchase', [])),
        }

        return request.render('accounting_pdf_reports.tax_report_view', {
            'sales': groups.get('sale') or [],
            'purchases': groups.get('purchase') or [],
            'sales_total': sales_total,
            'purchase_total': purchase_total,
            'data': data['form'],
            'company': request.env.company,
            'fmt': _money_formatter(),
            'apply_url': '/accounting/report/tax',
            'pdf_url': '/accounting/report/tax/pdf',
        })

    @http.route('/accounting/report/tax/pdf', type='http', auth='user',
                methods=['POST', 'GET'], csrf=False)
    def pdf_tax_report(self, **kwargs):
        wizard, data = self._build_tax_report_data(kwargs)
        return _render_pdf_response(
            'accounting_pdf_reports.action_report_account_tax',
            wizard, data, 'Tax_Report.pdf',
        )

    # ---------------------------------------------------------------------
    # Journals Audit
    # ---------------------------------------------------------------------

    def _build_journal_audit_data(self, kwargs):
        date_from, date_to = _default_dates(kwargs)
        target_move = kwargs.get('target_move') or 'posted'
        journal_ids = _parse_int_list(request.httprequest.values.getlist('journal_ids'))
        sort_selection = kwargs.get('sort_selection') or 'move_name'
        amount_currency = _truthy(kwargs.get('amount_currency'))

        company = request.env.company
        if not journal_ids:
            # Wizard default: only sale + purchase journals.
            journal_ids = request.env['account.journal'].search([
                ('company_id', '=', company.id),
                ('type', 'in', ['sale', 'purchase']),
            ]).ids

        wizard = request.env['account.print.journal'].create({
            'date_from': date_from,
            'date_to': date_to,
            'target_move': target_move,
            'journal_ids': [(6, 0, journal_ids)],
            'sort_selection': sort_selection,
            'amount_currency': amount_currency,
            'company_id': company.id,
        })

        data = {'ids': wizard.ids, 'model': 'account.print.journal', 'form': {}}
        data['form'] = wizard.read([
            'date_from', 'date_to', 'journal_ids', 'target_move', 'company_id',
        ])[0]
        wizard.pre_print_report(data)  # adds amount_currency
        data['form']['sort_selection'] = sort_selection
        used_context = wizard._build_contexts(data)
        data['form']['used_context'] = dict(used_context, lang=get_lang(request.env).code)
        return wizard, data

    @http.route('/accounting/report/journal_audit', type='http', auth='user', methods=['GET'])
    def view_journal_audit(self, **kwargs):
        wizard, data = self._build_journal_audit_data(kwargs)

        report_model = request.env['report.accounting_pdf_reports.report_journal']
        result = report_model._get_report_values(wizard.ids, data=data)

        journals_data = []
        for journal in result['docs']:
            move_lines = result['lines'].get(journal.id)
            taxes_raw = result['get_taxes'](data, journal)
            taxes = [
                {'name': tax.name, 'base': vals.get('base_amount') or 0.0,
                 'amount': vals.get('tax_amount') or 0.0}
                for tax, vals in taxes_raw.items()
            ]
            journals_data.append({
                'journal': journal,
                'move_lines': move_lines,
                'debit': result['sum_debit'](data, journal),
                'credit': result['sum_credit'](data, journal),
                'taxes': taxes,
            })

        return request.render('accounting_pdf_reports.journal_audit_view', {
            'journals_data': journals_data,
            'data': data['form'],
            'company': request.env.company,
            'fmt': _money_formatter(),
            'all_journals': _all_company_journals(),
            'selected_journal_ids': set(data['form'].get('journal_ids') or []),
            'apply_url': '/accounting/report/journal_audit',
            'pdf_url': '/accounting/report/journal_audit/pdf',
        })

    @http.route('/accounting/report/journal_audit/pdf', type='http', auth='user',
                methods=['POST', 'GET'], csrf=False)
    def pdf_journal_audit(self, **kwargs):
        wizard, data = self._build_journal_audit_data(kwargs)
        return _render_pdf_response(
            'accounting_pdf_reports.action_report_journal',
            wizard, data, 'Journals_Audit.pdf',
        )
