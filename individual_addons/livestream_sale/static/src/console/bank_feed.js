import { Component, types, useProps } from "@odoo/owl";
import { formatDateTime, deserializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { formatVnd } from "./console_model";

export class BankFeed extends Component {
    static template = "livestream_sale.BankFeed";

    props = useProps({ model: types.object() });

    formatVnd = formatVnd;

    get model() {
        return this.props.model;
    }

    get state() {
        return this.props.model.state;
    }

    get unmatchedCount() {
        return this.state.bankTransactions.filter((t) => t.state === "unmatched").length;
    }

    get openOrder() {
        return this.state.panel?.order;
    }

    time(value) {
        return value ? formatDateTime(deserializeDateTime(value), { format: "dd/MM HH:mm" }) : "";
    }

    simulate() {
        const order = this.openOrder;
        const amount = parseInt(
            window.prompt(_t("Simulated transfer amount (VND)"), order ? String(order.deposit_due) : "100000")
        );
        if (!amount) {
            return;
        }
        const content = window.prompt(
            _t("Transfer content"),
            order ? `CK ${order.payment_ref}` : "chuyen tien coc"
        );
        this.model.simulateBank(amount, content || "");
    }
}
