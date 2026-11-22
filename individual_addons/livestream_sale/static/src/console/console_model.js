import { proxy } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

const vnd = new Intl.NumberFormat("vi-VN");

export function formatVnd(amount) {
    return `${vnd.format(Math.round(amount || 0))} đ`;
}

/**
 * Shared state + server calls of the operator console. Panels receive this
 * object as `model` prop and only read `model.state` / call its methods.
 */
export class ConsoleModel {
    constructor({ orm, notification, store }) {
        this.orm = orm;
        this.notification = notification;
        this.store = store;
        this.state = proxy({
            loaded: false,
            sessions: [],
            session: null,
            canSimulate: false,
            defaultDeposit: 0,
            comments: [],
            bankTransactions: [],
            tagFilter: false, // false = all, "__none__" = without tag, else code
            search: "",
            activeCommentId: false,
            panel: null, // result of livestream.console.order_panel
            thread: null, // mail.thread of the open conversation
            form: { lines: [], phone: "", name: "", street: "", deposit: 0 },
            highlight: {},
            busy: false,
            mobileTab: "comments",
        });
    }

    // ------------------------------------------------------------------
    // Loading
    // ------------------------------------------------------------------
    async load(sessionId) {
        const data = await this.orm.call("livestream.console", "load", [sessionId || false]);
        Object.assign(this.state, {
            loaded: true,
            sessions: data.sessions,
            session: data.session,
            canSimulate: data.can_simulate,
            defaultDeposit: data.default_deposit,
            comments: data.comments,
            bankTransactions: data.bank_transactions,
            tagFilter: false,
            activeCommentId: false,
            panel: null,
            thread: null,
        });
    }

    async loadMoreComments() {
        const s = this.state;
        if (!s.session || !s.comments.length) {
            return;
        }
        const lastId = Math.min(...s.comments.map((c) => c.id));
        const tag = s.tagFilter && s.tagFilter !== "__none__" ? s.tagFilter : false;
        const more = await this.orm.call("livestream.console", "load_more_comments", [
            s.session.id,
            lastId,
            tag,
        ]);
        s.comments.push(...more.filter((c) => !s.comments.some((x) => x.id === c.id)));
    }

    get filteredComments() {
        const { comments, tagFilter, search } = this.state;
        const q = search.trim().toLowerCase();
        return comments.filter((c) => {
            if (tagFilter === "__none__" && c.tag_code) {
                return false;
            }
            if (tagFilter && tagFilter !== "__none__" && c.tag_code !== tagFilter) {
                return false;
            }
            return !q || c.customer_name.toLowerCase().includes(q) || c.message.toLowerCase().includes(q);
        });
    }

    tagCount(code) {
        return this.state.comments.filter((c) => c.tag_code === code).length;
    }

    // ------------------------------------------------------------------
    // Bus
    // ------------------------------------------------------------------
    onCommentNotification(payload) {
        const s = this.state;
        if (!s.session || payload.account_id !== s.session.account_id) {
            return;
        }
        for (const item of payload.items) {
            if (item.session_id !== s.session.id) {
                continue;
            }
            const idx = s.comments.findIndex((c) => c.id === item.id);
            if (idx >= 0) {
                s.comments[idx] = item;
            } else {
                s.comments.unshift(item);
                this._flash(`c${item.id}`);
            }
        }
    }

    async onBankNotification(payload) {
        const s = this.state;
        if (!s.session || payload.account_id !== s.session.account_id) {
            return;
        }
        let refresh = false;
        for (const item of payload.items) {
            const idx = s.bankTransactions.findIndex((t) => t.id === item.id);
            if (idx >= 0) {
                s.bankTransactions[idx] = item;
            } else {
                s.bankTransactions.unshift(item);
                this._flash(`t${item.id}`);
            }
            if (s.panel?.order && item.sale_order_id === s.panel.order.id) {
                refresh = true;
            }
        }
        if (refresh) {
            await this.refreshOrder();
        }
    }

    _flash(key) {
        this.state.highlight[key] = true;
        setTimeout(() => delete this.state.highlight[key], 2500);
    }

    // ------------------------------------------------------------------
    // Actions
    // ------------------------------------------------------------------
    async _run(fn) {
        this.state.busy = true;
        try {
            return await fn();
        } catch (e) {
            const message = e?.data?.message || e?.message || String(e);
            this.notification.add(message, { type: "danger" });
            return undefined;
        } finally {
            this.state.busy = false;
        }
    }

