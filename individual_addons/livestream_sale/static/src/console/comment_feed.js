import { Component, types, useProps } from "@odoo/owl";
import { formatDateTime, deserializeDateTime } from "@web/core/l10n/dates";
import { platformInfo } from "./console_model";

export class CommentFeed extends Component {
    static template = "livestream_sale.CommentFeed";

    platformInfo = platformInfo;

    props = useProps({ model: types.object() });

    get model() {
        return this.props.model;
    }

    get state() {
        return this.props.model.state;
    }

    time(value) {
        return value ? formatDateTime(deserializeDateTime(value), { format: "HH:mm:ss" }) : "";
    }

    setFilter(code) {
        this.state.tagFilter = this.state.tagFilter === code ? false : code;
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
    }

    onScroll(ev) {
        const el = ev.target;
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40 && !this._loadingMore) {
            this._loadingMore = true;
            this.model.loadMoreComments().finally(() => (this._loadingMore = false));
        }
    }

    stateBadge(state) {
        return {
            new: "text-bg-primary",
            contacted: "text-bg-warning",
            ordered: "text-bg-success",
            ignored: "text-bg-secondary",
        }[state];
    }
}
