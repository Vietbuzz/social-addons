import { Component, onWillStart, onWillUnmount, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

import { ConsoleModel, platformInfo } from "./console_model";
import { CommentFeed } from "./comment_feed";
import { ConversationPanel } from "./conversation_panel";
import { OrderPanel } from "./order_panel";
import { BankFeed } from "./bank_feed";

export class LivestreamConsole extends Component {
    static template = "livestream_sale.Console";
    static components = { CommentFeed, ConversationPanel, OrderPanel, BankFeed };

    platformInfo = platformInfo;

    props = useProps(standardActionServiceProps);

    setup() {
        this.model = new ConsoleModel({
            orm: useService("orm"),
            notification: useService("notification"),
            store: useService("mail.store"),
        });
        this.action = useService("action");
        const bus = useService("bus_service");
        const offComment = bus.subscribe("livestream/comment", (p) => this.model.onCommentNotification(p));
        const offBank = bus.subscribe("livestream/bank_transaction", (p) => this.model.onBankNotification(p));
        onWillUnmount(() => {
            offComment();
            offBank();
        });
        const params = this.props.action.params || {};
        onWillStart(() => this.model.load(params.session_id || "all"));
    }

    get state() {
        return this.model.state;
    }

    onChangeSession(ev) {
        const value = ev.target.value;
        this.model.load(value === "all" ? "all" : parseInt(value));
    }

    get liveSessions() {
        return this.state.sessions.filter((s) => s.source_type !== "post");
    }

    get postSessions() {
        return this.state.sessions.filter((s) => s.source_type === "post");
    }

    sessionLabel(s) {
        const unseen = this.state.unseen[s.id];
        const closed = s.state === "live" ? "" : " ✓";
        return `[${this.platformInfo(s.platform).label}] ${s.name}${closed}${unseen ? ` (+${unseen})` : ""}`;
    }

    openSession() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "livestream.session",
            res_id: this.state.session.id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("livestream_console", LivestreamConsole);