    async openComment(commentId) {
        await this._run(async () => {
            const res = await this.orm.call("livestream.comment", "action_open_conversation", [[commentId]]);
            this.state.activeCommentId = commentId;
            const idx = this.state.comments.findIndex((c) => c.id === commentId);
            if (idx >= 0) {
                this.state.comments[idx] = res.comment;
            }
            await this._loadPanel(commentId);
            const channel = await this.store["discuss.channel"].getOrFetch(res.channel_id);
            this.state.thread = channel?.thread || null;
            this.state.mobileTab = "chat";
        });
    }

    async _loadPanel(commentId) {
        const panel = await this.orm.call("livestream.console", "order_panel", [commentId]);
        this.state.panel = panel;
        const lines = panel.lines.length
            ? panel.lines.map((l) => ({ ...l }))
            : [];
        const total = lines.reduce((sum, l) => sum + l.quantity * l.price_unit, 0);
        this.state.form = {
            lines,
            phone: panel.customer.phone,
            name: panel.customer.name,
            street: panel.customer.street,
            deposit: this.state.defaultDeposit || Math.round((total * 0.3) / 1000) * 1000,
        };
    }

    async refreshPanel() {
        if (this.state.activeCommentId) {
            await this._loadPanel(this.state.activeCommentId);
        }
    }

    async refreshOrder() {
        const order = this.state.panel?.order;
        if (!order) {
            return;
        }
        this.state.panel.order = await this.orm.call("livestream.console", "order_summary", [order.id]);
    }

    addLineFromTag(code) {
        const tag = this.state.session?.tags.find((t) => t.code === code);
        if (!tag) {
            return;
        }
        const existing = this.state.form.lines.find((l) => l.product_id === tag.product_id);
        if (existing) {
            existing.quantity += 1;
        } else {
            this.state.form.lines.push({
                product_id: tag.product_id,
                product_name: tag.product_name,
                quantity: 1,
                price_unit: tag.price_unit,
            });
        }
    }

    removeLine(index) {
        this.state.form.lines.splice(index, 1);
    }

    get formTotal() {
        return this.state.form.lines.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.price_unit) || 0), 0);
    }

    async createOrder() {
        const { form, activeCommentId } = this.state;
        if (!form.phone.trim()) {
            this.notification.add(_t("Enter the customer's phone number."), { type: "warning" });
            return;
        }
        await this._run(async () => {
            await this.orm.call("livestream.comment", "action_create_order", [
                [activeCommentId],
                form.lines.map((l) => ({
                    product_id: l.product_id,
                    quantity: Number(l.quantity) || 1,
                    price_unit: Number(l.price_unit) || 0,
                })),
                form.phone,
                form.name,
                form.street,
                Number(form.deposit) || 0,
            ]);
            await this._loadPanel(activeCommentId);
            this.notification.add(_t("Order %s created.", this.state.panel.order.name), { type: "success" });
        });
    }

    async sendDepositRequest() {
        const order = this.state.panel?.order;
        if (!order) {
            return;
        }
        await this._run(async () => {
            await this.orm.call("sale.order", "action_livestream_send_deposit_request", [[order.id]]);
            await this.refreshPanel();
        });
    }

    async copyTransferContent() {
        const order = this.state.panel?.order;
        if (order) {
            await navigator.clipboard.writeText(order.payment_ref);
            this.notification.add(_t("Copied %s", order.payment_ref), { type: "info" });
        }
    }

    async matchTransaction(txId, orderId) {
        await this._run(async () => {
            const res = await this.orm.call("livestream.bank.transaction", "action_match_manual", [[txId], orderId]);
            const idx = this.state.bankTransactions.findIndex((t) => t.id === txId);
            if (idx >= 0) {
                this.state.bankTransactions[idx] = res;
            }
            await this.refreshOrder();
            this.notification.add(_t("Deposit matched to %s.", res.sale_order_name), { type: "success" });
        });
    }

    // ------------------------------------------------------------------
    // Simulator
    // ------------------------------------------------------------------
    async simulateComment() {
        await this._run(() => this.orm.call("livestream.simulator", "simulate_comment", [this.state.session.id]));
    }

    async simulateCustomerReply(text) {
        const channelId = this.state.panel?.channel?.id;
        if (!channelId) {
            return;
        }
        await this._run(async () => {
            await this.orm.call("livestream.simulator", "simulate_customer_reply", [channelId, text]);
            await this.refreshPanel();
        });
    }

    async simulateBank(amount, content) {
        await this._run(() =>
            this.orm.call("livestream.simulator", "simulate_bank", [this.state.session.account_id, amount, content])
        );
    }
}
