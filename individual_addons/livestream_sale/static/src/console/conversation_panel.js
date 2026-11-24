import { Component, types, useProps } from "@odoo/owl";
import { Thread } from "@mail/core/common/thread";
import { Composer } from "@mail/core/common/composer";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { platformInfo } from "./console_model";

export class ConversationPanel extends Component {
    static template = "livestream_sale.ConversationPanel";
    static components = { Thread, Composer };

    platformInfo = platformInfo;

    props = useProps({ model: types.object() });

    get model() {
        return this.props.model;
    }

    get state() {
        return this.props.model.state;
    }

    get originComment() {
        return this.state.panel?.comment;
    }

    get windowLabel() {
        const channel = this.state.panel?.channel;
        if (!channel) {
            return "";
        }
        if (channel.window_state === "open") {
            const end = deserializeDateTime(channel.window_expires_at);
            const minutes = Math.max(0, Math.round(end.diffNow("minutes").minutes));
            const h = Math.floor(minutes / 60);
            const m = minutes % 60;
            return _t("Chat window open: %(h)sh%(m)s left", { h, m: String(m).padStart(2, "0") });
        }
        if (channel.window_state === "waiting") {
            return _t("Waiting for the customer to reply (1 private reply allowed per comment)");
        }
        return _t("Chat window closed (customer has not written for 24h)");
    }

    get igLiveHint() {
        const session = this.state.session;
        return session?.platform === "instagram" && session.state === "live";
    }

    get windowClass() {
        return {
            open: "text-bg-success",
            waiting: "text-bg-warning",
            closed: "text-bg-danger",
        }[this.state.panel?.channel?.window_state || "waiting"];
    }

    simulateReply() {
        const text = window.prompt(_t("Simulated customer message"), "Sđt em 0912345678, giao về 1 Lê Lợi Q1");
        if (text) {
            this.model.simulateCustomerReply(text);
        }
    }
}
