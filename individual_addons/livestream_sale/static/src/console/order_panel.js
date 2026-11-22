import { Component, types, useProps } from "@odoo/owl";
import { formatVnd } from "./console_model";

export class OrderPanel extends Component {
    static template = "livestream_sale.OrderPanel";

    props = useProps({ model: types.object() });

    formatVnd = formatVnd;

    get model() {
        return this.props.model;
    }

    get state() {
        return this.props.model.state;
    }

    get order() {
        return this.state.panel?.order;
    }

    setField(name, ev) {
        this.state.form[name] = ev.target.value;
    }

    setLine(line, name, ev) {
        line[name] = Number(ev.target.value);
    }

    onAddTag(ev) {
        if (ev.target.value) {
            this.model.addLineFromTag(ev.target.value);
            ev.target.value = "";
        }
    }
}
