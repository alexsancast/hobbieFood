/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

export class ReportIframe extends Component {
    static template = "accounting_pdf_reports.ReportIframe";
    static props = ["*"];

    setup() {
        const params = (this.props.action && this.props.action.params) || {};
        this.url = params.url || "/";
    }
}

registry.category("actions").add("accounting_pdf_reports.report_iframe", ReportIframe);
